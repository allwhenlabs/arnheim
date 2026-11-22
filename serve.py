#!/usr/bin/env python3
"""Shows Arnheim: run `python3 serve.py`, then open the address it prints.

  python3 serve.py          on this computer only, at http://127.0.0.1:8740
  python3 serve.py 8741     on another port
  python3 serve.py --lan    on phones and other computers on this network too (README, "Phones")
  python3 serve.py --share  the same, but only for those you give its view-only link (README, "A view-only link")
  python3 serve.py --drawn  in the drawn look, without downloading the photo-real look's pictures
  python3 serve.py --always  start it now and each time you log in, so it keeps running when this window
                            closes (Mac and Linux; --always off takes that out again)
  python3 serve.py --set-up-voice
                            give this computer the voice the walk's people speak with, once (1.5 to 3 GB;
                            README, "Voice")
  python3 serve.py --control  and let the page talk to your Claude Code agents, answer their
                            permission requests, and start and stop them (docs/connect.md)
  python3 serve.py --brain  and let the receptionist and your assistant talk about anything, with
                            Claude through your own Claude Code (docs/brain.md)
  python3 serve.py --remote my-mac.your-tailnet.ts.net
                            and let your own phone in, from anywhere, through a private way in such as
                            Tailscale Serve, once it is paired with a code from this computer (docs/phone.md)

It opens the page in your browser when it starts in a terminal (--no-browser leaves that). If you chose,
in connect/setup.py, to answer your agents from the building, it starts with --control on (data/serve.json;
--no-control leaves it off this time).

It serves the page and its files from this folder, and nothing else: no other folders, no
listings, nothing cached, so a change shows on the next reload. Your own company goes in data/
(README, "Make it yours"); without it, the page shows the made-up sample. The page opens in the photo-real
look, whose pictures (baked/) it downloads the first time, once, from this version's release on GitHub; with no
connection, or with pictures from another version, it shows the drawn look and says why (README, "The photo-real
look"). It answers only to the
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
The page on this computer, and only there, can also connect your agents (/setup/, connect/setup.py run here with
what you chose on the page) and update Arnheim (/update): once a day, and at the start, a git checkout of Arnheim
asks GitHub whether a newer one is out, sending only which version it is (the "Look for a newer Arnheim" switch).
"""
import argparse
import errno
import hashlib
import hmac
import http.client
import http.server
import io
import ipaddress
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import webbrowser
import zipfile
from html import escape as html_escape
from urllib.parse import parse_qs, unquote

from connect import always, switches
from connect import secret_scan
from connect import day as day_cycle  # the daily cycle: a plan in the morning, a close in the evening
from connect import night as night_shift  # the night shift: approved work, overnight, on allowance that would go unused
from connect import week as week_page  # the week on one page: each floor's week, and where the allowance went
from connect import setup as connect_setup
from connect import agent_setup  # setting your agents up well, from the page (/setup/well, /setup/agents)
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
ICONS = {".png": "image/png"}  # the home-screen icons (src/app/): from src/ only, so a picture left in data/ stays put
# What a phone fetches for its home-screen icon, without the cookie a view-only link or a pairing left: the same public
# files for everyone, so they pass those two gates. Nothing else does.
HOME_SCREEN = ("/src/app/manifest.json", "/src/app/icon-180.png", "/src/app/icon-192.png", "/src/app/icon-512.png")
PORT_TAKEN = {errno.EADDRINUSE, getattr(errno, "WSAEADDRINUSE", errno.EADDRINUSE)}
HERE_ONLY = ("127.0.0.1", "::1", "::ffff:127.0.0.1")  # what this computer's own requests come from
SHARE_KEY = os.path.join(ROOT, ".share-key")  # the view-only link's key (--share), kept so the link stays the same
VIEW = "arnheim_view"  # the cookie a view-only link leaves, so the page's own files come with it
KEY = re.compile(r"^[A-Za-z0-9_-]{20,64}$")
# Control's mail with Claude Code, and each agent's screen (connect/live.py: its steps and the lines it changed): never to
# another computer, link or not. A paired phone that controls agents reads the screens only through /control/live.
NEVER_AWAY = ("/data/control/", "/data/live/")
HERE_ONLY_FOLDERS = ("control", "live")  # the same, in data/, by what each is on disk
# Control requests sent as POST that only read (an agent's screen, its changes): counted for a phone, never logged
READS = ("live", "changes")
# Show me (connect/show.py): pictures of the projects' own pages, for this computer only (a phone gets one through
# /control/show_image), and its two reads, counted for a phone, never logged.
NEVER_AWAY = NEVER_AWAY + ("/data/shows/",)
HERE_ONLY_FOLDERS = HERE_ONLY_FOLDERS + ("shows",)
READS = READS + ("shows", "show_image")
READS += day_cycle.READS  # the daily cycle's read, "day" (connect/day.py)
# The daily cycle's days (data/day/): your plan in your words, for this computer only, as control's mail is. A paired
# phone reads today's through /control/day.
NEVER_AWAY = NEVER_AWAY + ("/data/day/",)
# Where the leads' decisions were kept before data/control/: moved there on the first read, never served away before it.
NEVER_AWAY = NEVER_AWAY + ("/data/decisions.json",)
HERE_ONLY_FOLDERS = HERE_ONLY_FOLDERS + ("day",)
READS += night_shift.READS  # the night shift's read, "night" (connect/night.py)
READS += week_page.READS  # the week on one page's read, "week" (connect/week.py): it writes nothing, so it keeps no folder
NOT_SHARED = ("/data/notes.json",)  # the founder's notes: never through a view-only link
NEVER_SERVED = ("/data/remote/",)  # the paired phones and their log: never to anyone, this computer included
# One front door's ready tasks (connect/intake.py): read only through /control/, never as files, this computer included.
NEVER_SERVED += ("/data/control/intake/",)
# The night shift's nights and Tonight ticks (connect/night.py): read only through /control/ too.
NEVER_SERVED += ("/data/night/",)
# A request that came through a proxy carries one of these. Without --remote it is refused; with it, it is a phone's.
FORWARDED = ("X-Forwarded-For", "X-Forwarded-Host", "X-Forwarded-Proto", "Forwarded", "X-Real-IP",
             "Tailscale-User-Login", "Tailscale-User-Name", "Tailscale-Headers-Info")
# Both are checked by spelling in lower case, and again by what the file is on disk: a Mac's disk takes
# /data/Notes.json for /data/notes.json.
BAKED = os.path.join(ROOT, "baked")
SAVED = os.path.join(ROOT, "data", "serve.json")  # what you chose in connect/setup.py: {"control": true}
# The photo-real look's pictures this version of Arnheim is made for: baked/, from a release's baked.zip (README,
# "The photo-real look"). A new bake goes out as a new release, and these four change with it (studio/publish.py).
PICTURES = {
    "url": "https://github.com/allwhenlabs/arnheim/releases/download/photo-real-3/baked.zip",
    "bytes": 52337228,  # the zip
    "sha256": "aa09c0863f47062658d64fe9853181af05b80052b671387bf7a8fa619a290b0b",  # the zip's
    "files": "c234a46095c053ee032289b8a03f42f6177ef5a2c9bed0eb235c3b7c0849c5bc",  # baked/'s files, by name and size (files_print)
}
CLUTTER = ("Thumbs.db", "desktop.ini")  # what a file browser leaves in a folder it has shown; hidden files are left out too
WHY_MISSING = ("Showing the drawn look: the photo-real pictures aren't here. Start serve.py again to download them "
               "(README, \"The photo-real look\").")
WHY_FAILED = "Showing the drawn look: the photo-real pictures couldn't be downloaded ({}). serve.py tries again the next time it starts."
WHY_OTHER = ("Showing the drawn look: the pictures in the baked folder are from another version of Arnheim. To get the "
             "right ones, delete the baked folder and start serve.py again.")
WHY_AWAY = ("Showing the drawn look: the baked folder links to somewhere outside this folder, which serve.py doesn't show. "
            "Delete the link and start serve.py again to download the pictures.")


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


def kind_of(full):
    """The Content-Type a file of Arnheim's is sent with, or None for a kind it never sends. A PNG only from src/."""
    ext = os.path.splitext(full)[1]
    if ext in ICONS:
        return ICONS[ext] if full.startswith(os.path.join(ROOT, "src") + os.sep) else None
    return TYPES.get(ext)


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
<p>On your computer, open Arnheim's Settings and choose Pair a phone. Type the code it shows here.</p>
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
        if path in HOME_SCREEN and self.command in ("GET", "HEAD"):
            named = os.path.join(ROOT, *path.split("/")[1:])
            if os.path.realpath(named) == named:  # the file itself, never a link to something else
                return True
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
        mail and the agents' screens never go to another computer, the founder's notes never through a view-only link, and Markdown
        in data/ only if it is a how-to company.json lists."""
        data = os.path.join(ROOT, "data")
        folder = os.path.dirname(full)
        while folder.startswith(ROOT + os.sep):  # the paired phones' records, to no one
            if same_file(folder, os.path.join(data, "remote")):
                return True
            if same_file(folder, os.path.join(data, "control", "intake")):  # one front door's ready tasks, to no one
                return True
            if same_file(folder, os.path.join(data, "night")):  # the night shift's nights and Tonight ticks, to no one
                return True
            folder = os.path.dirname(folder)
        if not self.here():
            folder = os.path.dirname(full)
            while folder.startswith(ROOT + os.sep):
                if any(same_file(folder, os.path.join(data, name)) for name in HERE_ONLY_FOLDERS):
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
            code, data = (200, {"on": False}) if off else (404, {"error": "Control is off. Switch it on in Settings, under Switches, or start Arnheim with --control."})
            kind, data, extra = "application/json; charset=utf-8", json.dumps(data).encode(), {}
        elif not self.here() and not self.phone_controls():
            if self.phone() is not None and name == "token" and method == "GET":
                code, data = 200, {"on": False, "phone": "Control from this phone is off. Switch it on for this phone on your computer."}
            else:
                code, data = 403, {"error": "Only on this computer, or from a phone it has let control agents."}
            kind, data, extra = "application/json; charset=utf-8", json.dumps(data).encode(), {}
        elif not self.here() and not self.server.remote.acted(self.phone(), f"{method} {name}" if method == "POST" and name not in READS else "", 0):
            code, kind, data, extra = 429, "application/json; charset=utf-8", b'{"error": "Too many at once from this phone. Wait a minute."}', {}
        else:
            control.brain = getattr(self.server, "brain", None)  # one front door: a floor's lead writes ready tasks with it while it is on
            code, kind, data, extra = control.handle(method, name, body, self.headers.get("X-Arnheim-Control", ""))
            if self.server.control is not control:  # switched off while this was answered: nobody is here to answer
                try:
                    os.remove(control.box.path("watched"))
                except OSError:
                    pass
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
            code, data = (200, {"on": False}) if off else (404, {"error": "The brain is off. Switch it on in Settings, under Switches, or start Arnheim with --brain."})
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

    def switches(self, body=None):
        """/switches: each feature on or off (connect/switches.py), for the page on this computer only. GET gives
        them with the page's token; POST {"name", "on"} with that token changes one, at once and for every start."""
        board = self.server.board
        own = host_ok(self.headers.get("Host", ""), self.server.server_address[1])  # 127.0.0.1 or localhost, even with --lan
        if board is None or not self.here() or not own:
            code, data = 403, {"error": "The switches are only on this computer's own page."}
        elif body is None:
            code, data = 200, {"token": board.token, "switches": board.listing()}
        elif not hmac.compare_digest(self.headers.get("X-Arnheim-Switches", "").encode("utf-8", "replace"), board.token.encode()):
            code, data = 403, {"error": "This page can't change the switches. Reload it."}
        else:
            try:
                given = json.loads(body.decode("utf-8") or "{}")
            except (UnicodeDecodeError, ValueError):
                given = None
            if not isinstance(given, dict) or given.get("name") not in switches.NAMES or not isinstance(given.get("on"), bool):
                code, data = 400, {"error": "That isn't a switch."}
            else:
                try:
                    note = board.switch(given["name"], given["on"])
                    code, data = 200, {"token": board.token, "switches": board.listing(), **({"note": note} if note else {})}
                except Refused as why:
                    code, data = 409, {"error": str(why), "switches": board.listing()}
        out = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        return io.BytesIO(out)

    def own_page(self):
        """The page on this computer, by 127.0.0.1 or localhost, even with --lan: what /switches, /setup/ and /update answer."""
        return self.server.board is not None and self.here() and host_ok(self.headers.get("Host", ""), self.server.server_address[1])

    def token_ok(self):
        given = self.headers.get("X-Arnheim-Switches", "").encode("utf-8", "replace")
        return hmac.compare_digest(given, self.server.board.token.encode())

    def json_answer(self, code, data):
        out = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        return io.BytesIO(out)

    def setup_route(self, path, body=None):
        """/setup/: connecting your agents from the made-up company's page (connect/setup.py, run here), and Undo.
        GET here and plan say what there is; POST connect and undo, with the page's token, do it."""
        name = path[len("/setup/"):]
        if not self.own_page():
            return self.json_answer(403, {"error": "Connecting your agents works only on this computer's own page."})
        data = os.path.dirname(SAVED)
        if body is None:
            if name == "here":
                return self.json_answer(200, {"token": self.server.board.token, **setup_here(data)})
            if name == "plan":
                return self.json_answer(200, {"token": self.server.board.token, **setup_plan(data)})
            if name == "agents":  # Settings' card: what is in place on each floor
                return self.json_answer(200, {"token": self.server.board.token, **well_status(data)})
            return self.json_answer(404, {"error": "No such request."})
        if not self.token_ok():
            return self.json_answer(403, {"error": "This page can't connect your agents. Reload it."})
        try:
            given = json.loads(body.decode("utf-8") or "{}")
        except (UnicodeDecodeError, ValueError):
            given = None
        if not isinstance(given, dict):
            return self.json_answer(400, {"error": "That wasn't a JSON object."})
        if name == "connect":
            return self.json_answer(*setup_connect(given, data, self.server.board))
        if name == "undo":
            return self.json_answer(*setup_undo(data))
        if name == "well":  # a plan only, for a folder typed or a check changed: nothing changes
            return self.json_answer(*well_plan(given, data))
        if name == "agents":  # Settings' Set up: what is missing on floors already connected
            return self.json_answer(*well_apply(given, data))
        return self.json_answer(404, {"error": "No such request."})

    def update_route(self, body=None):
        """/update: whether a newer Arnheim is out (look_for_newer), and Update now, for this computer's page only."""
        if not self.own_page():
            return self.json_answer(403, {"error": "Updating works only on this computer's own page."})
        if body is None:
            newer = self.server.update
            return self.json_answer(200, {"token": self.server.board.token, **({"behind": newer["behind"]} if newer else {})})
        if not self.token_ok():
            return self.json_answer(403, {"error": "This page can't update Arnheim. Reload it."})
        done, words = update_now(self.server)
        if not done:
            return self.json_answer(409, {"error": words})
        if words != UP_TO_DATE:
            self.server.update = None
            threading.Thread(target=restart_self, args=(self.server,), daemon=True).start()
            return self.json_answer(200, {"said": words, "restarting": True})
        self.server.update = None
        return self.json_answer(200, {"said": words})

    def secrets_route(self, path, body=None):
        """/secrets/: the secrets check (connect/secret_scan.py), for this computer's own page only, never a phone, --lan
        or --share. GET gives what it found; POST check, out, exclude, undo and forget, with the page's token."""
        if not self.own_page():
            return self.json_answer(403, {"error": "The secrets check is only on this computer's own page."})
        if body is not None and not self.token_ok():
            return self.json_answer(403, {"error": "This page can't change that. Reload it."})
        code, said = secret_scan.handle(path[len("/secrets/"):], body, os.path.dirname(SAVED), self.server.board.on("secrets"))
        return self.json_answer(code, {"token": self.server.board.token, **said})

    def look(self):
        """/look: which look the page opens in, and, when it is the drawn one but wasn't asked for, why in one line."""
        if self.server.drawn:
            said = {"look": "drawn"}
        else:
            look, why = pictures_state()
            if look == "drawn" and self.server.fetched and not os.path.lexists(BAKED):
                why = self.server.fetched  # why the download at the start didn't work
            said = {"look": look, "why": why} if why else {"look": look}
        data = json.dumps(said).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        return io.BytesIO(data)

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
        if path.startswith("/secrets/"):  # the secrets check's fixes (connect/secret_scan.py)
            reply = self.secrets_route(path, self.rfile.read(size)) if 0 <= size <= 100_000 else self.json_answer(413, {"error": "Too big."})
            self.wfile.write(reply.getvalue())
            return
        known = path.startswith(("/voice/", "/control/", "/brain/", "/remote/", "/setup/")) or path in ("/switches", "/update")
        if not known or not 0 <= size <= 2_000_000:
            self.send_error(404 if not known else 413)
            return
        body = self.rfile.read(size)
        if path == "/switches":
            reply = self.switches(body)
        elif path.startswith("/setup/"):
            reply = self.setup_route(path, body)
        elif path == "/update":
            reply = self.update_route(body)
        elif path.startswith("/brain/"):
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
        if path == "/look":
            return self.look()
        if path == "/switches":
            return self.switches()
        if path.startswith("/setup/"):
            return self.setup_route(path)
        if path == "/update":
            return self.update_route()
        if path.startswith("/secrets/"):
            return self.secrets_route(path)
        if path in ("/", "/index.html"):
            path = "/index.html"
        else:
            parts = path.split("/")[1:]
            if len(parts) < 2 or parts[0] not in SHOWN or any(p in ("", ".", "..") or p.startswith(".") or any(c in p for c in "\\:\0") for p in parts):
                self.send_error(404)
                return None
        full = os.path.realpath(os.path.join(ROOT, *path.split("/")[1:]))
        kind = kind_of(full)
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


class Refused(Exception):
    """A switch the page can't change now, in words for the person who pressed it."""


class Switchboard:
    """The switches as this start has them (connect/switches.py): what you chose in Settings, unless a word
    given to serve.py as it started holds one for this start. A change works at once: control and the brain are
    made or put away here, and the minute jobs ask before each run."""

    def __init__(self, args, away, make_brain=None):
        self.data = os.path.dirname(SAVED)
        self.token = secrets.token_urlsafe(24)
        self.lock = threading.Lock()
        self.server = None
        self.kept = None  # the Control made once, kept while control is off, so agents started here stay known
        self.make_brain = make_brain
        given = lambda word: bool(getattr(args, word, False))  # noqa: E731
        held = {}
        if away:  # control and the brain work only on this computer
            held["control"] = held["brain"] = (False, away)
        if given("control"):
            held["control"] = (True, "--control")
        elif given("no_control"):
            held["control"] = (False, "--no-control")
        if given("brain"):
            held["brain"] = (True, "--brain")
        if given("routines"):
            held["routines"] = (True, "--routines")
        if given("pings"):
            held["pings"] = (True, "--pings")
        if given("no_git"):
            held["git"] = (False, "--no-git")
        self.held = held

    def on(self, name):
        held = self.held.get(name)
        return held[0] if held else switches.on(name, self.data)

    def listing(self):
        """The switches for the page. Control and the brain as they are running now: a brain kept on that
        couldn't start shows as off, so pressing it tries again and says why."""
        rows = switches.listing(self.data, self.held)
        server = self.server
        if server is not None:
            for row in rows:
                if row["name"] == "control":
                    row["on"] = server.control is not None
                elif row["name"] == "brain":
                    row["on"] = server.brain is not None
        return rows

    def switch(self, name, on):
        """Changes one switch, for now and every start. Refused, with nothing changed, for one a start word
        holds, for one that can't be kept on disk, for the brain or control when it can't start, and for
        control while agents started from the building are still at work. Gives a note to show, or None."""
        with self.lock:
            held = self.held.get(name)
            if held:
                where = "only on this computer" if held[1] in ("--lan", "--share") else None
                raise Refused(f"Arnheim started with {held[1]}, which holds this for now"
                              + (f": it works {where}." if where else f". Start it without {held[1]} to switch it here."))
            server = self.server
            if name == "control" and not on and server is not None and server.control is not None:
                working = [r for r in list(server.control.runs.values()) if server.control.alive(r)]
                if working:
                    raise Refused(f"{len(working)} agent{'s' if len(working) != 1 else ''} started from the building "
                                  f"{'are' if len(working) != 1 else 'is'} still at work, and only control can stop "
                                  f"{'them' if len(working) != 1 else 'it'} from here. Stop {'them' if len(working) != 1 else 'it'} first, then switch this off.")
            before = switches.saved(self.data).get(name)
            try:
                switches.save(name, on, self.data)
            except (OSError, ValueError) as error:
                raise Refused(f"The switch couldn't be kept in data/serve.json: {error}")
            if server is None:
                return None
            try:
                if name == "brain" and on and server.brain is None:
                    server.brain = self.make_brain(server.control)
                if name == "control" and on and self.kept is None:
                    self.kept = server.control or Control()
            except (ValueError, OSError) as error:
                try:  # kept off, so a brain that can't start here doesn't stay "on" with no way to switch it off
                    switches.save(name, False, self.data) if name == "brain" else switches.restore(name, before, self.data)
                except OSError:
                    pass
                raise Refused(f"{'The brain' if name == 'brain' else 'Control'} can't start: {error}")
            if name == "brain" and not on and server.brain is not None:
                gone, server.brain = server.brain, None
                gone.close()
            if name == "control":
                server.control = self.kept if on else None
                if not on and self.kept is not None:
                    try:  # nobody can answer here now: a waiting request goes back to the agent's own window at once
                        os.remove(self.kept.box.path("watched"))
                    except OSError:
                        pass
                if server.brain is not None:
                    server.brain.control = server.control  # the assistant passes things on only while control is on
            return None


class Server(http.server.ThreadingHTTPServer):
    request_queue_size = 128  # one page load asks for about 25 files at once
    lan = False
    share = None  # the view-only link's key, with --share
    control = None  # connect/control.py's Control, with --control
    brain = None  # connect/brain.py's Brain, with --brain
    remote = None  # connect/remote.py's Remote, with --remote
    board = None  # the switches as this start has them (Switchboard)
    drawn = False  # --drawn: the page opens in the drawn look, and nothing is downloaded
    fetched = None  # why the photo-real pictures couldn't be downloaded at the start, if they couldn't
    update = None  # {"behind": n} while GitHub has a newer Arnheim than this copy (look_for_newer)


# ---------- connecting your agents from the page (connect/setup.py, run here) ----------

SETUP_LOCK = threading.Lock()  # one setup at a time, and setup's data folder set for it
SETUP_MOST_FOLDERS = 50
CLAUDE_CODE_URL = "https://claude.com/claude-code"


def home_said(lines, tool):
    """What setup did, as the page shows it: ~ for the home folder, as a person would write it (and as a screenshot of
    it should say), without the computer's user name. Only for showing: the files themselves keep whole paths."""
    mine = tool.home()
    out = []
    for line in lines:
        if line.strip():
            out.append(line.replace(mine + os.sep, "~" + os.sep) if mine and mine != os.sep else line)
    return out


def setup_tool(data):
    """connect/setup.py, writing to this server's data folder (setup's own is the same unless ARNHEIM_DATA says
    otherwise). Called with SETUP_LOCK held."""
    connect_setup.DATA = data
    return connect_setup


def setup_here(data):
    """What the made-up company's card needs at once: whether Claude Code is on this computer."""
    tool = connect_setup
    return {"claude": tool.claude_code_here(), "install": CLAUDE_CODE_URL,
            "company": os.path.isfile(os.path.join(data, "company.json")),
            "codex": tool.codex_here()}  # with control off, Carry on at a limit offers Codex only where it is (src/carry-on.js)


def setup_plan(data):
    """What Connect my agents shows before anything changes: the projects setup.py finds, most recent first, with ~
    for the home folder; whether Claude Code and Codex are here, and Codex's notes as setup gives them; and the
    answer about control kept from before, if any."""
    with SETUP_LOCK:
        tool = setup_tool(data)
        found = tool.find_projects()[:tool.MOST]
        codex = tool.codex_here()
        version = tool.codex_version() if codex else None
        old = bool(version) and version < tool.CODEX_HOOKS
        notes = [tool.codex_old_note(version, done=False)] if old else tool.codex_notes() if codex else []
        try:
            kept = tool.saved_choices().get("control")
        except tool.Refused:
            kept = None
        well = agent_setup.shown_plan(agent_setup.plan([p["folder"] for p in found], tool), tool)  # Set your agents up well
    return {
        "well": well,
        "claude": tool.claude_code_here(), "install": CLAUDE_CODE_URL,
        "codex": {"here": codex, "version": f"{version[0]}.{version[1]}" if version else None, "hooks": codex and not old, "notes": notes},
        "projects": [{"folder": tool.shown(p["folder"]), "label": tool.label_of(p["folder"]), "when": tool.ago(p["at"]),
                      "git": bool(p["repo"])} for p in found],
        "control": kept if isinstance(kept, bool) else None,
        "company": os.path.isfile(os.path.join(data, "company.json")),
    }


def setup_connect(given, data, board=None):
    """Connect my agents: setup.py for the folders chosen on the page, as `python3 connect/setup.py --folder ... --yes`
    would, but with the page's answer about control, and never offering to start at login. Only folders setup found
    (by the name the page showed) and one typed folder that is there and isn't too wide are taken. Control chosen is
    switched on through the Switchboard, so it works at once. Gives (code, answer)."""
    folders, typed, control = given.get("folders", []), given.get("typed") or "", given.get("control")
    if not isinstance(folders, list) or len(folders) > SETUP_MOST_FOLDERS or not all(isinstance(f, str) for f in folders) \
            or not isinstance(typed, str) or len(typed) > 4096 or not isinstance(control, bool):
        return 400, {"error": "That request doesn't make sense."}
    lines = []
    with SETUP_LOCK:
        tool = setup_tool(data)
        found = {}
        for p in tool.find_projects()[:tool.MOST]:
            found[tool.shown(p["folder"])] = found[p["folder"]] = p["folder"]
        chosen = []
        for name in folders:
            if name not in found:
                return 400, {"error": f"{name} isn't one of the projects found. Reload the page and try again."}
            chosen.append(found[name])
        said = typed.strip().strip("'\"")
        if said:
            full = os.path.expanduser(said)
            if "\0" in said or not os.path.isabs(full):
                return 400, {"error": "Give the folder's whole path, starting with / or ~."}
            full = os.path.realpath(full)
            if not os.path.isdir(full):
                return 400, {"error": f"There is no folder at {said}."}
            if tool.too_wide(full):
                return 400, {"error": f"{said} holds everything, not one project. Give a project's own folder."}
            chosen.append(full)
        chosen = list(dict.fromkeys(chosen))
        if not chosen:
            return 400, {"error": "Choose at least one project, or type a project's folder."}
        well, why = well_choice(given.get("well"), {name: f for f in chosen for name in (f, tool.shown(f))})  # Set your agents up well
        if why:
            return 400, {"error": why}
        args = argparse.Namespace(folder=chosen, yes=True, name=None, no_hooks=False, undo=False)
        try:
            tool.setup(args, say=lines.append, control=control, page=True)
        except tool.Refused as why:
            return 409, {"error": str(why), "lines": home_said(lines, tool)}
        kept = switches.saved(data).get("control")
        well_note = well_after(well, tool, lines)
    note = well_note
    if board is not None and isinstance(kept, bool) and (board.server is None or (board.server.control is not None) != kept):
        try:
            board.switch("control", kept)
        except Refused as why:
            note = str(why)
    return 200, {"lines": home_said(lines, connect_setup), "control": kept if isinstance(kept, bool) else None,
                 **({"note": note} if note else {})}


def setup_undo(data):
    """Undo: Arnheim's hooks and status line taken out, as `python3 connect/setup.py --undo` does, and data/company.json
    moved aside into data/backups/, so the page shows the made-up company again. Gives (code, answer)."""
    lines = []
    with SETUP_LOCK:
        tool = setup_tool(data)
        try:
            tool.undo(say=lines.append, page=True)
        except tool.Refused as why:
            return 409, {"error": str(why), "lines": home_said(lines, tool)}
        company = os.path.join(data, "company.json")
        if os.path.isfile(company):
            backups = os.path.join(data, "backups")
            aside = os.path.join(backups, f"company.undone-{tool.stamp()}.json")
            n = 2
            while os.path.exists(aside):
                aside = os.path.join(backups, f"company.undone-{tool.stamp()}-{n}.json")
                n += 1
            try:
                os.makedirs(backups, exist_ok=True)
                os.replace(company, aside)
            except OSError as error:
                return 409, {"error": f"Your building, data/company.json, couldn't be moved aside: {error.strerror or error}.", "lines": home_said(lines, tool)}
            lines.append(f"Moved your building to {tool.shown(aside)}, so the page shows the made-up company again. "
                         "Move it back to data/company.json to have it again.")
    return 200, {"lines": home_said(lines, connect_setup)}


# ---------- setting your agents up well, from the page (connect/agent_setup.py) ----------

def well_choice(given, names):
    """(what to set up, or None; why the request doesn't make sense, or None): the page's ticks, for folders it
    named by the names it was shown (`names` maps each to its whole path). A check comes as the words typed."""
    if given is None:
        return None, None
    projects = given.get("projects", []) if isinstance(given, dict) else None
    if not isinstance(projects, list) or len(projects) > SETUP_MOST_FOLDERS \
            or not isinstance(given.get("secrets", False), bool) or not isinstance(given.get("mcp", False), bool):
        return None, "That request doesn't make sense."
    out = []
    for p in projects:
        if not isinstance(p, dict) or p.get("folder") not in names or not isinstance(p.get("items", []), list) \
                or not all(i in agent_setup.ITEMS for i in p.get("items", [])):
            return None, "That request doesn't make sense. Reload the page and try again."
        check = p.get("check")
        if check is not None:
            try:
                check = shlex.split(check) if isinstance(check, str) and len(check) <= 1000 and "\0" not in check else None
            except ValueError:
                return None, "The check has a quote that isn't closed."
            if check is None or len(check) > 64:
                return None, "That check doesn't make sense."
        out.append({"folder": names[p["folder"]], "items": list(p.get("items", [])), "check": check})
    return {"projects": out, "secrets": given.get("secrets", False), "mcp": given.get("mcp", False)}, None


def well_after(choice, tool, lines):
    """Sets your agents up well as the page chose, once setup has connected them. Gives a note when it couldn't."""
    if not choice:
        return None
    try:
        agent_setup.apply(choice, tool, say=lines.append)
    except tool.Refused as why:
        lines.append(str(why))
        return f"Your agents are connected, but setting them up well didn't finish: {why}"
    return None


def well_floors(tool, data):
    """{name the page shows: whole path}: each floor's first folder on this computer."""
    company = None
    try:
        company = tool.read_json(os.path.join(data, "company.json"), "data/company.json")
    except tool.Refused:
        pass
    out = {}
    for floor in (company or {}).get("floors") or [] if isinstance(company, dict) else []:
        folders = [f for f in tool.floor_folders(floor) if os.path.isdir(f)][:1]
        for f in folders:
            out[tool.shown(f)] = out[f] = f
    return out


def well_status(data):
    """Settings' card: what is in place on each floor, and what could be set up, changing nothing."""
    with SETUP_LOCK:
        tool = setup_tool(data)
        folders = list(dict.fromkeys(well_floors(tool, data).values()))
        return {"well": agent_setup.shown_plan(agent_setup.plan(folders, tool), tool)}


def well_plan(given, data):
    """The plan for folders the page names (projects setup found, floors, or one typed), with checks as typed,
    changing nothing. Gives (code, answer)."""
    names, checks = given.get("folders"), given.get("checks") or {}
    if not isinstance(names, list) or not 0 < len(names) <= SETUP_MOST_FOLDERS or not all(isinstance(n, str) for n in names) \
            or not isinstance(checks, dict):
        return 400, {"error": "That request doesn't make sense."}
    with SETUP_LOCK:
        tool = setup_tool(data)
        known = well_floors(tool, data)
        for p in tool.find_projects()[:tool.MOST]:
            known[tool.shown(p["folder"])] = known[p["folder"]] = p["folder"]
        folders = []
        for name in names:
            full = known.get(name)
            if full is None:
                said = name.strip().strip("'\"")
                path = os.path.expanduser(said)
                if "\0" in said or not os.path.isabs(path) or not os.path.isdir(path) or tool.too_wide(os.path.realpath(path)):
                    return 400, {"error": f"There is no project folder at {said}."}
                full = os.path.realpath(path)
            folders.append(full)
            known[name] = full
        typed = {}
        for name, words in checks.items():
            if name in known and isinstance(words, str) and len(words) <= 1000:
                try:
                    typed[known[name]] = shlex.split(words)
                except ValueError:
                    return 400, {"error": "The check has a quote that isn't closed."}
        return 200, {"well": agent_setup.shown_plan(agent_setup.plan(folders, tool, typed), tool)}


def well_apply(given, data):
    """Settings' Set up: what was ticked, on floors already connected. Gives (code, answer) with the fresh plan."""
    lines = []
    with SETUP_LOCK:
        tool = setup_tool(data)
        names = well_floors(tool, data)
        choice, why = well_choice(given, names)
        if why or not choice:
            return 400, {"error": why or "That request doesn't make sense."}
        try:
            agent_setup.apply(choice, tool, say=lines.append)
        except tool.Refused as why:
            return 409, {"error": str(why), "lines": home_said(lines, tool)}
        folders = list(dict.fromkeys(names.values()))
        return 200, {"lines": home_said(lines, tool) or ["Everything chosen was in place already: nothing changed."],
                     "well": agent_setup.shown_plan(agent_setup.plan(folders, tool), tool)}


# ---------- a newer Arnheim (the "Look for a newer Arnheim" switch) ----------

UPSTREAM = re.compile(r"^(?:https://(?:[^@/\s]+@)?|ssh://git@|git@)github\.com[:/]allwhenlabs/arnheim(?:\.git)?/?$", re.I)
COMPARE = "https://api.github.com/repos/allwhenlabs/arnheim/compare/main...{}?per_page=1"
UP_TO_DATE = "Arnheim is already up to date."
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0"}  # git never stops to ask for a password


def git_env(run=subprocess.run):
    """The environment git pull runs in: it never stops to ask for a password, a passphrase or a host key, over HTTPS
    or ssh. An ssh command you chose yourself (GIT_SSH_COMMAND, GIT_SSH or git's core.sshCommand) is kept as it is."""
    env = {**os.environ, **NO_PROMPT}
    if not env.get("GIT_SSH_COMMAND") and not env.get("GIT_SSH") and not git_says(["config", "--get", "core.sshCommand"], run):
        env["GIT_SSH_COMMAND"] = "ssh -o BatchMode=yes"
    return env


def git_says(words, run=subprocess.run):
    """What git prints for a fixed list of words, run in this folder, or None when it can't say."""
    try:
        done = run(["git", *words], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=30,
                   env={**os.environ, **NO_PROMPT})  # only ever words that stay in this folder
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None


def upstream(run=subprocess.run):
    """The name of the remote that is Arnheim's own repository on GitHub, when this folder is a checkout of it; else
    None. Like local_head, it never runs git in a folder with no .git."""
    if not os.path.lexists(os.path.join(ROOT, ".git")):
        return None
    top = git_says(["rev-parse", "--show-toplevel"], run)
    if not top or not same_file(top, ROOT):
        return None
    names = arnheim_remotes(run)
    return names[0] if names else None


def arnheim_remotes(run=subprocess.run):
    """The remotes that fetch from Arnheim's own repository on GitHub, by name (a plain name, never one like an option)."""
    names = []
    for line in (git_says(["remote", "-v"], run) or "").splitlines():
        parts = line.split()
        if (len(parts) >= 3 and parts[2] == "(fetch)" and UPSTREAM.search(parts[1])  # a partial clone adds [blob:none]
                and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", parts[0])):
            names.append(parts[0])
    return names


def local_head(run=subprocess.run):
    """This copy's commit, when this folder is a git checkout of Arnheim's own repository on GitHub; else None. A
    folder with no .git (a download) never runs git at all: on a Mac without Apple's tools, that would offer to
    install them."""
    if not os.path.lexists(os.path.join(ROOT, ".git")):
        return None
    top = git_says(["rev-parse", "--show-toplevel"], run)
    if not top or not same_file(top, ROOT):
        return None
    if not arnheim_remotes(run):
        return None
    sha = git_says(["rev-parse", "HEAD"], run)
    return sha if sha and re.fullmatch(r"[0-9a-f]{40}", sha) else None


def newer_arnheim(run=subprocess.run, opener=urllib.request.urlopen):
    """How many changes GitHub's main has that this copy hasn't, or None: not a git checkout of Arnheim, commits here
    that GitHub doesn't know (it answers 404), no network, or nothing newer. GitHub is sent only this copy's commit,
    with a User-Agent that says Arnheim and nothing else."""
    sha = local_head(run)
    if not sha:
        return None
    request = urllib.request.Request(COMPARE.format(sha), headers={"User-Agent": "Arnheim", "Accept": "application/vnd.github+json"})
    try:
        with opener(request, timeout=20) as reply:
            said = json.loads(reply.read(1 << 22).decode("utf-8"))
    except urllib.error.HTTPError as error:
        if error.fp is not None:  # an answer with no body has nothing to close, and Python 3.9 fails trying
            error.close()
        return None
    except (OSError, ValueError, http.client.HTTPException):
        return None
    behind = said.get("behind_by") if isinstance(said, dict) and said.get("status") == "behind" else None
    return behind if isinstance(behind, int) and not isinstance(behind, bool) and behind > 0 else None


def check_newer(server, board, last, ask=newer_arnheim, now=None, every=86400):
    """One round of look_for_newer: asks GitHub when a day has passed since the last time (or never), while the switch is
    on; with it off, the notice goes. Gives when it last asked."""
    now = time.time() if now is None else now
    if not board.on("updates"):
        server.update = None
        return 0  # switched on again, it asks at its next round, within the hour
    if last and now - last < every:
        return last
    behind = ask()
    server.update = {"behind": behind} if behind else None
    return now


def look_for_newer(server, board, every=3600):
    """At the start and once a day: whether GitHub has a newer Arnheim, for the Needs you notice."""
    last = 0
    while True:
        try:
            last = check_newer(server, board, last)
        except Exception:  # whatever went wrong, it asks again later
            pass
        time.sleep(every)


def update_now(server, run=subprocess.run):
    """Update now: `git pull --ff-only <Arnheim's own remote> main` in this folder, only on main and only while the
    the Needs you notice says GitHub has a newer one. Gives (whether it worked, what to say)."""
    if not server.update:
        return False, "There is no newer Arnheim to update to just now."
    control = server.control
    working = [r for r in list(control.runs.values()) if control.alive(r)] if control is not None else []
    if working:
        return False, (f"{len(working)} agent{'s' if len(working) != 1 else ''} started from the building "
                       f"{'are' if len(working) != 1 else 'is'} still at work, and Arnheim starts again to update. Update once "
                       f"{'they have' if len(working) != 1 else 'it has'} finished.")
    remote = upstream(run)
    if remote is None:
        return False, "This folder isn't a copy of Arnheim from GitHub, so it can't update itself. Nothing was changed."
    if git_says(["rev-parse", "--abbrev-ref", "HEAD"], run) != "main":
        return False, ("This copy isn't on Arnheim's main branch, so Update now leaves it as it is. Nothing was changed. "
                       "Update it by hand with git.")
    try:
        done = run(["git", "pull", "--ff-only", remote, "main"], cwd=ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                   text=True, timeout=180, env=git_env(run))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return False, f"git couldn't run here ({getattr(error, 'strerror', None) or error}). Update by hand: git pull, in Arnheim's folder."
    said = f"{done.stdout or ''}\n{done.stderr or ''}"
    if done.returncode != 0:
        if re.search(r"local changes|commit your changes|stash them|would be overwritten", said, re.I):
            return False, ("Arnheim's folder has changes of its own that the update would overwrite, so nothing was changed. "
                           "Save them somewhere else, or put them aside with git stash, then try again.")
        if re.search(r"not possible to fast-forward|diverg", said, re.I):
            return False, ("This copy has commits of its own that GitHub's doesn't, so it can't simply move up to the newer one. "
                           "Nothing was changed. Update it by hand with git pull.")
        last = [line.strip() for line in said.splitlines() if line.strip()][-1:]
        return False, f"git pull didn't work{': ' + last[0] if last else ''}. Nothing was changed."
    if re.search(r"already up[ -]to[ -]date", said, re.I):
        return True, UP_TO_DATE
    return True, "Updated. Arnheim is starting again, and the page reloads when it is back."


def restart_self(server, wait=0.5):
    """Starts serve.py again in this same process, with the same words it was started with, once the page has its answer.
    The listening socket closes as it does (Python's sockets never pass to what replaces them), and the new start takes
    the port at once. It never opens another browser tab."""
    time.sleep(wait)
    for brain in {id(b): b for b in (server.brain,) if b is not None}.values():
        try:
            brain.close()
        except Exception:
            pass
    os.environ["ARNHEIM_NO_BROWSER"] = "1"
    os.environ["ARNHEIM_UPDATED"] = "1"  # the new start may replace pictures made for the old version
    sys.stdout.flush()
    sys.stderr.flush()
    words = [w for w in (getattr(sys, "orig_argv", None) or [sys.executable, *sys.argv]) if w != "--new-link"]  # once only
    # (main's parser takes no shortened words, so --new-link is only ever written in full)
    os.execv(sys.executable, words)


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


def saved():
    """What you chose in connect/setup.py for each start, such as answering your agents from the building."""
    try:
        with open(SAVED, encoding="utf-8-sig") as handle:
            got = json.load(handle)
    except (OSError, ValueError):
        return {}
    return got if isinstance(got, dict) else {}


def control_wanted(args, away, board=None):
    """(whether control is on, whether you chose it in setup or in Settings): --control, or your choice in
    data/serve.json unless --no-control, and never on the network (away is --lan or --share, or None)."""
    board = board or Switchboard(args, away)
    return board.on("control"), saved().get("control") is True and not args.no_control


def answers(port, wait=0.5):
    """Whether something already answers on this computer at the port."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=wait):
            return True
    except OSError:
        return False


def open_page(url):
    """The page in this computer's browser, if it has one to open."""
    try:
        webbrowser.open(url)
    except Exception:  # no browser here (a server, say): the address printed is enough
        pass


def python_name():
    """This Python by the name that survives an upgrade, where there is one (connect/setup.py)."""
    try:
        from connect.setup import interpreter
        return interpreter()
    except Exception:
        return sys.executable


def wait_for_port(where, every=30):
    """The login copy, when something else has its port: says so once, then takes the port when it frees."""
    print(f"Port {where[1]} is in use. Arnheim takes it as soon as it is free (python3 serve.py --always off stops this).", flush=True)
    while True:
        time.sleep(every)
        try:
            return Server(where, Handler)
        except OSError as error:
            if error.errno not in PORT_TAKEN:
                raise


def keep_running(args):
    """python3 serve.py --always [off]: Arnheim started by itself when you log in, and kept running
    (connect/always.py)."""
    if args.always == "off":
        path = always.turn_off()
        for _ in range(20):  # until its copy has let go of the port
            if not path or not answers(args.port):
                break
            time.sleep(0.25)
        print("Arnheim no longer starts by itself, and the copy it started has stopped." if path
              else "Arnheim wasn't set to start by itself: nothing changed.")
        return 0
    words = [str(args.port)] if args.port != 8740 else []
    for flag in ("lan", "share", "control", "no_control", "routines", "pings", "no_git", "brain", "drawn"):
        if getattr(args, flag):
            words.append("--" + flag.replace("_", "-"))
    if args.remote:
        words += ["--remote", args.remote]
    if always.kind() is None:
        sys.exit("Starting Arnheim when you log in works on a Mac and on Linux for now. Keep this window open with "
                 "python3 serve.py, or add it to your computer's own list of things to start at login.")
    always.stop_running()  # the copy it started before lets go of the port
    for _ in range(20):
        if not answers(args.port):
            break
        time.sleep(0.25)
    else:
        sys.exit(f"Port {args.port} is in use, perhaps by Arnheim in another window. Stop that one (Ctrl-C there), then run this again.")
    try:
        path = always.turn_on([python_name(), os.path.join(ROOT, "serve.py"), *words], ROOT)
    except always.Unsupported as why:
        sys.exit(str(why))
    except (OSError, RuntimeError) as error:
        sys.exit(f"Arnheim couldn't be set to start by itself: {error}")
    url = f"http://127.0.0.1:{args.port}"
    print(f"Arnheim now starts by itself when you log in, and keeps running when you close this window ({path}).", flush=True)
    print("Starting it now. The first start downloads the photo-real look's pictures, so it can take a minute...", flush=True)
    end = time.time() + 180
    while time.time() < end and not answers(args.port):
        time.sleep(0.5)
    log = always.log_of()
    if answers(args.port):
        print(f"Arnheim is at {url}", flush=True)
        if sys.stdout.isatty() and not args.no_browser:
            open_page(url)
    else:
        print(f"It hasn't answered yet. {'What it says is in ' + log if log else 'journalctl --user -u arnheim says why'}.", flush=True)
    print("python3 serve.py --always off stops it and takes it out.", flush=True)
    return 0


def company_note():
    """Which company the page will show, and why any of data/'s files can't be read."""
    def shown(name):  # as the page will get it: a file inside this folder, links resolved
        path = os.path.realpath(os.path.join(ROOT, "data", name))
        return path if path.startswith(ROOT + os.sep) and os.path.isfile(path) else None

    if not shown("company.json"):
        if os.path.exists(os.path.join(ROOT, "data", "company.json")):
            return ["data/company.json links to somewhere outside this folder, which serve.py doesn't show, "
                    "so the page shows the made-up sample. Copy the files into data/ instead."]
        return ["Showing the sample company, which is made up. To show your own projects and agents, press Connect my "
                f"agents on the page, or run: {'py' if os.name == 'nt' else 'python3'} connect/setup.py"]
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
        except Exception:  # whatever went wrong, it tries again next minute
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

def files_print(entries):
    """A set of pictures in one line: its files' names and sizes, hidden files and a file browser's clutter left
    out. A baked/ folder from another version of Arnheim, or one half unpacked, comes out different."""
    lines = sorted(f"{name}\t{size}" for name, size in entries
                   if not any(part.startswith(".") or part in CLUTTER for part in name.split("/")))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def folder_files(folder):
    """A folder's files as (name, size), with / between a name's parts, as in a zip."""
    for top, _folders, names in os.walk(folder):
        for name in names:
            full = os.path.join(top, name)
            yield os.path.relpath(full, folder).replace(os.sep, "/"), os.path.getsize(full)


def pictures_state(folder=None, expected=None):
    """Which look the page opens in: ("photo", None) when baked/ holds the pictures this version of Arnheim is made
    for, else ("drawn", why), why in one plain line. Nothing is downloaded here."""
    folder = folder or BAKED
    if not os.path.lexists(folder):
        return "drawn", WHY_MISSING
    if not os.path.realpath(folder).startswith(os.path.realpath(os.path.dirname(folder)) + os.sep):
        return "drawn", WHY_AWAY
    try:
        same = files_print(folder_files(folder)) == (expected or PICTURES["files"])
    except OSError:
        same = False
    return ("photo", None) if same else ("drawn", WHY_OTHER)


def safe_unzip(path, into, top="baked", most=1 << 30):
    """Unpacks a zip into the folder `into`, but only if every entry stays under top/: no absolute paths, drive
    letters, backslashes or `..`, no links, and no more than `most` bytes in all. Otherwise raises ValueError
    and unpacks nothing."""
    with zipfile.ZipFile(path) as zipped:
        entries = zipped.infolist()
        total = 0
        for entry in entries:
            name = entry.filename
            parts = name.rstrip("/").split("/")
            if (name.startswith("/") or any(c in name for c in "\\:\0") or parts[0] != top
                    or any(p in ("", ".", "..") for p in parts) or (len(parts) < 2 and not entry.is_dir())
                    or stat.S_ISLNK(entry.external_attr >> 16)):
                raise ValueError(f"the download had a file outside {top}/ ({name!r}), so nothing was unpacked")
            total += entry.file_size
        if total > most:
            raise ValueError("the download unpacks to far more than it should, so nothing was unpacked")
        for entry in entries:
            target = os.path.join(into, *entry.filename.rstrip("/").split("/"))
            if entry.is_dir():
                os.makedirs(target, exist_ok=True)
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with zipped.open(entry) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out, 1 << 20)


def download_trouble(error):
    """What went wrong with a download, in a few plain words."""
    if isinstance(error, urllib.error.HTTPError):
        return f"GitHub answered {error.code} {error.reason}"
    text = str(getattr(error, "reason", "") or error)
    if "CERTIFICATE_VERIFY_FAILED" in text:
        return ("this Python can't check GitHub's certificate; with Python from python.org on a Mac, "
                "run Install Certificates in its folder")
    if isinstance(error, socket.timeout) or "timed out" in text:
        return "the connection stalled"
    if isinstance(error, (urllib.error.URLError, ConnectionError, http.client.HTTPException)):
        return "no connection to GitHub"
    if isinstance(error, zipfile.BadZipFile):
        return "the download wasn't a whole zip"
    return f"they couldn't be saved here: {getattr(error, 'strerror', None) or error}"


def fetch_pictures(say, folder=None, url=None, size=None, sha256=None, opener=urllib.request.urlopen):
    """Downloads the photo-real look's pictures into baked/, once and unattended. Returns None when they are in
    place, or why not in a few plain words. The zip goes to a hidden file beside baked/ and must be the very one
    this version is made for; it is unpacked into a hidden folder, and that is moved into place in one step, so a
    download cut short never leaves a half-made baked/."""
    folder = folder or BAKED
    url, size, sha256 = url or PICTURES["url"], size or PICTURES["bytes"], sha256 or PICTURES["sha256"]
    parent = os.path.dirname(folder)
    for name in os.listdir(parent):  # what a download that was stopped dead left, an hour or more ago
        old = os.path.join(parent, name)
        try:
            if name.startswith(".baked-") and time.time() - os.lstat(old).st_mtime > 3600:
                shutil.rmtree(old) if os.path.isdir(old) and not os.path.islink(old) else os.remove(old)
        except OSError:
            pass
    need = size * 3  # the zip, and what it unpacks to
    try:
        if shutil.disk_usage(parent).free < need:
            return f"this disk needs about {need // 1_000_000} MB free for them"
    except OSError:
        pass
    say(f"Downloading the photo-real look's pictures, once: {round(size / 1e6)} MB from GitHub into baked/. "
        "python3 serve.py --drawn skips this.")
    tty = sys.stdout.isatty()
    part = unpack = None
    try:
        handle, part = tempfile.mkstemp(prefix=".baked-", suffix=".zip", dir=parent)
        digest, got, shown = hashlib.sha256(), 0, 0.0
        with os.fdopen(handle, "wb") as out:
            request = urllib.request.Request(url, headers={"User-Agent": "Arnheim serve.py"})
            with opener(request, timeout=30) as reply:  # 30 seconds with nothing coming, and it gives up
                while True:
                    chunk = reply.read(1 << 20)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > size:
                        break
                    digest.update(chunk)
                    out.write(chunk)
                    if tty and (time.monotonic() - shown > 0.5 or got == size):
                        shown = time.monotonic()
                        print(f"\r  {got // 1_000_000} of {size // 1_000_000} MB", end="", flush=True)
        if tty and got:
            print(flush=True)
        if got != size or digest.hexdigest() != sha256:
            return "the download wasn't the file this version of Arnheim expects"
        unpack = tempfile.mkdtemp(prefix=".baked-", dir=parent)
        safe_unzip(part, unpack)
        if not os.path.lexists(folder):  # else another copy of serve.py got there first
            os.rename(os.path.join(unpack, "baked"), folder)
        return None
    except ValueError as error:
        return str(error)
    except (OSError, http.client.HTTPException, zipfile.BadZipFile) as error:
        if tty and got:
            print(flush=True)
        if isinstance(error, urllib.error.HTTPError) and error.fp is not None:
            error.close()  # GitHub's answer, unread (one with no body has nothing to close, and Python 3.9 fails trying)
        return download_trouble(error)
    finally:
        if part and os.path.exists(part):
            os.remove(part)
        if unpack:
            shutil.rmtree(unpack, ignore_errors=True)


def pictures_at_start(drawn, say, fetch=None):
    """At the start: the photo-real look's pictures, downloaded if baked/ isn't there yet (never with --drawn).
    Returns why the page shows the drawn look, in one plain line, or None when it shows the photo-real look or
    --drawn asked for the drawn one."""
    updated = os.environ.pop("ARNHEIM_UPDATED", None) == "1"  # never passed on to what this start runs
    if drawn:
        return None
    trouble = None
    if updated and os.path.isdir(BAKED) and not os.path.islink(BAKED) and pictures_state() == ("drawn", WHY_OTHER):
        say("This version of Arnheim has new pictures: replacing the old ones in baked/.")
        shutil.rmtree(BAKED, ignore_errors=True)  # only after Update now, and only pictures made for another version
    if not os.path.lexists(BAKED):
        trouble = (fetch or fetch_pictures)(say)
        if trouble is None:
            say("The pictures are in baked/, so the page shows the photo-real look.")
    look, why = pictures_state()
    if look == "photo":
        return None
    return WHY_FAILED.format(trouble) if trouble else why


def main():
    parser = argparse.ArgumentParser(description="Shows Arnheim in a browser.", allow_abbrev=False)
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
    parser.add_argument("--drawn", action="store_true",
                        help="open in the drawn look, and don't download the photo-real look's pictures (README, \"The photo-real look\")")
    parser.add_argument("--remote", metavar="NAME",
                        help="let your own paired phone in from anywhere, through a private https way in such as Tailscale Serve "
                             "that answers at NAME (docs/phone.md)")
    parser.add_argument("--no-control", action="store_true", help="leave control off this time, though you chose it in connect/setup.py")
    parser.add_argument("--no-browser", action="store_true", help="don't open the page in the browser when it starts")
    parser.add_argument("--always", nargs="?", const="on", choices=["on", "off"],
                        help="start it now and each time you log in, so it keeps running when this window closes (Mac and Linux); "
                             "--always off takes that out")
    parser.add_argument("--set-up-voice", action="store_true",
                        help="give this computer the voice the walk's people speak with, once: it asks first (1.5 to 3 GB; README, \"Voice\")")
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
    if args.always:
        sys.exit(keep_running(args))
    if args.set_up_voice:
        from voice import install
        sys.exit(install.main([]))
    def make_brain(control):
        return Brain(tell=lambda why: print(f"The brain had no answer: {why}", file=sys.stderr, flush=True), control=control)

    board = Switchboard(args, away, make_brain)  # the switches in Settings, and the words given here (connect/switches.py)
    control_on, chose = control_wanted(args, away, board)
    try:
        remote = Remote(args.remote, os.path.join(ROOT, "data")) if args.remote else None
    except ValueError as error:
        sys.exit(str(error))
    control = Control() if control_on else None
    brain = brain_trouble = None
    if board.on("brain"):
        try:
            brain = make_brain(control)
        except ValueError as error:
            if args.brain:
                sys.exit(str(error))
            brain_trouble = str(error)  # switched on in Settings, but it can't start here now
    where = ("0.0.0.0" if args.lan or args.share else "127.0.0.1", args.port)
    login_copy = os.environ.get("ARNHEIM_ALWAYS") == "1"  # the copy that starts at login (connect/always.py)
    server = None
    try:
        server = Server(where, Handler)
    except OSError as error:
        if error.errno in PORT_TAKEN and login_copy:
            pass  # it waits for the port below, rather than start again every minute
        elif error.errno in PORT_TAKEN:
            if always.installed():
                sys.exit(f"Arnheim already runs by itself (python3 serve.py --always): open http://127.0.0.1:{args.port}. "
                         "To start it here instead, first run python3 serve.py --always off.")
            sys.exit(f"Port {args.port} is already in use, perhaps by another copy of Arnheim. Stop that one, "
                     f"or give another port: python3 serve.py {args.port + 1 if args.port < 65535 else 8741}")
        elif error.errno == errno.EACCES:
            sys.exit(f"This computer won't let Arnheim use port {args.port}. Give one above 1024: python3 serve.py 8740")
        else:
            raise
    if server is None:
        server = wait_for_port(where)
    server.lan = args.lan or args.share
    server.remote = remote
    server.share = share_key(new=args.new_link) if args.share else None
    server.control = control
    server.brain = brain
    server.board = board
    board.server, board.kept = server, control
    server.drawn = args.drawn
    try:
        looks = pictures_at_start(args.drawn, lambda line: print(line, flush=True))
    except KeyboardInterrupt:
        server.server_close()
        if brain:
            brain.close()
        sys.exit("\nStopped before the pictures were in place. Nothing was kept.")
    server.fetched = looks
    print(f"Arnheim is at http://127.0.0.1:{args.port}", flush=True)
    if sys.stdout.isatty() and not args.no_browser and not os.environ.get("ARNHEIM_NO_BROWSER"):
        threading.Timer(0.5, open_page, args=(f"http://127.0.0.1:{args.port}",)).start()
    if looks:
        print(looks, flush=True)
    if not VOICE.installed():
        print("The walk's people speak once this computer has a voice: python3 serve.py --set-up-voice (about 1.5 GB, or 3 GB on Linux, once).", flush=True)
    if remote:
        print(f"Phones are on: a phone paired with this computer can open https://{remote.name}/ from anywhere your "
              f"private way in reaches. With Tailscale, run once: tailscale serve --bg {args.port}. To pair a phone, open "
              "Settings here and choose Pair a phone (docs/phone.md).", flush=True)
    if control_on:
        print("Control is on: the page on this computer can talk to your Claude Code and Codex agents, answer their "
              "permission requests, and start and stop them (docs/connect.md)."
              + ("" if args.control else " Switch it off in Settings, or start with --no-control for once."), flush=True)
    elif chose and away:
        print(f"Control stays off with {away}: it works only on this computer.", flush=True)
    if brain_trouble:
        print(f"The brain is switched on, but can't start: {brain_trouble}", flush=True)
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
    # The minute jobs run while their switch is on, and look again each minute, so the switches in Settings work at once.
    threading.Thread(target=every_minute, args=("projects.py", lambda: board.on("git") and floors_have_folders()), daemon=True).start()
    threading.Thread(target=every_minute, args=("routines.py", lambda: board.on("routines")), daemon=True).start()
    threading.Thread(target=every_minute, args=("ping.py", lambda: board.on("pings")), daemon=True).start()
    threading.Thread(target=look_for_newer, args=(server, board), daemon=True).start()  # once a day, while its switch is on
    # The daily cycle (connect/day.py): every half a minute, today's plan and close when they are due, and approved items
    # started one at a time on each floor while control is on. It looks at its switch each time.
    threading.Thread(target=day_cycle.keep_going, args=(lambda: server.control, lambda: os.path.dirname(SAVED)), daemon=True).start()
    # The night shift (connect/night.py): every half a minute, during your quiet hours, approved work started on allowance
    # that would otherwise go unused, while control is on; and the morning's report once they end.
    threading.Thread(target=night_shift.keep_going, args=(lambda: server.control, lambda: os.path.dirname(SAVED)), daemon=True).start()
    # The secrets check: at the start, then with the minute's look in project folders (connect/secret_scan.py).
    threading.Thread(target=every_minute, args=("secret_scan.py", lambda: board.on("secrets") and floors_have_folders()), daemon=True).start()
    if board.on("git") and floors_have_folders():
        print("Looking at your floors' folders every minute for unsaved changes and open pull requests "
              "(connect/projects.py).", flush=True)
    if board.on("routines"):
        print("Routines are on: each floor's routines in data/company.json run when they are due, while this runs "
              "(docs/connect.md, \"Routines\").", flush=True)
    if board.on("pings"):
        print("Pings are on: the morning brief, and decisions that wait on you, go to your phone at the times "
              "\"pings\" in data/company.json gives (docs/connect.md).", flush=True)
    if board.on("daily_cycle"):  # the daily cycle (connect/day.py)
        times = day_cycle.times_of(os.path.dirname(SAVED))
        print(f"The daily cycle is on: today's plan at {times['day_plan']} and its close at {times['day_close']}, while this "
              "runs (docs/connect.md, \"The daily cycle\").", flush=True)
    if board.on("night"):  # the night shift (connect/night.py)
        quiet = night_shift.settings(os.path.dirname(SAVED))["quiet"]
        print(f"The night shift is on: from {quiet['from']} to {quiet['to']}, approved work runs on allowance that would "
              "otherwise go unused, while this runs (docs/connect.md, \"The night shift\").", flush=True)
    if os.path.isfile(os.path.join(ROOT, "data", "company.json")):  # your own company: the made-up one has no Switches
        print("Each feature can be switched on or off in Settings, under Switches.", flush=True)
    print("Ctrl-C stops it.", flush=True)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))  # stopped by its process id: tidy up as for Ctrl-C
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        for running in {id(b): b for b in (brain, server.brain) if b is not None}.values():  # one switched on from the page too
            running.close()


if __name__ == "__main__":
    main()
