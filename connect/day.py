#!/usr/bin/env python3
"""The daily cycle: a plan in the morning and a close in the evening, for the whole company (docs/connect.md,
"The daily cycle").

Off unless you switch it on (Settings, Switches: "The daily cycle"). Then, at the plan time (09:00 unless you set
another; "day_plan" and "day_close" in data/serve.json, beside the switches), each floor's lead proposes the day for
its floor: what was approved yesterday and didn't get done, work whose check failed, the front door's ready tasks
(when that part is there), the floor's open tasks, and a next step toward each of its open goals. Fitted to the
allowance left today: a floor's budget (connect/budget.py) and your plan's limits as Claude Code and Codex report
them (connect/usage.py). With no reading of the limits, it says so plainly, and never makes a number up. An item
says what it costs only when the floor has finished enough work to tell (the middle of what its finished work spent).

You approve the whole day with one tap, or a floor at a time, or change it in words ("drop the second one on
Tidepool", "add: tidy the README on Lantern", "do the third one first"). Approved items start in order, one at a
time on each floor: through the front door's ready tasks when that part is there (Control names "intake" and
"ready_start"), or else as an agent started from the building (Control.start). Never while every agent is paused,
and never on a floor past its budget for today. At the close time (18:00), the close: what was proven today, what is
stuck and why, what needs you tomorrow, and what today cost.

Nothing runs when Arnheim isn't running. serve.py looks every half a minute while it runs, and the page's own reads
make the plan when it next opens after a missed time. `python3 connect/day.py` makes what is due and gives back at
once (a scheduler of your own can run it); `--plan` and `--close` make them now, `--show` says today's plan.

Each day is kept in data/day/<date>.json, two weeks back, for this computer only: serve.py never gives the files to
another computer, a paired phone or a view-only link (a phone reads the day through /control/day). Words you add to
it pass the front door's secrets check first (connect/intake.py). Standard library only.
"""
import argparse
import datetime
import json
import math
import os
import re
import secrets
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
    from . import budget, switches  # as connect.day, from serve.py
except ImportError:
    try:
        import budget  # beside this file
        import switches
    except ImportError:
        budget = _beside("budget")
        switches = _beside("switches")

_door = None


def _intake():
    """connect/intake.py (one front door), loaded when first wanted: its secrets check and its words for one."""
    global _door
    if _door is None:
        try:
            from . import intake as found  # as connect.day, from serve.py
        except ImportError:
            try:
                import intake as found  # beside this file
            except ImportError:
                found = _beside("intake")
        _door = found
    return _door


HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
SWITCH = "daily_cycle"
NAMES = ("day", "day_plan", "day_approve", "day_change", "day_close", "day_times")  # Control.handle's, for the daily cycle
READS = ("day",)  # the one that only reads: serve.py counts it for a phone, and never logs it
TIMES = {"day_plan": "09:00", "day_close": "18:00"}  # in data/serve.json, beside the switches
MOST = 3  # things a floor proposes at most
TIGHT = 1  # and when your plan's limits are tight
KEEP_DAYS = 14
EVERY = 15  # seconds: the page's reads look at what is due at most this often
ENOUGH = 3  # finished pieces of work a floor needs before an item says what it may cost
TITLE = 120
WORDS = 600
CLOCK = re.compile(r"^(\d{1,2}):(\d{2})$")
ABOUT = ("Today's plan and close, from the daily cycle (connect/day.py; docs/connect.md, \"The daily cycle\"). "
         "Safe to delete: the plan is made again at its time.")


class Refused(Exception):
    """A change the daily cycle can't make, in words for the person who asked."""


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


def upper_first(text):
    return text[:1].upper() + text[1:] if text else text


def today(now=None):
    return datetime.datetime.fromtimestamp(now or time.time()).strftime("%Y-%m-%d")


def clock_of(at, now=None):
    """15:40 today, or "Thu 15:40" on another day."""
    when = datetime.datetime.fromtimestamp(at)
    if when.date() == datetime.datetime.fromtimestamp(now or time.time()).date():
        return when.strftime("%H:%M")
    return when.strftime("%a %H:%M")


def times_of(data):
    """The plan's and the close's times, as "09:00" and "18:00", from data/serve.json."""
    kept = switches.saved(data)
    out = {}
    for name, usual in TIMES.items():
        m = CLOCK.match(str(kept.get(name) or "").strip())
        out[name] = f"{int(m.group(1)):02d}:{m.group(2)}" if m and int(m.group(1)) < 24 and int(m.group(2)) < 60 else usual
    return out


def at_today(clock, now=None):
    """When a time of day ("09:00") is today, on this computer's clock."""
    hour, minute = (int(x) for x in clock.split(":"))
    day = datetime.datetime.fromtimestamp(now or time.time()).date()
    return datetime.datetime.combine(day, datetime.time(hour, minute)).timestamp()


def save_times(data, plan=None, close=None):
    """Keeps new times in data/serve.json, leaving everything else there as it was."""
    given = {}
    for name, value in (("day_plan", plan), ("day_close", close)):
        if value is None:
            continue
        m = CLOCK.match(str(value).strip())
        if not m or int(m.group(1)) > 23 or int(m.group(2)) > 59:
            raise Refused("A time of day is like 09:00 or 18:30.")
        given[name] = f"{int(m.group(1)):02d}:{m.group(2)}"
    if not given:
        raise Refused("Say a time for the plan, the close, or both.")
    with switches._Locked(data):
        kept = {**switches.saved(data), **given}
        part = f"{switches.path(data)}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(kept, handle, indent=1)
            handle.write("\n")
        os.replace(part, switches.path(data))
    return times_of(data)


_RLOCK = threading.RLock()
_HELD = threading.local()


class locked:
    """One change to a day at a time: between threads here (serve.py's look and the page's requests), and between
    processes (another server, or this file run by a scheduler)."""

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        _RLOCK.acquire()
        depth = getattr(_HELD, "depth", 0)
        if depth == 0:
            folder = os.path.join(self.data, "day")
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


def path_of(data, date):
    return os.path.join(data, "day", date + ".json")


def load(data, date):
    doc = read(path_of(data, date))
    return doc if doc and isinstance(doc.get("plan"), list) else None


def keep(data, doc):
    doc["about"] = ABOUT
    write(path_of(data, doc["date"]), doc)
    try:  # two weeks are kept
        oldest = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
        for name in os.listdir(os.path.join(data, "day")):
            if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", name) and name[:10] < oldest:
                os.remove(os.path.join(data, "day", name))
    except OSError:
        pass


# ---------- what the building knows ----------

def company_of(data):
    return read(os.path.join(data, "company.json")) or {}


def floors_here(data):
    """Each floor that names a folder on this computer, in the building's order: {project, label, id, lead}. Only
    these can start an agent, so only these are planned."""
    out = []
    for floor in company_of(data).get("floors") or []:
        if not isinstance(floor, dict):
            continue
        folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
        here = [f for f in folders if isinstance(f, str) and os.path.isdir(os.path.realpath(os.path.expanduser(f)))] if isinstance(folders, list) else []
        if not here:
            continue
        project = str(floor.get("project") or floor.get("label") or floor.get("id") or "")
        lead = floor.get("lead") if isinstance(floor.get("lead"), dict) else {}
        out.append({"project": project, "label": str(floor.get("label") or project), "id": str(floor.get("id") or ""),
                    "lead": one_line(lead.get("name"), 40) or None})
    return out


def work_of(data):
    """work.json, with each feed company.json lists added to it, as the page reads them: tasks, goals, conversations,
    and what conversations that left the feeds today spent."""
    sources = [os.path.join(data, "work.json")]
    for path in company_of(data).get("feeds") or []:
        if isinstance(path, str) and re.match(r"^[\w-]+(/[\w.-]+)*\.json$", path) and ".." not in path:
            sources.append(os.path.join(data, path))
    out = {"tasks": [], "goals": [], "conversations": [], "ended": []}
    for path in sources:
        feed = read(path) or {}
        for key in ("tasks", "goals", "conversations"):
            out[key] += [x for x in feed.get(key) or [] if isinstance(x, dict)]
        if isinstance(feed.get("ended"), dict):
            out["ended"].append(feed["ended"])
    return out


def spent_today(work, project, day):
    total = budget.spent_today(work["conversations"], project, day)
    for ended in work["ended"]:
        total += budget.spent_today([], project, day, ended)
    return total


def over_budget(data, work, project, ctrl=None, day=None):
    """Whether a floor's agents are past their budget for today (as many times as you let them go on), and words."""
    limit = budget.budget_of(company_of(data), project)
    if not limit:
        return False, None
    day = day or budget.local_day()
    times = 1
    if ctrl is not None:
        try:
            times += int(ctrl.box.allowances(day).get(project) or 0)
        except Exception:  # an allowance that can't be read counts as none
            pass
    spent = spent_today(work, project, day)
    return spent >= limit * times, {"spent": spent, "limit": limit * times}


# ---------- your plan's limits (connect/usage.py, src/usage.js) ----------

LENGTH = {"five_hour": 5 * 3600, "seven_day": 7 * 86400}
LIMIT_NAMES = {"five_hour": "5-hour limit", "seven_day": "weekly limit"}


def number(value):
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def forecast(data, now=None):
    """Each limit's last reading and where it is heading, as src/usage.js's forecastOf works it out: [{source, name,
    label, used, resets, reaches, reach, rate, at}], where reaches is now, before, after or unknown, rate is points a
    second (None until there is a pace) and at is when it was read. [] with no readings."""
    now = now or time.time()
    sources = (read(os.path.join(data, "feeds", "usage.json")) or {}).get("sources")
    out = []
    for source, windows in (sources.items() if isinstance(sources, dict) else []):
        for name, rows in (windows.items() if isinstance(windows, dict) else []):
            rows = sorted((r for r in rows or [] if isinstance(r, dict) and number(r.get("at")) is not None and number(r.get("used")) is not None),
                          key=lambda r: number(r["at"]))
            if not rows:
                continue
            last = rows[-1]
            at, used = number(last["at"]), number(last["used"])
            if now - at > 6 * 3600:
                continue
            resets = number(last.get("resets_at"))
            if resets and resets <= now:
                continue

            def same(r):
                other = number(r.get("resets_at"))
                return other == resets or (resets and other and abs(other - resets) < 120)
            recent = [r for r in rows if number(r["at"]) >= at - 3600 and same(r)]
            span = at - number(recent[0]["at"]) if recent else 0
            began = resets - LENGTH[name] if resets and name in LENGTH else None
            since = at - began if began is not None else 0
            average = used / since if since >= 300 else None
            hour = max(0, used - number(recent[0]["used"])) / span if span >= 300 else None
            rate = (average if average is not None else hour) if name == "seven_day" else (hour if hour is not None else average)
            reach = at + max(0, 100 - used) / rate if rate else None
            reaches = ("now" if used >= 100 else "before" if reach and (not resets or reach < resets)
                       else "unknown" if rate is None else "after")
            out.append({"source": str(source), "name": str(name), "label": LIMIT_NAMES.get(name, str(name).replace("_", " ")),
                        "used": round(used, 1), "resets": resets, "reaches": reaches, "reach": reach, "rate": rate, "at": at})
    return out


def allowance(data, now=None):
    """The allowance left today, in words: {known, tight, words}. Never a number that wasn't reported."""
    now = now or time.time()
    limits = forecast(data, now)
    if not limits:
        return {"known": False, "tight": False,
                "words": ("No forecast: Claude Code and Codex haven't reported your plan's limits to Arnheim yet, so this "
                          f"plan isn't fitted to them. Each floor proposes up to {MOST} things.")}
    said = []
    tight = False
    for f in limits:
        if f["reaches"] == "now":
            tight = tight or f["name"] == "seven_day"  # a week used up shapes the day; a few hours' limit only delays it
            said.append(f"{f['source']}'s {f['label']} is used up" + (f" until {clock_of(f['resets'], now)}." if f["resets"] else "."))
        elif f["name"] == "seven_day":
            left = max(0.0, 100 - f["used"])
            if f["resets"]:
                days = max(1, math.ceil((f["resets"] - now) / 86400))
                said.append(f"{f['source']} has {round(left)}% of its weekly limit left until {clock_of(f['resets'], now)}: "
                            f"about {round(left / days)}% a day.")
            else:
                said.append(f"{f['source']} has {round(left)}% of its weekly limit left.")
            if f["reaches"] == "before":
                tight = True
                said.append(f"At this pace {f['source']} reaches it before it starts again.")
        elif f["reaches"] == "before" and f["reach"]:
            said.append(f"At this pace {f['source']} reaches its {f['label']} around {clock_of(f['reach'], now)}"
                        + (f", before it starts again at {clock_of(f['resets'], now)}." if f["resets"] else "."))
        else:
            said.append(f"{f['source']}: {round(f['used'])}% of the {f['label']} used.")
    said.append("Your plan is tight, so each floor proposes one thing." if tight else f"Each floor proposes up to {MOST} things.")
    return {"known": True, "tight": tight, "words": " ".join(said)}


def cost_of(data, project, work, now=None):
    """What one piece of work on a floor has cost, as the middle of what its finished work spent: earlier days' plan
    items, and today's finished conversations. None until there are enough of them to tell."""
    now = now or time.time()
    seen = []
    day = datetime.date.fromtimestamp(now)
    for back in range(1, KEEP_DAYS + 1):
        doc = load(data, (day - datetime.timedelta(days=back)).isoformat())
        for floor in (doc or {}).get("plan") or []:
            if isinstance(floor, dict) and floor.get("floor") == project:
                seen += [it["spent"] for it in floor.get("items") or [] if isinstance(it, dict) and isinstance(it.get("spent"), int) and it["spent"] > 0]
    date = today(now)
    for c in work["conversations"]:
        spent = c.get("spent") if isinstance(c.get("spent"), dict) else {}
        if c.get("project") == project and not c.get("working") and spent.get("day") == date and isinstance(spent.get("tokens"), int) and spent["tokens"] > 0:
            seen.append(spent["tokens"])
    for ended in work["ended"]:
        if ended.get("day") == date and isinstance(ended.get("talks"), dict):
            seen += [t["tokens"] for t in ended["talks"].values() if isinstance(t, dict) and t.get("project") == project and isinstance(t.get("tokens"), int) and t["tokens"] > 0]
    if len(seen) < ENOUGH:
        return None
    seen.sort()
    middle = seen[len(seen) // 2] if len(seen) % 2 else (seen[len(seen) // 2 - 1] + seen[len(seen) // 2]) // 2
    return {"tokens": int(middle), "words": f"about {budget.tokens(int(middle))} tokens", "from": len(seen)}


# ---------- the front door (round 1: Control names "intake", "ready_start"; state "ready") ----------

def call(ctrl, name, body):
    """One of Control's own requests, as the page makes it: (status, answer)."""
    code, _, raw, _ = ctrl.handle("POST", name, json.dumps(body).encode("utf-8"), ctrl.token)
    try:
        got = json.loads(raw.decode("utf-8"))
    except ValueError:
        got = {}
    return code, got if isinstance(got, dict) else {}


def missing(code, got):
    """Control answered that it has no such request: the front door isn't part of this Arnheim."""
    return code == 404 and got.get("error") == "No such request."


_NIGHT = []


def night_shift():
    """connect/night.py, loaded when first wanted: it loads this file itself. None if it can't be."""
    if not _NIGHT:
        try:
            from . import night as got
        except ImportError:
            try:
                import night as got
            except ImportError:
                try:
                    got = _beside("night")
                except Exception:  # an Arnheim without the night shift
                    got = None
        _NIGHT.append(got)
    return _NIGHT[0]


def night_holds(data, now=None):
    """The night shift is on, and it is its quiet hours: approved items wait for it (connect/night.py), which runs them
    only on allowance that would otherwise go unused."""
    shift = night_shift()
    return bool(shift and shift.quiet_now(data, now))


_INSIDE = threading.local()


class within:
    """While the daily cycle itself asks Control something (its state, a start): Control's state reads the day back,
    and must not make or start anything from inside."""

    def __enter__(self):
        _INSIDE.depth = getattr(_INSIDE, "depth", 0) + 1

    def __exit__(self, *_):
        _INSIDE.depth -= 1


def inside():
    return getattr(_INSIDE, "depth", 0) > 0


def ready_rows(ctrl):
    """The front door's ready tasks, when that part is there: [{id, project, title, done_when}] still to start. None
    for an Arnheim without the front door (its state names no "ready"), or whose state can't be read."""
    if ctrl is None:
        return None
    try:
        with within():
            got = ctrl.state()
    except Exception:
        return None
    rows = got.get("ready")
    if not isinstance(rows, list) or (isinstance(got.get("door"), dict) and got["door"].get("on") is False):
        return None  # no front door here, or it is switched off: approved items start as agents from the building
    out = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict) or not row.get("id") or row.get("state") not in (None, "ready", "queued"):
            continue
        title = one_line(row.get("title") or row.get("text") or "", TITLE)
        project = str(row.get("project") or row.get("floor") or "")
        if title and project:
            out.append({"id": str(row["id"]), "project": project, "title": title, "done_when": one_line(row.get("done_when") or "", 300)})
    return out


def key_in(got):
    for where in (got, got.get("ready"), got.get("task"), got.get("run")):
        if isinstance(where, dict) and isinstance(where.get("key"), str):
            return where["key"]
    return None


def id_in(got):
    for where in (got.get("ready"), got.get("task"), got):
        if isinstance(where, dict) and isinstance(where.get("id"), str):
            return where["id"]
    return None


def door_on(ctrl):
    """Whether this Arnheim's front door takes work now: it is there, and its switch is on."""
    try:
        return switches.on("front_door", ctrl.data)
    except Exception:
        return True


def door_task(ctrl, rid):
    """The front door's own record of a ready task (connect/intake.py): its state ("ready", "queued", "started",
    "finished", "dropped") and the key of the agent it started. None when there is no such record here."""
    door = getattr(ctrl, "intake", None)
    try:
        return door.task(rid) if door is not None and hasattr(door, "task") else None
    except Exception:  # not one of its ids, or it isn't kept any more
        return None


def start_item(ctrl, floor, item):
    """Starts one approved item: through the front door's ready tasks when that part is there, else as an agent
    started from the building. Gives (key or None, how). Raises Refused with the reason it can't start now, and then
    the item waits; a ready task the front door made for it is kept on the item ("ready"), so it is made only once."""
    note = (f"This is one item on today's plan for the {floor['label']} floor, approved by the person you work for in Arnheim's "
            "daily cycle. Keep to it, and finish it today if you can.")
    words = f"{item['text']}\n\n{note}"
    # The front door, when it is there and on: the item becomes a ready task (the floor's lead shapes it, with Done
    # when and Proven by, and the plan's title), and that is started. A 404 "No such request." means this Arnheim has
    # no front door.
    rid = item.get("ready")
    if door_on(ctrl):
        if not rid:
            code, got = call(ctrl, "intake", {"text": item["text"], "title": item.get("title"), "note": note, "project": floor["floor"],
                                              "floor": floor["floor"], "via": "day", "from": "daily_cycle"})
            if not missing(code, got):
                if code != 200:
                    raise Refused(one_line(got.get("error") or "The front door didn't take it.", 200))
                rid = id_in(got)
                if rid:
                    item["ready"] = rid  # made once: the next look starts this one, never a second
                if key_in(got):  # it started it itself (Start ready tasks by themselves)
                    return key_in(got), "front door"
        if rid:
            code, got = call(ctrl, "ready_start", {"id": rid})
            if not missing(code, got):
                task = door_task(ctrl, rid)
                if code != 200:
                    if task and task.get("state") == "started" and task.get("key"):
                        return task["key"], "front door"  # started there a moment ago, by its own queue: that agent
                    raise Refused(one_line(got.get("error") or "The front door didn't start it.", 200))
                key = key_in(got)
                if key:
                    return key, "front door"
                said = got.get("task") if isinstance(got.get("task"), dict) else {}
                if said.get("state") == "queued" or (task and task.get("state") == "queued"):
                    raise Refused(one_line(said.get("why") or (task or {}).get("why") or got.get("reply") or "It waits its turn at the front door.", 200))
                return None, "front door"
    # Without the front door (which queues it behind the agent at work), one agent at a time on a floor all the same
    if floor["floor"] in busy_floors(ctrl):
        raise Refused(f"An agent is at work on {floor['label']} now. It starts when that one is done.")
    try:
        got = ctrl.start(floor["floor"], words)
    except Exception as why:  # Control's Refused, in its own words
        raise Refused(one_line(str(why) or "It didn't start.", 200))
    return got.get("key"), "start"


# ---------- the plan ----------

def item_of(title, why, text, source, cost=None, **more):
    row = {"id": "d-" + secrets.token_hex(4), "title": one_line(upper_first(str(title).strip()), TITLE), "why": one_line(why, 200),
           "text": one_line(text, WORDS * 2), "source": source, "state": "proposed"}
    if cost:
        row["cost"] = cost
    row.update({k: v for k, v in more.items() if v is not None})
    return row


def candidates(floor, work, yesterday, ready):
    """Everything a floor's lead could propose today, in the order they'd take it: what was left unfinished, work
    whose check failed, the ready tasks, open tasks, then a next step toward each open goal."""
    project = floor["project"]
    out = []
    for f in (yesterday or {}).get("plan") or []:
        if not isinstance(f, dict) or f.get("floor") != project:
            continue
        for it in f.get("items") or []:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            if it.get("state") == "approved":
                out.append(item_of(it["title"], "Carried over: it was approved yesterday and didn't start.", it.get("text") or it["title"], "carried",
                                   ready=it.get("ready"), task=it.get("task"), goal=it.get("goal")))
            elif it.get("state") in ("stopped", "failed"):
                out.append(item_of(it["title"], f"Carried over: it {'was stopped' if it['state'] == 'stopped' else 'ended with an error'} yesterday before it was done.",
                                   f"Finish this, which was started yesterday and didn't get done: {it.get('text') or it['title']}", "carried"))
    for c in work["conversations"]:
        proof = c.get("proof") if isinstance(c.get("proof"), dict) else {}
        if c.get("project") != project or c.get("working") or proof.get("state") not in ("failed", "timeout", "error"):
            continue
        check = str(proof.get("check") or "its check")
        check = check[:1].lower() + check[1:] if check[1:2].islower() else check
        last = [ln for ln in str(proof.get("tail") or "").strip().splitlines() if ln.strip()][-1:]
        title = one_line(c.get("title") or "earlier work", 70)
        out.append(item_of(f"Get \"{title}\" past {check}", f"Its check didn't pass{': ' + one_line(last[0], 120) if last else '.'}",
                           f"Earlier work on this floor, \"{title}\", didn't pass {check}. Find out why and fix it, then run the check."
                           + (f" What the check said last: {one_line(proof.get('tail'), 300)}" if proof.get("tail") else ""), "unfinished", conversation=c.get("id")))
    for r in ready:
        if r["project"] in (project, floor["label"]):
            out.append(item_of(r["title"], "A ready task from the front door.", r["title"] + (f" Done when: {r['done_when']}" if r.get("done_when") else ""),
                               "ready", ready=r["id"]))
    for t in work["tasks"]:
        if t.get("project") == project and t.get("status") == "open" and t.get("title") and not t.get("routine") and not t.get("budget"):
            note = one_line(t.get("note"), 200)
            out.append(item_of(t["title"], "An open task on this floor.", t["title"] + (f". Note: {note}" if note else ""), "task", task=str(t.get("id") or "") or None))
    for g in work["goals"]:
        if g.get("project") == project and g.get("status", "open") == "open" and g.get("title"):
            goal = one_line(g["title"], 90)
            out.append(item_of(f"Next step toward: {goal}", "One of this floor's goals.",
                               f"Take the next useful step toward this goal of the floor's: {goal}. Pick one small piece you can finish "
                               "and prove today, and say first what you chose.", "goal", goal=str(g.get("id") or "") or None))
    seen = set()
    unique = []
    for it in out:  # the same work once, the first way it came
        k = it["title"].lower()
        if k not in seen:
            seen.add(k)
            unique.append(it)
    return unique


def propose(data, ctrl=None, now=None, keep_from=None, ready=None):
    """Today's plan, floor by floor, fitted to the allowance left. `keep_from`, today's plan as it is, keeps what you
    approved, added and dropped; `ready` is the front door's ready tasks (ready_rows), read beforehand."""
    now = now or time.time()
    date = today(now)
    work = work_of(data)
    yesterday = load(data, (datetime.date.fromtimestamp(now) - datetime.timedelta(days=1)).isoformat())
    ready = ready or []
    room = allowance(data, now)
    most = TIGHT if room["tight"] else MOST
    old = {f.get("floor"): f for f in (keep_from or {}).get("plan") or [] if isinstance(f, dict)}
    dropped = {str(t).lower() for t in (keep_from or {}).get("dropped") or []}
    plan = []
    for floor in floors_here(data):
        project = floor["project"]
        was = old.get(project)
        if was and was.get("approved"):  # approved: kept as it is
            plan.append(was)
            continue
        added = [it for it in (was or {}).get("items") or [] if isinstance(it, dict) and it.get("source") == "added" and it.get("state") != "dropped"]
        cost = cost_of(data, project, work, now)
        over, spend = over_budget(data, work, project, ctrl)
        items = [it for it in candidates(floor, work, yesterday, ready) if it["title"].lower() not in dropped]
        if cost:
            for it in items:
                it["cost"] = cost
        note = None
        fitted = items[:most]
        if spend and cost and not over:
            left = spend["limit"] - spend["spent"]
            can = max(1, left // cost["tokens"]) if left > 0 else 0
            if can < len(fitted):
                fitted = fitted[:can]
                note = f"{budget.tokens(left)} tokens are left of its budget today, so it proposes {plural(len(fitted), 'thing', 'things')}."
        if over:
            note = "Its agents have used today's budget, so nothing here starts until you let them go on."
        left_out = len(items) - len(fitted)
        row = {"floor": project, "label": floor["label"], "id": floor["id"], "lead": floor["lead"], "approved": False,
               "items": fitted + [it for it in added if it["title"].lower() not in {x["title"].lower() for x in fitted}]}
        if note:
            row["note"] = note
        if left_out > 0:
            row["later"] = left_out
        if row["items"] or note:
            plan.append(row)
    return {"date": date, "made": now, "plan": plan, "allowance": room, "dropped": sorted(dropped),
            "close": (keep_from or {}).get("close"), "log": (keep_from or {}).get("log") or []}


def make_plan(data, ctrl=None, now=None, again=False):
    """Makes today's plan, or with `again` makes it afresh, keeping what was approved, added or dropped."""
    now = now or time.time()
    ready = ready_rows(ctrl)  # read before the lock: it asks Control's state
    with locked(data):
        doc = load(data, today(now))
        if doc and doc.get("made") and not again:
            return doc
        fresh = propose(data, ctrl, now, keep_from=doc, ready=ready)
        keep(data, fresh)
        return fresh


def building_floor(data, name):
    """A floor of the building with a folder here, by its project, label or id in any case, as a plan's floor. None."""
    want = re.sub(r"^the\s+|\s+(?:floor|project)$|'s$", "", str(name or "").strip().lower().rstrip(".!?"))
    for f in floors_here(data):
        if want and want in (f["project"].lower(), f["label"].lower(), f["id"].lower()):
            return {"floor": f["project"], "label": f["label"], "id": f["id"], "lead": f["lead"], "approved": False, "items": []}
    return None


def split_floor(said, data):
    """Words that end with "on <a floor>" (or for, in): (the words before it, that floor as a plan's floor), the last
    such that names a floor; or (the words, None)."""
    for m in reversed(list(re.finditer(r"[\s,]+(?:on|for|in)\s+", said, re.I))):
        floor = building_floor(data, said[m.end():])
        if floor:
            return said[: m.start()].strip(), floor
    return said, None


def floor_named(doc, name):
    """The plan's floor a word names: its project, label or id, in any case. None for none."""
    want = str(name or "").strip().lower()
    want = re.sub(r"^the\s+|\s+(?:floor|project)$|'s$", "", want)
    if not want:
        return None
    for f in doc.get("plan") or []:
        if want in (str(f.get("floor") or "").lower(), str(f.get("label") or "").lower(), str(f.get("id") or "").lower()):
            return f
    return None


def approve(data, ctrl, floors=None, now=None):
    """Approves the whole day, or the floors named. Then starts what can start."""
    now = now or time.time()
    with locked(data):
        doc = load(data, today(now))
        if not doc or not doc.get("made"):
            raise Refused("There's no plan for today yet. Make it first.")
        if floors:
            if not isinstance(floors, list) or not all(isinstance(f, str) for f in floors):
                raise Refused("Name the floors as a list.")
            chosen = []
            for name in floors:
                f = floor_named(doc, name)
                if not f:
                    raise Refused(f"Today's plan has no floor called {one_line(name, 40)}.")
                chosen.append(f)
        else:
            chosen = [f for f in doc["plan"] if f.get("items")]
        if not chosen:
            raise Refused("Today's plan has nothing to approve.")
        n = 0
        for f in chosen:
            if not f.get("approved"):
                f.update(approved=True, approved_at=now)
            for it in f.get("items") or []:
                if it.get("state") == "proposed":
                    it["state"] = "approved"
                    n += 1
        keep(data, doc)
        started = step(data, ctrl, now) if ctrl is not None else []
    view_now = view(data, now)
    names = [f["label"] for f in chosen]
    said = (f"Approved {plural(n, 'thing', 'things')} on {names[0] if len(names) == 1 else plural(len(names), 'floor', 'floors')}. "
            if n else f"Nothing new to approve on {' and '.join(names) if len(names) < 3 else 'those floors'}. ")
    said += "They start in order, one at a time on each floor."
    if ctrl is not None and ctrl.box.paused():
        said += " Every agent is paused, so nothing starts until you resume them."
    elif started:
        said += f" Starting now: {'; '.join(started[:3])}."
    return {"ok": True, "said": said, "day": view_now}


ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "last": -1,
            "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
NTH = r"(?P<n>first|second|third|fourth|fifth|sixth|seventh|eighth|last|\d{1,2}(?:st|nd|rd|th)?)"
DROP = re.compile(r"^(?:please\s+)?(?:drop|remove|skip|cut|delete|scrap|lose|take out|leave out|forget)\s+(?:the\s+)?" + NTH
                  + r"(?:\s+(?:one|item|thing|task))?$", re.I)
DROP_NUMBER = re.compile(r"^(?:please\s+)?(?:drop|remove|skip|cut|delete|scrap|take out|leave out)\s+(?:item|number|no\.?)\s*(?P<n>\d{1,2})$", re.I)
DROP_NAMED = re.compile(r"^(?:please\s+)?(?:drop|remove|skip|cut|delete|scrap|take out|leave out)\s+(?:the\s+one\s+(?:about|on|for|to)\s+)?[\"']?(?P<what>.{3,}?)[\"']?$", re.I)
FIRST = re.compile(r"^(?:please\s+)?(?:do|put|move|start(?:\s+with)?)\s+(?:the\s+)?" + NTH + r"(?:\s+(?:one|item|thing|task))?\s+first$", re.I)
ADD = re.compile(r"^(?:please\s+)?(?:add|also)\b(?:\s+(?:this\s+)?to\s+(?:the|today's)\s+(?:plan|day|list))?\s*[:,]?\s*(?P<what>.+?)"
                 r"(?:\s+to\s+(?:the|today's)\s+(?:plan|day|list))?$", re.I)


def nth_of(word, count):
    word = str(word).lower()
    n = ORDINALS.get(word)
    if n is None:
        m = re.match(r"^(\d{1,2})", word)
        n = int(m.group(1)) if m else 0
    if n == -1:
        n = count
    return n if 1 <= n <= count else None


def change(data, ctrl, floor, words, now=None):
    """Changes today's plan in words: drop the second one, drop "the README", add: tidy the README, do the third one
    first. `floor` names the floor, or the words end with "on <floor>"; with one floor planned it may be left out."""
    now = now or time.time()
    said = " ".join(str(words or "").split()).strip().rstrip(".!")
    if not said:
        raise Refused("Say what to change.")
    if len(said) > 2000:
        raise Refused("That's too long: keep it under 2000 characters.")
    if ADD.match(said) and _intake().has_secret(said):  # before any reply that says the words back ("On which floor?")
        raise Refused(_intake().SECRET_SAID)
    with locked(data):
        doc = load(data, today(now))
        if not doc or not doc.get("made"):
            raise Refused("There's no plan for today yet. Make it first.")
        said, named = split_floor(said, data)  # the words' own floor comes first: "add: tidy the README on Lantern"
        if named is None and floor:
            named = building_floor(data, floor)
            if named is None:
                raise Refused(f"There's no floor called {one_line(floor, 40)} with a folder on this computer.")
        target = None
        if named is not None:
            target = floor_named(doc, named["floor"])
            if target is None:  # a floor with nothing planned yet gets a plan of its own
                target = named
                doc["plan"].append(target)
        if not target:
            planned = [f for f in doc["plan"] if f.get("items")]
            if len(planned) == 1:
                target = planned[0]
            else:
                raise Refused(f"On which floor? Say it with the floor, such as \"{said} on {planned[0]['label'] if planned else 'a floor'}\".")
        items = [it for it in target["items"] if it.get("state") != "dropped"]
        open_items = [it for it in items if it.get("state") in ("proposed", "approved")]
        m = DROP.match(said) or DROP_NUMBER.match(said)
        if m:
            n = nth_of(m.group("n"), len(items))
            if not n:
                raise Refused(f"{target['label']}'s plan has {plural(len(items), 'thing', 'things')}.")
            it = items[n - 1]
            if it.get("state") not in ("proposed", "approved"):
                raise Refused(f"\"{it['title']}\" has started already. Stop its agent instead.")
            it["state"] = "dropped"
            doc["dropped"] = sorted({*(doc.get("dropped") or []), it["title"].lower()})
            reply = f"Dropped \"{it['title']}\" from {target['label']}'s plan."
        elif FIRST.match(said):
            n = nth_of(FIRST.match(said).group("n"), len(items))
            if not n:
                raise Refused(f"{target['label']}'s plan has {plural(len(items), 'thing', 'things')}.")
            it = items[n - 1]
            if it.get("state") not in ("proposed", "approved"):
                raise Refused(f"\"{it['title']}\" has started already.")
            target["items"].remove(it)
            at = next((i for i, x in enumerate(target["items"]) if x.get("state") in ("proposed", "approved")), len(target["items"]))
            target["items"].insert(at, it)
            reply = f"\"{it['title']}\" is first on {target['label']} now."
        elif ADD.match(said):
            what = ADD.match(said).group("what").strip().strip("\"'").rstrip(".!")
            if len(what) < 3:
                raise Refused("Say what to add, such as \"add: tidy the README on Lantern\".")
            if _intake().has_secret(what):  # the front door's own check, and its own words: nothing is written down
                raise Refused(_intake().SECRET_SAID)
            work = work_of(data)
            it = item_of(what, "You added it.", upper_first(what) + ".", "added", cost=cost_of(data, target["floor"], work, now))
            if target.get("approved"):
                it["state"] = "approved"
            target["items"].append(it)
            doc["dropped"] = [t for t in doc.get("dropped") or [] if t != it["title"].lower()]
            reply = f"Added \"{it['title']}\" to {target['label']}'s plan" + (", approved with the rest." if target.get("approved") else ".")
        else:
            m = DROP_NAMED.match(said)
            hit = None
            if m:  # "drop the README one": an item whose title has those words
                want = re.sub(r"^(?:the|that|this)\s+|\s+(?:one|item|thing|task)$", "", m.group("what").lower()).strip()
                hits = [it for it in open_items if want and want in it["title"].lower()]
                hit = hits[0] if len(hits) == 1 else None
            if not hit:
                raise Refused("I can drop one (\"drop the second one\"), add one (\"add: tidy the README\"), or move one up "
                              "(\"do the third one first\").")
            hit["state"] = "dropped"
            doc["dropped"] = sorted({*(doc.get("dropped") or []), hit["title"].lower()})
            reply = f"Dropped \"{hit['title']}\" from {target['label']}'s plan."
        keep(data, doc)
        if target.get("approved") and ctrl is not None:
            step(data, ctrl, now)
    return {"ok": True, "said": reply, "day": view(data, now)}


# ---------- starting approved items, one at a time on each floor ----------

def running(ctrl, key):
    """At work still, or finished work that waits for your look on Show me before it is counted done (Control.awaiting_look)."""
    if not key:
        return False
    try:
        return bool(ctrl.working(key)) or bool(getattr(ctrl, "awaiting_look", lambda k: False)(key))
    except Exception:
        return False


def ended_state(ctrl, key, work):
    run = (getattr(ctrl, "runs", {}) or {}).get(key) or {}
    state = run.get("state")
    if state in ("done", "failed", "stopped"):
        return state
    return "done"


def spent_by(work, key, date):
    for c in work["conversations"]:
        spent = c.get("spent") if isinstance(c.get("spent"), dict) else {}
        if c.get("id") == key and spent.get("day") == date and isinstance(spent.get("tokens"), int):
            return spent["tokens"]
    for ended in work["ended"]:
        t = (ended.get("talks") or {}).get(key) if ended.get("day") == date and isinstance(ended.get("talks"), dict) else None
        if isinstance(t, dict) and isinstance(t.get("tokens"), int):
            return t["tokens"]
    return None


def busy_floors(ctrl):
    """The floors with an agent started from the building at work now (yours, the front door's, the night's), by name."""
    lock, runs = getattr(ctrl, "lock", None), getattr(ctrl, "runs", None)
    if lock is None or not isinstance(runs, dict):
        return set()
    with lock:
        rows = list(runs.values())
    return {x.get("project") for x in rows if isinstance(x, dict) and x.get("state") == "working" and ctrl.alive(x)}


def step(data, ctrl, now=None):
    """Settles what finished, and starts the next approved item on each floor with nothing at work from the plan.
    Never while every agent is paused, or on a floor past its budget. Gives what started, in words."""
    now = now or time.time()
    if ctrl is None or not switches.on(SWITCH, data):
        return []
    rows = ready_rows(ctrl)  # read before the lock: it asks Control's state
    ready = None if rows is None else {r["id"] for r in rows}
    started = []
    with locked(data):
        doc = load(data, today(now))
        if not doc:
            return []
        before = json.dumps(doc, sort_keys=True)
        work = work_of(data)
        paused = ctrl.box.paused()
        night = night_holds(data, now)  # the night shift's quiet hours: what is approved waits for it
        for f in doc["plan"]:
            if not f.get("approved"):
                continue
            for it in f.get("items") or []:
                if it.get("state") == "started" and not running(ctrl, it.get("key")) and now - float(it.get("started_at") or 0) > 5:
                    it.update(state=ended_state(ctrl, it.get("key"), work), ended_at=now)
                    tokens = spent_by(work, it.get("key"), doc["date"])
                    if tokens:
                        it["spent"] = tokens
            if any(it.get("state") == "started" for it in f.get("items") or []):
                continue
            nxt = next((it for it in f.get("items") or [] if it.get("state") == "approved"), None)
            if not nxt:
                continue
            if paused:
                nxt["waiting"] = "Every agent is paused. It starts when you resume them."
                continue
            if night:
                nxt["waiting"] = ("It's the night shift's quiet hours, so it waits for the night shift, which runs it if allowance "
                                  "would otherwise go unused.")
                continue
            over, _ = over_budget(data, work, f["floor"], ctrl, doc["date"])
            if over:
                nxt["waiting"] = f"{f['label']}'s agents have used today's budget. It starts if you let them go on."
                continue
            if nxt.get("ready") and ready is not None and nxt["ready"] not in ready:
                # the front door has it no longer: started there already (by its own queue or switch, or by you), or
                # dropped. Its own record says which, and which agent took it up.
                task = door_task(ctrl, nxt["ready"])
                if task and task.get("state") in ("started", "finished") and task.get("key"):
                    nxt.update(state="started", key=task["key"], started_at=float(task.get("started") or now), how="front door")
                elif task and task.get("state") == "dropped":
                    nxt.update(state="dropped", ended_at=now, why=one_line(f"{nxt.get('why') or ''} It was dropped at the front door.", 200))
                else:
                    nxt.update(state="done", ended_at=now, why=one_line(f"{nxt.get('why') or ''} It was taken up at the front door.", 200))
                nxt.pop("waiting", None)
                continue
            try:
                with within():
                    key, how = start_item(ctrl, f, nxt)
            except Refused as why:
                nxt["waiting"] = str(why)
                continue
            nxt.update(state="started", key=key, started_at=now, how=how)
            nxt.pop("waiting", None)
            started.append(f"\"{nxt['title']}\" on {f['label']}")
        if json.dumps(doc, sort_keys=True) != before:
            keep(data, doc)
    return started


# ---------- the close ----------

def make_close(data, ctrl=None, now=None):
    """The evening close: what was proven today, what is stuck and why, what needs you tomorrow, and what today cost."""
    now = now or time.time()
    date = today(now)
    start = at_today("00:00", now)
    work = work_of(data)
    labels = {f["project"]: f["label"] for f in floors_here(data)}
    for f in company_of(data).get("floors") or []:
        if isinstance(f, dict):
            p = str(f.get("project") or f.get("label") or f.get("id") or "")
            labels.setdefault(p, str(f.get("label") or p))
    label = lambda p: labels.get(p, p or "No floor")  # noqa: E731
    with locked(data):
        doc = load(data, date) or {"date": date, "made": None, "plan": [], "dropped": [], "log": []}
        proven, stuck, tomorrow = [], [], []
        for c in work["conversations"]:
            proof = c.get("proof") if isinstance(c.get("proof"), dict) else {}
            at = number(proof.get("at")) or 0
            if proof.get("state") == "passed" and at >= start:
                proven.append({"floor": label(c.get("project")), "title": one_line(c.get("title") or "A conversation", 90)})
            elif proof.get("state") in ("failed", "timeout", "error") and at >= start and not c.get("working"):
                last = [ln for ln in str(proof.get("tail") or "").strip().splitlines() if ln.strip()][-1:]
                stuck.append({"floor": label(c.get("project")), "title": one_line(c.get("title") or "A conversation", 90),
                              "why": f"Its check didn't pass{': ' + one_line(last[0], 120) if last else '.'}"})
        for f in doc.get("plan") or []:
            for it in f.get("items") or []:
                state = it.get("state")
                if state == "approved":
                    why = it.get("waiting") or ("It waited its turn behind the floor's earlier items." if f.get("approved") else "")
                    stuck.append({"floor": f.get("label"), "title": it.get("title"), "why": why or "It didn't start."})
                elif state in ("failed", "stopped"):
                    stuck.append({"floor": f.get("label"), "title": it.get("title"),
                                  "why": "It was stopped before it was done." if state == "stopped" else "It ended with an error."})
                elif state == "proposed":
                    tomorrow.append({"floor": f.get("label"), "title": it.get("title"), "why": "Proposed today and not approved."})
        seen = set()
        stuck = [s for s in stuck if (s["floor"], s["title"]) not in seen and not seen.add((s["floor"], s["title"]))]  # each once
        if ctrl is not None:
            try:
                for q in ctrl.box.questions():
                    tomorrow.append({"floor": label(q.get("project")), "title": one_line(q.get("title") or "An agent", 90),
                                     "why": f"It asks: {one_line(q.get('text'), 160)}"})
            except Exception:  # a question that can't be read never costs the close
                pass
        for t in work["tasks"]:
            if t.get("status") == "needs_you" and t.get("title"):
                tomorrow.append({"floor": label(t.get("project")), "title": one_line(t["title"], 90), "why": one_line(t.get("note") or "It needs you.", 160)})
        history = read(os.path.join(data, "feeds", "history", date + ".json")) or {}
        kept = history.get("spent") if isinstance(history.get("spent"), dict) else {}
        projects = sorted({*labels, *[p for p in kept if isinstance(p, str)]}, key=lambda p: list(labels).index(p) if p in labels else 99)
        floors = []
        for p in projects:
            tokens = max(spent_today(work, p, date), kept.get(p) if isinstance(kept.get(p), int) else 0)
            if tokens > 0:
                floors.append({"floor": label(p), "tokens": tokens, "words": f"{budget.tokens(tokens)} tokens"})
        total = sum(f["tokens"] for f in floors)
        limits = [f for f in forecast(data, now) if f["name"] == "seven_day"]
        plan_words = " ".join(f"{f['source']} has used {round(f['used'])}% of its weekly limit." for f in limits)
        cost = {"total": total, "floors": floors,
                "words": (f"{budget.tokens(total)} new tokens today" + (f": {', '.join(f['floor'] + ' ' + f['words'] for f in floors[:4])}." if floors else ".")
                          if total else "No spending was counted today.") + (f" {plan_words}" if plan_words else "")}
        done = [it for f in doc.get("plan") or [] for it in f.get("items") or [] if it.get("state") == "done"]
        words = (f"Today: {plural(len(proven), 'piece', 'pieces')} of work proven, {len(stuck)} stuck, "
                 f"{plural(len(tomorrow), 'thing needs', 'things need')} you tomorrow."
                 + (f" {plural(len(done), 'item', 'items')} from the plan finished." if done else "")
                 + (f" {budget.tokens(total)} new tokens." if total else ""))
        doc["close"] = {"at": now, "proven": proven[:20], "stuck": stuck[:20], "tomorrow": tomorrow[:20], "cost": cost, "words": words}
        keep(data, doc)
        return doc


# ---------- what is due, and the page's view ----------

def due(data, now=None):
    """What is due now: "plan" when today's plan time has come and there is no plan yet, "close" when the close time
    has come and today's close is older than it. None when nothing is."""
    now = now or time.time()
    times = times_of(data)
    doc = load(data, today(now)) or {}
    if now >= at_today(times["day_plan"], now) and not doc.get("made"):
        return "plan"
    close_at = at_today(times["day_close"], now)
    if now >= close_at and float((doc.get("close") or {}).get("at") or 0) < close_at:
        return "close"
    return None


def tick(data=None, ctrl=None, now=None):
    """Makes what is due (the plan, the close) and starts what can start. Gives what it did."""
    data = data or (ctrl.data if ctrl is not None else DATA)
    now = now or time.time()
    if not switches.on(SWITCH, data):
        return []
    did = []
    for _ in range(2):
        what = due(data, now)
        if what == "plan":
            make_plan(data, ctrl, now)
            did.append("plan")
        elif what == "close":
            make_close(data, ctrl, now)
            did.append("close")
        else:
            break
    if ctrl is not None:
        did += [f"started {s}" for s in step(data, ctrl, now)]
    return did


_TICKING = threading.Lock()
_LAST = {}


def maybe_tick(ctrl, now=None):
    """tick(), at most every EVERY seconds, and never inside itself (it reads Control's state, which asks here)."""
    now = now or time.time()
    if inside() or now - _LAST.get(ctrl.data, 0) < EVERY or not _TICKING.acquire(blocking=False):
        return
    try:
        _LAST[ctrl.data] = now
        tick(ctrl.data, ctrl, now)
    except Exception as error:  # trouble goes to the log, and the page still reads the day
        note(ctrl.data, error)
    finally:
        _TICKING.release()


ITEM_SHOWN = ("id", "title", "why", "cost", "state", "waiting", "key", "source")


def view(data, now=None):
    """Today as the page and a phone get it: {on, date, plan_at, close_at, made, plan: [{floor, label, id, lead,
    approved, note?, later?, items: [{id, title, why, cost?, state, waiting?, key?, source}]}], approved, allowance,
    close, due, night}, where night is how last night's night shift went, in a line, or None."""
    now = now or time.time()
    times = times_of(data)
    doc = load(data, today(now)) or {}
    plan = []
    for f in doc.get("plan") or []:
        if not isinstance(f, dict):
            continue
        items = [{k: it[k] for k in ITEM_SHOWN if k in it} for it in f.get("items") or [] if isinstance(it, dict) and it.get("state") != "dropped"]
        for it in items:
            if isinstance(it.get("cost"), dict):
                it["cost"] = it["cost"].get("words")
        plan.append({**{k: f.get(k) for k in ("floor", "label", "id", "lead", "approved", "note", "later") if f.get(k) is not None}, "items": items})
    with_items = [f for f in plan if f["items"]]
    shift = night_shift()
    return {"on": True, "date": today(now), "plan_at": times["day_plan"], "close_at": times["day_close"], "made": doc.get("made"),
            "plan": plan, "approved": bool(with_items) and all(f.get("approved") for f in with_items),
            "allowance": doc.get("allowance"), "close": doc.get("close"), "due": due(data, now),
            "night": shift.morning_line(data, now) if shift else None}  # how last night went (connect/night.py), or None


def state_part(ctrl):
    """What Control's state adds: "day", today's plan and close, or None while the daily cycle is switched off.
    Reading it makes what is due, so a missed plan time makes the plan when the page next opens."""
    if not switches.on(SWITCH, ctrl.data):
        return {"day": None}
    maybe_tick(ctrl)
    try:
        return {"day": view(ctrl.data)}
    except Exception as error:
        note(ctrl.data, error)
        return {"day": None}


def handle(ctrl, name, given):
    """Control.handle's names for the daily cycle. Raises Refused (Control's) with words for the person."""
    data = ctrl.data
    if not switches.on(SWITCH, data):
        raise Refused("The daily cycle is switched off. Switch it on in Settings, under Switches.")
    if name == "day":
        maybe_tick(ctrl)
        return view(data)
    if name == "day_plan":
        doc = make_plan(data, ctrl, again=True)
        n = sum(len([it for it in f.get("items") or [] if it.get("state") != "dropped"]) for f in doc["plan"])
        return {"ok": True, "said": f"Today's plan: {plural(n, 'thing', 'things')} on {plural(len([f for f in doc['plan'] if f.get('items')]), 'floor', 'floors')}.",
                "day": view(data)}
    if name == "day_approve":
        return approve(data, ctrl, given.get("floors"))
    if name == "day_change":
        return change(data, ctrl, given.get("floor"), given.get("words"))
    if name == "day_close":
        doc = make_close(data, ctrl)
        return {"ok": True, "said": doc["close"]["words"], "day": view(data)}
    if name == "day_times":
        times = save_times(data, given.get("plan"), given.get("close"))
        return {"ok": True, "said": f"The plan comes at {times['day_plan']} and the close at {times['day_close']}.", "day": view(data)}
    raise Refused("No such request.")


def keep_going(control_of, data_of, every=30):
    """For serve.py: every half a minute while it runs, makes what is due and starts what can start. `control_of()`
    gives Control while it is on (approved items start only then), `data_of()` the data folder."""
    while True:
        try:
            ctrl = control_of()
            data = ctrl.data if ctrl is not None else data_of()
            if switches.on(SWITCH, data):
                if ctrl is not None and _TICKING.acquire(blocking=False):
                    try:
                        _LAST[data] = time.time()
                        tick(data, ctrl)
                    finally:
                        _TICKING.release()
                elif ctrl is None:
                    tick(data, None)
        except Exception as error:  # whatever went wrong, it looks again next time
            note(data_of(), error)
        time.sleep(every)


def note(data, error):
    try:
        log = os.path.join(data, "feeds", "claude-code.log")
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} day {type(error).__name__}: {error}\n")
    except OSError:
        pass


def words_of(v):
    """Today's plan in words, for a terminal."""
    if not v.get("made"):
        return f"There's no plan for today yet. It comes at {v['plan_at']}."
    lines = []
    for f in v["plan"]:
        lines.append(f"{f['label']}{' (approved)' if f.get('approved') else ''}:" + (f" {f['note']}" if f.get("note") else ""))
        for i, it in enumerate(f["items"], 1):
            lines.append(f"  {i}. {it['title']} [{it['state']}]" + (f", {it['cost']}" if it.get("cost") else "") + f". {it['why']}")
    if v.get("allowance"):
        lines.append(v["allowance"]["words"])
    if v.get("close"):
        lines.append("Close: " + v["close"]["words"])
    return "\n".join(lines) or "Today's plan is empty: no floor has a folder on this computer."


def main(argv=None):
    parser = argparse.ArgumentParser(description="The daily cycle: makes today's plan and close when they are due (docs/connect.md, \"The daily cycle\").")
    parser.add_argument("--plan", action="store_true", help="make today's plan now, keeping what was approved, added or dropped")
    parser.add_argument("--close", action="store_true", help="make today's close now")
    parser.add_argument("--show", action="store_true", help="say today's plan, and change nothing")
    args = parser.parse_args(argv)
    try:
        if args.show:
            print(words_of(view(DATA)))
            return 0
        if args.plan:
            make_plan(DATA, None, again=True)
        if args.close:
            make_close(DATA, None)
        if args.plan or args.close:
            print(words_of(view(DATA)))
            return 0
        if not switches.on(SWITCH, DATA):
            print("The daily cycle is switched off. Switch it on in Settings, under Switches.")
            return 0
        tick(DATA, None)
        return 0
    except Exception as error:
        note(DATA, error)
        print(f"It didn't work: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
