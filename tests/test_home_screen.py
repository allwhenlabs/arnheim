"""Arnheim on a phone's or tablet's home screen: the page names its icon and its manifest, the manifest opens the
building full screen from wherever Arnheim is served, the icons are the sizes they say, and the server sends a
picture from src/ only. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import http.client
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import unittest
from urllib.parse import urljoin

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import serve  # noqa: E402  (after the path is set)

APP = os.path.join(ROOT, "src", "app")


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def pixels(path):
    """A PNG's width and height, from its header."""
    with open(path, "rb") as handle:
        head = handle.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", path
    return struct.unpack(">II", head[16:24])


class HomeScreenTest(unittest.TestCase):
    def test_the_page_names_its_icon_and_manifest(self):
        page = read(os.path.join(ROOT, "index.html"))
        for tag in ('<link rel="manifest" href="src/app/manifest.json" crossorigin="use-credentials">',  # with the cookie a view-only link or a paired phone holds
                    '<link rel="apple-touch-icon" href="src/app/icon-180.png">',
                    '<meta name="apple-mobile-web-app-capable" content="yes">',
                    '<meta name="mobile-web-app-capable" content="yes">',
                    '<meta name="apple-mobile-web-app-title" content="Arnheim">',
                    '<meta name="theme-color"'):
            self.assertIn(tag, page)
        self.assertLess(page.index('rel="manifest"'), page.index("<title>"))  # in the head, before anything loads

    def test_the_manifest_opens_the_building_full_screen(self):
        manifest = json.loads(read(os.path.join(APP, "manifest.json")))
        for where in ("http://127.0.0.1:8740", "http://192.168.1.5:8740", "https://my-mac.example.ts.net"):
            base = where + "/src/app/manifest.json"
            self.assertEqual(urljoin(base, manifest["start_url"]), where + "/")
            self.assertEqual(urljoin(base, manifest["scope"]), where + "/")
        self.assertEqual(manifest["display"], "standalone")
        self.assertEqual(manifest["name"], "Arnheim")
        self.assertLessEqual(len(manifest["short_name"]), 12)  # what fits under an icon

    def test_the_icons_are_the_sizes_they_say(self):
        manifest = json.loads(read(os.path.join(APP, "manifest.json")))
        purposes = set()
        for icon in manifest["icons"]:
            wide, high = (int(n) for n in icon["sizes"].split("x"))
            self.assertEqual(pixels(os.path.join(APP, icon["src"])), (wide, high), icon["src"])
            self.assertEqual(icon["type"], "image/png")
            purposes.add(icon.get("purpose", "any"))
        self.assertEqual(purposes, {"any", "maskable"})
        self.assertEqual(pixels(os.path.join(APP, "icon-180.png")), (180, 180))  # the iPhone's and iPad's


class HomeScreenServeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def ask(self, path):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request("GET", path, headers={"Host": f"127.0.0.1:{self.port}"})
            reply = conn.getresponse()
            return reply.status, reply.getheader("Content-Type"), reply.read()
        finally:
            conn.close()

    def test_the_icons_and_manifest_are_sent(self):
        for name in ("icon-180.png", "icon-192.png", "icon-512.png"):
            status, kind, body = self.ask("/src/app/" + name)
            self.assertEqual((status, kind), (200, "image/png"), name)
            self.assertTrue(body.startswith(b"\x89PNG"), name)
        status, kind, body = self.ask("/src/app/manifest.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["display"], "standalone")

    def test_the_icon_needs_no_link_or_pairing(self):
        """A phone fetches its home-screen icon without the cookie a view-only link left, so those four public files
        pass that gate. Everything else still needs the link, the page included."""
        class Away(serve.Handler):  # a request marked "away" stands for one from another computer
            def here(self):
                return self.headers.get("X-Test-From") != "away"
        server = serve.Server(("127.0.0.1", 0), Away)
        server.lan, server.share = True, "k" * 32
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def away(path, method="GET"):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            try:
                conn.request(method, path, headers={"Host": f"127.0.0.1:{server.server_address[1]}", "X-Test-From": "away"})
                return conn.getresponse().status
            finally:
                conn.close()
        for path in serve.HOME_SCREEN:
            self.assertEqual(away(path), 200, path)
            self.assertEqual(away(path, "HEAD"), 200, path)
        for path in ("/", "/index.html", "/src/demo.js", "/src/app/../demo.js", "/src/app/../app/icon-180.png", "/SRC/app/icon-180.png",
                     "/src/app/icon-180.png/", "/data/company.json", "/sample/company.json", "/voice/status"):
            self.assertEqual(away(path), 403, path)
        self.assertEqual(away("/src/app/icon-180.png", "POST"), 403)

    def test_a_linked_icon_file_is_not_let_through(self):
        """If one of the four were ever a link to something else, it would need the view-only link like any file."""
        base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, base, ignore_errors=True)
        os.makedirs(os.path.join(base, "src", "app"))
        os.makedirs(os.path.join(base, "data"))
        with open(os.path.join(base, "data", "company.json"), "w", encoding="utf-8") as handle:
            handle.write('{"company": "private"}')
        shutil.copy(os.path.join(APP, "icon-180.png"), os.path.join(base, "src", "app", "icon-180.png"))
        os.symlink(os.path.join(base, "data", "company.json"), os.path.join(base, "src", "app", "manifest.json"))
        kept, serve.ROOT = serve.ROOT, base
        self.addCleanup(setattr, serve, "ROOT", kept)

        class Away(serve.Handler):
            def here(self):
                return False
        server = serve.Server(("127.0.0.1", 0), Away)
        server.lan, server.share = True, "k" * 32
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)

        def away(path):
            conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
            try:
                conn.request("GET", path, headers={"Host": f"127.0.0.1:{server.server_address[1]}"})
                reply = conn.getresponse()
                return reply.status, reply.read()
            finally:
                conn.close()
        status, body = away("/src/app/manifest.json")
        self.assertEqual(status, 403)
        self.assertNotIn(b"private", body)
        self.assertEqual(away("/src/app/icon-180.png")[0], 200)  # the real file beside it still comes

    def test_a_picture_only_from_src(self):
        self.assertEqual(serve.kind_of(os.path.join(APP, "icon-180.png")), "image/png")
        for elsewhere in (("data", "x.png"), ("sample", "x.png"), ("vendor", "x.png"), ("baked", "x.png"), ("x.png",)):
            self.assertIsNone(serve.kind_of(os.path.join(ROOT, *elsewhere)), elsewhere)
        self.assertIsNone(serve.kind_of(os.path.join(ROOT, "src-old", "x.png")))  # a folder that only starts with src
        self.assertIsNone(serve.kind_of(os.path.join(APP, "icon-180.PNG")))  # the kind is matched exactly, as TYPES is
        self.assertEqual(self.ask("/src/app/icon-180.png.map")[0], 404)


if __name__ == "__main__":
    unittest.main()
