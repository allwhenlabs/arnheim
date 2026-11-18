#!/usr/bin/env python3
"""Your plan's limits, and when you'll reach them (docs/connect.md, "Usage forecast").

Claude Code and Codex each stop your agents when your plan's limit for the next few hours (or the week)
is used up, and the most common complaint about both is reaching it without warning. Each says how much
is used and when it starts again: Claude Code to its status line, as each message is answered, and Codex
in each conversation's own record. This keeps a few hours of those readings in data/feeds/usage.json,
and the page draws from them how fast the limit is going, when you'd reach it at that pace, and whether
that is before it starts again (src/usage.js).

  python3 connect/usage.py                 Claude Code's status line: notes the limits, and shows them
  python3 connect/usage.py --then 'CMD'    the same, but shows your own status line, CMD, as before

connect/setup.py sets it as Claude Code's status line, keeping yours: it wraps it with --then, and
--undo puts it back. Codex's readings come in through connect/claude_code.py, as Codex's hooks run. It
never troubles Claude Code: any trouble goes to data/feeds/claude-code.log. Standard library only.
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
KEEP = 12 * 3600  # readings kept this long
MOST = 400  # readings kept at most, for each limit
EVERY = 60  # seconds: a reading that hasn't changed is noted at most this often
WINDOWS = {300: "five_hour", 10080: "seven_day"}  # Codex's window lengths in minutes, by Claude Code's names


def path_of(data=None):
    return os.path.join(data or DATA, "feeds", "usage.json")


def number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def from_claude(given):
    """Claude Code's status line input: {"five_hour": {"used": %, "resets_at": epoch}, ...}, or {}."""
    limits = given.get("rate_limits") if isinstance(given, dict) else None
    out = {}
    for name, window in (limits.items() if isinstance(limits, dict) else []):
        if not isinstance(window, dict):
            continue
        used = number(window.get("used_percentage"))
        resets = number(window.get("resets_at"))
        if used is not None:
            out[str(name)] = {"used": max(0.0, min(100.0, used)), "resets_at": resets}
    return out


def from_codex(limits, now=None):
    """Codex's rate_limits from a token count: {"primary": {"used_percent", "window_minutes", "resets_at" or
    "resets_in_seconds"}, "secondary": {...}}, by the same names as Claude Code's."""
    now = now or time.time()
    out = {}
    for window in (limits.values() if isinstance(limits, dict) else []):
        if not isinstance(window, dict):
            continue
        used = number(window.get("used_percent"))
        minutes = number(window.get("window_minutes"))
        if used is None:
            continue
        name = WINDOWS.get(int(minutes)) if minutes else None
        name = name or (f"{int(minutes)}_minutes" if minutes else "limit")
        resets = number(window.get("resets_at"))
        if resets is None and number(window.get("resets_in_seconds")) is not None:
            resets = now + number(window.get("resets_in_seconds"))
        out[name] = {"used": max(0.0, min(100.0, used)), "resets_at": resets}
    return out


def keep(source, limits, data=None, now=None):
    """Notes a reading of one agent's limits ("Claude Code" or "Codex"), unless the same was noted a minute ago."""
    if not limits:
        return False
    now = now or time.time()
    path = path_of(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = open(path + ".lock", "a")
    try:
        try:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX)
        except ImportError:
            pass
        try:
            with open(path, encoding="utf-8") as handle:
                feed = json.load(handle)
        except (OSError, ValueError):
            feed = {}
        feed = feed if isinstance(feed, dict) else {}
        sources = feed.get("sources") if isinstance(feed.get("sources"), dict) else {}
        mine = sources.get(source) if isinstance(sources.get(source), dict) else {}
        changed = False
        for name, reading in limits.items():
            rows = [r for r in mine.get(name) or [] if isinstance(r, dict) and now - (number(r.get("at")) or 0) < KEEP]
            last = rows[-1] if rows else None
            same = last and last.get("used") == round(reading["used"], 1) and last.get("resets_at") == reading.get("resets_at")
            if same and now - (number(last.get("at")) or 0) < EVERY:
                mine[name] = rows
                continue
            rows.append({"at": round(now, 1), "used": round(reading["used"], 1), "resets_at": reading.get("resets_at")})
            mine[name] = rows[-MOST:]
            changed = True
        if not changed:
            return False
        sources[source] = mine
        part = f"{path}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump({"about": "Your plan's limits as Claude Code and Codex report them, a few hours back, for the forecast "
                                "(connect/usage.py). Safe to delete.", "sources": sources}, handle, ensure_ascii=False)
        os.replace(part, path)
        return True
    finally:
        lock.close()


def line_of(limits):
    """A short status line of its own: "5h 37% · week 12%"."""
    names = {"five_hour": "5h", "seven_day": "week"}
    parts = [f"{names.get(k, k)} {round(v['used'])}%" for k, v in limits.items()]
    return "Arnheim · " + " · ".join(parts) if parts else "Arnheim"


def note(error):
    try:
        log = os.path.join(DATA, "feeds", "claude-code.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} usage {type(error).__name__}: {error}\n")
    except OSError:
        pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    then = argv[argv.index("--then") + 1] if "--then" in argv and argv.index("--then") + 1 < len(argv) else None
    raw = ""
    limits = {}
    try:
        raw = sys.stdin.read()
        limits = from_claude(json.loads(raw) if raw.strip() else {})
        keep("Claude Code", limits)
    except Exception as error:  # never troubles Claude Code's status line
        note(error)
    if then:  # your own status line, as it was: its words and its exit
        try:
            done = subprocess.run(then, shell=True, input=raw, capture_output=True, text=True, timeout=10)
            sys.stdout.write(done.stdout)
        except Exception as error:
            note(error)
        return 0
    sys.stdout.write(line_of(limits))
    return 0


if __name__ == "__main__":
    sys.exit(main())
