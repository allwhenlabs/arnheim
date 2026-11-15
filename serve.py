#!/usr/bin/env python3
"""Shows Arnheim: run `python3 serve.py`, then open the address it prints.

  python3 serve.py          on this computer only, at http://127.0.0.1:8740
  python3 serve.py 8741     on another port
  python3 serve.py --lan    on phones and other computers on this network too (README, "Phones")
  python3 serve.py --share  the same, but only for those you give its view-only link (README, "A view-only link")
  python3 serve.py --control  and let the page talk to your Claude Code agents, answer their
                            permission requests, and start and stop them (docs/connect.md)
  python3 serve.py --brain  and let the receptionist and your assistant talk about anything, with
                            Claude through your own Claude Code (docs/brain.md)
  python3 serve.py --remote my-mac.your-tailnet.ts.net
                            and let your own phone in, from anywhere, through a private way in such as
                            Tailscale Serve, once it is paired with a code from this computer (docs/phone.md)

It serves the page and its files from this folder, and nothing else: no other folders, no
listings, nothing cached, so a change shows on the next reload. Your own company goes in data/
(README, "Make it yours"); without it, the page shows the made-up sample. It answers only to the
names it was opened by (127.0.0.1 and localhost, and with --lan an IP address or a name ending
.local), so a web page elsewhere can't read it by pointing a name of its own here.
It also answers /voice/, the voice the walk's people speak with, if this computer has one
(voice/bridge.py, and README, "Voice"), and with --control, /control/ (connect/control.py), and
with --brain, /brain/ (connect/brain.py), only to the page on this computer: never with --lan.
With --share, another computer gets in only through the view-only link it prints, and only to look: it
never gets the founder's notes, and nothing it sends is acted on.
With --remote, it still listens only on this computer; what reaches it forwarded (from your phone, through
Tailscale Serve) is never taken for this computer, and needs a paired phone (connect/remote.py). Without
--remote, anything forwarded is refused.
"""
import argparse
import errno
import hmac
import http.server
import io
import ipaddress
import json
import os
import re
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
from html import escape as html_escape
from urllib.parse import parse_qs, unquote

from connect.brain import Brain
from connect.control import Control
from connect.remote import COOKIE as PHONE_COOKIE, LIFE as PHONE_LIFE, Remote
from voice.bridge import Voice

ROOT = os.path.dirname(os.path.realpath(__file__))  # links resolved, as every file below is
SHOWN = ("src", "sample", "vendor", "data", "baked")  # baked: the photo-real floors (studio/publish.py)
TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg", ".hdr": "image/vnd.radiance",  # the real materials walk mode loads (vendor/polyhaven)
    ".bin": "application/octet-stream",  # the photo-real floors' shapes (baked/)
    ".md": "text/markdown; charset=utf-8",  # the company's how-tos (docs/data.md, "How-tos")
}
PORT_TAKEN = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
HERE_ONLY = ("127.0.0.1", "::1", "::ffff:127.0.0.1")  # what this computer's own requests come from
SHARE_KEY = os.path.join(ROOT, ".share-key")  # the view-only link's key (--share), kept so the link stays the same
VIEW = "arnheim_view"  # the cookie a view-only link leaves, so the page's own files come with it
KEY = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
NEVER_AWAY = ("/data/control/",)  # control's mail with Claude Code: never to another computer, link or not
NOT_SHARED = ("/data/notes.json",)  # the founder's notes: never through a view-only link
NEVER_SERVED = ("/data/remote/",)  # the paired phones and their log: never to anyone, this computer included
# A request that came through a proxy carries one of these. Without --remote it is refused; with it, it is a phone's.
FORWARDED = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-IP",
             "Tailscale-User-Login", "Tailscale-User-Name", "Tailscale-Headers-Info")
# Both are checked by spelling in lower case, and again by what the file is on disk: a Mac's disk takes
# /data/Notes.json for /data/notes.json.


def same_file(a, b):
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def howto_files():
    """The how-tos data/company.json lists (docs/data.md, "How-tos"): the only Markdown in data/ the page gets."""
    try:
        with open(os.path.join(ROOT, "data", "company.json"), encoding="utf-8-sig") as handle:
            company = json.load(handle)
    except (OSError, ValueError):
        return []
    listed = company.get("howtos") if isinstance(company, dict) else None
    return [os.path.join(ROOT, "data", *str(x["file"]).split("/")) for x in listed or [] if isinstance(x, dict) and isinstance(x.get("file"), str)]


def share_key(new=False):
    """The view-only link's key: the one kept beside this file, or a new one (--new-link), which ends the old link."""
    if not new:
        try:
            with open(SHARE_KEY, encoding="utf-8") as handle:
                key = handle.read().strip()
            if KEY.match(key):
                os.chmod(SHARE_KEY, 0o600)  # only you, even if the file was made some other way
                return key
        except OSError:
            pass
    key = secrets.token_urlsafe(24)
    handle = os.open(SHARE_KEY, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as out:
        out.write(key + "\n")
    return key


def without_pings(raw):
    """data/company.json as the page gets it: without "pings" (connect/ping.py), which only this server
    needs and whose ntfy topic is as good as a password, since anyone who knows it can read the pings."""
    try:
        company = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return raw
    if not isinstance(company, dict) or "pings" not in company:
        return raw
    company.pop("pings")
    return json.dumps(company, ensure_ascii=False, indent=2).encode("utf-8")


VOICE = Voice()


def host_ok(host, port, lan=False):
    """Whether a request's Host is a name this server answers to, with its port: 127.0.0.1 or
    localhost, and with --lan an address or a name ending .local. A page elsewhere can point a name
    of its own at this computer, but it can't make the browser send one of these."""
    name, colon, given = host.rpartition(":")
    if not colon or "]" in given:  # no port, or an IPv6 address with none
        name, given = host, ""
    if given != str(port) and not (port == 80 and given == ""):
        return False
    name = name.lower()
    if name in ("127.0.0.1", "localhost", "[::1]"):
        return True
    if not lan:
        return False
    if name.endswith(".local"):
        return True
    try:
        ipaddress.ip_address(name[1:-1] if name.startswith("[") else name)
    except ValueError:
        return False
    return True


PAIRING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="same-origin"><title>Pair this phone</title>
<style>body{font:17px/1.45 -apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;background:#0d0f13;color:#eceef3;margin:0;padding:28px 18px}
main{max-width:420px;margin:0 auto}h1{font-size:22px;margin:0 0 12px}p{color:#b9bfca}label{display:block;font-weight:600;margin:20px 0 8px}
input{width:100%;box-sizing:border-box;font:600 22px/1.2 ui-monospace,Menlo,monospace;letter-spacing:.12em;padding:12px;border-radius:12px;border:1px solid #3a404c;background:#171a20;color:#fff;text-transform:uppercase}
button{margin-top:16px;width:100%;font:600 17px/1 inherit;padding:14px;border-radius:12px;border:0;background:#eceef3;color:#0d0f13}
.no{color:#ff9aac;font-weight:600}</style></head>
<body><main><h1>Pair this phone with Arnheim</h1>
<p>On your computer, open Arnheim's Company page and choose Pair a phone. Type the code it shows here.</p>
{error}<form method="post" action="/remote/pair"><label for="code">The code from your computer</label>
<input id="code" name="code" autocomplete="one-time-code" autocapitalize="characters" spellcheck="false" maxlength="12" required autofocus>
<button type="submit">Pair</button></form></main></body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    timeout = 120  # a phone that stops mid-request lets go of its thread

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT, **kwargs)

    def log_message(self, *_args):
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "same-origin")  # nothing to other sites; this page's own posts keep their Origin
        if self.away():
            self.send_header("Strict-Transport-Security", "max-age=31536000")
            self.send_header("Permissions-Policy", "microphone=(self), camera=(), geolocation=()")
            self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def forwarded(self):
        headers = getattr(self, "headers", None)  # none yet on a request too broken to read
        return headers is not None and any(headers.get(name) for name in FORWARDED)

    def host_name(self):
        headers = getattr(self, "headers", None)
        host = (headers.get("Host", "") if headers is not None else "").strip().lower()
        name, colon, port = host.rpartition(":")
        return name if colon and "]" not in port else host

    def away(self):
        """A request that came through the way in for phones (--remote): never this computer."""
        remote = self.server.remote
        return remote is not None and (self.forwarded() or self.host_name() == remote.name)

    def here(self):
        return self.client_address[0] in HERE_ONLY and not self.forwarded() and not self.away()

    def phone(self):
        """The paired phone this request came from, or None (not away, or not paired)."""
        if not self.away():
            return None
        return self.server.remote.phone(self.headers.get("Cookie", ""), self.headers.get("Tailscale-User-Login", ""))

    def has_key(self):
        """With --share: whether another computer came through the view-only link (its cookie)."""
        key = self.server.share
        for part in self.headers.get("Cookie", "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == VIEW and key and hmac.compare_digest(value.strip().encode("utf-8", "replace"), key.encode()):
                return True
        return False

    def let_in(self, path):
        """With --share, for another computer: a request with the link's key in the address leaves the cookie and
        goes on to the page; one without the key, or asking for what a viewer never gets, is refused. True when
        the request may go on; otherwise the answer has been sent."""
        low = path.lower()
        if low.startswith(NEVER_SERVED) or (not self.here() and low.startswith(NEVER_AWAY)):
            self.send_error(404)
            return False
        if self.away():
            if self.phone() is not None:
                if low.startswith("/remote/") and path not in ("/remote/me", "/remote/leave"):
                    self.send_error(403, "That is for your computer's own page.")
                    return False
                return True
            if path == "/remote/pair" and self.command == "POST":
                return True
            if path in ("/", "/index.html") and self.command in ("GET", "HEAD"):
                page = self.pairing_page()
                if self.command == "GET":
                    self.wfile.write(page.getvalue())
                return False
            self.send_error(403, "Pair this phone first: open its address and type the code from your computer.")
            return False
        if not self.server.share or self.here():
            return True
        given = parse_qs(self.path.split("?", 1)[1] if "?" in self.path else "").get("view", [""])[0]
        if path in ("/", "/index.html") and given and hmac.compare_digest(given.encode("utf-8", "replace"), self.server.share.encode()):
            self.send_response(303)
            self.send_header("Location", "/")
            self.send_header("Set-Cookie", f"{VIEW}={self.server.share}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return False
        if not self.has_key():
            self.send_error(403, "This building opens only through its view-only link. Ask for the link again: it may have changed.")
            return False
        if self.command == "POST" or low.startswith(("/voice/", "/control/", "/brain/")) or low in NOT_SHARED:
            self.send_error(403 if self.command == "POST" else 404, "A view-only link can look, not change anything.")
            return False
        return True

    def kept_back(self, full):
        """Whether a file is one this request never gets, by what it is on disk, however it was spelled: control's
        mail never goes to another computer, the founder's notes never through a view-only link, and Markdown
        in data/ only if it is a how-to company.json lists."""
        data = os.path.join(ROOT, "data")
        folder = os.path.dirname(full)
        while folder.startswith(ROOT + os.sep):  # the paired phones' records, to no one
            if same_file(folder, os.path.join(data, "remote")):
                return True
            folder = os.path.dirname(folder)
        if not self.here():
            folder = os.path.dirname(full)
            while folder.startswith(ROOT + os.sep):
                if same_file(folder, os.path.join(data, "control")):
                    return True
                folder = os.path.dirname(folder)
            if self.server.share and same_file(full, os.path.join(data, "notes.json")):
                return True
        if full.lower().endswith(".md") and full.lower().startswith(data.lower() + os.sep):
            return not any(same_file(full, listed) for listed in howto_files())
        return False

    def allowed(self):
        """A name this server answers to, and on a POST its own page (the Origin). Something forwarded is
        refused unless the way in for phones is on (--remote), and then it must be for that name."""
        remote = self.server.remote
        if self.forwarded() and remote is None:
            return False
        if self.away():
            sent = self.headers.get("X-Forwarded-Host", "").strip().lower().split(":")[0]
            if self.host_name() != remote.name and sent != remote.name:
                return False
            return self.command != "POST" or self.headers.get("Origin") == f"https://{remote.name}"
        host = self.headers.get("Host", "")
        if not host_ok(host, self.server.server_address[1], self.server.lan):
            return False
        return self.command != "POST" or self.headers.get("Origin") == f"http://{host}"

    def voice(self, path, body=b""):
        code, kind, data, extra = VOICE.handle(self.command if self.command != "HEAD" else "GET", path[len("/voice/"):], body)
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for name, value in extra.items():
            self.send_header(name, value)
        self.end_headers()
        return io.BytesIO(data)

    def control(self, path, body=b""):
        """/control/: off unless serve.py was started with --control, and then only for this computer."""
        method = self.command if self.command != "HEAD" else "GET"
        name = path[len("/control/"):]
        control = self.server.control
        if control is None:
            off = name == "token" and method == "GET"
            code, data = (200, {"on": False}) if off else (404, {"error": "Control is off. Start Arnheim with --control to switch it on."})
            kind, data, extra = "application/json; charset=utf-8", json.dumps(data).encode(), {}
        elif not self.here() and not self.phone_controls():
            if self.phone() is not None and name == "token" and method == "GET":
                code, data = 200, {"on": False, "phone": "Control from this phone is off. Switch it on for this phone on your computer."}
            else:
                code, data = 403, {"error": "Only on this computer, or from a phone it has let control agents."}
            kind, data, extra = "application/json; charset=utf-8", json.dumps(data).encode(), {}
        elif not self.here() and not self.server.remote.acted(self.phone(), f"{method} {name}" if method == "POST" else "", 0):
            code, kind, data, extra = 429, "application/json; charset=utf-8", b'{"error": "Too many at once from this phone. Wait a minute."}', {}
        else:
            code, kind, data, extra = control.handle(method, name, body, self.headers.get("X-Arnheim-Control", ""))
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        for header, value in extra.items():
            self.send_header(header, value)
        self.end_headers()
        return io.BytesIO(data)

    def brain(self, path, body=b""):
        """/brain/: off unless serve.py was started with --brain, and then only for this computer, as
        /control/ is. An answer goes back a line at a time, as Claude says it."""
        method = self.command if self.command != "HEAD" else "GET"
        name = path[len("/brain/"):]
        brain = self.server.brain
        if brain is None:
            off = name == "status" and method == "GET"
            code, data = (200, {"on": False}) if off else (404, {"error": "The brain is off. Start Arnheim with --brain to switch it on."})
            kind, data, extra = "application/json; charset=utf-8", json.dumps(data).encode(), {}
        elif not self.here() and self.phone() is None:
            code, kind, data, extra = 403, "application/json; charset=utf-8", b'{"error": "Only on this computer, or a phone paired with it."}', {}
        else:
            # an instruction passed on from a phone counts as control: only while this computer lets that phone,
            # counted and written down like any other
            phone = None if self.here() else self.phone()
            may = self.here() or self.phone_controls()

            def done(key, result=None):
                if result is None:  # about to send: counted, and False for one too many this minute
                    return self.server.remote.acted(phone, "", 0)
                self.server.remote.log(event="control", phone=phone["id"], label=phone["label"], request=f"POST brain pass {key}", result=result)
                return True
            code, kind, data, extra = brain.handle(method, name, body, self.headers.get("X-Arnheim-Brain", ""), may_pass=may, passed=done if phone else None)
        self.send_response(code)
        self.send_header("Content-Type", kind)
        for header, value in extra.items():
            self.send_header(header, value)
        if isinstance(data, bytes):
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            return io.BytesIO(data)
        self.end_headers()  # no length: the answer ends when the connection closes
        self.close_connection = True
        try:
            for part in data:
                self.wfile.write(part)
                self.wfile.flush()
        except OSError:
            pass  # the page stopped listening
        finally:
            data.close()
        return None

    def phone_controls(self):
        """Whether this request is from a paired phone that this computer has let control agents, for now."""
        phone = self.phone()
        return phone is not None and self.server.remote.may_control(phone)

    def pairing_page(self, error=""):
        said = f'<p class="no">{html_escape(error)}</p>' if error else ""
        data = PAIRING.replace("{error}", said).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)

    def remote_route(self, path, body=b""):
        """/remote/: pairing a phone and what it may do. On this computer's page: status, a new code, control
        for a phone, removing phones. From a phone: pairing, what it may do, and leaving."""
        method = self.command if self.command != "HEAD" else "GET"
        name = path[len("/remote/"):]
        remote = self.server.remote

        def answer(code, data, headers=()):
            out = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(out)))
            for header, value in headers:
                self.send_header(header, value)
            self.end_headers()
            return io.BytesIO(out)

        if remote is None:
            return answer(200, {"on": False}) if name == "status" and method == "GET" and self.here() else answer(404, {"error": "Phones are off. Start Arnheim with --remote (docs/phone.md)."})
        if self.away():
            phone = self.phone()
            if name == "pair" and method == "POST":
                given = parse_qs(body.decode("utf-8", "replace")).get("code", [""])[0]
                key, got = remote.pair(given, self.headers.get("User-Agent", ""), self.headers.get("Tailscale-User-Login", ""))
                if key is None:
                    return self.pairing_page(got)
                self.send_response(303)
                self.send_header("Location", "/")
                self.send_header("Set-Cookie", f"{PHONE_COOKIE}={key}; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age={PHONE_LIFE}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return io.BytesIO(b"")
            if phone is not None and name == "me" and method == "GET":
                return answer(200, {"phone": True, "label": phone["label"], "control": round(phone["control"]) if remote.may_control(phone) else 0})
            if phone is not None and name == "leave" and method == "POST":
                remote.remove(phone["id"])
                return answer(200, {"ok": True}, [("Set-Cookie", f"{PHONE_COOKIE}=; Path=/; Secure; HttpOnly; SameSite=Strict; Max-Age=0")])
            return answer(403, {"error": "Not from a phone."})
        if not self.here():
            return answer(403, {"error": "Only on this computer."})
        if method == "GET" and name == "status":
            return answer(200, remote.status())
        if method != "POST" or self.headers.get("X-Arnheim-Remote") != "1":
            return answer(404, {"error": "No such request."})
        try:
            given = json.loads(body.decode("utf-8") or "{}")
        except ValueError:
            return answer(400, {"error": "That wasn't JSON."})
        if not isinstance(given, dict):
            return answer(400, {"error": "That wasn't a JSON object."})
        if name == "code":
            return answer(200, remote.code())
        if name == "grant" and isinstance(given.get("id"), str) and isinstance(given.get("minutes"), (int, float)):
            return answer(200, {"ok": remote.grant(given["id"], given["minutes"])})
        if name == "remove" and (given.get("id") is None or isinstance(given.get("id"), str)):
            return answer(200, {"removed": remote.remove(given.get("id"))})
        return answer(400, {"error": "That request doesn't make sense."})

    def do_POST(self):
        path = unquote(self.path.split("?", 1)[0])
        if not self.allowed():
            self.send_error(403)
            return
        if not self.let_in(path):
            return
        try:
            size = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self.send_error(400)
            return
        known = path.startswith(("/voice/", "/control/", "/brain/", "/remote/"))
        if not known or not 0 <= size <= 2_000_000:
            self.send_error(404 if not known else 413)
            return
        body = self.rfile.read(size)
        if path.startswith("/brain/"):
            reply = self.brain(path, body)
        elif path.startswith("/remote/"):
            reply = self.remote_route(path, body)
        else:
            reply = self.voice(path, body) if path.startswith("/voice/") else self.control(path, body)
        if reply is not None:
            self.wfile.write(reply.getvalue())

    def send_head(self):
        if not self.allowed():
            self.send_error(403)
            return None
        path = unquote(self.path.split("?", 1)[0].split("#", 1)[0])
        if not self.let_in(path):
            return None
        if path.startswith("/voice/"):
            return self.voice(path)
        if path.startswith("/control/"):
            return self.control(path)
        if path.startswith("/brain/"):
            return self.brain(path)
        if path.startswith("/remote/"):
            return self.remote_route(path)
        if path in ("/", "/index.html"):
            path = "/index.html"
        else:
            parts = path.split("/")[1:]
            if len(parts) < 2 or parts[0] not in SHOWN or any(p in ("", ".", "..") or p.startswith(".") or any(c in p for c in "\\:\0") for p in parts):
                self.send_error(404)
                return None
        full = os.path.realpath(os.path.join(ROOT, *path.split("/")[1:]))
        kind = TYPES.get(os.path.splitext(full)[1])
        if not kind or not full.startswith(ROOT + os.sep) or not os.path.isfile(full) or self.kept_back(full):
            self.send_error(404)
            return None
        company = os.path.join(ROOT, "data", "company.json")
        if os.path.basename(full).lower() == "company.json" and os.path.isfile(company) and os.path.samefile(full, company):  # any spelling of it
            with open(full, "rb") as handle:
                body = without_pings(handle.read())
            self.send_response(200)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            return io.BytesIO(body)
        handle = open(full, "rb")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(os.fstat(handle.fileno()).st_size))
        self.end_headers()
        return handle


class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 128  # one page load asks for about 25 files at once
    lan = False
    share = None  # the view-only link's key, with --share
    control = None  # connect/control.py's Control, with --control
    brain = None  # connect/brain.py's Brain, with --brain
    remote = None  # connect/remote.py's Remote, with --remote


def network_address():
    """This computer's address on its network, as a phone would reach it. Nothing is sent: a UDP
    socket only picks the way out when it is connected."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("192.0.2.1", 9))  # an address kept for examples, never reached
        address = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()
    return None if address.startswith(("0.", "127.")) else address


def company_note():
    """Which company the page will show, and why any of data/'s files can't be read."""
    def shown(name):  # as the page will get it: a file inside this folder, links resolved
        path = os.path.realpath(os.path.join(ROOT, "data", name))
        return path if path.startswith(ROOT + os.sep) and os.path.isfile(path) else None

    if not shown("company.json"):
        if os.path.exists(os.path.join(ROOT, "data", "company.json")):
            return ["data/company.json links to somewhere outside this folder, which serve.py doesn't show, "
                    "so the page shows the made-up sample. Copy the files into data/ instead."]
        return ["Showing the sample company, which is made up. To show your own projects and agents, run: "
                f"{'py' if os.name == 'nt' else 'python3'} connect/setup.py"]
    lines = ["Showing your own company, from data/."]
    then = {"notes.json": "The founder's office has no notes until it is fixed."}
    for name in ("company.json", "work.json", "notes.json"):
        path = shown(name)
        if path:
            try:
                with open(path, encoding="utf-8-sig") as handle:  # as a browser reads it, a BOM or not
                    json.load(handle)
            except ValueError as error:  # not JSON, or not UTF-8
                lines.append(f"data/{name} can't be read: {error}. {then.get(name, 'The page will say so until it is fixed.')}")
    return lines


def every_minute(name, when=None):
    """Every minute, runs a connector: connect/routines.py starts the routines that are due (each in the
    background), connect/ping.py sends the ping that is due, connect/projects.py looks at git and GitHub.
    With `when`, only in the minutes it says yes."""
    runner = os.path.join(ROOT, "connect", name)
    while True:
        try:
            if when is None or when():
                subprocess.run([sys.executable, runner], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=60)
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(60 - time.time() % 60 + 1)  # just after each minute begins


def floors_have_folders():
    """Whether data/company.json gives any floor a folder, so there is git to look at (connect/setup.py
    writes them). Read again each time, so a company made while this runs is seen within a minute."""
    try:
        with open(os.path.join(ROOT, "data", "company.json"), encoding="utf-8-sig") as handle:
            company = json.load(handle)
        return any(isinstance(f, dict) and (f.get("folder") or f.get("folders")) for f in company.get("floors") or [])
    except (OSError, ValueError, AttributeError):
        return False


def main():
    parser = argparse.ArgumentParser(description="Shows Arnheim in a browser.")
    parser.add_argument("port", nargs="?", type=int, default=8740, help="the port to use (8740 if left out)")
    parser.add_argument("--lan", action="store_true", help="show it to phones and other computers on this network too")
    parser.add_argument("--share", action="store_true",
                        help="show it on this network only to those you give its view-only link, who can look but not change anything")
    parser.add_argument("--new-link", action="store_true", help="with --share: make a new view-only link, so the old one stops working")
    parser.add_argument("--control", action="store_true",
                        help="let the page on this computer talk to your Claude Code agents, answer their permission requests, and start and stop them")
    parser.add_argument("--routines", action="store_true",
                        help="run the routines in data/company.json when they are due, while this runs (connect/routines.py)")
    parser.add_argument("--pings", action="store_true",
                        help="ping your phone with the morning brief and decisions that wait on you, as data/company.json says, while this runs (connect/ping.py)")
    parser.add_argument("--no-git", action="store_true",
                        help="don't look at your floors' folders for unsaved changes and open pull requests (connect/projects.py)")
    parser.add_argument("--brain", action="store_true",
                        help="let the receptionist and your assistant talk about anything, with Claude through your own Claude Code")
    parser.add_argument("--remote", metavar="NAME",
                        help="let your own paired phone in from anywhere, through a private https way in such as Tailscale Serve "
                             "that answers at NAME (docs/phone.md)")
    args = parser.parse_args()
    if not 0 < args.port < 65536:
        parser.error("the port is a number from 1 to 65535")
    if args.share and args.lan:
        sys.exit("--share is --lan with a view-only link that only its holders can open. Leave out one of them.")
    if args.new_link and not args.share:
        sys.exit("--new-link goes with --share: python3 serve.py --share --new-link")
    away = "--lan" if args.lan else "--share" if args.share else None
    if args.control and away:
        sys.exit(f"Control works only on this computer, so it can't go with {away}. Leave out one of them, or run a second "
                 f"copy on another port: python3 serve.py --control, and python3 serve.py {args.port + 1} {away}")
    if args.brain and away:
        sys.exit(f"The brain works only on this computer, so it can't go with {away}. Leave out one of them, or run a second "
                 f"copy on another port: python3 serve.py --brain, and python3 serve.py {args.port + 1} {away}")
    if args.remote and away:
        sys.exit(f"--remote keeps Arnheim on this computer and lets only paired phones in, so it can't go with {away}. Leave out one of them.")
    try:
        remote = Remote(args.remote, os.path.join(ROOT, "data")) if args.remote else None
    except ValueError as error:
        sys.exit(str(error))
    control = Control() if args.control else None
    try:
        brain = Brain(tell=lambda why: print(f"The brain had no answer: {why}", file=sys.stderr, flush=True), control=control) if args.brain else None
    except ValueError as error:
        sys.exit(str(error))
    try:
        server = Server(("0.0.0.0" if args.lan or args.share else "127.0.0.1", args.port), Handler)
    except OSError as error:
        if error.errno in PORT_TAKEN:
            sys.exit(f"Port {args.port} is already in use, perhaps by another copy of Arnheim. Stop that one, "
                     f"or give another port: python3 serve.py {args.port + 1 if args.port < 65535 else 8741}")
        if error.errno == errno.EACCES:
            sys.exit(f"This computer won't let Arnheim use port {args.port}. Give one above 1024: python3 serve.py 8740")
        raise
    server.lan = args.lan or args.share
    server.remote = remote
    server.share = share_key(new=args.new_link) if args.share else None
    server.control = control
    server.brain = brain
    print(f"Arnheim is at http://127.0.0.1:{args.port}", flush=True)
    if remote:
        print(f"Phones are on: a phone paired with this computer can open https://{remote.name}/ from anywhere your "
              f"private way in reaches. With Tailscale, run once: tailscale serve --bg {args.port}. To pair a phone, open "
              "the Company page here and choose Pair a phone (docs/phone.md).", flush=True)
    if args.control:
        print("Control is on: the page on this computer can talk to your Claude Code agents, answer their "
              "permission requests, and start and stop them (docs/connect.md).", flush=True)
    if brain:
        print(f"The brain is on: the receptionist and your assistant answer with Claude ({brain.model}), through "
              "your own Claude Code and on your own Claude plan. What you ask them goes to Claude with the "
              "building's facts, and nothing is kept on disk (docs/brain.md).", flush=True)
    if args.lan:
        address = network_address()
        where = f"http://{address}:{args.port}" if address else f"this computer's network address, port {args.port}"
        print(f"On phones and other computers on this network, open {where}", flush=True)
        print("Anyone on this network can open it while it runs, data/ included.", flush=True)
    if args.share:
        address = network_address()
        where = f"http://{address}:{args.port}" if address else f"http://<this computer's network address>:{args.port}"
        print(f"The view-only link, for people on this network: {where}/?view={server.share}", flush=True)
        print("Whoever has it can look round and walk in while this runs, but not change anything, and never sees the "
              "founder's notes. It stays the same each time; python3 serve.py --share --new-link makes a new one and ends this one.", flush=True)
    for line in company_note():
        print(line, flush=True)
    if not args.no_git:  # each floor's unsaved changes and open pull requests, once there are floors with folders
        threading.Thread(target=every_minute, args=("projects.py", floors_have_folders), daemon=True).start()
        if floors_have_folders():
            print("Looking at your floors' folders every minute for unsaved changes and open pull requests "
                  "(connect/projects.py). --no-git leaves it off.", flush=True)
    if args.routines:
        threading.Thread(target=every_minute, args=("routines.py",), daemon=True).start()
        print("Routines are on: each floor's routines in data/company.json run when they are due, while this runs "
              "(docs/connect.md, \"Routines\").", flush=True)
    if args.pings:
        threading.Thread(target=every_minute, args=("ping.py",), daemon=True).start()
        print("Pings are on: the morning brief, and decisions that wait on you, go to your phone at the times "
              "\"pings\" in data/company.json gives (docs/connect.md).", flush=True)
    print("Ctrl-C stops it.", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # stopped by its process id: tidy up as for Ctrl-C
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if brain:
            brain.close()


if __name__ == "__main__":
    main()
