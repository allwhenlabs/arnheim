"""Your phone (serve.py --remote, connect/remote.py): Arnheim stays on this computer, anything forwarded is
never taken for this computer, a phone gets in only once paired with a one-time code from this computer's own
page, and it controls agents only while this computer lets it. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import urlencode

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serve  # noqa: E402  (after the path is set)
from connect import remote as phones  # noqa: E402

NAME = "mac.example-tailnet.ts.net"


class StubControl:
    """Stands in for connect/control.py: says yes to everything, and counts what reached it."""

    def __init__(self):
        self.calls = []

    def handle(self, method, name, body=b"", token=""):
        self.calls.append((method, name))
        return 200, "application/json; charset=utf-8", json.dumps({"on": True, "token": "t"} if name == "token" else {"ok": True}).encode(), {}


class RemoteTest(unittest.TestCase):
    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.data, ignore_errors=True)
        self.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        self.server.remote = phones.Remote(NAME, self.data)
        self.server.control = StubControl()
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, path, method="GET", headers=None, body=None, server_port=None):
        conn = http.client.HTTPConnection("127.0.0.1", server_port or self.port, timeout=10)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            for name, value in {"Host": f"127.0.0.1:{self.port}", **(headers or {})}.items():
                conn.putheader(name, value)
            if body is not None:
                conn.putheader("Content-Length", str(len(body)))
            conn.endheaders(body)
            reply = conn.getresponse()
            return reply.status, dict(reply.getheaders()), reply.read()
        finally:
            conn.close()

    def phone(self, path, method="GET", key=None, body=None, origin=f"https://{NAME}", extra=None):
        headers = {"Host": NAME, "X-Forwarded-For": "100.64.0.7", "Tailscale-User-Login": "someone@example.com"}
        if key:
            headers["Cookie"] = f"{phones.COOKIE}={key}"
        if method == "POST":
            headers["Origin"] = origin
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        headers.update(extra or {})
        return self.ask(path, method, headers, body)

    def ours(self, name, body=None):
        return self.ask(f"/remote/{name}", "POST", {"Origin": f"http://127.0.0.1:{self.port}", "X-Arnheim-Remote": "1", "Content-Type": "application/json"},
                        json.dumps(body or {}).encode())

    def code(self):
        status, _, data = self.ours("code")
        self.assertEqual(status, 200)
        return json.loads(data)["code"]

    def pair(self, code=None):
        status, headers, _ = self.phone("/remote/pair", "POST", body=urlencode({"code": code or self.code()}).encode())
        self.assertEqual(status, 303)
        cookie = headers["Set-Cookie"]
        for part in ("Secure", "HttpOnly", "SameSite=Strict"):
            self.assertIn(part, cookie)
        return cookie.split(";")[0].split("=", 1)[1]

    def test_an_unpaired_phone_sees_only_the_pairing_page(self):
        status, _, page = self.phone("/")
        self.assertEqual(status, 200)
        self.assertIn(b"Pair this phone with Arnheim", page)
        for path in ("/src/demo.js", "/sample/company.json", "/control/token", "/brain/status", "/voice/status"):
            self.assertEqual(self.phone(path)[0], 403, path)
        for path in serve.HOME_SCREEN:  # its home-screen icon, fetched without the phone's cookie: public files
            self.assertEqual(self.phone(path)[0], 200, path)

    def test_pairing_takes_the_code_once(self):
        code = self.code()
        self.assertEqual(len(code), 9)  # four, a dash, four
        status, _, page = self.phone("/remote/pair", "POST", body=b"code=0000-0000")
        self.assertIn(b"That isn&#x27;t the code", page)
        key = self.pair(code.lower().replace("-", " "))  # however it is typed
        self.assertEqual(self.phone("/src/demo.js", key=key)[0], 200)
        status, _, page = self.phone("/remote/pair", "POST", body=urlencode({"code": code}).encode())
        self.assertIn(b"That code has run out", page)

    def test_wrong_codes_end_pairing_for_a_while(self):
        code = self.code()
        for _ in range(phones.TRIES_A_MINUTE):
            self.phone("/remote/pair", "POST", body=b"code=0000-0000")
        status, _, page = self.phone("/remote/pair", "POST", body=urlencode({"code": code}).encode())
        self.assertIn(b"Too many wrong codes", page)  # even the right one, until a new code is made
        self.pair()  # a new code from this computer: someone else's wrong tries don't keep you out

    def test_only_this_computers_page_makes_codes_and_changes_phones(self):
        key = self.pair()
        self.assertEqual(self.phone("/remote/code", "POST", key=key, body=b"{}", extra={"X-Arnheim-Remote": "1"})[0], 403)
        self.assertEqual(self.phone("/remote/status", key=key)[0], 403)
        # this computer, but from another site: refused
        self.assertEqual(self.ask("/remote/code", "POST", {"Origin": "https://evil.example", "X-Arnheim-Remote": "1"}, b"{}")[0], 403)
        # this computer's page without the header a plain form can't send
        self.assertEqual(self.ask("/remote/code", "POST", {"Origin": f"http://127.0.0.1:{self.port}"}, b"{}")[0], 404)

    def test_a_phone_controls_agents_only_while_this_computer_lets_it(self):
        key = self.pair()
        status, _, data = self.phone("/control/token", key=key)
        self.assertEqual((status, json.loads(data)["on"]), (200, False))
        self.assertEqual(self.phone("/control/state", key=key)[0], 403)
        self.assertEqual(self.server.control.calls, [])
        phone_id = json.loads(self.ask("/remote/status")[2])["phones"][0]["id"]
        self.assertEqual(self.ours("grant", {"id": phone_id, "minutes": 15})[0], 200)
        self.assertEqual(json.loads(self.phone("/control/token", key=key)[2]), {"on": True, "token": "t"})
        self.assertEqual(self.phone("/control/answer", "POST", key=key, body=b"{}")[0], 200)
        self.assertEqual(self.phone("/control/answer", "POST", key=key, body=b"{}", origin="https://evil.example")[0], 403)
        with open(os.path.join(self.data, "remote", "log.jsonl"), encoding="utf-8") as handle:
            log = [json.loads(line) for line in handle]
        self.assertEqual([x["event"] for x in log], ["code", "paired", "control on", "control"])
        self.assertEqual(log[-1]["request"], "POST answer")
        self.assertNotIn(key, json.dumps(log))
        self.ours("grant", {"id": phone_id, "minutes": 0})
        self.assertEqual(self.phone("/control/state", key=key)[0], 403)

    def test_too_many_control_requests_wait(self):
        key = self.pair()
        phone_id = json.loads(self.ask("/remote/status")[2])["phones"][0]["id"]
        self.ours("grant", {"id": phone_id, "minutes": 5})
        codes = [self.phone("/control/state", key=key)[0] for _ in range(phones.ACTS_A_MINUTE + 2)]
        self.assertEqual(codes[-1], 429)

    def test_the_records_are_never_served_and_keep_no_key(self):
        key = self.pair()
        self.assertEqual(self.phone("/data/remote/phones.json", key=key)[0], 404)
        self.assertEqual(self.ask("/data/remote/phones.json")[0], 404)
        with open(os.path.join(self.data, "remote", "phones.json"), encoding="utf-8") as handle:
            kept = handle.read()
        self.assertNotIn(key, kept)
        self.assertIn(phones.fingerprint(key), kept)
        self.assertEqual(oct(os.stat(os.path.join(self.data, "remote", "phones.json")).st_mode & 0o777), "0o600")

    def test_removed_phones_and_other_logins_are_out(self):
        key = self.pair()
        self.assertEqual(self.phone("/src/demo.js", key=key, extra={"Tailscale-User-Login": "someone-else@example.com"})[0], 403)
        self.ours("remove", {"id": None})
        self.assertEqual(self.phone("/src/demo.js", key=key)[0], 403)
        self.assertEqual(self.phone("/src/demo.js", key="made-up-key")[0], 403)

    def test_a_phone_can_leave(self):
        key = self.pair()
        status, headers, _ = self.phone("/remote/leave", "POST", key=key, body=b"")
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", headers["Set-Cookie"])
        self.assertEqual(self.phone("/src/demo.js", key=key)[0], 403)

    def test_forwarded_for_another_name_is_refused(self):
        self.assertEqual(self.ask("/", headers={"Host": "evil.example", "X-Forwarded-For": "1.2.3.4"})[0], 403)
        self.assertEqual(self.ask("/", headers={"X-Forwarded-For": "1.2.3.4"})[0], 403)  # this computer's name, but forwarded

    def test_this_computer_is_unchanged(self):
        self.assertEqual(self.ask("/")[0], 200)
        self.assertEqual(json.loads(self.ask("/control/token")[2])["on"], True)
        self.assertEqual(json.loads(self.ask("/remote/status")[2])["name"], NAME)

    def test_phone_pages_say_how_to_treat_them(self):
        key = self.pair()
        _, headers, _ = self.phone("/", key=key)
        self.assertIn("max-age", headers.get("Strict-Transport-Security", ""))
        self.assertEqual(headers.get("Referrer-Policy"), "same-origin")  # no-referrer would make a browser send Origin: null
        self.assertEqual(headers.get("X-Frame-Options"), "DENY")


class WithoutRemoteTest(unittest.TestCase):
    """With --remote off, anything that came through a proxy is refused, so a way in set up by mistake (a
    forgotten tailscale serve, a tunnel) is never taken for this computer."""

    def test_forwarded_is_refused(self):
        server = serve.Server(("127.0.0.1", 0), serve.Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for header in ("X-Forwarded-For", "Forwarded", "Tailscale-User-Login", "X-Real-IP"):
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                conn.request("GET", "/", headers={"Host": f"127.0.0.1:{port}", header: "1.2.3.4"})
                self.assertEqual(conn.getresponse().status, 403, header)
                conn.close()
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/remote/status", headers={"Host": f"127.0.0.1:{port}"})
            self.assertEqual(json.loads(conn.getresponse().read()), {"on": False})
            conn.close()
        finally:
            server.shutdown()
            server.server_close()


class NameTest(unittest.TestCase):
    def test_only_a_host_name(self):
        self.assertEqual(phones.clean_name("https://Mac.Example-Tailnet.ts.net/"), "mac.example-tailnet.ts.net")
        for bad in ("", "localhost", "100.64.0.7", "mac", "evil.example/path", "a b.ts.net", "-x.ts.net"):
            with self.assertRaises(ValueError, msg=bad):
                phones.clean_name(bad)

    def test_codes_run_out(self):
        with tempfile.TemporaryDirectory() as data:
            r = phones.Remote(NAME, data)
            code = r.code()["code"]
            r.pending["until"] = time.time() - 1
            self.assertEqual(r.pair(code), (None, "That code has run out. Make a new one on your computer."))


if __name__ == "__main__":
    unittest.main()
