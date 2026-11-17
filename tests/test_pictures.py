"""The photo-real look's pictures (README, "The photo-real look"): serve.py downloads them once, unpacks only a
zip that stays inside baked/, falls back to the drawn look when it can't, --drawn skips them, and a baked/ folder
from another version opens the drawn look. Nothing here reaches the internet. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import hashlib
import http.client
import io
import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serve  # noqa: E402  (after the path is set)

SET = {"baked/building.json": b'{"shells": {}}', "baked/kit/kit.json": b"{}", "baked/kit/desk.bin": b"\0" * 64}


def make_zip(path, entries, links=()):
    with zipfile.ZipFile(path, "w") as out:
        for name, data in entries.items():
            out.writestr(name, data)
        for name in links:  # an entry that unpacks as a link
            info = zipfile.ZipInfo(name)
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            out.writestr(info, "/etc/passwd")


def leftovers(folder):
    return [name for name in os.listdir(folder) if name.startswith(".baked-")]


class Reply(io.BytesIO):
    """What urlopen gives back, as far as fetch_pictures reads it."""


class SafeUnzipTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.zip = os.path.join(self.dir, "x.zip")
        self.into = os.path.join(self.dir, "into")
        os.mkdir(self.into)

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_zip_inside_baked_unpacks(self):
        make_zip(self.zip, dict(SET, **{"baked/people/": b""}))
        serve.safe_unzip(self.zip, self.into)
        with open(os.path.join(self.into, "baked", "kit", "desk.bin"), "rb") as handle:
            self.assertEqual(handle.read(), b"\0" * 64)
        self.assertTrue(os.path.isdir(os.path.join(self.into, "baked", "people")))

    def test_a_way_out_unpacks_nothing(self):
        for bad in ("baked/../evil.json", "../evil.json", "/etc/evil.json", "baked/kit/../../evil.json",
                    "other/evil.json", "baked\\..\\evil.json", "C:/evil.json", "baked/./evil.json", "baked//evil.json",
                    "baked"):
            with self.subTest(bad=bad):
                make_zip(self.zip, dict(SET, **{bad: b"x"}))
                with self.assertRaises(ValueError):
                    serve.safe_unzip(self.zip, self.into)
                self.assertEqual(os.listdir(self.into), [])

    def test_a_link_unpacks_nothing(self):
        make_zip(self.zip, SET, links=("baked/kit/link.bin",))
        with self.assertRaises(ValueError):
            serve.safe_unzip(self.zip, self.into)
        self.assertEqual(os.listdir(self.into), [])

    def test_too_big_unpacks_nothing(self):
        make_zip(self.zip, SET)
        with self.assertRaises(ValueError):
            serve.safe_unzip(self.zip, self.into, most=10)
        self.assertEqual(os.listdir(self.into), [])


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = self.tmp.name
        self.baked = os.path.join(self.dir, "baked")
        self.said = []
        source = os.path.join(self.dir, "src.zip.keep")
        make_zip(source, SET)
        with open(source, "rb") as handle:
            self.data = handle.read()
        os.remove(source)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, opener, data=None):
        data = self.data if data is None else data
        return serve.fetch_pictures(self.said.append, folder=self.baked, url="https://example.invalid/baked.zip",
                                    size=len(data), sha256=hashlib.sha256(data).hexdigest(), opener=opener)

    def test_offline_leaves_nothing(self):
        def offline(request, timeout):
            raise urllib.error.URLError(socket.gaierror(8, "nodename nor servname provided, or not known"))
        self.assertEqual(self.fetch(offline), "no connection to GitHub")
        self.assertFalse(os.path.exists(self.baked))
        self.assertEqual(leftovers(self.dir), [])
        self.assertEqual(len(self.said), 1)  # the one line before it starts, with the size
        self.assertIn("MB from GitHub", self.said[0])

    def test_a_refusal_and_a_stall_say_so(self):
        def refused(request, timeout):
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)

        def stalled(request, timeout):
            raise socket.timeout("timed out")
        self.assertEqual(self.fetch(refused), "GitHub answered 404 Not Found")
        self.assertEqual(self.fetch(stalled), "the connection stalled")
        self.assertFalse(os.path.exists(self.baked))
        self.assertEqual(leftovers(self.dir), [])

    def test_cut_short_leaves_nothing(self):
        cut = lambda request, timeout: Reply(self.data[:100])  # noqa: E731
        self.assertEqual(self.fetch(cut), "the download wasn't the file this version of Arnheim expects")
        self.assertFalse(os.path.exists(self.baked))
        self.assertEqual(leftovers(self.dir), [])

    def test_another_file_is_not_unpacked(self):
        other = os.path.join(self.dir, "other.zip.keep")
        make_zip(other, {"baked/building.json": b'{"other": true}'})
        with open(other, "rb") as handle:
            data = handle.read()
        os.remove(other)
        given = lambda request, timeout: Reply(data)  # noqa: E731
        trouble = serve.fetch_pictures(self.said.append, folder=self.baked, url="https://example.invalid/baked.zip",
                                       size=len(self.data), sha256=hashlib.sha256(self.data).hexdigest(), opener=given)
        self.assertEqual(trouble, "the download wasn't the file this version of Arnheim expects")
        self.assertFalse(os.path.exists(self.baked))
        self.assertEqual(leftovers(self.dir), [])

    def test_the_right_file_lands_whole(self):
        seen = []

        def opener(request, timeout):
            seen.append((request.full_url, timeout))
            return Reply(self.data)
        self.assertIsNone(self.fetch(opener))
        self.assertEqual(seen, [("https://example.invalid/baked.zip", 30)])
        self.assertEqual(serve.files_print(serve.folder_files(self.baked)),
                         serve.files_print((name[len("baked/"):], len(data)) for name, data in SET.items()))
        self.assertEqual(leftovers(self.dir), [])


class LookTest(unittest.TestCase):
    """Which look the page opens in, from serve.py's /look, and what it says at the start."""

    @classmethod
    def setUpClass(cls):
        cls.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.baked = os.path.join(self.tmp.name, "baked")
        for name, data in SET.items():
            path = os.path.join(self.tmp.name, *name.split("/"))
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "wb") as handle:
                handle.write(data)
        self.right = serve.files_print(serve.folder_files(self.baked))
        self.patches = [mock.patch.object(serve, "BAKED", self.baked)]
        for patch in self.patches:
            patch.start()
        self.server.drawn = False
        self.server.fetched = None

    def tearDown(self):
        for patch in self.patches:
            patch.stop()
        self.server.drawn = False
        self.server.fetched = None
        self.tmp.cleanup()

    def look(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", "/look", headers={"Host": f"127.0.0.1:{self.port}"})
            reply = conn.getresponse()
            self.assertEqual(reply.status, 200)
            self.assertIn("json", reply.getheader("Content-Type"))
            return json.loads(reply.read())
        finally:
            conn.close()

    def test_the_right_pictures_open_photo_real(self):
        with mock.patch.dict(serve.PICTURES, files=self.right):
            self.assertEqual(serve.pictures_state(), ("photo", None))
            with open(os.path.join(self.baked, ".DS_Store"), "wb") as handle:  # a file browser's clutter changes nothing
                handle.write(b"x")
            self.assertEqual(self.look(), {"look": "photo"})

    def test_another_version_opens_drawn_and_says_how_to_refresh(self):
        self.assertEqual(serve.pictures_state(), ("drawn", serve.WHY_OTHER))  # not the set PICTURES names
        with mock.patch.dict(serve.PICTURES, files=self.right):
            with open(os.path.join(self.baked, "kit", "desk.bin"), "ab") as handle:  # one file changed
                handle.write(b"\0")
            self.assertEqual(self.look(), {"look": "drawn", "why": serve.WHY_OTHER})
            os.remove(os.path.join(self.baked, "kit", "desk.bin"))  # or half unpacked
            self.assertEqual(serve.pictures_state()[0], "drawn")
        self.assertIn("delete the baked folder and start serve.py again", serve.WHY_OTHER)

    @unittest.skipIf(os.name == "nt", "links need more rights on Windows")
    def test_a_link_outside_opens_drawn(self):
        outside = tempfile.TemporaryDirectory()
        self.addCleanup(outside.cleanup)
        moved = os.path.join(outside.name, "baked")
        os.rename(self.baked, moved)
        os.symlink(moved, self.baked)
        with mock.patch.dict(serve.PICTURES, files=self.right):
            self.assertEqual(serve.pictures_state(), ("drawn", serve.WHY_AWAY))

    def test_offline_at_the_start_opens_drawn_and_says_so(self):
        os.rename(self.baked, self.baked + "-away")
        said = []
        why = serve.pictures_at_start(False, said.append, fetch=lambda say: "no connection to GitHub")
        self.assertEqual(why, serve.WHY_FAILED.format("no connection to GitHub"))
        self.assertNotIn("\n", why)
        self.server.fetched = why
        self.assertEqual(self.look(), {"look": "drawn", "why": why})

    def test_fetched_at_the_start_opens_photo_real(self):
        os.rename(self.baked, self.baked + "-away")

        def fetch(say):
            os.rename(self.baked + "-away", self.baked)
            return None
        said = []
        with mock.patch.dict(serve.PICTURES, files=self.right):
            self.assertIsNone(serve.pictures_at_start(False, said.append, fetch=fetch))
        self.assertEqual(said, ["The pictures are in baked/, so the page shows the photo-real look."])

    def test_drawn_skips_the_download(self):
        os.rename(self.baked, self.baked + "-away")

        def never(say):
            raise AssertionError("--drawn must not download anything")
        self.assertIsNone(serve.pictures_at_start(True, print, fetch=never))
        self.server.drawn = True
        self.assertEqual(self.look(), {"look": "drawn"})  # asked for, so nothing to explain


class ReadmeTest(unittest.TestCase):
    def test_the_hand_download_is_the_same_release(self):
        with open(os.path.join(ROOT, "README.md"), encoding="utf-8") as handle:
            readme = handle.read()
        self.assertIn(f"curl -LO {serve.PICTURES['url']}", readme)
        self.assertEqual(len(serve.PICTURES["sha256"]), 64)
        self.assertEqual(len(serve.PICTURES["files"]), 64)


class DrawnFlagTest(unittest.TestCase):
    def test_serve_py_drawn_starts_without_downloading(self):
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()
        before = set(os.listdir(ROOT))
        proc = subprocess.Popen([sys.executable, os.path.join(ROOT, "serve.py"), str(port), "--drawn", "--no-git"],
                                cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                universal_newlines=True)
        try:
            lines = []
            deadline = time.time() + 20
            while time.time() < deadline:
                line = proc.stdout.readline()
                if not line:
                    break
                lines.append(line)
                if line.startswith("Ctrl-C stops it."):
                    break
            self.assertTrue(any(x.startswith("Ctrl-C stops it.") for x in lines), lines)
            self.assertFalse(any("Downloading" in x or "drawn look" in x for x in lines), lines)
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            conn.request("GET", "/look", headers={"Host": f"127.0.0.1:{port}"})
            self.assertEqual(json.loads(conn.getresponse().read()), {"look": "drawn"})
            conn.close()
        finally:
            proc.terminate()
            proc.wait(10)
            proc.stdout.close()
        self.assertEqual(set(os.listdir(ROOT)) - before, set())  # no download, and nothing left behind


if __name__ == "__main__":
    unittest.main()
