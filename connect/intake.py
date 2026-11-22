#!/usr/bin/env python3
"""One front door (docs/connect.md, step 25): anything you say or type that is work becomes a ready task for a floor.

From Talk, the receptionist, a floor's lead, the "What needs doing?" box on Needs you and in a floor's Work room, or a
paired phone, the page sends your words through control ("intake"). The floor is the one the words name, else the one
you are on, else one the words begin to name, else the only one there is; with several and none of those, the lead
asks which. A ready task has:

- a short title and "Done when", one sentence: by rule from your words, or, with the brain on (serve.py --brain),
  written by the floor's lead from them and then checked (its length, nothing secret, and nothing the building refuses
  that you didn't say yourself), else the rule;
- "Proven by": the floor's check in data/company.json, or the test command the project's own files name (as setup
  finds it, connect/agent_setup.py), else "You look at it";
- its agent: Claude Code, unless the floor says "agent": "Codex";
- an estimate only from the floor's own finished work: the median time in the history (data/feeds/history/) and the
  median spend in the feed, once at least three pieces of work there have finished. None otherwise, never a guess.

Start (one tap, or "start it") starts an agent with Control.start, its prompt carrying your words, Done when and Proven
by, and asking it to prove the work that way before it says it is done. One agent started from the building works on a
floor at a time: another waits, queued, and the next starts when the last finishes. Nothing starts while every agent is
paused, or while the floor is over today's budget: it waits, queued, and starts once that changes.

The switch "Start ready tasks by themselves" (off unless you switch it on) starts each new ready task without the tap,
one at a time per floor, but never one that names a password or key, or does something that can't be taken back
(merge, publish, deploy, push, delete and the like): those wait for your Start. Words with a password or token in them
are never written down, and work the building never hands out (signing in, sending messages, buying or paying for you)
is refused.

Each task is a file in data/control/intake/, written whole, never served as a file (serve.py), read only through
control. Ready and queued tasks go after 7 days, finished and dropped ones after 30. Standard library only.
"""
import json
import os
import re
import secrets
import statistics
import threading
import time


def _beside(name):
    """A module beside this file, loaded by its path, as connect/control.py loads its own."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import brain as wits, budget, carry_on, live, switches  # as connect.intake, from serve.py
except ImportError:
    try:
        import brain as wits  # beside this file
        import budget
        import carry_on
        import live
        import switches
    except ImportError:
        wits, budget, carry_on, live, switches = (_beside(n) for n in ("brain", "budget", "carry_on", "live", "switches"))

TASK_ID = re.compile(r"^rd-[a-f0-9]{10}$")
STATES = ("ready", "queued", "started", "finished", "dropped")
WAITING = ("ready", "queued")  # what the page lists
VIA = ("talk", "box", "phone", "day")  # "day": an item on the daily cycle's approved plan (connect/day.py)
MAX_TEXT = 2000
TITLE_MOST = 60  # a title by rule
TITLE_LONGEST = 80  # one the lead or you wrote
DONE_LONGEST = 240
WORDS_IN_PROMPT = 1200
READY_DAYS = 7
KEPT_DAYS = 30
LEAST_FINISHED = 3  # pieces of finished work before there is an estimate
LOOK = "You look at it"
TICK = 2.0  # seconds between looks at the queue, from the page's polls
SWEEP = 3600.0
SHAPE_WAIT = 30  # seconds the lead may take to write a task, with the brain on

SECRET_SAID = ("That looks like it has a password or token in it, so I won't write it down or hand it to an agent. "
               "Say it again without it: the agent can ask you for what it needs.")
NEVER_SAID = ("I can't hand that to an agent: Arnheim never has an agent sign in, send messages or posts, buy or pay "
              "for you. Do that one yourself.")
# Work the building never hands out, in words as brain.norm gives them.
NEVER_HANDED = re.compile(r" (sign in to|sign me in|log in to|log me in|buy (a|an|the|some|me|us)|pay (for|the|a|an|my|our|them|him|her)|"
                          r"purchase (a|an|the)|transfer (money|funds|the money)|tweet (it|this|that|about)|"
                          r"send (an|the|a) (email|message|text|tweet)|email (them|him|her|the|everyone)|post (it|this|that) (on|to)) ")
# Words that name a secret: such a task starts only when you press Start.
SECRET_WORDS = re.compile(r" (password|passwords|passphrase|secret|secrets|api key|api keys|access key|private key|ssh key|"
                          r"token|tokens|credential|credentials|env file|dotenv) ")
HELD_SECRET = "It mentions a password or key, so it starts only when you press Start."
HELD_FINAL = "It can't be taken back once it's done, so it starts only when you press Start."
LEAD_IN = re.compile(r"^(?:(?:please|ok|okay|so|hey|right|and|also)[,\s]+)*"
                     r"(?:(?:can|could|would|will)\s+(?:you|someone|somebody|an?\s+agent)\s+(?:please\s+)?|"
                     r"(?:we|i)\s+(?:really\s+)?(?:need|want|would like|'d like)\s+(?:you\s+|someone\s+|an?\s+agent\s+)?to\s+|"
                     r"(?:let'?s|someone should|somebody should|we should|you should)\s+|"
                     r"(?:i\s+want|we\s+need|i\s+need)\s+)", re.I)
HAND_OUT = re.compile(r"^(?:(?:please|can you|could you)\s+)?(?:get|have|ask|send|find)\s+(?:someone|somebody|an?\s+(?:new\s+)?agent|claude|codex)\s+", re.I)


class Refusal(ValueError):
    """Something the front door won't do, in words for the person who asked."""


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


def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def lower_first(text):
    return text[:1].lower() + text[1:] if text[:1].isupper() and not text[1:2].isupper() else text


def upper_first(text):
    return text[:1].upper() + text[1:]


def sentence(text):
    text = text.strip()
    return text if text[-1:] in ".!?" else text + "."


# "the password is ...", said in a sentence: the name and the value, for the scanner's own test of a named value.
SAID_SECRET = re.compile(r"\b(password|passphrase|passcode|pin|token|api[ _-]?key|secret|key)(\s+(?:is|was)|\s*[=:])?\s+[\"']?([^\s\"']{6,})", re.I)


def has_secret(text):
    """Whether words have a password, token or key in them, as the building finds them anywhere (connect/live.py), or
    said in a sentence ("the password is ..."). A scanner that fails counts as yes."""
    text = str(text or "")
    try:
        if live.secret_spans(text):
            return True
        for m in SAID_SECRET.finditer(text):
            value = m.group(3).rstrip(".,;!?")
            # "the password is ...": the scanner's test of a named value; "password Xq9...": only one that looks random
            if live.secret_scan.named_hit(m.group(1).replace(" ", "_"), value) and (m.group(2) or live.secret_scan.looks_random(value)):
                return True
        return False
    except Exception:
        return True


def plural(label):
    low = label.lower()
    return low.endswith("s") and not low.endswith("ss")


def and_list(names):
    names = list(names)
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1] if names else ""


# ---------- which floor ----------

def floor_named(text, floors):
    """The floor the words name, by its label or project as a whole word ("on Tidepool", "Tidepool's login"). When
    several are named, the last after "on", "for", "in" or "at". None when none is, or it isn't clear."""
    low = text.lower()
    found = []
    for f in floors:
        for name in {f["label"].lower(), f["project"].lower()}:
            if name:
                found += [(m.start(), f) for m in re.finditer(r"(?<![a-z0-9])" + re.escape(name) + r"(?![a-z0-9])", low)]
    if not found:
        return None
    if len({f["project"] for _, f in found}) == 1:
        return found[0][1]
    for at, f in sorted(found, key=lambda x: -x[0]):
        if re.search(r"\b(?:on|for|in|at)\s+(?:the\s+)?$", low[:at]):
            return f
    return None


def floor_guessed(text, floors):
    """A floor the words begin to name after "on", "for", "in" or "at" ("on tide" for Tidepool), as the receptionist's
    hand-out parsing has it (src/control.js), the last first. None if none."""
    for m in reversed(list(re.finditer(r"\b(?:on|for|in|at)\s+(?:the\s+)?([a-z0-9][a-z0-9_-]{2,})", text.lower()))):
        word = m.group(1)
        hits = [f for f in floors if f["label"].lower().startswith(word) or f["project"].lower().startswith(word)]
        if len(hits) == 1:
            return hits[0]
    return None


def floor_given(given, floors):
    """The floor the page says you are on (or picked): its id, label or project."""
    if given is None or given == "":
        return None
    if not isinstance(given, str) or len(given) > 120:
        raise Refusal("That isn't a floor.")
    low = given.strip().lower()
    hit = next((f for f in floors if low in (f["floor"].lower(), f["label"].lower(), f["project"].lower())), None)
    if not hit:
        raise Refusal(f'"{one_line(given, 40)}" has no folder on this computer, so no agent can work there. Give its floor a folder '
                      "in data/company.json.")
    return hit


def title_of(text, floors):
    """A title by rule: your words without "can you", "get someone to" and the floor's name at the end, cut to about
    60 characters at a word."""
    words = " ".join(text.split())
    names = sorted({n for f in floors for n in (f["label"], f["project"]) if n}, key=len, reverse=True)
    floor_part = "|".join(re.escape(n) for n in names) or "(?!)"
    words = re.sub(r"^(?:on|for|in|at)\s+(?:the\s+)?(?:" + floor_part + r")(?:\s+(?:floor|project))?\s*[,:]\s*", "", words, flags=re.I)
    words = re.sub(r"^(?:" + floor_part + r")\s*[:,]\s*", "", words, flags=re.I)
    m = HAND_OUT.match(words)
    if m:
        words = words[m.end():]
        words = re.sub(r"^(?:on|from|for)\s+(?:the\s+)?(?:" + floor_part + r")(?:\s+(?:floor|project))?\s+", "", words, flags=re.I)
        words = re.sub(r"^to\s+", "", words, flags=re.I)
    for _ in range(3):
        cut = LEAD_IN.sub("", words, count=1)
        if cut == words:
            break
        words = cut
    words = re.sub(r"(?:\s*,?\s*please)?[\s.!?]*$", "", words, flags=re.I)
    words = re.sub(r"\s+(?:on|for|in|at)\s+(?:the\s+)?(?:" + floor_part + r")(?:\s+(?:floor|project))?\s*$", "", words, flags=re.I)
    words = re.sub(r"(?:\s*,?\s*please)?[\s.!?]*$", "", words, flags=re.I).strip(" ,;:-")
    words = upper_first(words or text.strip())
    if len(words) > TITLE_MOST:
        cut = words[:TITLE_MOST].rsplit(" ", 1)[0].rstrip(" ,;:-")
        words = (cut if len(cut) > 20 else words[:TITLE_MOST - 1]) + "…"
    return words


def plain_done(check_label):
    """"Done when" by rule."""
    if check_label:
        label = lower_first(check_label)
        return f"What you asked for is done, and {label} {'pass' if plural(label) else 'passes'}."
    return "What you asked for is done, and you have looked at it."


def refused_new(text, words):
    """What the building refuses or can't take back, in the lead's words but not in yours."""
    mine, theirs = wits.norm(words), wits.norm(text)
    for rule in (wits.REFUSE, wits.FINAL):
        said = {m if isinstance(m, str) else m[0] for m in rule.findall(theirs)}
        if said - {m if isinstance(m, str) else m[0] for m in rule.findall(mine)}:
            return True
    return False


def written(value, least, most, words):
    """What the lead wrote, if it will do: one line, not too short or long, nothing secret, nothing new the building
    refuses or can't take back. Else None, and the rule's is used."""
    if not isinstance(value, str) or "\n" in value.strip():
        return None
    text = " ".join(value.split()).strip(" \"'")
    if not least <= len(text) <= most or has_secret(text) or refused_new(text, words):
        return None
    return text


# ---------- what the floor's finished work took ----------

def estimate(data, project):
    """The median time and spend of a floor's finished work, from the history (data/feeds/history/, a file a day) and
    the feed's spending: {"minutes", "tokens" (or None), "from"}, or None until LEAST_FINISHED pieces have finished."""
    folder = os.path.join(data, "feeds", "history")
    try:
        names = sorted(n for n in os.listdir(folder) if n.endswith(".json"))[-14:]
    except OSError:
        return None
    took, keys = [], set()
    for name in names:
        rows = (read(os.path.join(folder, name)) or {}).get("moments")
        began = {}
        for m in sorted((r for r in rows or [] if isinstance(r, dict) and r.get("project") == project), key=lambda r: r.get("at") or 0):
            key, kind, at = m.get("key"), m.get("kind"), m.get("at")
            if not key or not isinstance(at, (int, float)):
                continue
            if kind == "working" and key not in began:
                began[key] = at
            elif kind == "finished" and key in began:
                seconds = at - began.pop(key)
                if 30 <= seconds <= 12 * 3600:
                    took.append(seconds)
                    keys.add(key)
    if len(took) < LEAST_FINISHED:
        return None
    feed = read(os.path.join(data, "feeds", "claude-code.json")) or {}
    spent = {}
    ended = feed.get("ended") if isinstance(feed.get("ended"), dict) else {}
    for key, t in (ended.get("talks") or {}).items() if isinstance(ended.get("talks"), dict) else []:
        if key in keys and isinstance(t, dict) and isinstance(t.get("tokens"), int) and t["tokens"] > 0:
            spent[key] = t["tokens"]
    for c in feed.get("conversations") or []:
        s = c.get("spent") if isinstance(c, dict) and c.get("id") in keys else None
        if isinstance(s, dict) and isinstance(s.get("tokens"), int) and s["tokens"] > 0:
            spent[c["id"]] = max(spent.get(c["id"], 0), s["tokens"])
    tokens = int(statistics.median(spent.values())) if len(spent) >= LEAST_FINISHED else None
    return {"minutes": max(1, round(statistics.median(took) / 60)), "tokens": tokens, "from": len(took)}


def found_test(folder):
    """The test command the project's own files name, as setup finds it (connect/agent_setup.py), or None."""
    try:
        try:
            from . import agent_setup
        except ImportError:
            import agent_setup
        run = agent_setup.detect(folder).get("test")
    except Exception:  # setup can't be loaded here, or the folder can't be read: the person looks at it
        return None
    return list(run) if isinstance(run, list) and run and all(isinstance(w, str) and w for w in run) else None


def prompt(task):
    """What the new agent is handed, before Control.brief adds where it was started from: your words, Done when and
    Proven by, and to prove it that way before it says it is done."""
    words = one_line(task["text"], WORDS_IN_PROMPT)
    out = [words]
    if task["title"].rstrip("…").lower() not in words.lower():
        out.append(f"In short: {task['title']}.")
    out.append(f"Done when: {sentence(task['done_when'])}")
    if task.get("proof_run"):
        out.append(f"Proven by: {task['proven_by']}. Before you say it is done, prove it: run {' '.join(task['proof_run'])} yourself, "
                   "make sure it passes, and say what it showed.")
    else:
        out.append("Proven by: the person looks at it. Before you say it is done, say plainly what they should look at, and how, "
                   "to see that it works.")
    if task.get("note"):
        out.append(task["note"])
    return "\n\n".join(out)


class Intake:
    """The front door's side of control: making, starting, dropping and changing ready tasks, and the queue."""

    def __init__(self, control, check_for):
        self.control = control
        self.check_for = check_for  # connect/control.py's: a floor's check, or None
        self.data = control.data
        self.root = control.box.path("intake")
        self.lock = threading.RLock()
        self.ticked = 0.0
        self.swept = 0.0

    # ---------- the files ----------

    def path(self, tid):
        return os.path.join(self.root, tid + ".json")

    def task(self, tid):
        if not isinstance(tid, str) or not TASK_ID.match(tid):
            raise Refusal("That isn't a ready task.")
        row = read(self.path(tid))
        if not row or row.get("state") not in STATES:
            raise Refusal("That task isn't kept any more.")
        return row

    def save(self, task):
        task["updated"] = time.time()
        write(self.path(task["id"]), task)

    def tasks(self):
        try:
            names = os.listdir(self.root)
        except OSError:
            return []
        rows = (read(os.path.join(self.root, n)) for n in names if n.endswith(".json") and TASK_ID.match(n[:-5]))
        return sorted((r for r in rows if r and r.get("state") in STATES), key=lambda r: r.get("created") or 0)

    def sweep(self, now=None):
        """Ready and queued tasks go after 7 days; started, finished and dropped ones after 30."""
        now = now or time.time()
        for task in self.tasks():
            age = now - float(task.get("updated") or task.get("created") or 0)
            if age > (READY_DAYS if task["state"] in WAITING else KEPT_DAYS) * 86400:
                try:
                    os.remove(self.path(task["id"]))
                except OSError:
                    pass

    # ---------- the page's side ----------

    def views(self):
        """The ready and queued tasks, as control's state gives them: queued first, in the order they start."""
        if not switches.on("front_door", self.data):
            return []
        labels = {f["project"]: f["label"] for f in self.control.floors()}
        rows = [t for t in self.tasks() if t["state"] in WAITING]
        rows.sort(key=lambda t: (t["state"] != "queued", t.get("queued_at") or 0, t.get("created") or 0))
        return [self.view(t, labels) for t in rows]

    def switched(self):
        """The front door's switches, for a phone, which can't read data/serve.json."""
        return {"on": switches.on("front_door", self.data), "auto": switches.on("ready_auto", self.data)}

    @staticmethod
    def view(task, labels=None):
        out = {k: task.get(k) for k in ("id", "project", "title", "done_when", "proven_by", "agent", "estimate", "state", "key",
                                        "created", "via", "why", "held")}
        out["at"] = task.get("updated")
        out["label"] = (labels or {}).get(task.get("project")) or task.get("label") or task.get("project")
        return out

    def take(self, given):
        """Your words, as a ready task: {"task", "reply"}. With no floor to be had, {"task": None, "reply"} asking which,
        and "floors", their names."""
        if not switches.on("front_door", self.data):
            raise Refusal("One front door is switched off. Switch it on in Settings, under Switches.")
        text = str(given.get("text") or "").strip()
        if not text:
            raise Refusal("Say what needs doing first.")
        if len(text) > MAX_TEXT:
            raise Refusal(f"That's too long: keep it under {MAX_TEXT} characters.")
        via = given.get("via") if given.get("via") in VIA else "talk"
        if has_secret(text):
            raise Refusal(SECRET_SAID)
        if NEVER_HANDED.search(wits.norm(text)):
            raise Refusal(NEVER_SAID)
        floors = self.control.floors()
        if not floors:
            raise Refusal("I can't take work yet: no floor names its project's folder in data/company.json.")
        planned = floor_given(given.get("floor"), floors) if via == "day" else None  # the plan's own floor, whatever the words name
        floor = planned or floor_named(text, floors) or floor_given(given.get("floor"), floors) or floor_guessed(text, floors) \
            or (floors[0] if len(floors) == 1 else None)
        if floor is None:
            labels = [f["label"] for f in floors]
            return {"task": None, "reply": f"Which floor is that for? {and_list(labels)}.", "floors": labels}
        task = self.shape(text, floor, via)
        titled = written(given.get("title"), 3, TITLE_LONGEST, text) if via == "day" else None
        if titled:  # the plan's item keeps its title on the card
            task["title"] = titled.rstrip(".")
        note = written(given.get("note"), 10, 400, given.get("note") or "") if via == "day" else None
        if note:  # the daily cycle's word to the agent, after Done when and Proven by
            task["note"] = note
        with self.lock:
            self.sweep()
            self.save(task)
            reply = self.read_back(task, floor["label"])
            if switches.on("ready_auto", self.data) and task.get("held"):
                reply += f" {task['held']}"
            elif switches.on("ready_auto", self.data):
                why = self.blocked(task)
                if why:
                    self.queue(task, why)
                    reply = f'Queued on {floor["label"]}: "{task["title"]}". {why}'
                else:
                    try:
                        self.launch(task, night=via == "day" and given.get("night") is True)
                        reply = f'Started on {floor["label"]} by itself: "{task["title"]}". {self.done_said(task)}'
                    except Refusal as why_not:
                        reply += f" It didn't start by itself: {lower_first(str(why_not))}"
        return {"task": self.view(task, {floor["project"]: floor["label"]}), "reply": reply}

    def shape(self, text, floor, via):
        """A ready task from your words, for a floor: by rule, or written by its lead with the brain on, and checked."""
        project = floor["project"]
        check = self.check_for(project, self.data)
        run, label = (check["run"], check["label"]) if check else (None, None)
        found_by = "check" if check else None
        if not run:
            run = found_test(floor["folder"])
            label, found_by = ("The tests", "setup") if run else (None, None)
        title, done, by = title_of(text, self.control.floors()), plain_done(label), "rules"
        shaped = self.lead_writes(text, floor["label"])
        if shaped:
            t = written(shaped.get("title"), 3, TITLE_LONGEST, text)
            d = written(shaped.get("done_when"), 10, DONE_LONGEST, text)
            if t and d:
                title, done, by = t.rstrip("."), sentence(d), "lead"
        company = read(os.path.join(self.data, "company.json")) or {}
        row = next((f for f in company.get("floors") or [] if isinstance(f, dict)
                    and str(f.get("project") or f.get("label") or f.get("id") or "") == project), {})
        agent = "Codex" if str(row.get("agent") or "").strip().lower() == "codex" else "Claude Code"
        norm = wits.norm(text)
        held = HELD_SECRET if SECRET_WORDS.search(norm) else HELD_FINAL if wits.FINAL.search(norm) else None
        now = time.time()
        return {"id": "rd-" + secrets.token_hex(5), "project": project, "floor": floor["floor"], "label": floor["label"],
                "text": text, "title": title, "done_when": done, "by": by,
                "proven_by": f"{label}: {' '.join(run)}" if run else LOOK, "proof_run": run, "proof_label": label, "found_by": found_by,
                "agent": agent, "estimate": estimate(self.data, project), "state": "ready", "key": None, "held": held, "why": None,
                "via": via, "created": now, "updated": now}

    def lead_writes(self, text, label):
        """With the brain on: the lead's title and Done when, as connect/brain.py's shape gives them, or None."""
        mind = getattr(self.control, "brain", None)
        if mind is None or not hasattr(mind, "shape") or not switches.on("brain", self.data):
            return None
        try:
            got = mind.shape(text, label, wait=SHAPE_WAIT)
        except Exception:  # no answer: the rule's words
            return None
        return got if isinstance(got, dict) else None

    def read_back(self, task, label):
        """The ready task in one or two sentences, and "Start it?"."""
        return f'Ready on {label}: "{task["title"]}". {self.done_said(task)} Start it?'

    @staticmethod
    def done_said(task):
        if task.get("by") == "lead":
            return "Done when " + sentence(lower_first(task["done_when"]))
        label = task.get("proof_label")
        if label:
            label = lower_first(label)
            return f"It counts as done when {label} {'pass' if plural(label) else 'passes'}."
        return "It counts as done once you've looked at it."

    def start(self, tid):
        """Start: now, or queued when it can't start yet (paused, over budget, or another agent from here is at work there)."""
        with self.lock:
            task = self.task(tid)
            label = self.label(task)
            if task["state"] == "started":
                raise Refusal(f"It has started already. Look for it on {label}.")
            if task["state"] not in WAITING:
                raise Refusal("That task isn't ready any more.")
            why = self.blocked(task)
            if why:
                self.queue(task, why)
                return {"task": self.view(task), "reply": f'Queued on {label}: "{task["title"]}". {why}'}
            self.launch(task)
            return {"task": self.view(task), "reply": f'Started on {label}: "{task["title"]}". The new agent has your words, '
                    f"Done when and Proven by. Watch it sit down in {label}'s Conversations room."}

    def drop(self, tid):
        with self.lock:
            task = self.task(tid)
            if task["state"] not in WAITING:
                raise Refusal("Only a ready or queued task can be dropped." if task["state"] != "dropped" else "It was dropped already.")
            task.update(state="dropped", why=None)
            self.save(task)
        return {"task": self.view(task), "reply": f'Dropped: "{task["title"]}".'}

    def change(self, tid, given):
        """Your own title or Done when, for a task that hasn't started."""
        with self.lock:
            task = self.task(tid)
            if task["state"] not in WAITING:
                raise Refusal("Only a ready or queued task can be changed.")
            for field, least, most in (("title", 3, TITLE_LONGEST), ("done_when", 5, DONE_LONGEST)):
                value = given.get(field)
                if value is None:
                    continue
                text = " ".join(str(value).split()) if isinstance(value, str) else ""
                if not least <= len(text) <= most:
                    raise Refusal(f"Keep {'the title' if field == 'title' else 'Done when'} between {least} and {most} characters.")
                if has_secret(text):
                    raise Refusal(SECRET_SAID)
                task[field] = text.rstrip(".") if field == "title" else sentence(text)
                if field == "done_when":
                    task["by"] = "lead"  # said as you wrote it
            self.save(task)
        return {"task": self.view(task), "reply": "Changed."}

    # ---------- starting, and the queue ----------

    def label(self, task):
        return next((f["label"] for f in self.control.floors() if f["project"] == task.get("project")), task.get("label") or task.get("project"))

    def queue(self, task, why):
        if task["state"] != "queued":
            task["queued_at"] = time.time()
        task.update(state="queued", why=why)
        self.save(task)

    def busy(self, project):
        """An agent started from the building is at work on this floor."""
        with self.control.lock:
            runs = list(self.control.runs.values())
        return any(r.get("project") == project and r.get("state") == "working" and self.control.alive(r) for r in runs)

    def over_budget(self, project):
        if not switches.on("budget", self.data):
            return False
        company = read(os.path.join(self.data, "company.json")) or {}
        per_day = budget.budget_of(company, project)
        if not per_day:
            return False
        day = budget.local_day()
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        talks = [c for c in feed.get("conversations") or [] if isinstance(c, dict)]
        used = budget.spent_today(talks, project, day, feed.get("ended"))
        return used >= per_day * (1 + self.control.box.allowances(day).get(project, 0))

    def blocked(self, task):
        """Why it can't start now, in words, or None."""
        label = self.label(task)
        if self.control.box.paused():
            return "Every agent is paused, so it starts when you resume them."
        if self.over_budget(task["project"]):
            return f"{label} is over today's budget, so it starts once you let its agents go on."
        if self.busy(task["project"]):
            return f"An agent started from the building is at work on {label}, so it starts when that one finishes."
        if self.looking(task["project"]):
            return f"Work on {label} waits for you to look at it on Show me, so it starts once you say Looks good."
        return None

    def looking(self, project):
        """Finished work on this floor waits for your look on Show me before it counts as done (Control.awaiting_look)."""
        waits = getattr(self.control, "awaiting_look", None)
        if waits is None:
            return False
        with self.control.lock:
            runs = [r for r in self.control.runs.values() if r.get("project") == project and r.get("look")]
        return any(waits(r) for r in runs)

    def launch(self, task, night=False):
        """Starts its agent: Claude Code through Control.start, Codex as carrying on does. Under the lock. `night`: the
        night shift starts it, so its git pushes go nowhere (connect/night.py, no_push_env)."""
        floor = next((f for f in self.control.floors() if f["project"] == task["project"]), None)
        if not floor:
            raise Refusal("Its floor has no folder on this computer any more. Give it one in data/company.json.")
        text = prompt(task)
        try:
            if task.get("agent") == "Codex":
                if not carry_on.installed(self.control.claude, self.control.codex).get("Codex"):
                    raise Refusal("Codex isn't on this computer, or isn't on its PATH. ARNHEIM_CODEX can name its command.")
                if not carry_on.in_git(floor["folder"]):
                    raise Refusal(f"Codex works only in a project kept in git, and {floor['label']}'s folder isn't.")
                run = {"key": "cc-" + secrets.token_hex(6), "sid": None, "agent": "Codex", "project": floor["project"],
                       "folder": floor["folder"], "title": task["title"], "said": "", "at": time.time(), "ready": task["id"],
                       **({"night": True} if night else {})}
                with self.control.lock:
                    self.control.spawn_codex(run, self.control.brief(text, floor))
                key = run["key"]
            else:
                key = self.control.start(floor["project"], text, more={"title": task["title"], "ready": task["id"],
                                                                       **({"night": True} if night else {})})["key"]
        except Refusal:
            raise
        except Exception as why:  # control's own Refused: Claude Code or Codex didn't start
            if why.__class__.__name__ == "Refused":
                raise Refusal(str(why))
            raise
        task.update(state="started", key=key, why=None, started=time.time())
        self.save(task)

    def finished(self, run):
        """An agent started from the building finished: its task is finished, and the next queued on its floor starts."""
        tid = run.get("ready") if isinstance(run, dict) else None
        with self.lock:
            if isinstance(tid, str) and TASK_ID.match(tid):
                task = read(self.path(tid))
                if task and task.get("state") == "started":
                    task.update(state="finished", key=run.get("key") or task.get("key"), outcome=run.get("state"), finished=time.time())
                    self.save(task)
            if isinstance(run, dict) and run.get("project"):
                self.next_on(run["project"])

    def reviewed(self, key, at=None):
        """Looks good, on Show me's card for the work of the agent a ready task started (key): the task is marked looked
        at, and finished if it wasn't yet, and then the next queued on its floor may start. Gives the task, or None."""
        if not isinstance(key, str) or not key:
            return None
        at = at or time.time()
        with self.lock:
            task = next((t for t in self.tasks() if t.get("key") == key and t["state"] in ("started", "finished")), None)
            if task is None:
                return None
            task["reviewed"] = at
            was = task["state"]
            if was == "started":
                task.update(state="finished", outcome="approved", finished=at)
            self.save(task)
            if was == "started":
                self.next_on(task["project"])
        return task

    def next_on(self, project):
        """The first queued task on a floor starts, if it can now. Under the lock."""
        queued = sorted((t for t in self.tasks() if t["state"] == "queued" and t.get("project") == project),
                        key=lambda t: t.get("queued_at") or t.get("created") or 0)
        if not queued:
            return None
        task = queued[0]
        why = self.blocked(task)
        if why:
            if why != task.get("why"):
                task["why"] = why
                self.save(task)
            return None
        try:
            self.launch(task)
        except Refusal as why_not:
            task["why"] = f"It didn't start: {lower_first(str(why_not))}"
            self.save(task)
            return None
        return task

    def tick(self):
        """From control's state, every few seconds at most: what finished while nobody said so (a restart), the queue
        once a pause or a budget lifts, and the sweep."""
        now = time.time()
        if now - self.ticked < TICK or not self.lock.acquire(blocking=False):
            return
        try:
            self.ticked = now
            if now - self.swept > SWEEP:
                self.swept = now
                self.sweep(now)
            rows = self.tasks()
            if not rows:
                return
            with self.control.lock:
                runs = list(self.control.runs.values())
            for task in rows:
                if task["state"] != "started":
                    continue
                run = next((r for r in runs if r.get("ready") == task["id"]), None) or next((r for r in runs if r.get("key") == task.get("key")), None)
                if run is not None and getattr(self.control, "awaiting_look", lambda r: False)(run):
                    continue  # Show me asks you first about this kind of change: done once you say Looks good (reviewed)
                if run is None or (run.get("state") != "working" or not self.control.alive(run)):
                    task.update(state="finished", outcome=(run or {}).get("state") or "done", finished=now)
                    self.save(task)
            for project in dict.fromkeys(t["project"] for t in rows if t["state"] == "queued"):
                self.next_on(project)
        except Exception:  # the queue never costs the page its state
            pass
        finally:
            self.lock.release()
