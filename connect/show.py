#!/usr/bin/env python3
"""Show me: finished work comes with something to look at (docs/connect.md, "Show me").

A floor in data/company.json can say how to show its work, with either or both of:

    "show_url": "http://localhost:3000/"           a page of the project to take a picture of
    "show": {"run": ["npm", "run", "shots"], "timeout": 60}
                                                   a command that writes pictures or prints what it did

`show_url` is an http or https address, usually the project's dev server, or a page inside the floor's folder
("site/index.html"). Its pictures are taken with a browser already on this computer, Chrome, Chromium or Edge,
without a window (`--headless --screenshot`), at a desktop width and a phone width. The browser is found where
each system keeps it (find_browser), or named by ARNHEIM_BROWSER. With no browser, or no `show_url`, the floor's
`show` command runs instead, in the floor's folder, as an argument list with no shell and with a time limit. It
is handed ARNHEIM_SHOW_OUT, a folder to write .png or .jpg pictures into, ARNHEIM_SHOW_PHASE ("before" or
"after") and ARNHEIM_SHOW_URL; what it prints is kept too, with anything that looks like a secret hidden.

The hook (connect/claude_code.py) takes the pictures from before as an agent starts its first change after your
message (it waits for them, within a short time limit, so they show the work as it was), and starts this file in
the background as the turn ends, when it changed files and doesn't end with a question: `show.py --after <key>
<project> <turn>`. A turn the building started (connect/control.py) does the same as its agent finishes. The
pictures from after are taken then, put beside those from before by width or by name, with the lines changed in
short. The building shows a Show me card for each: Looks good, or Not quite with what to change, which reaches
the agent as any message from the building does.

Everything stays in data/shows/ on this computer: nothing is sent anywhere, and serve.py gives that folder to
this computer only. A phone, or a page whose server keeps the data elsewhere, gets a picture through control
(`show_image`), as base64. The last 20 shows of each conversation are kept, for 30 days. Standard library only.
"""
import base64
import json
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request


def _beside(name):
    """A module beside this file, loaded by its path: for a server that loads this file by its path alone."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import live, switches  # as connect.show, from serve.py
except ImportError:
    try:
        import live  # beside this file, as the hook has it
        import switches
    except ImportError:
        live = _beside("live")
        switches = _beside("switches")

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
CONV = re.compile(r"^cc-[A-Za-z0-9]{1,12}$")  # a conversation, as the feed names it
SHOW_KEY = re.compile(r"^(cc-[A-Za-z0-9]{1,12})-([0-9]{1,12})$")  # a show: its conversation and the turn it shows
VIEWS = (("desktop", 1280, 800), ("phone", 390, 844))  # the widths a page's picture is taken at
PICTURES = (".png", ".jpg", ".jpeg")
PICTURE_MOST = 6_000_000  # bytes in one picture at most
MADE_MOST = 6  # pictures a show command may make
OUTPUT_LINES = 30
OUTPUT_CHARS = 3000
KEEP_EACH = 20  # shows kept for each conversation
KEEP_DAYS = 30
KEEP_ALL = 200  # shows kept in all, the newest
LISTED_DECIDED = 20  # shows already looked at, still listed for the page
STRAY = 3600  # seconds before a picture no show names is taken away
STATES = ("waiting", "approved", "again")
ABOUT = "A Show me card: pictures of an agent's finished work (connect/show.py, docs/connect.md \"Show me\"). Safe to delete."
APPS = ("Google Chrome", "Chromium", "Microsoft Edge", "Google Chrome Beta", "Google Chrome Canary", "Microsoft Edge Beta", "Microsoft Edge Dev")
COMMANDS = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge", "microsoft-edge-stable",
            "msedge", "chrome")
WINDOWS = (("Google", "Chrome", "Application", "chrome.exe"), ("Microsoft", "Edge", "Application", "msedge.exe"),
           ("Chromium", "Application", "chrome.exe"))
NO_BROWSER = ("No picture: Chrome, Chromium or Edge isn't installed here. Install one, or give the floor a show command "
              "(docs/connect.md, \"Show me\").")


def seconds_from(name, usual, least=1, most=600):
    """A time limit in seconds from the environment, within limits."""
    try:
        return max(least, min(most, float(os.environ.get(name) or usual)))
    except ValueError:
        return usual


def browser_seconds():
    """How long one picture may take: 30 seconds, or ARNHEIM_SHOW_SECONDS."""
    return seconds_from("ARNHEIM_SHOW_SECONDS", 30)


def before_seconds():
    """How long an agent's first change waits for the pictures from before: 20 seconds, or ARNHEIM_SHOW_BEFORE."""
    return seconds_from("ARNHEIM_SHOW_BEFORE", 20, least=0.5, most=120)


def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def seconds_words(wait):
    n = max(1, int(round(float(wait))))
    return "1 second" if n == 1 else f"{n} seconds"


def read(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def write(path, data):
    """Whole, so a reader never sees half a file."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False)
    os.replace(part, path)


def gone(path):
    try:
        os.remove(path)
    except OSError:
        pass


class _Lock:
    """One writer at a time to data/shows/, between the hooks, the background runs and serve.py."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self.handle = open(self.path, "a")
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:  # Windows has no flock: a clash there costs one listing at most
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


# ---------- what a floor shows ----------

def floor_of(project, data=DATA):
    company = read(os.path.join(data, "company.json")) or {}
    for floor in company.get("floors") or []:
        if isinstance(floor, dict) and project and str(floor.get("project") or floor.get("label") or "") == project:
            return floor
    return None


def folder_of(floor):
    folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
    first = folders[0] if isinstance(folders, list) and folders and isinstance(folders[0], str) else None
    path = os.path.realpath(os.path.expanduser(first)) if first else None
    return path if path and os.path.isdir(path) else None


def show_of(floor):
    """How a floor shows its work: {"url", "run", "folder", "timeout"}, or None when it says nothing about it or its
    folder isn't on this computer. `url` is an http(s) address, or a file inside the floor's folder as a file: address."""
    if not isinstance(floor, dict):
        return None
    folder = folder_of(floor)
    if not folder:
        return None
    url = None
    given = floor.get("show_url")
    if isinstance(given, str) and given.strip():
        given = given.strip()
        if re.match(r"^https?://[^\s]+$", given, re.I):
            url = given
        elif "://" not in given and "\0" not in given:
            path = os.path.realpath(os.path.join(folder, given))
            if path.startswith(folder.rstrip(os.sep) + os.sep) and os.path.isfile(path):
                url = "file://" + urllib.request.pathname2url(path)
    run, wait, where = None, 60, folder
    command = floor.get("show")
    if isinstance(command, list):
        command = {"run": command}
    if isinstance(command, dict):
        args = command.get("run")
        if isinstance(args, list) and 0 < len(args) <= 64 and all(isinstance(a, str) and a for a in args):
            run = list(args)
        try:
            wait = max(1, min(600, int(command.get("timeout") or 60)))
        except (TypeError, ValueError):
            wait = 60
        if isinstance(command.get("folder"), str) and command["folder"]:
            other = os.path.realpath(os.path.expanduser(command["folder"]))
            where = other if os.path.isdir(other) else folder
    if not url and not run:
        return None
    return {"url": url, "run": run, "folder": where, "timeout": wait}


def show_for(project, data=DATA):
    """The show of the floor whose project (or label) this is, or None."""
    return show_of(floor_of(project, data))


# ---------- the browser ----------

def find_browser(env=None, which=shutil.which, isfile=os.path.isfile, system=None, home=None):
    """A Chrome, Chromium or Edge on this computer, where each system keeps it: ARNHEIM_BROWSER first (a path or a
    command; "none" for none), then the usual places on a Mac, Windows and Linux, then the commands on the PATH.
    None when there is none. Nothing is assumed: each place is looked at."""
    env = os.environ if env is None else env
    named = str(env.get("ARNHEIM_BROWSER") or "").strip()
    if named:
        if named.lower() in ("none", "off", "no"):
            return None
        path = os.path.expanduser(named)
        if isfile(path):
            return path
        return which(named)
    system = system or platform.system()
    home = home or os.path.expanduser("~")
    places = []
    if system == "Darwin":
        for app in APPS:
            for root in ("/Applications", os.path.join(home, "Applications")):
                places.append(os.path.join(root, app + ".app", "Contents", "MacOS", app))
    elif system == "Windows":
        for root in (env.get("PROGRAMFILES"), env.get("PROGRAMFILES(X86)"), env.get("LOCALAPPDATA")):
            if root:
                places.extend(os.path.join(root, *parts) for parts in WINDOWS)
    for place in places:
        if isfile(place):
            return place
    for name in COMMANDS:
        found = which(name)
        if found:
            return found
    return None


def answers(url, wait=3, opener=None):
    """Whether something answers at an http(s) address: a page there, or an error from it. False when nothing is
    listening, so the card can say its dev server isn't running. Asked directly, never through a proxy."""
    if not url.lower().startswith(("http://", "https://")):
        return True
    opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(urllib.request.Request(url, method="GET"), timeout=wait) as reply:
            reply.read(1)
        return True
    except urllib.error.HTTPError:
        return True  # it answered, with an error page: that is still a page to see
    except Exception:
        return False


def halt(proc):
    """Stops something that ran too long, with everything it started."""
    def send(sig):
        try:
            if hasattr(os, "killpg"):
                os.killpg(proc.pid, sig)
            else:
                proc.kill()
        except OSError:
            pass
    send(signal.SIGTERM)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        send(getattr(signal, "SIGKILL", signal.SIGTERM))
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def browser_args(browser, url, out, width, height, profile):
    """The browser's words for one picture: no window, a profile of its own that is thrown away, nothing of its own
    sent anywhere (no sync, no updates, no reports), and a few seconds for the page's scripts to draw it."""
    args = [browser, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", "--disable-sync", "--disable-background-networking", "--disable-component-update",
            "--disable-default-apps", "--disable-breakpad", "--metrics-recording-only", "--mute-audio",
            "--use-mock-keychain", "--password-store=basic",  # never asks for the Mac's keychain, or a Linux desktop's
            f"--user-data-dir={profile}", f"--window-size={width},{height}", "--virtual-time-budget=3000",
            f"--screenshot={out}"]
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        args.insert(2, "--no-sandbox")  # Chrome refuses to start as root otherwise
    return args + [url]


def picture_kind(path):
    """'png' or 'jpg' by what the file starts with, or None for anything else."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(8)
    except OSError:
        return None
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if head.startswith(b"\xff\xd8\xff"):
        return "jpg"
    return None


def size_of(path):
    """A PNG's width and height, from its header, or (None, None)."""
    try:
        with open(path, "rb") as handle:
            head = handle.read(24)
        if head.startswith(b"\x89PNG\r\n\x1a\n") and head[12:16] == b"IHDR":
            return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")
    except OSError:
        pass
    return None, None


def capture(browser, url, out, width, height, wait=None, popen=subprocess.Popen):
    """One picture of a page, within its time limit: None when it was taken, else why not, in words."""
    wait = browser_seconds() if wait is None else wait
    profile = tempfile.mkdtemp(prefix="arnheim-show-")
    try:
        try:
            proc = popen(browser_args(browser, url, out, width, height, profile), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=hasattr(os, "setsid"))
        except OSError as error:
            return f"The browser didn't start ({error.strerror or error})."
        try:
            proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            halt(proc)
            gone(out)
            return f"No picture: it took longer than {seconds_words(wait)}, so it was stopped."
        if picture_kind(out) != "png" or os.path.getsize(out) > PICTURE_MOST:
            gone(out)
            return "The browser made no picture."
        return None
    finally:
        shutil.rmtree(profile, ignore_errors=True)


# ---------- a show command ----------

def run_command(given, phase, into, url=None, wait=None, popen=subprocess.Popen):
    """Runs a floor's show command once, with a folder for its pictures: (picture paths, what it printed, why not or None)."""
    wait = given["timeout"] if wait is None else wait
    os.makedirs(into, exist_ok=True)
    env = dict(os.environ, ARNHEIM_SHOW_OUT=into, ARNHEIM_SHOW_PHASE=phase)
    if url:
        env["ARNHEIM_SHOW_URL"] = url
    why = None
    with tempfile.TemporaryFile() as out:
        try:
            proc = popen(given["run"], cwd=given["folder"], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=env,
                         start_new_session=hasattr(os, "setsid"))
        except OSError as error:
            return [], "", f"The show command didn't start ({error.strerror or error})."
        try:
            code = proc.wait(timeout=wait)
            if code != 0:
                why = f"The show command stopped with code {code}."
        except subprocess.TimeoutExpired:
            halt(proc)
            why = f"The show command took longer than {seconds_words(wait)}, so it was stopped."
        out.seek(0, os.SEEK_END)
        out.seek(max(0, out.tell() - 16384))
        raw = out.read()
    text = re.sub(r"\x1b\[[0-9;?]*[ -/]*[@-~]", "", raw.decode("utf-8", "replace")).replace("\r\n", "\n").replace("\r", "\n")
    lines = [part.rstrip() for part in text.split("\n")]
    while lines and not lines[-1]:
        lines.pop()
    said = "\n".join(live.redact_lines(lines[-OUTPUT_LINES:]))[-OUTPUT_CHARS:]
    said = live.home_less(said)
    made = []
    try:
        names = sorted(os.listdir(into))
    except OSError:
        names = []
    for name in names:
        path = os.path.join(into, name)
        if os.path.splitext(name)[1].lower() in PICTURES and not os.path.islink(path) and os.path.isfile(path) \
                and os.path.getsize(path) <= PICTURE_MOST and picture_kind(path):
            made.append(path)
        if len(made) >= MADE_MOST:
            break
    return made, said, why


# ---------- the shows ----------

def root(data=DATA):
    return os.path.join(data, "shows")


def record_path(data, key):
    return os.path.join(root(data), key + ".json")


def key_for(conv, turn):
    return f"{conv}-{int(turn)}"


def record(data, key):
    if not isinstance(key, str) or not SHOW_KEY.match(key):
        return None
    return read(record_path(data, key))


def turn_started(talk):
    """When the turn a conversation is in began: your last message to it, or None."""
    try:
        at = float((talk or {}).get("asked_at") or 0)
    except (TypeError, ValueError):
        return None
    return int(at) if at > 0 else None


def turn_of(talk):
    """The turn a finishing conversation shows, or None when it changed no files in it: your last message, or the
    time it first changed files when no message is known."""
    talk = talk or {}
    try:
        since = float(talk.get("asked_at") or 0)
        changed = float(talk.get("changed") or 0)
    except (TypeError, ValueError):
        return None
    if not changed or changed < since:
        return None
    return int(since) if since > 0 else int(changed)


def safe_name(text):
    return re.sub(r"[^A-Za-z0-9]+", "-", str(text or "")).strip("-").lower()[:40] or "picture"


def take(data, key, project, phase, given, wait=None, browser=None, finder=find_browser):
    """Takes one phase's pictures for a show: {"pictures": [...], "output": str or None, "how", "why"}. The browser's,
    at each width, when the floor has a show_url and a browser is here; else the floor's show command."""
    folder = root(data)
    os.makedirs(folder, exist_ok=True)
    now = round(time.time(), 2)
    pictures, why, said, how = [], None, None, None
    url = given.get("url")
    browser = (browser if browser is not None else finder()) if url else None
    if url and browser and not answers(url):
        why = f"No picture: nothing answered at {url}. Is its server running?"
        browser = None  # no picture of a page that isn't there; the show command, if any, runs instead
    if url and browser:
        how = "browser"
        found = {}

        def one(view, width, height):
            out = os.path.join(folder, f"{key}-{phase}-{view}.png")
            found[view] = capture(browser, given["url"], out, width, height, wait)
        threads = [threading.Thread(target=one, args=view, daemon=True) for view in VIEWS]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        for view, _, _ in VIEWS:
            if found.get(view) is None:
                w, h = size_of(os.path.join(folder, f"{key}-{phase}-{view}.png"))
                pictures.append({"file": f"{key}-{phase}-{view}.png", "phase": phase, "view": view, "width": w, "height": h, "at": now})
            else:
                why = found[view]
    elif given.get("run"):
        how = "command"
        work = os.path.join(folder, f".work-{key}-{phase}")
        shutil.rmtree(work, ignore_errors=True)
        try:
            made, said, ran_why = run_command(given, phase, work, url, wait=None if wait is None else min(wait, given["timeout"]))
            why = ran_why or why
            for i, path in enumerate(made):
                kind = picture_kind(path)
                name = f"{key}-{phase}-m{i}.{kind}"
                os.replace(path, os.path.join(folder, name))
                w, h = size_of(os.path.join(folder, name))
                base = safe_name(os.path.splitext(os.path.basename(path))[0])
                pictures.append({"file": name, "phase": phase, "view": base, "width": w, "height": h, "at": now})
        finally:
            shutil.rmtree(work, ignore_errors=True)
        if not pictures and not said and not why:
            why = "The show command made no pictures and printed nothing."
    else:
        why = why or NO_BROWSER
    return {"pictures": pictures, "output": said or None, "how": how, "why": why if not pictures and not said else None}


def save(data, row):
    """Keeps a show, and the list the page reads, data/shows/index.json, under one lock."""
    with _Lock(os.path.join(root(data), ".lock")):
        write(record_path(data, row["key"]), row)
        index(data)


def index(data):
    """data/shows/index.json: every show's line, newest first. Under the lock."""
    rows = []
    folder = root(data)
    try:
        names = os.listdir(folder)
    except OSError:
        names = []
    for name in names:
        if name.endswith(".json") and name != "index.json" and SHOW_KEY.match(name[:-5]):
            row = read(os.path.join(folder, name))
            if row and row.get("phase") == "ready":
                rows.append({k: row.get(k) for k in ("key", "conv", "title", "project", "turn", "at", "state", "how", "why", "pictures",
                                                     "changed", "said", "output", "words", "decided_at", "address", "why_before")})
    rows.sort(key=lambda r: r.get("at") or 0, reverse=True)
    write(os.path.join(folder, "index.json"), {"about": "Each Show me card, for the building (connect/show.py). Safe to delete.", "shows": rows})
    return rows


def before(data, conv, project, turn, given=None, wait=None, finder=find_browser):
    """The pictures from before, as an agent starts its first change of a turn: taken now, within before_seconds.
    Gives the show's key, or None when there is nothing to take or they were taken already."""
    given = given or show_for(project, data)
    if not given or not CONV.match(conv or ""):
        return None
    key = key_for(conv, turn)
    had = record(data, key)
    if had and had.get("phase") in ("taking before", "before", "taking", "ready"):
        return None  # taken already this turn, or being taken by another of its steps
    write(record_path(data, key), {"about": ABOUT, "key": key, "conv": conv, "project": project, "turn": int(turn), "phase": "taking before",
                                   "at": time.time()})
    got = take(data, key, project, "before", given, wait=before_seconds() if wait is None else wait, finder=finder)
    row = {"about": ABOUT, "key": key, "conv": conv, "project": project, "turn": int(turn), "phase": "before", "at": time.time(),
           "pictures": got["pictures"], "output": {"before": got["output"]} if got["output"] else {}, "how": got["how"],
           "why_before": got["why"]}
    save(data, row)
    return key


def changed_since(data, conv, turn):
    """The lines a conversation changed since its turn began, in short, from its screen (connect/live.py), or None."""
    doc = live.Live(data).read(conv) or {}
    hunks = [h for h in doc.get("changes") or [] if isinstance(h, dict) and float(h.get("at") or 0) >= float(turn) - 1]
    files = live.by_file({"changes": hunks})
    if not files:
        return None
    return {"files": len(files), "added": sum(f["added"] for f in files), "removed": sum(f["removed"] for f in files),
            "names": [one_line(f["file"], 120) for f in files[:6]]}


def after(data, conv, project, turn, title=None, said=None, given=None, wait=None, finder=find_browser):
    """The pictures from after, as the turn finishes, beside those from before: the show is ready to look at.
    Gives its key, or None when the floor shows nothing."""
    given = given or show_for(project, data)
    if not given or not CONV.match(conv or ""):
        return None
    key = key_for(conv, turn)
    was = record(data, key) or {}
    talk = talk_of(data, conv)
    title = title or talk.get("title") or was.get("title_given")
    said = said or (talk.get("says") or {}).get("now") or was.get("said_given")
    got = take(data, key, project, "after", given, wait=wait, finder=finder)
    olds = [p for p in was.get("pictures") or [] if isinstance(p, dict) and p.get("phase") == "before"]
    for p in [p for p in was.get("pictures") or [] if isinstance(p, dict) and p.get("phase") == "after"]:
        if p.get("file") not in {q["file"] for q in got["pictures"]}:
            gone(os.path.join(root(data), p["file"]))  # an earlier finish of the same turn: these replace them
    output = dict(was.get("output") or {}) if isinstance(was.get("output"), dict) else {}
    if got["output"]:
        output["after"] = got["output"]
    else:
        output.pop("after", None)
    row = {"about": ABOUT, "key": key, "conv": conv, "project": project, "turn": int(turn), "phase": "ready", "at": round(time.time(), 2),
           "state": "waiting", "title": one_line(title, 90) if title else None, "said": one_line(said, 300) if said else None,
           "how": got["how"] or was.get("how"), "why": got["why"], "pictures": olds + got["pictures"], "output": output,
           "changed": changed_since(data, conv, turn), "address": given.get("url") if (given.get("url") or "").lower().startswith("http") else None,
           "why_before": was.get("why_before") if not olds else None}
    save(data, row)
    sweep(data)
    return key


def run_finished(data, run, since):
    """An agent started from the building has finished (connect/control.py). When its hooks never saw it (it isn't in
    the feed), its floor's show is taken here instead, unless it ended with a question. The hook decides otherwise."""
    conv, project = str(run.get("key") or ""), run.get("project")
    if not switches.on("show_me", data) or not CONV.match(conv) or not show_for(project, data) or talk_of(data, conv):
        return None
    said = str(run.get("said") or "").rstrip()
    if said.endswith("?") or shown_since(data, conv, since):
        return None
    return after_later(data, conv, project, int(since), run.get("title"), said)


def after_later(data, conv, project, turn, title=None, said=None):
    """For the hook, or control, as a turn ends: marks the show as being taken, then takes it in the background. Its
    title and last words come from the feed, or from `title` and `said` for an agent the hooks didn't see."""
    key = key_for(conv, turn)
    was = record(data, key) or {"about": ABOUT, "key": key, "conv": conv, "project": project, "turn": int(turn)}
    was.update(phase="taking", taking_at=time.time())
    if title:
        was["title_given"] = one_line(title, 90)
    if said:
        was["said_given"] = one_line(said, 300)
    write(record_path(data, key), was)
    args = [sys.executable, os.path.realpath(__file__), "--after", conv, project, str(int(turn))]
    return subprocess.Popen(args, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, ARNHEIM_DATA=data), close_fds=True, start_new_session=hasattr(os, "setsid"))


def talk_of(data, conv):
    """A conversation as the feed has it (data/feeds/claude-code.json), or {}."""
    feed = read(os.path.join(data, "feeds", "claude-code.json")) or {}
    return next((c for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id") == conv), None) or {}


def shown_since(data, conv, since):
    """Whether a show of this conversation is of a turn that began at or after `since` (seconds), give or take one."""
    folder = root(data)
    try:
        names = os.listdir(folder)
    except OSError:
        return False
    for name in names:
        m = SHOW_KEY.match(name[:-5]) if name.endswith(".json") else None
        if m and m.group(1) == conv and int(m.group(2)) >= since - 1.5:
            return True
    return False


def sweep(data, now=None, each=KEEP_EACH, days=KEEP_DAYS):
    """The last `each` shows of each conversation, for `days` days; any picture no show names goes after an hour."""
    now = time.time() if now is None else now
    folder = root(data)
    try:
        names = os.listdir(folder)
    except OSError:
        return 0
    rows = {}
    for name in names:
        if name.endswith(".json") and SHOW_KEY.match(name[:-5]):
            rows[name[:-5]] = read(os.path.join(folder, name)) or {}
    drop = set()
    by_conv = {}
    for key, row in rows.items():
        at = float(row.get("at") or row.get("taking_at") or 0)
        if now - at > days * 86400:
            drop.add(key)
        else:
            by_conv.setdefault(SHOW_KEY.match(key).group(1), []).append((int(row.get("turn") or 0), key))
    for keys in by_conv.values():
        keys.sort(reverse=True)
        drop.update(k for _, k in keys[each:])
    kept = sorted((float(rows[k].get("at") or rows[k].get("taking_at") or 0), k) for k in rows if k not in drop)
    drop.update(k for _, k in kept[:max(0, len(kept) - KEEP_ALL)])  # and the newest KEEP_ALL in all, so the folder stays small
    with _Lock(os.path.join(folder, ".lock")):
        for key in drop:
            for p in rows[key].get("pictures") or []:
                if isinstance(p, dict) and isinstance(p.get("file"), str) and "/" not in p["file"] and os.sep not in p["file"]:
                    gone(os.path.join(folder, p["file"]))
            gone(record_path(data, key))
        named = {p.get("file") for key, row in rows.items() if key not in drop for p in row.get("pictures") or [] if isinstance(p, dict)}
        for name in names:
            path = os.path.join(folder, name)
            if os.path.splitext(name)[1].lower() in PICTURES and name not in named:
                try:
                    if now - os.path.getmtime(path) > STRAY:
                        gone(path)
                except OSError:
                    pass
            elif name.startswith(".work-") and os.path.isdir(path):
                try:
                    if now - os.path.getmtime(path) > STRAY:
                        shutil.rmtree(path, ignore_errors=True)
                except OSError:
                    pass
        index(data)
    return len(drop)


# ---------- the page's side (connect/control.py) ----------

def picture_view(rows):
    return [{"n": n, **{k: p.get(k) for k in ("phase", "view", "width", "height")}} for n, p in enumerate(rows) if isinstance(p, dict)]


def listing(data, talks=None):
    """The shows as the page gets them: every one waiting to be looked at, then the last LISTED_DECIDED looked at,
    newest first, each with its floor's check result beside it (src/proof.js) from the feed's conversations."""
    rows = (read(os.path.join(root(data), "index.json")) or {}).get("shows") or []
    talks = {c.get("id"): c for c in talks or [] if isinstance(c, dict)}
    out, decided = [], 0
    for row in rows:
        if not isinstance(row, dict) or row.get("state") not in STATES:
            continue
        if row["state"] != "waiting":
            decided += 1
            if decided > LISTED_DECIDED:
                continue
        talk = talks.get(row.get("conv")) or {}
        proof = {"changed": talk.get("changed"), "proof": talk.get("proof")} if talk.get("changed") or talk.get("proof") else None
        out.append({**{k: row.get(k) for k in ("key", "conv", "title", "project", "at", "state", "how", "why", "changed", "said", "words",
                                                 "decided_at", "address", "why_before")},
                    "title": row.get("title") or talk.get("title") or "An agent's work",
                    "output": row.get("output") if isinstance(row.get("output"), dict) else {},
                    "pictures": picture_view(row.get("pictures") or []), "proof": proof})
    return out


def decide(data, key, state, words=None):
    """Marks a show approved (Looks good) or again (Not quite, with the words). Gives the show as it is now."""
    with _Lock(os.path.join(root(data), ".lock")):
        row = record(data, key)
        if not row or row.get("phase") != "ready":
            return None
        row.update(state=state, decided_at=round(time.time(), 2))
        if words:
            row["words"] = one_line(words, 2000)
        write(record_path(data, key), row)
        index(data)
    return row


def image(data, key, n):
    """One picture of a show, as base64: for a phone, or a page whose server keeps the data elsewhere. None if there
    is no such picture."""
    row = record(data, key)
    if not row or isinstance(n, bool) or not isinstance(n, int):
        return None
    pictures = row.get("pictures") or []
    if not 0 <= n < len(pictures) or not isinstance(pictures[n], dict):
        return None
    name = str(pictures[n].get("file") or "")
    folder = os.path.realpath(root(data))
    path = os.path.realpath(os.path.join(folder, name))
    if not name or os.path.dirname(path) != folder or not os.path.isfile(path) or os.path.getsize(path) > PICTURE_MOST:
        return None
    kind = picture_kind(path)
    if not kind:
        return None
    with open(path, "rb") as handle:
        raw = handle.read()
    return {"key": key, "n": n, "type": "image/png" if kind == "png" else "image/jpeg", "data": base64.b64encode(raw).decode("ascii"),
            **{k: pictures[n].get(k) for k in ("phase", "view", "width", "height")}}


def again_words(words):
    """What an agent is handed when you say Not quite."""
    return ("You finished, and the person you are working for looked at your work in Arnheim, the building (Show me), and said "
            f'it isn\'t quite right yet: "{one_line(words, 1500)}". Change it as they say, then finish again and say what you changed.')


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Show me: pictures of an agent's finished work (docs/connect.md, \"Show me\").")
    parser.add_argument("--after", nargs=3, metavar=("KEY", "PROJECT", "TURN"), help="take the pictures from after, as a turn finishes")
    parser.add_argument("--sweep", action="store_true", help="take away shows past their time")
    args = parser.parse_args()
    data = os.environ.get("ARNHEIM_DATA") or DATA
    if args.after and (not CONV.match(args.after[0]) or not args.after[2].isdigit()):
        parser.error("--after takes a conversation's key, its floor's project, and the turn's time in seconds")
    try:
        if args.after:
            conv, project, turn = args.after
            print(after(data, conv, project, int(turn)) or "nothing")
        elif args.sweep:
            print(sweep(data))
    except Exception as error:  # trouble goes to the feed's log, as the hook's does
        try:
            os.makedirs(os.path.join(data, "feeds"), exist_ok=True)
            with open(os.path.join(data, "feeds", "claude-code.log"), "a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} show {type(error).__name__}: {error}\n")
        except OSError:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
