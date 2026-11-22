#!/usr/bin/env python3
"""The night shift: work you approved, run overnight on allowance that would otherwise go unused (docs/connect.md,
"The night shift").

Claude Code's and Codex's allowances start again on a timer, and what you haven't used by then is lost. Off unless you
switch it on (Settings, Switches: "The night shift"). Then, during your quiet hours (23:00 to 07:00 unless you set
others; "night_from" and "night_to" in data/serve.json, beside the switches), and only while the forecast says some of
an allowance would go unused before it starts again, the night shift runs work you approved for it:

- a ready task at the front door (connect/intake.py) you ticked Tonight, or said "do it tonight" to;
- an item of the day's approved plan (connect/day.py) that didn't start.

Never one that needs a decision from you, names a password or key, or would push, publish, deploy, send or delete:
the front door's own words for those (connect/intake.py) and the chain of command's (connect/deputy.py, NEVER). Never
while every agent is paused, on a floor past its budget, or on a floor whose folder isn't kept in git, where no restore
point could be kept. One agent at a time on each floor, Claude Code or Codex as the floor says, started through the
front door (or, with it switched off, as an agent started from the building).

What would go unused comes from your plan's limits as Claude Code and Codex report them (connect/usage.py, read as
connect/day.py's forecast reads them): all of what is left of a weekly limit when it starts again before you're back,
or else what the week's forecast at your own pace leaves when it starts again. A 5-hour window that ends before you're
back is said too; its unused part is only lost when the week has room to spare, so the week decides. The night shift
may use your share of what would go unused (80% unless you set another; "night_share"), and never comes closer than
MARGIN points to any limit. With no forecast, it runs nothing and says why. The cap is set once a night, from the
reading when its first run on that agent starts, and every later start waits for a reading taken since the last one
began, so it never runs twice on the same old numbers.

Each run is told it is on the night shift: work only on that task, and no pushing, publishing, deploying, sending or
deleting. The night shift keeps a restore point of the floor's files just before it starts each run (connect/restore.py),
so there is a way back even where Arnheim's hooks aren't set up. It counts as proven only when its floor's check passes
after its last change (connect/prove.py), which Arnheim knows only where its hooks see the agent's steps. When a reading shows the cap reached, or the week
started again, it is stopped at its next step (the brake: Box.stop, as the hook honours it), and what is left waits for
another night.

In the morning, the Night shift report on Needs you: "4 things finished overnight, 3 proven, 1 not", each with its
proof, its Show me card when there is one, and Undo, which puts its restore point back (Control.restore). A desktop
alert comes when the page next opens.

Nothing runs while Arnheim isn't running: serve.py looks every half a minute, and the page's reads look too.
`python3 connect/night.py --show` says what the night shift would do now, and changes nothing.

Each night is kept in data/night/<date>.json (the evening it began), two weeks back, and the Tonight ticks in
data/night/tonight.json. Standard library only.
"""
import argparse
import datetime
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time


def _beside(name):
    """A module beside this file, loaded by its path (python3 -I, no folder on the path), as control.py does."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import day, deputy, intake, restore, switches, usage  # as connect.night, from serve.py
except ImportError:
    try:
        import day  # beside this file
        import deputy
        import intake
        import restore
        import switches
        import usage
    except ImportError:
        day, deputy, intake, restore, switches, usage = (_beside(n) for n in ("day", "deputy", "intake", "restore", "switches", "usage"))

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
SWITCH = "night"
NAMES = ("night", "night_set", "night_tick", "night_undo")  # Control.handle's, for the night shift
READS = ("night",)  # the one that only reads: serve.py counts it for a phone, and never logs it
QUIET = {"from": "23:00", "to": "07:00"}
SHARE = 80  # percent of what would go unused that the night shift may use, unless you set another
LEAST_SHARE, MOST_SHARE = 10, 100
MARGIN = 10  # points of each limit the night shift never uses
LEAST = 3  # points of room it needs before it starts anything
FIVE = "five_hour"
WEEK = "seven_day"
AGENTS = ("Claude Code", "Codex")
KEEP_NIGHTS = 14
EVERY = 15  # seconds: the page's reads look at the night at most this often
BRAKE_WAIT = 120  # seconds after the brake before an agent started here that hasn't stopped is stopped outright
SAME_WINDOW = 120  # seconds: two readings whose reset times are this close are the same window
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
RAN_ID = re.compile(r"^n-[0-9a-f]{8}$")
ABOUT = ("One night of the night shift (connect/night.py; docs/connect.md, \"The night shift\"): what it ran on allowance that "
         "would otherwise go unused, and the morning's report. Safe to delete.")
TICKS_ABOUT = ("The ready tasks you ticked Tonight, for the night shift (connect/night.py). Safe to delete: the ticks are then "
               "forgotten.")
# What the agent is told, after Done when and Proven by (at most 400 characters: connect/intake.py's limit for a note).
NOTE = ("Arnheim's night shift started you: the person you work for approved this for tonight and is away until {back}. Work "
        "only on this. Never push, publish, deploy, merge, upload, open a pull request, send, reply or delete anything: leave "
        "that to them. If something needs their decision, leave that part, finish the rest, and say what you need.")
DAY_NOTE = ("This is one item of the plan for the {label} floor that the person you work for approved in Arnheim's daily "
            "cycle.")
# Words that ask the person to decide something: such work waits for them.
DECIDE = re.compile(r"\?|\b(?:decide|decides|deciding|decision|decisions|choose|chosen|pick between|pick one of|which one|"
                    r"which of|whether|should we|should i|ask me|check with me|up to you|your call|let me know)\b", re.I)


# Work the night shift never does, beyond the chain of command's words (deputy.NEVER): anything that reaches outside this
# computer or tidies away what is there. Such work waits for you.
NIGHT_NEVER = re.compile(r"\b(?:upload\w*|pull[ -]?requests?|gh\s+pr|sync\w*|rsync|scp|sftp|repl(?:y|ies|ied|ying)|"
                         r"comment\w*|prun\w*|clean(?:s|ed|ing)?[ -]?up|cleanups?)\b", re.I)
# A night run's shell steps that reach outside this computer or tidy away what is there: the hook turns them down
# (connect/claude_code.py), as it does deputy.PUSHY's and restore.risky's. Options may come before git's or gh's
# own word (git -C "my dir" push, gh -R owner/repo pr create).
NIGHT_STEPS = re.compile(
    r"\bgit\b[^|;&\n]*?\s(?:push|merge|send-email|request-pull|remote\s+prune|worktree\s+prune)\b|"
    r"\bgh\b[^|;&\n]*?\s(?:pr|release|issue|api|gist|repo|workflow|run|secret)\b|"
    r"\b(?:rsync|scp|sftp|ftp|rclone|upload\w*|sync|prune|ssh)\b|"
    r"\baws\b[^|;&\n]*?\s(?:s3\s+(?:cp|mv|sync|rm|rb|mb)|s3api\s+(?:put|delete|copy|create|upload)[\w-]*)\b|"
    r"\b(?:cargo|poetry|flit|hatch|uv)\s+publish\b|\bgem\s+push\b|\btwine\s+upload\b|\b(?:docker|podman)\s+push\b|"
    r"\bkubectl\s+(?:apply|delete|create|rollout)\b|\bterraform\s+(?:apply|destroy)\b|\b(?:heroku|vercel|netlify|flyctl)\b|"
    r"\b(?:sendmail|msmtp)\b|\bmailx?\s+-s\b", re.I)
SENDS = re.compile(r"\b(?:curl|wget)\b[^|;&\n]*(?:\s(?:-X|--request|--method)[\s=]*['\"]?(?:POST|PUT|PATCH|DELETE|post|put|patch|delete)\b|"
                   r"\s--data\S*|\s--json\b|\s--form\b|\s--upload-file\b|\s--post-\w+|\s-[a-zA-Z]*[dFT])|"
                   r"\b(?:https?|xh)\s+(?:-\S+\s+)*(?:POST|PUT|PATCH|DELETE)\b")
# A script may push or publish where no step says so (./ship.sh, npm run release, make publish): at night, a shell step
# with one of these words anywhere in it is turned down too. As a bare word, so "pushd" or "relationship" is not; a
# build's --release is a build, not a release.
SCRIPT_WORDS = re.compile(r"(?<![A-Za-z])(?:[Pp]ush|PUSH|[Pp]ublish|PUBLISH|[Uu]npublish|[Rr]elease|RELEASE|[Ss]hip|SHIP|"
                          r"[Dd]eploy|DEPLOY|[Uu]pload|UPLOAD)(?![a-z])")
BUILD_RELEASE = re.compile(r"(?<!\S)--release\b(?!\s*=)")
# What would undo the night's git settings (no_push_env): turned down, whatever else the step says.
GIT_GUARD = re.compile(r"GIT_CONFIG|pushinsteadof|\benv\s+(?:-\S*\s+)*?(?:-[a-zA-Z]*[iu]\b|--ignore-environment|--unset|-(?:\s|$))", re.I)
# Tools a step's "command" is not a command for: a patch, or a file's new words.
NOT_SHELL = ("apply_patch", "Edit", "Write", "MultiEdit", "NotebookEdit")
# Another server's tools (mcp__server__tool): at night, only one whose own name starts with a word that only reads, and
# says nothing that changes, sends or names a secret.
READ_VERBS = ("get", "list", "read", "search", "fetch", "view", "find", "query", "describe", "show", "status")
WRITE_WORDS = re.compile(
    r"\b(?:create|update|write|edit|add|delete|remove|send|post|put|patch|set|save|upload|push|merge|publish|deploy|release|"
    r"run|exec|execute|fork|move|rename|archive|close|reopen|mark|assign|reply|comment|invite|approve|reject|cancel|submit|"
    r"insert|upsert|replace|clear|reset|sync|apply|start|stop|trigger|dispatch|share|transfer|pay|buy|install|uninstall|"
    r"import|copy|drop|purge|lock|unlock|enable|disable|subscribe|unsubscribe|follow|unfollow|react|vote|notify|schedule|"
    r"book|order|sign|login|logout|secrets?|passwords?|tokens?|credentials?|keys?)\b")
# A night run's agent is started with git's pushes sent nowhere (no_push_env): each address below, as a push gives it,
# is rewritten to a scheme git has no way to reach, so the push fails before it connects. Pushes to a folder on this
# computer (a file:// or plain path remote) are untouched.
NO_PUSH_SCHEME = "night-shift-never-pushes://"
NO_PUSH_FROM = ("https://", "http://", "ssh://", "git://", "git@", "git+ssh://", "ssh+git://", "ftp://", "ftps://")
STALE = 15 * 60  # seconds: a Codex night run at work this long since its last weekly reading is stopped, to be safe
# Claude Code tells its limits once a run, at its first request (seen with 2.1.325), so a long Claude Code night run
# asks again with a tiny probe of its own: no tools, no hooks, no session kept.
PROBE_AFTER = 10 * 60  # seconds: a Claude Code night run whose newest weekly reading is older than this sends a probe
PROBE_WAIT = 60  # seconds the probe may take
PROBE_GAP = 60  # seconds between one probe's end and the next one's start
PROBE_MISSES = 2  # probes in a row with no reading before a run is stopped to be safe
PROBE_ARGS = ["-p", "ok", "--model", "haiku", "--max-turns", "1", "--no-session-persistence", "--settings",
              '{"disableAllHooks": true}', "--strict-mcp-config", "--tools", "", "--output-format", "stream-json", "--verbose"]
PROBE_KEPT = 5  # the start times of the last few probes in a row that brought no reading
LONGEST = 20_000  # characters: a night run's command longer than this is not read, it waits (the hook has a time limit)
TOO_LONG = "a command too long to read"
BLIND = "No fresh reading of your limits, so it stopped to be safe."


class Refused(Exception):
    """Something the night shift can't do, in words for the person who asked."""


# ---------- small helpers ----------

def read(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            got = json.load(handle)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
    os.replace(part, path)


def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def points(n):
    """A share of a limit, as people say it: 42%, or 4.5% when it is small."""
    n = max(0.0, float(n))
    return f"{round(n)}%" if n >= 10 or n == round(n) else f"{round(n, 1)}%"


def clock(at, now=None):
    return day.clock_of(at, now)


# ---------- the settings, in data/serve.json beside the switches ----------

def clock_ok(value):
    m = CLOCK.match(str(value or "").strip())
    if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
        return None
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def settings(data):
    """The quiet hours ({"from", "to"}) and the share, as you set them, else as usual."""
    kept = switches.saved(data)
    start, end = clock_ok(kept.get("night_from")), clock_ok(kept.get("night_to"))
    quiet = {"from": start, "to": end} if start and end and start != end else dict(QUIET)
    share = kept.get("night_share")
    share = int(share) if isinstance(share, (int, float)) and not isinstance(share, bool) and LEAST_SHARE <= share <= MOST_SHARE else SHARE
    return {"quiet": quiet, "share": share}


def save_settings(data, quiet=None, share=None):
    """Keeps new quiet hours or a new share in data/serve.json, leaving everything else there as it was."""
    given = {}
    if quiet is not None:
        if isinstance(quiet, str) and re.match(r"^\s*\d{1,2}:\d{2}\s*(?:-|to|until)\s*\d{1,2}:\d{2}\s*$", quiet):
            quiet = [p.strip() for p in re.split(r"-|to|until", quiet)]
        if isinstance(quiet, dict):
            quiet = [quiet.get("from"), quiet.get("to")]
        if not isinstance(quiet, (list, tuple)) or len(quiet) != 2:
            raise Refused("Quiet hours are a start and an end, like 23:00 and 07:00.")
        start, end = clock_ok(quiet[0]), clock_ok(quiet[1])
        if not start or not end:
            raise Refused("A time of day is like 23:00 or 07:30.")
        if start == end:
            raise Refused("Quiet hours start and end at different times.")
        given.update(night_from=start, night_to=end)
    if share is not None:
        if isinstance(share, bool) or not isinstance(share, (int, float)) or not LEAST_SHARE <= share <= MOST_SHARE:
            raise Refused(f"The share is a number from {LEAST_SHARE} to {MOST_SHARE}: the percent of what would go unused it may use.")
        given["night_share"] = int(round(share))
    if not given:
        return settings(data)
    with switches._Locked(data):
        kept = {**switches.saved(data), **given}
        part = f"{switches.path(data)}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(kept, handle, indent=1)
            handle.write("\n")
        os.replace(part, switches.path(data))
    return settings(data)


# ---------- the quiet hours ----------

def span(quiet, now=None):
    """The quiet hours under way, or the next: {"in", "began", "ends", "night"}, where night is the date they began on,
    on this computer's clock. Quiet hours may run across midnight (23:00 to 07:00) or within a day (01:00 to 06:00)."""
    now = now or time.time()
    today = datetime.datetime.fromtimestamp(now).date()
    one = datetime.timedelta(days=1)

    def at(date, hhmm):
        hour, minute = (int(x) for x in hhmm.split(":"))
        return datetime.datetime.combine(date, datetime.time(hour, minute)).timestamp()
    start, end = quiet["from"], quiet["to"]
    if start < end:  # within one day
        began, ends, date = at(today, start), at(today, end), today
        if now >= ends:
            began, ends, date = at(today + one, start), at(today + one, end), today + one
    elif now < at(today, end):  # across midnight, before the end: they began yesterday evening
        began, ends, date = at(today - one, start), at(today, end), today - one
    else:
        began, ends, date = at(today, start), at(today + one, end), today
    return {"in": began <= now < ends, "began": began, "ends": ends, "night": date.isoformat()}


def quiet_now(data, now=None):
    """Whether the night shift is on and it is its quiet hours: the daily cycle then leaves its approved items to it."""
    try:
        return switches.on(SWITCH, data) and span(settings(data)["quiet"], now)["in"]
    except Exception:  # whatever can't be read leaves the daily cycle as it was
        return False


# ---------- what would go unused (your plan's limits, as connect/day.py's forecast reads them) ----------

def agent_room(source, week, five, now, back, share):
    """One agent's allowance tonight: {agent, known, open, used, at, resets, lost, room, five, words}. `week` and
    `five` are its forecasts (connect/day.py forecast), or None; `back` is when you're back; `share` 0 to 1."""
    out = {"agent": source, "known": False, "open": False, "used": None, "at": None, "resets": None, "lost": None, "room": 0.0,
           "five": None, "five_resets": None}
    if five:
        out.update(five=five["used"], five_resets=five.get("resets"))
    if not week:
        out["words"] = (f"No forecast for {source}: it hasn't reported its weekly limit in the last 6 hours, so the night shift "
                        f"can't tell what would go unused, and runs nothing on it.")
        return out
    used, resets, rate, at = week["used"], week.get("resets"), week.get("rate"), week.get("at") or now
    out.update(used=used, at=at, resets=resets)
    if used >= 100:
        out.update(known=True, lost=0.0, words=f"{source}'s weekly limit is used up" + (f" until {clock(resets, now)}." if resets else "."))
        return out
    if resets and resets <= back:
        lost = 100 - used
        said = (f"{source}'s weekly limit starts again at {clock(resets, now)}, before you're back at {clock(back, now)}, with "
                f"{points(lost)} unused.")
    elif resets and rate is not None:
        lost = max(0.0, 100 - used - rate * max(0.0, resets - at))
        said = (f"At your pace, {source} uses all of its weekly limit before it starts again at {clock(resets, now)}, so none "
                "would go unused." if lost <= 0 else
                f"At your pace, about {points(lost)} of {source}'s weekly limit would be left unused when it starts again at "
                f"{clock(resets, now)}.")
    else:
        out["words"] = (f"Not enough readings yet to tell {source}'s pace this week, so the night shift can't tell what would go "
                        "unused, and runs nothing on it.")
        return out
    room = max(0.0, min(share * lost, (100 - MARGIN) - used))
    out.update(known=True, lost=round(lost, 1), room=round(room, 1))
    if lost <= 0:
        out["words"] = said
        return out
    if room < LEAST:
        said += f" Keeping {MARGIN} points in hand, that leaves too little for the night shift."
    else:
        said += f" The night shift may use up to {points(room)} of it ({round(share * 100)}% of that, keeping {MARGIN} points in hand)."
    if five and five["used"] >= 100 - MARGIN:
        said += (f" Its 5-hour limit is {points(five['used'])} used, so nothing starts on it until "
                 f"{clock(five['resets'], now) if five.get('resets') else 'it starts again'}.")
    elif five and five.get("resets") and five["resets"] <= back:
        said += f" Its 5-hour window ends at {clock(five['resets'], now)} with {points(100 - five['used'])} unused."
    out["open"] = room >= LEAST and not (five and five["used"] >= 100 - MARGIN)
    out["words"] = said
    return out


def window(data, now=None, kept=None, sp=None):
    """What would go unused tonight, agent by agent: {known, open, back, words, agents: {name: agent_room}}."""
    now = now or time.time()
    kept = kept or settings(data)
    sp = sp or span(kept["quiet"], now)
    back = sp["ends"]
    limits = day.forecast(data, now)
    agents = {}
    for source in AGENTS:
        mine = [f for f in limits if f.get("source") == source]
        week = next((f for f in mine if f.get("name") == WEEK), None)
        five = next((f for f in mine if f.get("name") == FIVE), None)
        if week or five:
            agents[source] = agent_room(source, week, five, now, back, kept["share"] / 100)
    if not agents:
        words = ("No forecast: Claude Code and Codex haven't reported your plan's limits to Arnheim in the last 6 hours, so the "
                 "night shift can't tell what would go unused, and runs nothing.")
    else:
        words = " ".join(a["words"] for a in agents.values())
    return {"known": any(a["known"] for a in agents.values()), "open": any(a["open"] for a in agents.values()),
            "back": back, "words": words, "agents": agents}


def unknown_agent(source):
    return {"agent": source, "known": False, "open": False, "used": None, "at": None, "resets": None, "lost": None, "room": 0.0,
            "five": None, "five_resets": None,
            "words": f"No forecast for {source}: it hasn't reported your plan's limits in the last 6 hours, so the night shift "
                     "runs nothing on it."}


# ---------- what you approved for it ----------

def ticks_path(data):
    return os.path.join(data, "night", "tonight.json")


def ticks(data):
    got = (read(ticks_path(data)) or {}).get("ticked")
    return {k: v for k, v in got.items() if isinstance(k, str) and intake.TASK_ID.match(k) and isinstance(v, dict)} if isinstance(got, dict) else {}


def keep_ticks(data, ticked):
    write(ticks_path(data), {"about": TICKS_ABOUT, "ticked": ticked})


def refusal(words, held=None):
    """Why the night shift leaves work to you, in words, or None: it names a password or key, it is work the building
    never hands out, it says something the chain of command never answers for you (secrets, money, deleting, pushing,
    publishing, sending), or it asks you to decide something."""
    words = " ".join(str(words or "").split())
    norm = intake.wits.norm(words)
    if intake.has_secret(words) or intake.SECRET_WORDS.search(norm) or held == intake.HELD_SECRET:
        return "It mentions a password or key, so it waits for you, never the night shift."
    if intake.NEVER_HANDED.search(norm):
        return "It's work Arnheim never hands to an agent: signing in, sending, buying or paying."
    m = deputy.NEVER.search(words)
    if m:
        return (f"It says \"{m.group(0)}\", and anything to do with secrets, money, deleting, pushing, publishing or sending "
                "waits for you, never the night shift.")
    m = NIGHT_NEVER.search(words)
    if m:
        return (f"It says \"{m.group(0)}\": anything that reaches outside this computer (uploading, syncing, a pull request, a "
                "reply or a comment) or tidies away what is there waits for you, never the night shift.")
    if held == intake.HELD_FINAL or intake.wits.FINAL.search(norm):
        return "It can't be taken back once it's done, so it waits for you, never the night shift."
    if DECIDE.search(words):
        return "It needs a decision from you first, so it waits for you."
    return None


def held_why(task):
    """Why the front door holds a ready task back (it names a secret, or can't be taken back), as the night shift says
    it, or None: such a task starts only when you press Start, never at night."""
    held = (task or {}).get("held")
    return f"The night shift leaves it to you. {held}" if held else None


def working_run(data, key):
    """Whether a conversation is one of the night shift's runs at work, for the hook's night rule (connect/claude_code.py):
    by its key, or, for Codex, which names its thread once it starts, by the ready task its agent was started for. A row
    that isn't one (hand-edited, or half written) is passed over, never the cause of an error."""
    if not isinstance(key, str) or not key:
        return False
    record = None
    if re.match(r"^[A-Za-z0-9_-]{1,80}$", key):
        record = read(os.path.join(data, "control", "runs", key + ".json"))
        record = record if isinstance(record, dict) else None
    readies = set()
    for doc in nights(data, 2):
        for r in doc.get("ran") or []:
            if not isinstance(r, dict) or r.get("state") != "working":
                continue
            if r.get("key") == key:
                # your own words to it carry it on as yours (Control.say drops "night"), even before the next tick
                return record is None or (record.get("night") is True and record.get("state") == "working")
            if isinstance(r.get("ready"), str) and r["ready"]:
                readies.add(r["ready"])
    if readies and record is not None:
        return (isinstance(record.get("ready"), str) and record["ready"] in readies and record.get("state") == "working"
                and record.get("night") is True)
    return False


def shell_command(tool, given):
    """The command a step runs, as text, or None: any tool handed a "command" (or Codex's "cmd"), as text or as a list
    of words: Bash, Monitor, PowerShell, Codex's shell and exec_command (connect/live.py, SHELLS), a slash command. A
    patch or a file's new words is not a command."""
    if not isinstance(given, dict) or str(tool) in NOT_SHELL:
        return None
    command = given.get("command") if given.get("command") is not None else given.get("cmd")
    if isinstance(command, (list, tuple)):
        return " ".join(str(word) for word in command)
    return command if isinstance(command, str) else None


def command_refusal(command):
    """What in a night run's shell command makes it wait for the person, in its own words, or None."""
    command = str(command or "")
    if len(command) > LONGEST:
        return TOO_LONG
    m = (deputy.PUSHY.search(command) or NIGHT_STEPS.search(command) or SENDS.search(command) or GIT_GUARD.search(command)
         or SCRIPT_WORDS.search(BUILD_RELEASE.sub(" ", command)))
    if m:
        return m.group(0).strip()
    if restore.risky(command):
        return "deletes or overwrites files in bulk"
    return None


def name_words(name):
    """A tool's name in words: split at __, _, -, dots and spaces, and where camelCase turns (postMessage: post message)."""
    name = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", str(name or "")))
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", name) if w]


def mcp_refusal(tool):
    """Why a night run may not use another server's tool (mcp__server__tool), or None: only one whose own name starts
    with a word that only reads (READ_VERBS) and says nothing that changes, sends or names a secret."""
    parts = str(tool).split("__", 2)
    words = name_words(parts[2] if len(parts) == 3 else parts[-1])
    if not words or words[0] not in READ_VERBS:
        return f"its name doesn't start with a word that only reads ({', '.join(READ_VERBS)})"
    m = WRITE_WORDS.search(" ".join(words))
    return f"it says \"{m.group(0)}\"" if m else None


def step_refusal(tool, given):
    """Why a night run's step is turned down, or None: a shell command (any tool handed one) that pushes, publishes,
    deploys, sends, uploads, syncs, opens a pull request, deletes or overwrites files in bulk, runs a script named for
    any of that, or would undo the night's git settings; or another server's tool that does more than read."""
    tool = str(tool or "")
    command = shell_command(tool, given)
    said = command_refusal(command) if command is not None else None
    if said == TOO_LONG:
        return ("Not run: this command is too long for the night shift to read, so it waits for the person you work for. "
                "Leave it, finish the rest, and say in your summary what is left for them.")
    if said:
        return (f"Not run: the night shift never runs this step ({one_line(said, 60)}). It pushes, publishes, deploys, "
                "sends, uploads, syncs, opens a pull request or deletes, and that waits for the person you work for. "
                "Leave it, finish the rest, and say in your summary what is left for them.")
    if tool.startswith("mcp__"):
        said = mcp_refusal(tool)
        if said:
            return (f"Not run: the night shift uses another server's tools only to read, and {one_line(tool, 80)} may do "
                    f"more ({said}): that waits for the person you work for. Leave it, finish the rest, and say in your "
                    "summary what is left for them.")
    return None


def no_push_env(env=None, codex=False):
    """The environment a night run's agent starts with: as `env` (this one's, if None), with git's pushes to another
    computer sent nowhere. Each address in NO_PUSH_FROM is rewritten for a push (url.<scheme>.pushInsteadOf) to one git
    can't reach, so `git push` fails before it connects, whatever runs it: the agent itself, or a script of the
    project's. Settings already given this way are kept, and these added after them. Claude Code's are given as
    GIT_CONFIG_COUNT, GIT_CONFIG_KEY_n and GIT_CONFIG_VALUE_n. Codex leaves out of its commands any setting whose name
    says KEY (its shell_environment_policy), and git refuses every command when a KEY_n it was promised is missing, so
    Codex's go in GIT_CONFIG_PARAMETERS, as `git -c` hands them on."""
    env = dict(os.environ if env is None else env)
    pairs = [(f"url.{NO_PUSH_SCHEME}.pushInsteadOf", prefix) for prefix in NO_PUSH_FROM]
    if codex:
        quoted = " ".join("'" + f"{k}={v}".replace("'", "'\\''") + "'" for k, v in pairs)
        env["GIT_CONFIG_PARAMETERS"] = f"{env['GIT_CONFIG_PARAMETERS']} {quoted}" if env.get("GIT_CONFIG_PARAMETERS") else quoted
        return env
    try:
        count = int(env.get("GIT_CONFIG_COUNT") or 0)
    except ValueError:
        count = 0
    count = max(0, count)
    for i, (k, v) in enumerate(pairs, count):
        env[f"GIT_CONFIG_KEY_{i}"], env[f"GIT_CONFIG_VALUE_{i}"] = k, v
    env["GIT_CONFIG_COUNT"] = str(count + len(pairs))
    return env


def company_of(data):
    return read(os.path.join(data, "company.json")) or {}


def floor_rows(data):
    """Each floor with a folder on this computer: {project, label, id, folder, agent}."""
    out = []
    for floor in company_of(data).get("floors") or []:
        if not isinstance(floor, dict):
            continue
        folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
        here = [os.path.realpath(os.path.expanduser(f)) for f in folders if isinstance(f, str)] if isinstance(folders, list) else []
        here = [f for f in here if os.path.isdir(f)]
        if not here:
            continue
        project = str(floor.get("project") or floor.get("label") or floor.get("id") or "")
        out.append({"project": project, "label": str(floor.get("label") or project), "id": str(floor.get("id") or ""), "folder": here[0],
                    "agent": "Codex" if str(floor.get("agent") or "").strip().lower() == "codex" else "Claude Code"})
    return out


def door_open(ctrl, data):
    return ctrl is not None and getattr(ctrl, "intake", None) is not None and switches.on("front_door", data)


def ready_task(data, ctrl, rid):
    """A ready task's own record (connect/intake.py), or None."""
    try:
        if ctrl is not None and getattr(ctrl, "intake", None) is not None:
            return ctrl.intake.task(rid)
        row = read(os.path.join(data, "control", "intake", rid + ".json")) if intake.TASK_ID.match(rid) else None
        return row if row and row.get("state") in intake.STATES else None
    except Exception:  # not one of its ids, or it isn't kept any more
        return None


def plan_dates(sp, now):
    """The plans whose approved items the night shift may take: the evening's, and today's when that is another."""
    dates = [sp["night"]]
    if day.today(now) not in dates:
        dates.append(day.today(now))
    return dates


def queue(data, ctrl, now=None, sp=None, tidy=True):
    """What the night shift may take, in order: [{kind: "ready" or "day", id, title, project, label, agent, text, day?,
    ready?, why}], where why says why it waits for you (or None). Ticks whose task has started, finished or gone are
    let go of (unless tidy is False: then it only reads)."""
    now = now or time.time()
    sp = sp or span(settings(data)["quiet"], now)
    floors = {f["project"]: f for f in floor_rows(data)}
    door = door_open(ctrl, data) or (ctrl is None and switches.on("front_door", data))
    out, seen = [], set()
    ticked = ticks(data)
    gone = []
    for rid, tick_row in sorted(ticked.items(), key=lambda kv: number(kv[1].get("at")) or 0):
        task = ready_task(data, ctrl, rid)
        if not task or task.get("state") not in intake.WAITING:
            gone.append(rid)
            continue
        floor = floors.get(task.get("project"))
        row = {"kind": "ready", "id": rid, "title": one_line(task.get("title"), 120), "project": task.get("project"),
               "label": (floor or {}).get("label") or task.get("label") or task.get("project"), "agent": task.get("agent") or "Claude Code",
               "text": task.get("text") or "", "ready": rid, "ticked": number(tick_row.get("at"))}
        row["why"] = (refusal(f"{task.get('title')} {task.get('text')}", task.get("held")) or held_why(task)
                      or (None if floor else "Its floor has no folder on this computer any more.")
                      or (None if door else "One front door is switched off, so its ready tasks wait."))
        out.append(row)
        seen.add(rid)
    if gone and tidy:
        keep_ticks(data, {k: v for k, v in ticked.items() if k not in gone})
    if switches.on("daily_cycle", data):
        for date in plan_dates(sp, now):
            doc = day.load(data, date) or {}
            for f in doc.get("plan") or []:
                if not isinstance(f, dict) or not f.get("approved"):
                    continue
                floor = floors.get(f.get("floor"))
                for it in f.get("items") or []:
                    if not isinstance(it, dict) or it.get("state") != "approved" or it.get("ready") in seen:
                        continue
                    row = {"kind": "day", "id": str(it.get("id") or ""), "title": one_line(it.get("title"), 120), "project": f.get("floor"),
                           "label": f.get("label") or f.get("floor"), "text": it.get("text") or it.get("title") or "", "day": date,
                           "ready": it.get("ready"),
                           "agent": ((floor or {}).get("agent") or "Claude Code") if door else "Claude Code"}
                    task = ready_task(data, ctrl, it["ready"]) if it.get("ready") else None
                    # Its whole text, whatever it came from: an item carried from yesterday, an unfinished one or a goal's
                    # carries its own words, which may say "then deploy" under a harmless title.
                    row["why"] = (refusal(f"{it.get('title')} {it.get('text') or ''}", (task or {}).get("held")) or held_why(task)
                                  or (None if floor else "Its floor has no folder on this computer any more."))
                    out.append(row)
                    if it.get("ready"):
                        seen.add(it["ready"])
    return out


# ---------- the nights ----------

_RLOCK = threading.RLock()
_HELD = threading.local()


class locked:
    """One change to the night at a time: between threads here (serve.py's look and the page's requests), and between
    processes."""

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        _RLOCK.acquire()
        depth = getattr(_HELD, "depth", 0)
        if depth == 0:
            folder = os.path.join(self.data, "night")
            os.makedirs(folder, exist_ok=True)
            handle = open(os.path.join(folder, ".lock"), "a")
            try:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX)
            except ImportError:
                pass
            _HELD.handle = handle
        _HELD.depth = depth + 1
        return self

    def __exit__(self, *_):
        _HELD.depth -= 1
        if _HELD.depth == 0:
            _HELD.handle.close()
            _HELD.handle = None
        _RLOCK.release()


def path_of(data, night):
    return os.path.join(data, "night", night + ".json")


def load(data, night):
    doc = read(path_of(data, night))
    return doc if doc and isinstance(doc.get("ran"), list) else None


def keep(data, doc):
    doc["about"] = ABOUT
    write(path_of(data, doc["night"]), doc)
    try:  # two weeks are kept
        oldest = (datetime.date.today() - datetime.timedelta(days=KEEP_NIGHTS)).isoformat()
        for name in os.listdir(os.path.join(data, "night")):
            if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", name) and name[:10] < oldest:
                os.remove(os.path.join(data, "night", name))
    except OSError:
        pass


def nights(data, back=KEEP_NIGHTS):
    """The nights kept, newest first."""
    try:
        names = sorted((n for n in os.listdir(os.path.join(data, "night")) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", n)), reverse=True)
    except OSError:
        return []
    out = []
    for name in names[:back]:
        doc = load(data, name[:10])
        if doc:
            out.append(doc)
    return out


def fresh_night(sp):
    return {"night": sp["night"], "began": sp["began"], "ends": sp["ends"], "caps": {}, "ran": [], "said": None, "queued": 0, "report": None}


def last_ended(data, now=None):
    """The latest night that has ended, or None."""
    now = now or time.time()
    return next((d for d in nights(data, 3) if float(d.get("ends") or 0) <= now), None)


# ---------- the runs ----------

def run_of(ctrl, r):
    """The agent started here for a night run, by its key or its ready task (Codex takes a new key once it starts)."""
    if ctrl is None:
        return None
    with ctrl.lock:
        runs = list(ctrl.runs.values())
    return (next((x for x in runs if r.get("key") and x.get("key") == r["key"]), None)
            or next((x for x in runs if r.get("ready") and x.get("ready") == r["ready"]), None))


def feed_talks(data):
    feed = read(os.path.join(data, "feeds", "claude-code.json")) or {}
    return {c.get("id"): c for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id")}


def alive(ctrl, data, r, talks=None):
    run = run_of(ctrl, r)
    if run is not None:  # a run you have carried on yourself (no "night" now) is no longer the night's at work
        return run.get("state") == "working" and ctrl.alive(run) and run.get("night") is True, run
    talk = (talks if talks is not None else feed_talks(data)).get(r.get("key"))
    return bool(talk and talk.get("working")), None


def brake_why(r, doc, win, now):
    """Why a run must stop before the limit, or None: the night's cap reached, a 5-hour limit close, or the week started
    again (so what would have gone unused is gone)."""
    cap = (doc.get("caps") or {}).get(r.get("agent"))
    a = (win.get("agents") or {}).get(r.get("agent"))
    if not cap or not a:
        return None
    source = r["agent"]
    if a.get("resets") and cap.get("resets") and abs(a["resets"] - cap["resets"]) > SAME_WINDOW:
        return f"{source}'s week started again, so what would have gone unused is gone, and it stopped."
    if a.get("used") is not None and a["used"] >= cap["cap"]:
        return (f"Stopped before the limit: {source}'s weekly limit reached {points(a['used'])}, the most the night shift may use "
                "tonight.")
    if a.get("five") is not None and a["five"] >= cap.get("five", 100 - MARGIN):
        return f"Stopped before the limit: {source}'s 5-hour limit reached {points(a['five'])}."
    return None


def stale_why(r, win, now, data=None, ctrl=None):
    """Why a run must stop because nothing says how close the limit is, or None, so a long run never goes past the cap
    unseen. Measured from its agent's newest weekly reading, or from the run's start if that is later.

    Claude Code tells its limits once a run, at its first request, and none after: so while a Claude Code night run
    works and that reading is more than PROBE_AFTER old, a tiny probe asks for a fresh one (probe), one at a time for the
    whole building. A reading it brings is kept as a run's is, and the brake decides on it (brake_why). Only when
    PROBE_MISSES probes in a row bring none, and nothing else has since, does the run stop. Codex reports its limits
    through its hooks as it works, so a Codex run stops when no reading has come for STALE seconds. The next start waits
    for a fresh reading anyway (can_take), so the rest of the night may go on once one comes."""
    a = (win.get("agents") or {}).get(r.get("agent")) or {}
    last = max(float(a.get("at") or 0) if a.get("used") is not None else 0.0, float(r.get("started_at") or 0))
    if r.get("agent") != "Claude Code":
        return BLIND if now - last > STALE else None
    if data is None:
        return None
    p = probe_state(data)
    # only probes that began after this run's newest reading (or its start) count: an earlier run's, or an old night's
    missed = p.get("missed") if isinstance(p.get("missed"), list) else []
    missed = [t for t in missed if isinstance(t, (int, float)) and not isinstance(t, bool) and t > last]
    if len(missed) >= PROBE_MISSES:
        return BLIND
    if now - last > PROBE_AFTER:
        probe(data, ctrl, now)
    return None


# ---------- the probe: a fresh reading of Claude Code's limits ----------

_PROBING = {}  # data folder: the thread of the probe under way, if any (tests wait on it)


def probe_path(data):
    return os.path.join(data, "night", "probe.json")


def probe_state(data):
    """The last probe: {running (when the one under way began, or None), ended, got, misses, missed}, where missed holds
    when each of the last probes in a row that brought no reading began."""
    return read(probe_path(data)) or {}


def probe(data, ctrl, now=None):
    """Starts a probe, unless one is under way (for the whole building: kept in data/night/probe.json) or the last one
    ended less than PROBE_GAP ago. In the background: it never holds the night up. Gives whether one started."""
    now = now or time.time()
    command = list(getattr(ctrl, "claude", None) or []) or ["claude"]
    with locked(data):
        p = probe_state(data)
        running = float(p.get("running") or 0)
        if running and now - running < PROBE_WAIT + 30:
            return False
        if now - float(p.get("ended") or 0) < PROBE_GAP:
            return False
        p.update(running=now)
        write(probe_path(data), {**p, "about": "The night shift's last probe of Claude Code's limits (connect/night.py). Safe to delete."})
    thread = threading.Thread(target=probe_once, args=(data, command, now), daemon=True)
    _PROBING[data] = thread
    thread.start()
    return True


def probe_once(data, command, began=None):
    """One probe: `claude -p "ok"` on haiku, one turn, no tools, no hooks, no session kept, in an empty folder of its own
    under data/night/, at most PROBE_WAIT seconds. Its rate_limit_event, if it says one, is kept through connect/usage.py
    as an agent's is. A probe that says none, fails or runs too long counts as no reading. Gives whether it got one."""
    began = began or time.time()
    got = False
    folder = os.path.join(data, "night", "probe")
    try:
        os.makedirs(folder, exist_ok=True)
        # in a session of its own, so a probe that runs too long is stopped with everything it started
        proc = subprocess.Popen(list(command) + PROBE_ARGS, cwd=folder, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            out, _ = proc.communicate(timeout=PROBE_WAIT)
        except subprocess.TimeoutExpired:
            try:
                if not hasattr(os, "killpg"):
                    raise AttributeError("killpg")
                os.killpg(proc.pid, getattr(signal, "SIGKILL", signal.SIGTERM))
            except (OSError, AttributeError):
                proc.kill()
            try:
                proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:  # something it started holds the output open: let it go
                pass
            raise
        for raw in out.decode("utf-8", "replace").splitlines():
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if isinstance(event, dict) and event.get("type") == "rate_limit_event":
                limits = usage.from_claude_event(event.get("rate_limit_info"))
                if limits:
                    usage.keep("Claude Code", limits, data)
                got = got or WEEK in limits  # only the week's reading says how close the night's cap is
    except Exception as error:  # any trouble counts as no reading
        note(data, error)
    try:
        with locked(data):
            p = probe_state(data)
            kept = p.get("missed") if isinstance(p.get("missed"), list) else []
            kept = [t for t in kept if isinstance(t, (int, float)) and not isinstance(t, bool)]
            missed = [] if got else kept[-(PROBE_KEPT - 1):] + [began]
            p.pop("missed_since", None)  # how an earlier version kept them
            p.update(running=None, ended=max(time.time(), began), got=got, misses=len(missed), missed=missed)
            write(probe_path(data), p)
    except Exception as error:  # the record's trouble: the next probe tries again
        note(data, error)
    return got


def settle(data, ctrl, doc, now, win=None):
    """The night's runs: those that ended are marked so (and their plan items), and those at work are stopped before the
    limit when a reading shows it reached (the brake). Gives whether anything changed."""
    changed = False
    talks = None
    for r in doc.get("ran") or []:
        if r.get("state") != "working":
            continue
        talks = talks if talks is not None else feed_talks(data)
        working, run = alive(ctrl, data, r, talks)
        if run is not None and run.get("key") and run["key"] != r.get("key"):
            r["key"] = run["key"]  # Codex named its thread
            changed = True
        if working:
            win = win or window(data, now)
            why = brake_why(r, doc, win, now)
            blind = None if why else stale_why(r, win, now, data, ctrl)
            if (why or blind) and not r.get("braked_at"):
                r.update(braked_at=now, why=why or blind)
                cap = (doc.get("caps") or {}).get(r["agent"])
                if cap is not None and why:
                    cap["braked"] = True  # nothing more starts on that agent tonight: the rest waits
                if ctrl is not None:
                    try:
                        ctrl.box.stop(r["key"])  # the hook stops it at its next step
                    except Exception:
                        pass
                changed = True
            elif r.get("braked_at") and now - float(r["braked_at"]) > BRAKE_WAIT and not r.get("halted") and ctrl is not None:
                r["halted"] = now
                try:
                    ctrl.stop(r["key"])  # it hasn't reached a step: stopped outright, as Stop does
                except Exception:
                    pass
                changed = True
            continue
        if run is None and ctrl is not None and r.get("key") and now - float(r.get("started_at") or 0) < 10:
            continue  # just started: the building hasn't seen it yet
        state = (run or {}).get("state")
        r.update(state="braked" if r.get("braked_at") else state if state in ("done", "failed", "stopped") else "done", ended_at=now)
        spent = ((talks or {}).get(r.get("key")) or {}).get("spent")
        if isinstance(spent, dict) and isinstance(spent.get("tokens"), int):
            r["spent"] = spent["tokens"]
        if r.get("kind") == "day":
            settle_item(data, r, now)
        changed = True
    return changed


def settle_item(data, r, now):
    """A plan item the night shift ran: marked done, failed or stopped on its day's plan."""
    try:
        with day.locked(data):
            doc = day.load(data, r.get("day") or "")
            if not doc:
                return
            for f in doc.get("plan") or []:
                for it in f.get("items") or []:
                    if it.get("id") == r.get("ref") and it.get("state") == "started":
                        it.update(state={"done": "done", "failed": "failed"}.get(r["state"], "stopped"), ended_at=now)
                        if r.get("spent"):
                            it["spent"] = r["spent"]
            day.keep(data, doc)
    except Exception as error:  # the plan's trouble never costs the night
        note(data, error)


def busy(data, ctrl, project, doc, talks):
    """Why a floor can't take another agent now, or None: one from the building at work there, one of the night's, or
    any conversation the feed says is at work there."""
    if any(r.get("project") == project and r.get("state") == "working" for r in doc.get("ran") or []):
        return "One of the night's agents is at work on this floor."
    try:
        if ctrl is not None and ctrl.intake.busy(project):
            return "An agent started from the building is at work on this floor."
    except Exception:
        pass
    if any(c.get("project") == project and c.get("working") for c in talks.values()):
        return "An agent is at work on this floor."
    return None


def over_budget(data, ctrl, project):
    if not switches.on("budget", data):
        return False
    try:
        return bool(ctrl.intake.over_budget(project))
    except Exception:
        over, _ = day.over_budget(data, day.work_of(data), project, ctrl)
        return over


def can_take(doc, win, source, now):
    """Why nothing more may start on an agent tonight, or None. Sets the night's cap for it at its first start."""
    a = (win.get("agents") or {}).get(source) or unknown_agent(source)
    caps = doc.setdefault("caps", {})
    cap = caps.get(source)
    if not a.get("known"):
        return a["words"]
    if cap:
        if cap.get("braked"):
            return f"{source} reached the most the night shift may use tonight, so the rest waits for another night."
        if a.get("resets") and cap.get("resets") and abs(a["resets"] - cap["resets"]) > SAME_WINDOW:
            return f"{source}'s week started again, so what would have gone unused is gone."
        last = float(cap.get("last") or 0)
        if last and last != now and float(a.get("at") or 0) < last:  # floors started in the same look share one reading
            return f"Waiting for {source} to report your plan's limits since its last run began, so the night shift knows what's left."
        if a["used"] + LEAST > cap["cap"]:
            return f"{source} has used what the night shift may use tonight."
        if a.get("five") is not None and a["five"] >= cap.get("five", 100 - MARGIN):
            return f"{source}'s 5-hour limit is {points(a['five'])} used, so nothing more starts on it until it starts again."
        return None
    if not a.get("open"):
        return a["words"]
    caps[source] = {"resets": a.get("resets"), "cap": round(a["used"] + a["room"], 1), "five": 100 - MARGIN, "from": a["used"],
                    "room": a["room"], "set": now, "last": 0}
    return None


def launch_ready(ctrl, rid, note_words):
    """Starts a ready task through the front door: its agent is handed your words, Done when and Proven by, and the night
    shift's note; the card keeps its own words. Gives the new agent's key. Raises Refused with why it can't start."""
    door = ctrl.intake
    with door.lock:
        try:
            task = door.task(rid)
        except intake.Refusal as why:
            raise Refused(str(why))
        if task["state"] not in intake.WAITING:
            raise Refused("It isn't waiting to start any more.")
        if held_why(task):  # it names a secret, or can't be taken back: it starts only when you press Start
            raise Refused(held_why(task))
        why = refusal(f"{task.get('title')} {task.get('text')}")
        if why:
            raise Refused(f"The night shift leaves it to you. {why}")
        why = door.blocked(task)
        if why:
            raise Refused(why)
        before = task.get("note")
        task["note"] = f"{before} {note_words}" if before else note_words
        try:
            door.launch(task, night=True)
        except intake.Refusal as why_not:
            task.pop("note", None) if before is None else task.update(note=before)
            door.save(task)
            raise Refused(str(why_not))
        task.pop("note", None) if before is None else task.update(note=before)
        door.save(task)
        return task["key"]


def start_item(data, ctrl, entry, note_words, now):
    """Starts an item of the approved plan: made a ready task once (kept on the item), then started through the front
    door; or, with the front door off, as an agent started from the building. Gives (key, ready id or None)."""
    with day.locked(data):
        doc = day.load(data, entry["day"])
        f = next((x for x in (doc or {}).get("plan") or [] if x.get("floor") == entry["project"]), None)
        it = next((x for x in (f or {}).get("items") or [] if x.get("id") == entry["id"]), None)
        if not it or it.get("state") != "approved" or not f.get("approved"):
            raise Refused("It isn't waiting on the plan any more.")
        if any(x.get("state") == "started" and x is not it and day.running(ctrl, x.get("key")) for x in f.get("items") or []):
            raise Refused("Another item of the plan is at work on this floor.")
        rid, key = it.get("ready"), None
        try:
            if door_open(ctrl, data):
                if not rid:
                    # With Start ready tasks by themselves on, the front door starts it as it takes it: then its note is the
                    # night shift's. Otherwise the card keeps the plan's note, and the night's goes in only as it starts.
                    told = note_words if switches.on("ready_auto", data) else DAY_NOTE.format(label=f.get("label") or entry["project"])
                    try:
                        got = ctrl.intake.take({"text": it.get("text") or it["title"], "title": it["title"], "floor": entry["project"],
                                                "note": told, "via": "day", "night": True})
                    except intake.Refusal as why:
                        raise Refused(str(why))
                    task = got.get("task") or {}
                    rid = task.get("id")
                    if not rid:
                        raise Refused(one_line(got.get("reply") or "The front door didn't take it.", 200))
                    it["ready"] = rid  # made once: the next try starts this one
                    if task.get("state") == "started" and task.get("key"):
                        key = task["key"]  # Start ready tasks by themselves started it
                if not key:
                    key = launch_ready(ctrl, rid, note_words)
                how = "night shift"
            else:
                try:
                    key = ctrl.start(entry["project"], f"{it.get('text') or it['title']}\n\n{note_words}",
                                     more={"title": it["title"], "night": True})["key"]
                except Exception as why:  # Control's Refused, in its own words
                    raise Refused(one_line(str(why) or "It didn't start.", 200))
                how = "night shift"
        except Refused as why:
            it["waiting"] = str(why)
            day.keep(data, doc)
            raise
        it.update(state="started", key=key, started_at=now, how=how)
        it.pop("waiting", None)
        day.keep(data, doc)
    return key, rid


def work(data, ctrl, doc, kept, sp, now):
    """During the quiet hours: starts what may start, one agent at a time on each floor. Gives what started, in words."""
    q = queue(data, ctrl, now, sp)
    doc["queued"] = max(int(doc.get("queued") or 0), len([e for e in q if not e["why"]]))
    takeable = [e for e in q if not e["why"]]
    if not takeable:
        doc["said"] = "Nothing is approved for tonight." if not q else "What is approved for tonight waits for you: " + q[0]["why"]
        return []
    if ctrl is None:
        doc["said"] = "The night shift needs Answer agents from the building, in Settings, to start anything."
        return []
    if ctrl.box.paused():
        doc["said"] = "Every agent is paused, so the night shift starts nothing until you resume them."
        return []
    if not switches.on("restore", data):
        doc["said"] = "Restore points are switched off, so the night shift starts nothing: each run must keep a way back."
        return []
    win = window(data, now, kept, sp)
    if not win["known"]:
        doc["said"] = win["words"]
        return []
    floors = {f["project"]: f for f in floor_rows(data)}
    talks = feed_talks(data)
    started, waits, taken = [], [], set()
    for entry in takeable:
        project = entry["project"]
        if project in taken:
            continue
        floor = floors.get(project)
        if not floor:
            continue
        why = busy(data, ctrl, project, doc, talks)
        if not why and over_budget(data, ctrl, project):
            why = f"{entry['label']} is over today's budget."
        if not why and not restore.top(floor["folder"]):
            why = f"{entry['label']}'s folder isn't kept in git, so no restore point could be kept."
        if not why:
            why = can_take(doc, win, entry["agent"], now)
        if why:
            waits.append(f"\"{entry['title']}\" on {entry['label']}: {why}")
            continue
        # A way back before anything starts, kept here and not left to the hook: an agent whose hooks aren't set up
        # (or Codex without them) would otherwise run all night with no restore point.
        point = restore.take(floor["folder"], "before the night shift's run", project=project, title=entry["title"], by="night shift",
                             data=data, now=now)
        if not point:
            waits.append(f"\"{entry['title']}\" on {entry['label']}: no restore point could be kept of its files, so it waits.")
            continue
        words = NOTE.format(back=clock(sp["ends"], now))
        try:
            if entry["kind"] == "ready":
                key, rid = launch_ready(ctrl, entry["id"], words), entry["id"]
            else:
                key, rid = start_item(data, ctrl, entry, words, now)
        except Refused as why_not:
            waits.append(f"\"{entry['title']}\" on {entry['label']}: {why_not}")
            continue
        taken.add(project)
        doc["caps"][entry["agent"]]["last"] = now
        doc["ran"].append({"id": "n-" + secrets.token_hex(4), "kind": entry["kind"], "ref": entry["id"], "day": entry.get("day"),
                           "ready": rid, "title": entry["title"], "project": project, "label": entry["label"], "agent": entry["agent"],
                           "key": key, "point": point["id"], "started_at": now, "state": "working"})
        keep(data, doc)  # at once: the hook's night rule (connect/claude_code.py) knows it from its first step
        if entry["kind"] == "ready":
            ticked = ticks(data)
            if ticked.pop(entry["id"], None) is not None:
                keep_ticks(data, ticked)
        started.append(f"\"{entry['title']}\" on {entry['label']}")
    if started:
        doc["said"] = f"Started {'; '.join(started)}."
    elif waits:
        doc["said"] = waits[0]
    return started


def tick(data=None, ctrl=None, now=None):
    """Settles the night's runs (and stops one at the limit), starts what may start during the quiet hours, and makes the
    morning report once they end. Gives what it did."""
    data = data or (ctrl.data if ctrl is not None else DATA)
    now = now or time.time()
    if not switches.on(SWITCH, data):
        return []
    kept = settings(data)
    sp = span(kept["quiet"], now)
    did = []
    with locked(data):
        for doc in nights(data, 2):  # last night's runs may still be at work in the morning
            if not (sp["in"] and doc["night"] == sp["night"]) and float(doc.get("ends") or 0) > now:
                doc["ends"] = now  # the quiet hours were moved to end earlier: this night is over now
                keep(data, doc)
            if doc["night"] != sp["night"] and any(r.get("state") == "working" for r in doc["ran"]):
                if settle(data, ctrl, doc, now):
                    keep(data, doc)
        if sp["in"]:
            doc = load(data, sp["night"]) or fresh_night(sp)
            doc.update(began=sp["began"], ends=sp["ends"])  # as the quiet hours are now, if they were moved tonight
            settle(data, ctrl, doc, now)
            did += [f"started {s}" for s in work(data, ctrl, doc, kept, sp, now)]
            keep(data, doc)
        last = last_ended(data, now)
        if last and last.get("report") is None and (last["ran"] or last.get("queued")):
            last["report"] = {"at": now, "seen": False}
            keep(data, last)
            did.append("report")
    return did


_TICKING = threading.Lock()
_LAST = {}


def maybe_tick(ctrl, now=None):
    """tick(), at most every EVERY seconds, and never two at once."""
    now = now or time.time()
    if now - _LAST.get(ctrl.data, 0) < EVERY or not _TICKING.acquire(blocking=False):
        return
    try:
        _LAST[ctrl.data] = now
        tick(ctrl.data, ctrl, now)
    except Exception as error:  # trouble goes to the log, and the page still reads the night
        note(ctrl.data, error)
    finally:
        _TICKING.release()


def keep_going(control_of, data_of, every=30):
    """For serve.py: every half a minute while it runs. `control_of()` gives Control while it is on (only then does
    anything start), `data_of()` the data folder."""
    while True:
        data = None
        try:
            ctrl = control_of()
            data = ctrl.data if ctrl is not None else data_of()
            if switches.on(SWITCH, data) and _TICKING.acquire(blocking=False):
                try:
                    _LAST[data] = time.time()
                    tick(data, ctrl)
                finally:
                    _TICKING.release()
        except Exception as error:  # whatever went wrong, it looks again next time
            note(data or data_of(), error)
        time.sleep(every)


# ---------- the morning report ----------

def proof_of(talk, now=None):
    """What came of its floor's check after its last change, as src/proof.js's proofOf works it out: {state: proven,
    failed, checking, claimed or none, word, line, tail?}."""
    now = now or time.time()
    talk = talk if isinstance(talk, dict) else {}
    changed = number(talk.get("changed")) or 0
    p = talk.get("proof") if isinstance(talk.get("proof"), dict) else None
    if not changed and not p:
        return {"state": "none", "word": "Changed nothing", "line": "It changed no files, so there was nothing to prove."}
    name = str((p or {}).get("check") or "Its check")
    inner = name[:1].lower() + name[1:] if name[1:2].islower() else name
    at = number((p or {}).get("at")) or 0
    if p and p.get("state") == "checking" and at >= changed and now < (number(p.get("until")) or at + 3600) + 60:
        return {"state": "checking", "word": "Checking", "line": f"Running {inner} on its work now."}
    if not p or p.get("state") == "checking" or at < changed:
        return {"state": "claimed", "word": "Not proven", "line": "It changed files, and nothing has checked them yet."}
    tail = one_line(p.get("tail"), 300) if p.get("tail") else None
    if p.get("state") == "passed":
        return {"state": "proven", "word": "Proven", "line": f"{name} passed after its last change."}
    line = {"timeout": f"{name} ran too long and was stopped.", "error": f"{name} couldn't run."}.get(p.get("state"), f"{name} failed.")
    return {"state": "failed", "word": "Not proven", "line": line, **({"tail": tail} if tail else {})}


def show_of(data, key):
    """Its Show me card's key, the newest, or None."""
    rows = (read(os.path.join(data, "shows", "index.json")) or {}).get("shows") or []
    return next((r.get("key") for r in rows if isinstance(r, dict) and key and r.get("conv") == key), None)


def point_of(data, r, points_kept=None):
    """The restore point kept before its first change: the earliest for its conversation since it started. None."""
    rows = points_kept if points_kept is not None else restore.read_points(data)
    own = next((p for p in rows if r.get("point") and p.get("id") == r["point"]), None)
    if own:
        return own  # kept by the night shift just before it started
    mine = [p for p in rows if r.get("key") and p.get("key") == r["key"] and (number(p.get("at")) or 0) >= float(r.get("started_at") or 0) - 60]
    return min(mine, key=lambda p: number(p.get("at")) or 0) if mine else None


WORDS = {"done": "Finished", "failed": "Ended with an error", "stopped": "Stopped", "braked": "Stopped before the limit",
         "working": "Still at work"}


UNSEEN = {"state": "unseen", "word": "Not proven",
          "line": "Arnheim didn't see its steps (its hooks aren't set up where it ran), so nothing checked its work."}


def item_view(data, r, doc, talks, kept_points, now):
    talk = talks.get(r.get("key"))
    if r.get("state") == "working":
        proof = {"state": "checking", "word": "At work", "line": "It is still at work."}
    else:  # no record of it at all is not the same as a record that it changed nothing
        proof = proof_of(talk, now) if talk is not None else dict(UNSEEN)
    point = point_of(data, r, kept_points)
    nothing = proof["state"] == "none"
    later = [x for x in doc.get("ran") or [] if x is not r and x.get("project") == r.get("project")
             and float(x.get("started_at") or 0) > float(r.get("started_at") or 0) and not x.get("undone")]
    out = {"id": r["id"], "title": r.get("title"), "project": r.get("project"), "label": r.get("label"), "agent": r.get("agent"),
           "key": r.get("key"), "state": "undone" if r.get("undone") else r.get("state"),
           "word": "Undone" if r.get("undone") else WORDS.get(r.get("state"), "Finished"), "ended": r.get("state"), "proof": proof,
           "show": show_of(data, r.get("key")), "undo": bool(point) and not nothing and not r.get("undone") and r.get("state") != "working",
           "why": r.get("why"), "spent": r.get("spent"), "started_at": r.get("started_at"), "ended_at": r.get("ended_at")}
    if (not point or nothing) and r.get("state") != "working":
        out["no_undo"] = ("It changed no files, so there is nothing to put back." if nothing
                          else "No restore point was kept for it, so it can't be put back from here.")
    if out["undo"] and later:
        out["undo_note"] = (f"Undo puts {r.get('label')}'s files back as they were before this ran, so what ran there after it goes "
                            f"too: {', '.join(chr(34) + str(x.get('title')) + chr(34) for x in later[:3])}.")
    return out


def how_it_ended(i):
    """How a run ended, undone or not: a run stopped before the limit and then undone never counts as finished."""
    return (i.get("ended") or "done") if i["state"] == "undone" else i["state"]


def report_words(items, doc, queued=0):
    finished = [i for i in items if how_it_ended(i) == "done"]
    proven = [i for i in finished if i["proof"]["state"] == "proven"]
    if not items:
        return "Nothing ran overnight." + (f" {doc['said']}" if doc.get("said") else "")
    n, p = len(finished), len(proven)
    if n:
        words = f"{plural(n, 'thing', 'things')} finished overnight, " + ("all proven." if p == n else "none proven." if not p else f"{p} proven, {n - p} not.")
    else:
        words = "Nothing finished overnight."
    braked = len([i for i in items if how_it_ended(i) == "braked"])
    failed = len([i for i in items if how_it_ended(i) in ("failed", "stopped")])
    working = len([i for i in items if how_it_ended(i) == "working"])
    if braked:
        words += f" {braked} stopped before the limit."
    if failed:
        words += f" {failed} ended without finishing."
    if working:
        words += f" {working} still at work."
    if queued:
        words += f" {plural(queued, 'thing waits', 'things wait')} for another night."
    return words


def report_view(data, ctrl, doc, now, q=None):
    """The morning's report on a night: {night, id, at, seen, words, items, waiting}."""
    talks = feed_talks(data)
    kept_points = restore.read_points(data)
    items = [item_view(data, r, doc, talks, kept_points, now) for r in doc.get("ran") or []]
    waiting = len([e for e in (q or []) if not e["why"]])
    return {"night": doc["night"], "id": f"night-{doc['night']}", "at": (doc.get("report") or {}).get("at"),
            "seen": bool((doc.get("report") or {}).get("seen")), "words": report_words(items, doc, waiting), "items": items,
            "waiting": waiting, "said": doc.get("said")}


def morning_line(data, now=None):
    """The last night's report in a line, for the daily cycle's plan, or None."""
    try:
        if not switches.on(SWITCH, data):
            return None
        now = now or time.time()
        doc = last_ended(data, now)
        if not doc or not doc.get("report") or now - float(doc.get("ends") or 0) > 18 * 3600:
            return None
        talks, kept_points = feed_talks(data), restore.read_points(data)
        items = [item_view(data, r, doc, talks, kept_points, now) for r in doc.get("ran") or []]
        return "The night shift: " + report_words(items, doc)
    except Exception:  # the night's trouble never costs the plan
        return None


# ---------- what the page and a phone get ----------

def ran_view(data, doc, now):
    talks, kept_points = feed_talks(data), restore.read_points(data)
    return [item_view(data, r, doc, talks, kept_points, now) for r in doc.get("ran") or []]


def view(data, ctrl=None, now=None, tidy=True):
    """The night shift as the page and a phone get it: {on, quiet, share, margin, quiet_now, from, back, window: {known,
    open, words, agents}, queued: [{kind, id, title, project, label, agent, why}], ticked, ran, said, report}."""
    now = now or time.time()
    kept = settings(data)
    sp = span(kept["quiet"], now)
    win = window(data, now, kept, sp)
    q = queue(data, ctrl, now, sp, tidy=tidy)
    current = load(data, sp["night"]) if sp["in"] else None
    last = last_ended(data, now)
    report = None
    if last and last.get("report") is not None and not (sp["in"] and float(last.get("ends") or 0) < sp["began"]):
        report = report_view(data, ctrl, last, now, q)
    shown = current or last
    agents = [{k: a.get(k) for k in ("agent", "known", "open", "used", "lost", "room", "resets", "five", "words")} for a in win["agents"].values()]
    return {"on": True, "quiet": kept["quiet"], "share": kept["share"], "margin": MARGIN, "quiet_now": sp["in"],
            "from": clock(sp["began"], now), "back": clock(sp["ends"], now),
            "window": {"known": win["known"], "open": win["open"], "words": win["words"], "agents": agents},
            "queued": [{k: e.get(k) for k in ("kind", "id", "title", "project", "label", "agent", "why")} for e in q],
            "ticked": [e["id"] for e in q if e["kind"] == "ready"],
            "ran": ran_view(data, shown, now) if shown else [], "said": (current or {}).get("said"), "report": report}


def state_part(ctrl):
    """What Control's state adds: "night", or None while the night shift is switched off. Reading it moves the night on."""
    if not switches.on(SWITCH, ctrl.data):
        return {"night": None}
    maybe_tick(ctrl)
    try:
        return {"night": view(ctrl.data, ctrl)}
    except Exception as error:
        note(ctrl.data, error)
        return {"night": None}


def tick_tonight(data, ctrl, rid, tonight):
    """Ticks a ready task for tonight, or takes the tick off."""
    if not isinstance(rid, str) or not intake.TASK_ID.match(rid):
        raise Refused("That isn't a ready task.")
    if not isinstance(tonight, bool):
        raise Refused("Say tonight true or false.")
    task = ready_task(data, ctrl, rid)
    if not task:
        raise Refused("That ready task isn't kept any more.")
    title = one_line(task.get("title"), 80)
    label = task.get("label") or task.get("project")
    with locked(data):
        ticked = ticks(data)
        if not tonight:
            ticked.pop(rid, None)
            keep_ticks(data, ticked)
            return f"Not tonight: \"{title}\" stays ready on {label}."
        if task.get("state") not in intake.WAITING:
            raise Refused("It isn't waiting to start any more, so there's nothing to do tonight.")
        why = refusal(f"{task.get('title')} {task.get('text')}", task.get("held")) or (task.get("held") or None)
        if why:
            raise Refused(f"The night shift leaves \"{title}\" to you. {why}")
        ticked[rid] = {"at": time.time()}
        keep_ticks(data, ticked)
    quiet = settings(data)["quiet"]
    return (f"Ticked for tonight: \"{title}\" on {label}. Between {quiet['from']} and {quiet['to']} the night shift runs it if "
            f"{task.get('agent') or 'Claude Code'}'s allowance would otherwise go unused, and says how it went in the morning.")


def find_ran(data, rid):
    for doc in nights(data):
        for r in doc.get("ran") or []:
            if r.get("id") == rid:
                return doc, r
    return None, None


def undo(data, ctrl, rid):
    """Undo: puts a night run's restore point back (Control.restore, which keeps one of how things are first)."""
    if not isinstance(rid, str) or not RAN_ID.match(rid):
        raise Refused("That isn't one of the night shift's runs.")
    doc, r = find_ran(data, rid)
    if not r:
        raise Refused("That run isn't kept any more.")
    if r.get("undone"):
        raise Refused("It was undone already.")
    if r.get("state") == "working":
        raise Refused("It is still at work. Stop it first, then undo it.")
    if any(x.get("project") == r.get("project") and x.get("state") == "working" for d in [doc] + nights(data, 2) for x in d.get("ran") or []):
        raise Refused(f"One of the night shift's agents is still at work on {r.get('label') or r.get('project')}. Stop it first, "
                      "then undo this.")
    with ctrl.lock:  # any agent started from the building, yours too (a night run you carried on): never under it
        runs = list(ctrl.runs.values())
    if any(x.get("project") == r.get("project") and x.get("state") == "working" and ctrl.alive(x) for x in runs):
        raise Refused(f"An agent started from the building is at work on {r.get('label') or r.get('project')}. Let it finish "
                      "or stop it first, then undo this.")
    talk = feed_talks(data).get(r.get("key"))
    if talk is not None and proof_of(talk)["state"] == "none":
        raise Refused("It changed no files, so there is nothing to put back.")
    point = point_of(data, r)
    if not point:
        raise Refused("No restore point was kept for it, so it can't be put back from here.")
    done = ctrl.restore(point["id"])  # Control's own Refused says why it can't, in its words
    with locked(data):
        doc, r = find_ran(data, rid)
        r["undone"] = time.time()
        keep(data, doc)
    left = done.get("left") or []
    return (f"Put back: {r.get('label')}'s files are as they were before \"{r.get('title')}\" ran. How they were a moment ago is a "
            "restore point too, so this can be undone." + (f" Files made since are left where they are: {', '.join(left[:3])}." if left else ""))


def handle(ctrl, name, given):
    """Control.handle's names for the night shift. Raises Refused with words for the person."""
    data = ctrl.data
    if name == "night_set":
        said = []
        if "on" in given:
            if not isinstance(given["on"], bool):
                raise Refused("The night shift is on or off.")
            switches.save(SWITCH, given["on"], data)
            said.append("The night shift is on." if given["on"] else "The night shift is off: nothing more starts at night.")
        if "quiet" in given or "share" in given:
            kept = save_settings(data, given.get("quiet"), given.get("share"))
            said.append(f"Quiet hours are {kept['quiet']['from']} to {kept['quiet']['to']}, and it may use {kept['share']}% of what "
                        "would go unused.")
        seen = given.get("seen")
        if seen is True or (isinstance(seen, str) and re.match(r"^night-\d{4}-\d{2}-\d{2}$", seen)):
            with locked(data):  # the report named ("night-<date>"), or the last one
                doc = load(data, seen[6:]) if isinstance(seen, str) else last_ended(data)
                if doc and doc.get("report") is not None:
                    doc["report"]["seen"] = True
                    keep(data, doc)
            said.append("Done.")
        return {"ok": True, "said": " ".join(said) or "Nothing changed.", "night": view(data, ctrl) if switches.on(SWITCH, data) else None}
    if not switches.on(SWITCH, data):
        if name == "night":
            return {"on": False, **settings(data)}
        raise Refused("The night shift is switched off. Switch it on in Settings, under Switches.")
    if name == "night":
        maybe_tick(ctrl)
        return view(data, ctrl)
    if name == "night_tick":
        said = tick_tonight(data, ctrl, given.get("id"), given.get("tonight", True))
        return {"ok": True, "said": said, "night": view(data, ctrl)}
    if name == "night_undo":
        said = undo(data, ctrl, given.get("id"))
        return {"ok": True, "said": said, "night": view(data, ctrl)}
    raise Refused("No such request.")


def note(data, error):
    try:
        log = os.path.join(data, "feeds", "claude-code.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} night {type(error).__name__}: {error}\n")
    except OSError:
        pass


def words_of(v):
    """The night shift in words, for a terminal."""
    lines = [f"Quiet hours {v['quiet']['from']} to {v['quiet']['to']}; it may use {v['share']}% of what would go unused, keeping "
             f"{v['margin']} points of each limit in hand.", v["window"]["words"]]
    if v["queued"]:
        lines.append("Approved for tonight:")
        lines += [f"  {e['title']} on {e['label']} ({e['agent']})" + (f": {e['why']}" if e.get("why") else "") for e in v["queued"]]
    else:
        lines.append("Nothing is approved for tonight.")
    if v.get("report"):
        lines.append("Last night: " + v["report"]["words"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description="The night shift: what it would run tonight, and how last night went (docs/connect.md, \"The night shift\").")
    parser.add_argument("--show", action="store_true", help="say what the night shift would do now, and change nothing")
    parser.parse_args(argv)
    try:
        if not switches.on(SWITCH, DATA):
            print("The night shift is switched off. Switch it on in Settings, under Switches.")
            return 0
        print(words_of(view(DATA, tidy=False)))  # it only reads: --show changes nothing
        return 0
    except Exception as error:
        note(DATA, error)
        print(f"It didn't work: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
