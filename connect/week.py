#!/usr/bin/env python3
"""The week on one page (docs/connect.md, "The week on one page").

Each floor's week: what finished and was proven, what was undone, and what waits for you now; and where the week's
allowance went: the daily plans (connect/day.py), the night shift (connect/night.py), work Show me sent back with Not
quite (connect/show.py), and your own conversations, as shares of what was counted. All from what Arnheim keeps
already, read and never changed:

- the hook's history, a file a day (data/feeds/history/): each conversation's moments, what each floor's agents spent
  that day in new tokens, and, since this page came, each conversation's tokens at each moment and what its floor's
  check made of its work (connect/claude_code.py, add_moment and note_proof);
- the daily cycle's days (data/day/): the plan's items, who ran them and what each spent, and the evening's close;
- the night shift's nights (data/night/): what ran, what it spent, and what was undone;
- Show me's cards (data/shows/index.json), restore points put back (data/feeds/restore.json), the feed's
  conversations, the work list's tasks that need you, and your plan's limits (data/feeds/usage.json).

Shares are of the new tokens Arnheim counted, the same measure as a floor's budget and the day's close; your plan's own
weekly limit is said beside them as Claude Code and Codex report it. A day with no history is said plainly ("No
readings Tuesday"), and nothing is made up for it.

Reading it starts nothing and writes nothing. It is a switch (Settings, Switches: "The week on one page"), on unless
you switch it off, read through control (`week`), so a paired phone that may control agents has it too.
`python3 connect/week.py` says the week; `--json` gives what the page gets. Standard library only.
"""
import argparse
import datetime
import json
import os
import re
import sys
import time


def _beside(name):
    """A module beside this file, loaded by its path (python3 -I, no folder on the path), as control.py does."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import budget, intake, switches  # as connect.week, from serve.py
except ImportError:
    try:
        import budget  # beside this file
        import intake
        import switches
    except ImportError:
        budget, intake, switches = (_beside(n) for n in ("budget", "intake", "switches"))

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
SWITCH = "week"
NAMES = ("week",)  # Control.handle's, for the week on one page
READS = ("week",)  # it only reads: serve.py counts it for a phone, and never logs it
DAYS = 7  # today and the six days before
DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
GO_BACK = "before going back to "  # a restore point you took by putting a floor's files back (connect/restore.py, go_back)
SAME_ACT = 120  # seconds: a night run's Undo and the restore point it kept are one act
FINAL = ("passed", "failed", "timeout", "error")
SEALED = "A piece of work (its title names a secret, so it isn't shown)"
# (name, label as said in a sentence), in the order the page shows them
PARTS = (("plans", "the daily plans"), ("night", "the night shift"), ("show", "work Show me sent back"), ("own", "your own conversations"))


class Refused(Exception):
    """Words for the person, when a request can't be done."""


def read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            got = json.load(handle)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def number(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
    except (TypeError, ValueError):
        return None
    return n if n == n and abs(n) != float("inf") else None


def count(value):
    """A token count as kept: a whole number above nought, or 0."""
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def plural(n, one, many):
    return f"{n} {one if n == 1 else many}"


def title_of(text, most=90):
    """A title as the page may show it: one line, and never one that names a secret."""
    said = one_line(text, most) or "A piece of work"
    try:
        return SEALED if intake.has_secret(said) else said
    except Exception:  # a check that fails counts as a secret
        return SEALED


def tokens(n):
    return budget.tokens(n)


def and_list(words, last="and"):
    words = [w for w in words if w]
    if len(words) < 2:
        return "".join(words)
    return f"{', '.join(words[:-1])} {last} {words[-1]}"


def dates_of(now):
    """The week's days, oldest first: today and the six before, as local dates."""
    today = datetime.date.fromtimestamp(now)
    return [today - datetime.timedelta(days=n) for n in range(DAYS - 1, -1, -1)]


def labels_of(data):
    """Each floor's project and label, in the building's order."""
    company = read(os.path.join(data, "company.json")) or {}
    out = {}
    for f in company.get("floors") or []:
        if isinstance(f, dict):
            p = str(f.get("project") or f.get("label") or f.get("id") or "")
            if p:
                out.setdefault(p, str(f.get("label") or p))
    return out


# ---------- what was kept ----------

def history_of(data, date):
    """One day of the hook's history, or None when there is none."""
    got = read(os.path.join(data, "feeds", "history", date + ".json"))
    if got is None:
        return None
    got["moments"] = [m for m in got.get("moments") or [] if isinstance(m, dict) and m.get("key") and number(m.get("at")) is not None]
    got["spent"] = got.get("spent") if isinstance(got.get("spent"), dict) else {}
    got["proofs"] = got.get("proofs") if isinstance(got.get("proofs"), dict) else {}
    return got


def nights_of(data, first):
    """The night shift's nights from the evening before the week began on, oldest first."""
    folder = os.path.join(data, "night")
    try:
        names = sorted(n for n in os.listdir(folder) if re.match(r"^\d{4}-\d{2}-\d{2}\.json$", n))
    except OSError:
        return []
    since = (first - datetime.timedelta(days=1)).isoformat()
    out = []
    for name in names:
        if name[:10] >= since:
            doc = read(os.path.join(folder, name))
            if doc and isinstance(doc.get("ran"), list):
                out.append(doc)
    return out


def latest_proofs(history, feed, start):
    """Each conversation's newest known proof this week: {key: {state, at, project, title}}."""
    best = {}

    def offer(key, project, title, state, at):
        if state not in FINAL or at is None or at < start:
            return
        if key not in best or at >= best[key]["at"]:
            best[key] = {"state": state, "at": at, "project": project, "title": title}
    for h in history.values():
        for key, p in (h or {}).get("proofs", {}).items():
            if isinstance(p, dict):
                offer(key, p.get("project"), p.get("title"), p.get("state"), number(p.get("at")))
    for c in feed:
        p = c.get("proof") if isinstance(c.get("proof"), dict) else {}
        offer(c.get("id"), c.get("project"), c.get("title"), p.get("state"), number(p.get("done")) or number(p.get("at")))
    return best


# ---------- each floor ----------

def floors_of(data, ctrl, now, dates, history, plans, nights, shows, feed, start):
    labels = labels_of(data)
    rows = {}

    def floor(project):
        if project not in rows:
            rows[project] = {"project": project, "label": labels.get(project, project), "done": {}, "undone": [], "waits": []}
        return rows[project]

    def finished(project, key, title, how=None):
        if not project or not key:
            return
        f = floor(project)
        had = f["done"].get(key) or {}
        f["done"][key] = {"title": title or had.get("title"), "how": how or had.get("how")}

    # Conversations that changed files and finished this week, from the hook's moments.
    moments = [m for d in dates for m in (history[d] or {}).get("moments", []) if number(m.get("at")) >= start]
    changed = {m["key"] for m in moments if m.get("kind") == "changed"}
    for m in moments:
        if m.get("kind") == "finished" and m["key"] in changed:
            finished(m.get("project"), m["key"], m.get("title"))
    # The daily plans' items and the night shift's runs that finished, whoever's hooks saw them.
    for d in dates:
        for f in (plans[d] or {}).get("plan") or []:
            for it in f.get("items") or [] if isinstance(f, dict) else []:
                if isinstance(it, dict) and it.get("state") == "done" and it.get("key") and it.get("how") != "night shift":
                    finished(f.get("floor"), it["key"], it.get("title"), "plan")
    for doc in nights:
        for r in doc.get("ran") or []:
            if not isinstance(r, dict) or (number(r.get("started_at")) or 0) < start:
                continue
            if r.get("undone") and r.get("project"):
                floor(r["project"])["undone"].append({"title": title_of(r.get("title")), "at": number(r.get("undone")),
                                                         "how": "night shift"})
            elif r.get("state") == "done" and r.get("key"):
                finished(r.get("project"), r["key"], r.get("title"), "night")
    # What each one's check made of it, newest first.
    proofs = latest_proofs(history, feed, start)
    for key, p in proofs.items():
        if p.get("project"):
            finished(p["project"], key, p.get("title"))
    titles = {c.get("id"): c.get("title") for c in feed if c.get("id")}
    # A close's proven work that no record above has (its conversation left the feed before the page came).
    for d in dates:
        close = (plans[d] or {}).get("close") or {}
        for p in close.get("proven") or [] if isinstance(close, dict) else []:
            if not isinstance(p, dict):
                continue
            project = next((k for k, v in labels.items() if v == p.get("floor")), p.get("floor"))
            f = floor(project) if project else None
            if f and not any((x.get("title") or titles.get(k)) == p.get("title") for k, x in f["done"].items()):
                key = f"close-{d}-{len(f['done'])}"
                f["done"][key] = {"title": p.get("title"), "how": None}
                proofs[key] = {"state": "passed", "at": start, "project": project, "title": p.get("title")}

    # Files you put back from the building (each Undo keeps a restore point first): one with a night run's Undo is that.
    points = (read(os.path.join(data, "feeds", "restore.json")) or {}).get("restore") or []
    for p in points:
        if not isinstance(p, dict) or p.get("by") != "you" or not str(p.get("why") or "").startswith(GO_BACK):
            continue
        at = number(p.get("at"))
        if at is None or at < start or not p.get("project"):
            continue
        f = floor(p["project"])
        if any(u.get("how") == "night shift" and abs((u.get("at") or 0) - at) < SAME_ACT for u in f["undone"]):
            continue
        f["undone"].append({"title": f"Files put back to how they were at {str(p['why'])[len(GO_BACK):][:5]}", "at": at, "how": "you"})

    # What waits for you now.
    for row in shows:
        if isinstance(row, dict) and row.get("state") == "waiting" and row.get("project"):
            floor(row["project"])["waits"].append({"title": title_of(row.get("title") or titles.get(row.get("conv"))),
                                                   "why": "Its Show me card waits for Looks good or Not quite."})
    today = (plans[dates[-1]] or {}).get("plan") or []
    for f in today:
        for it in f.get("items") or [] if isinstance(f, dict) else []:
            if not isinstance(it, dict) or not f.get("floor"):
                continue
            if it.get("state") == "proposed" and not f.get("approved"):
                floor(f["floor"])["waits"].append({"title": title_of(it.get("title")), "why": "Today's plan proposes it, for you to approve."})
            elif it.get("state") == "approved" and it.get("waiting"):
                floor(f["floor"])["waits"].append({"title": title_of(it.get("title")), "why": one_line(it["waiting"], 200)})
    if ctrl is not None:
        try:
            for t in ctrl.intake.views():
                if t.get("state") == "ready" and t.get("project"):
                    floor(t["project"])["waits"].append({"title": title_of(t.get("title")), "why": "A ready task waits for Start."})
        except Exception:  # the front door's trouble never costs the week
            pass
        try:
            for q in ctrl.box.questions():
                if q.get("project"):
                    floor(q["project"])["waits"].append({"title": title_of(q.get("title") or "An agent"), "why": "It asks you something."})
        except Exception:
            pass
    tasks = []
    for path in [os.path.join(data, "work.json")] + [os.path.join(data, p) for p in (read(os.path.join(data, "company.json")) or {}).get("feeds") or []
                                                      if isinstance(p, str) and re.match(r"^[\w-]+(/[\w.-]+)*\.json$", p) and ".." not in p]:
        tasks += [t for t in (read(path) or {}).get("tasks") or [] if isinstance(t, dict)]
    for t in tasks:
        if t.get("status") == "needs_you" and t.get("title") and t.get("project"):
            floor(t["project"])["waits"].append({"title": title_of(t["title"]), "why": one_line(t.get("note") or "It needs you.", 200)})

    out = []
    order = list(labels)
    for project in sorted(rows, key=lambda p: (order.index(p) if p in order else len(order), p)):
        f = rows[project]
        items = []
        for key, x in f["done"].items():
            state = (proofs.get(key) or {}).get("state")
            items.append({"title": title_of(x.get("title") or titles.get(key)), "how": x.get("how"),
                          "proof": "proven" if state == "passed" else "failed" if state in FINAL else "unchecked"})
        n = len(items)
        p = len([i for i in items if i["proof"] == "proven"])
        x = len([i for i in items if i["proof"] == "failed"])
        if not n and not f["undone"] and not f["waits"]:
            continue
        undone = sorted(f["undone"], key=lambda u: u.get("at") or 0)
        row = {"project": project, "label": f["label"], "finished": n, "proven": p, "failed": x, "undone": len(undone),
               "waits": len(f["waits"]), "items": {"finished": items, "undone": [{"title": u["title"], "how": u["how"]} for u in undone],
                                                    "waits": f["waits"][:20]}}
        row["line"] = floor_words(row)
        out.append(row)
    return out


def floor_words(f):
    """A floor's week in a line: "4 finished: 3 proven, 1 not proven. 1 undone. 2 things wait for you."."""
    n, p, x = f["finished"], f["proven"], f["failed"]
    u = n - p - x
    if not n:
        words = "Nothing finished."
    elif p == n:
        words = f"{n} finished, {'all ' if n > 1 else ''}proven."
    elif not p and not x:
        words = f"{n} finished, not checked."
    else:
        words = f"{n} finished: " + and_list([f"{p} proven" if p else "", f"{x} not proven" if x else "", f"{u} not checked" if u else ""]) + "."
    if f["undone"]:
        words += f" {f['undone']} undone."
    if f["waits"]:
        words += f" {plural(f['waits'], 'thing waits', 'things wait')} for you."
    return words


# ---------- where the allowance went ----------

def show_spent(shows, history, dates, start, counted_as=None):
    """What work sent back with Not quite spent: for each, its conversation's tokens from the sending to the end of the
    work that followed, from the moments' own counts. `counted_as` maps a plan item's or a night run's conversation to
    when its share was taken (its row's ended_at): work sent back there that ended by then is in that share, so it is
    counted there alone, never twice; work that ended after is in neither, so it is Show me's. Gives (tokens, sent
    back, how many could be counted)."""
    counted_as = counted_as or {}
    by_key = {}
    for d in dates:
        for m in (history[d] or {}).get("moments", []):
            t = m.get("tokens")
            if isinstance(t, int) and not isinstance(t, bool) and t >= 0:
                by_key.setdefault(m["key"], []).append((number(m["at"]), d.isoformat(), m.get("kind"), t))
    sent = [r for r in shows if isinstance(r, dict) and r.get("state") == "again" and (number(r.get("decided_at")) or 0) >= start]
    spent, counted = 0, 0
    for r in sent:
        at = number(r["decided_at"])
        rows = sorted(by_key.get(r.get("conv")) or [])
        end = next((x for x in rows if x[0] > at and x[2] in ("finished", "stopped")), None)
        taken = counted_as.get(r.get("conv"))
        if taken is not None and (end[0] if end else at) <= taken:
            counted += 1  # in the plan's or the night's share already, taken once this work had ended
            continue
        if not end:
            continue  # still at work, or its steps weren't seen
        before = [x for x in rows if x[0] <= at and x[1] == end[1]]
        got = end[3] - (before[-1][3] if before else 0)
        if got > 0:
            spent += got
            counted += 1
    return spent, len(sent), counted


def limits_of(data, now):
    """Each agent's newest weekly reading, as Claude Code and Codex report it: [{source, used, resets, words}]."""
    out = []
    sources = (read(os.path.join(data, "feeds", "usage.json")) or {}).get("sources") or {}
    for source, kept in sorted(sources.items() if isinstance(sources, dict) else []):
        rows = [r for r in (kept if isinstance(kept, dict) else {}).get("seven_day") or [] if isinstance(r, dict) and number(r.get("used")) is not None]
        if not rows:
            continue
        last = max(rows, key=lambda r: number(r.get("at")) or 0)
        used, resets = number(last["used"]), number(last.get("resets_at"))
        words = f"{source} says {round(used)}% of its weekly limit is used"
        if resets and resets > now:
            when = datetime.datetime.fromtimestamp(resets)
            words += f", and it starts again {'at ' + when.strftime('%H:%M') if resets - now < 20 * 3600 else 'on ' + DAY_NAMES[when.weekday()]}"
        out.append({"source": str(source), "used": round(used, 1), "resets": resets, "words": words + "."})
    return out


def shares(parts, whole):
    """Whole percentages that add up to 100: the largest remainders round up."""
    if not whole:
        return {name: 0 for name, _ in parts}
    exact = {name: 100.0 * t / whole for name, t in parts}
    out = {name: int(v) for name, v in exact.items()}
    for name in sorted(exact, key=lambda k: exact[k] - out[k], reverse=True)[:100 - sum(out.values())]:
        out[name] += 1
    return out


def allowance_of(data, now, dates, history, plans, nights, shows, start):
    counted = sum(count(v) for d in dates for v in (history[d] or {}).get("spent", {}).values())
    plan_t = sum(count(it.get("spent")) for d in dates for f in (plans[d] or {}).get("plan") or [] if isinstance(f, dict)
                 for it in f.get("items") or [] if isinstance(it, dict) and it.get("how") != "night shift")
    night_t = sum(count(r.get("spent")) for doc in nights for r in doc.get("ran") or []
                  if isinstance(r, dict) and (number(r.get("started_at")) or 0) >= start)
    # the plan's and the night's shares are each taken once, as the item or the run ends: when, for each conversation
    owned = {}
    rows = [it for d in dates for f in (plans[d] or {}).get("plan") or [] if isinstance(f, dict)
            for it in f.get("items") or [] if isinstance(it, dict) and it.get("how") != "night shift"]
    rows += [r for doc in nights for r in doc.get("ran") or [] if isinstance(r, dict) and (number(r.get("started_at")) or 0) >= start]
    for row in rows:
        if row.get("key") and count(row.get("spent")):
            taken = number(row.get("ended_at"))
            taken = float("inf") if taken is None else taken  # an older row: its share is taken as having it all
            owned[row["key"]] = max(owned.get(row["key"], taken), taken)
    show_t, sent, seen = show_spent(shows, history, dates, start, owned)
    whole = max(counted, plan_t + night_t + show_t)
    raw = [("plans", plan_t), ("night", night_t), ("show", show_t), ("own", whole - plan_t - night_t - show_t)]
    pct = shares(raw, whole)
    labels = dict(PARTS)
    parts = [{"name": name, "label": labels[name], "tokens": t, "share": pct[name]} for name, t in raw]
    limits = limits_of(data, now)
    return {"known": whole > 0, "tokens": whole, "parts": parts, "sent_back": sent, "sent_counted": seen, "limits": limits,
            "words": allowance_words(whole, parts, sent, seen, limits)}


def allowance_words(whole, parts, sent, seen, limits):
    if not whole:
        said = "No spending was counted this week, so where the allowance went isn't known."
    else:
        ranked = [p for p in sorted(parts, key=lambda p: -p["tokens"]) if p["tokens"]]
        said = f"Of the {tokens(whole)} new tokens counted this week: " + and_list([f"{p['label']} {p['share']}%" for p in ranked]) + "."
    if sent and seen < sent:
        said += (f" What {plural(sent - seen, 'piece', 'pieces')} of work sent back with Not quite spent couldn't be counted, so it is "
                 "in your own conversations.")
    said += " Show me's pictures are taken on this computer and use none of it."
    if limits:
        said += " " + " ".join(x["words"] for x in limits)
    return said


# ---------- the whole week ----------

def missing_words(names):
    if not names:
        return ""
    if len(names) == len(DAY_NAMES):
        return "No readings all week: the hook wrote nothing, so your own conversations aren't counted."
    return f"No readings {and_list(names, 'or')}, so your own conversations then aren't counted."


def week_words(floors, allowance, missing, sample=False):
    """The receptionist's summing up."""
    n = sum(f["finished"] for f in floors)
    p = sum(f["proven"] for f in floors)
    u = sum(f["undone"] for f in floors)
    w = sum(f["waits"] for f in floors)
    head = "This week is made up, like the rest of the company. " if sample else ""
    if n:
        said = f"This week, {plural(n, 'piece of work', 'pieces of work')} finished on {plural(len([f for f in floors if f['finished']]), 'floor', 'floors')}, " + (
            "all proven." if p == n else "none proven." if not p else f"{p} proven.")
    else:
        said = "Nothing finished this week, as far as the building knows."
    if u:
        said += f" {u} undone."
    if w:
        said += f" {plural(w, 'thing waits', 'things wait')} for you."
    busiest = max(floors, key=lambda f: (f["finished"], f["proven"]), default=None)
    if busiest and busiest["finished"]:
        said += f" {busiest['label']}: {busiest['line']}"
    ranked = [x for x in sorted(allowance["parts"], key=lambda x: -x["tokens"]) if x["tokens"]]
    if ranked:
        said += " The allowance went to " + and_list([f"{x['label']}, {x['share']}%" for x in ranked[:3]], "and") + "."
    else:
        said += " No spending was counted."
    if missing:
        said += " " + missing
    return head + said


def view(data, ctrl=None, now=None):
    """The week as the page and a phone get it: {on, id, from, to, sunday, days: [{date, name, read}], missing, floors:
    [{project, label, finished, proven, failed, undone, waits, line, items: {finished: [{title, how, proof}], undone:
    [{title, how}], waits: [{title, why}]}}], allowance: {known, tokens, parts: [{name, label, tokens, share}], sent_back,
    sent_counted, limits, words}, words}."""
    now = now or time.time()
    dates = dates_of(now)
    start = time.mktime(dates[0].timetuple())
    history = {d: history_of(data, d.isoformat()) for d in dates}
    plans = {}
    for d in dates:
        doc = read(os.path.join(data, "day", d.isoformat() + ".json"))
        plans[d] = doc if doc and isinstance(doc.get("plan"), list) else None
    nights = nights_of(data, dates[0])
    shows = [r for r in (read(os.path.join(data, "shows", "index.json")) or {}).get("shows") or [] if isinstance(r, dict)]
    feed = [c for c in (read(os.path.join(data, "feeds", "claude-code.json")) or {}).get("conversations") or [] if isinstance(c, dict)]
    floors = floors_of(data, ctrl, now, dates, history, plans, nights, shows, feed, start)
    allowance = allowance_of(data, now, dates, history, plans, nights, shows, start)
    missing = [DAY_NAMES[d.weekday()] for d in dates if history[d] is None]
    said = missing_words(missing)
    return {"on": True, "id": f"week-{dates[-1].isoformat()}", "from": dates[0].isoformat(), "to": dates[-1].isoformat(),
            "sunday": dates[-1].weekday() == 6,
            "days": [{"date": d.isoformat(), "name": DAY_NAMES[d.weekday()], "read": history[d] is not None} for d in dates],
            "missing": said, "floors": floors, "allowance": allowance, "words": week_words(floors, allowance, said)}


def handle(ctrl, name, given):
    """Control.handle's name for the week. Raises Refused with words for the person."""
    if name != "week":
        raise Refused("No such request.")
    if not switches.on(SWITCH, ctrl.data):
        return {"on": False}
    return view(ctrl.data, ctrl)


def main(argv=None):
    parser = argparse.ArgumentParser(description="The week on one page (docs/connect.md, \"The week on one page\"). Reads only.")
    parser.add_argument("--json", action="store_true", help="what the page gets, as JSON")
    args = parser.parse_args(argv)
    v = view(DATA)
    if args.json:
        print(json.dumps(v, ensure_ascii=False, indent=1))
        return 0
    print(v["words"])
    for f in v["floors"]:
        print(f"  {f['label']}: {f['line']}")
    print(v["allowance"]["words"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
