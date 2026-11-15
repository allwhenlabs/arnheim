#!/usr/bin/env python3
"""Your phone, for talking to the building from anywhere: `python3 serve.py --remote <name>` (docs/phone.md).

Arnheim still listens only on this computer (127.0.0.1). A private way in that you run yourself, such as
Tailscale Serve, which is free for personal use, gives your phone a real https address for it. Only your
own devices can reach that address, and the phone needs no certificate of its own. Everything that comes
that way is treated as coming from away, never as this computer, and a request that arrives forwarded
when --remote is off is refused outright.

A phone gets in only once it is paired: the page on this computer shows a one-time code (8 letters and
numbers, 5 minutes, one use, 5 wrong tries ends it), you type it on the phone, and the phone is given a key
of its own in a cookie it can't read or send anywhere else. Only the key's fingerprint is kept here, in
data/remote/ (never served). A paired phone can see the building and talk to everyone in it, by voice too.
Answering and instructing agents from it needs a second step on this computer: "control from this phone",
for a short time you choose. Everything a phone does with control is written to data/remote/log.jsonl,
without what was said. Phones and their control can be removed at any time from this computer.

Standard library only.
"""
import hashlib
import hmac
import json
import os
import re
import secrets
import threading
import time

ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford's: no I, L, O or U to misread
CODE_LIFE = 300  # seconds a pairing code lasts
CODE_TRIES = 5  # wrong tries before a code is used up
TRIES_A_MINUTE = 5  # wrong codes a minute, all phones together, before pairing waits (a new code clears it)
IDLE = 30 * 86400  # a phone not seen for this long is let go
LIFE = 90 * 86400  # and any phone after this long, seen or not
GRANT_MOST = 12 * 3600  # control from a phone lasts this long at most
ACTS_A_MINUTE = 20  # control requests a minute from one phone
COOKIE = "__Host-arnheim_phone"  # __Host-: only this https page can set it, for all of it
NAME = re.compile(r"^(?=.{4,253}$)[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$")


def fingerprint(key):
    return hashlib.sha256(key.encode("utf-8", "replace")).hexdigest()


def clean_name(name):
    """The https name the phone opens, such as my-mac.tailnet.ts.net: a plain host name, never an address."""
    name = str(name or "").strip().lower().rstrip(".")
    if name.startswith("https://"):
        name = name[len("https://"):].rstrip("/")
    if not NAME.match(name) or re.match(r"^[0-9.]+$", name):
        raise ValueError("--remote wants the https name your phone opens, such as my-mac.your-tailnet.ts.net")
    return name


def label_of(agent):
    """A short label for a phone from its browser's own description: "iPhone", "Android phone", "iPad"."""
    a = str(agent or "")
    for word, said in (("iPhone", "iPhone"), ("iPad", "iPad"), ("Android", "Android phone"), ("Macintosh", "Mac"), ("Windows", "Windows computer")):
        if word in a:
            return said
    return "Phone"


class Remote:
    """Pairing, the phones' keys, control from a phone, and the log. `data` is the folder that holds
    data/remote/ (Arnheim's data/ folder)."""

    def __init__(self, name, data):
        self.name = clean_name(name)
        self.folder = os.path.join(data, "remote")
        self.file = os.path.join(self.folder, "phones.json")
        self.lock = threading.Lock()
        self.pending = None  # {"code", "until", "tries"}
        self.misses = []  # times of wrong codes
        self.acts = {}  # phone id -> times of its control requests
        self.phones = self.read()

    # ---------- what is kept ----------

    def read(self):
        try:
            with open(self.file, encoding="utf-8") as handle:
                kept = json.load(handle)
        except (OSError, ValueError):
            return []
        return [p for p in kept if isinstance(p, dict) and isinstance(p.get("key"), str) and isinstance(p.get("id"), str)] if isinstance(kept, list) else []

    def write(self):
        os.makedirs(self.folder, mode=0o700, exist_ok=True)
        os.chmod(self.folder, 0o700)
        temp = self.file + ".new"
        handle = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            json.dump(self.phones, out, indent=1)
        os.replace(temp, self.file)

    def log(self, **what):
        """One line in data/remote/log.jsonl: which phone did what, when. Never a key, a code or words said."""
        try:
            os.makedirs(self.folder, mode=0o700, exist_ok=True)
            handle = os.open(os.path.join(self.folder, "log.jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(handle, "a", encoding="utf-8") as out:
                out.write(json.dumps({"at": round(time.time()), **what}) + "\n")
        except OSError:
            pass

    # ---------- pairing ----------

    def code(self):
        """A new one-time code, shown on this computer, which ends any code before it."""
        with self.lock:
            raw = "".join(secrets.choice(ALPHABET) for _ in range(8))
            self.pending = {"code": raw, "until": time.time() + CODE_LIFE, "tries": 0}
            self.misses = []  # a new code from this computer: wrong tries before it don't keep you waiting
        self.log(event="code")
        return {"code": f"{raw[:4]}-{raw[4:]}", "seconds": CODE_LIFE, "url": f"https://{self.name}/"}

    def pair(self, given, agent="", login=""):
        """A phone's try with a code: its new key (for its cookie) and its record, or None with why not."""
        typed = re.sub(r"[^0-9A-Z]", "", str(given or "").upper()).translate(str.maketrans("ILOU", "110V"))
        now = time.time()
        with self.lock:
            self.misses = [t for t in self.misses if now - t < 60]
            if len(self.misses) >= TRIES_A_MINUTE:
                return None, "Too many wrong codes. Wait a minute, then make a new code on your computer."
            p = self.pending
            if not p or now > p["until"]:
                self.pending = None
                return None, "That code has run out. Make a new one on your computer."
            if not hmac.compare_digest(typed.encode(), p["code"].encode()):
                p["tries"] += 1
                self.misses.append(now)
                if p["tries"] >= CODE_TRIES:
                    self.pending = None
                    return None, "That code is used up after too many wrong tries. Make a new one on your computer."
                return None, "That isn't the code on your computer. Try again."
            self.pending = None
            key = secrets.token_urlsafe(32)
            phone = {"id": secrets.token_hex(6), "key": fingerprint(key), "label": label_of(agent), "login": str(login or "")[:120],
                     "paired": round(now), "seen": round(now), "control": 0}
            self.phones.append(phone)
            self.write()
        self.log(event="paired", phone=phone["id"], label=phone["label"])
        return key, phone

    def phone(self, cookie_header, login=""):
        """The paired phone a request's cookie belongs to, still in date, or None."""
        given = ""
        for part in str(cookie_header or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE and not given:
                given = value.strip()
        if not given or len(given) > 100:
            return None
        print_ = fingerprint(given)
        now = time.time()
        with self.lock:
            for p in self.phones:
                if not hmac.compare_digest(p["key"], print_):
                    continue
                if now - p.get("seen", 0) > IDLE or now - p.get("paired", 0) > LIFE:
                    return None
                if p.get("login") and login != p["login"]:
                    return None  # paired from one Tailscale login, now arriving from another, or from none
                if now - p.get("seen", 0) > 600:
                    p["seen"] = round(now)
                    self.write()
                return dict(p)
        return None

    # ---------- control from a phone ----------

    def may_control(self, phone):
        return bool(phone) and time.time() < float(phone.get("control") or 0)

    def acted(self, phone, what, code):
        """A control request from a phone, counted and written down. False when it is one too many this minute."""
        now = time.time()
        with self.lock:
            times = [t for t in self.acts.get(phone["id"], []) if now - t < 60]
            if len(times) >= ACTS_A_MINUTE:
                return False
            times.append(now)
            self.acts[phone["id"]] = times
        if what:
            self.log(event="control", phone=phone["id"], label=phone["label"], request=what, result=code)
        return True

    # ---------- this computer's own page ----------

    def status(self):
        now = time.time()
        with self.lock:
            live = [p for p in self.phones if now - p.get("seen", 0) <= IDLE and now - p.get("paired", 0) <= LIFE]
            shown = [{"id": p["id"], "label": p["label"], "paired": p["paired"], "seen": p["seen"],
                      "control": round(p["control"]) if now < float(p.get("control") or 0) else 0} for p in live]
            waiting = self.pending is not None and now <= self.pending["until"]
        return {"on": True, "name": self.name, "url": f"https://{self.name}/", "phones": shown, "code": waiting}

    def grant(self, phone_id, minutes):
        """Control from one phone for this many minutes (0 ends it)."""
        seconds = max(0, min(GRANT_MOST, int(float(minutes) * 60)))
        with self.lock:
            p = next((x for x in self.phones if x["id"] == phone_id), None)
            if not p:
                return False
            p["control"] = round(time.time() + seconds) if seconds else 0
            self.write()
        self.log(event="control on" if seconds else "control off", phone=phone_id, minutes=seconds // 60)
        return True

    def remove(self, phone_id=None):
        """Lets one phone go, or every phone (None)."""
        with self.lock:
            before = len(self.phones)
            self.phones = [p for p in self.phones if phone_id is not None and p["id"] != phone_id]
            gone = before - len(self.phones)
            self.write()
        self.log(event="removed", phone=phone_id or "all", count=gone)
        return gone
