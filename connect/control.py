#!/usr/bin/env python3
"""Control of your Claude Code agents from the building, for the person at this computer.

Off unless you switch it on: `python3 serve.py --control` (docs/connect.md, "Control your agents").
Then, on a walk and in the panel:

- what you say to an agent reaches its Claude Code conversation at its next step, and its answer
  comes back to you;
- a permission it asks for shows in the building, with Allow and Deny;
- you can start an agent on a floor's project with a first instruction, and stop one at work;
- you can have a floor's check run again on an agent's work (connect/prove.py);
- you can add to the company's memory, the decisions every agent is told, and take them out again;
- you can pause every agent at once and let them go on again, and let a floor's agents go past
  today's budget (connect/budget.py);
- you can put a project's files back as they were at a restore point, taken before an agent changed
  them (connect/restore.py);
- you can work beside them (docs/connect.md, "Work beside your agents"): each message gets a reply straight
  away and shows as queued, taken and answered; a question an agent asks waits a while for your answer here;
  you can leave a note on one changed line, ask it to walk you through its changes, see its changes so far
  (connect/live.py), and hold it at its next step to talk it through until you say carry on.

The page and Claude Code meet in data/control/, on this computer. Control, below, answers the
page's /control/ requests for serve.py, or for a server of your own. Box is the mail between them.
On Claude Code's side the hook (connect/claude_code.py) reads it: it hands your messages to the
conversation, waits a while for your answer to a permission while someone is using the building,
and stops the conversation when you ask.

Nothing here allows anything by itself. An answer is for the one request it was shown with, and
with no answer Claude Code asks as it always does. It never works over --lan. Standard library only.
"""
import hmac
import json
import os
import re
import secrets
import shlex
import signal
import subprocess
import sys
import threading
import time
import uuid



def _beside(name):
    """A module beside this file, loaded by its path: for another server that loads this file by its path
    alone (python3 -I, no folder on the path)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import budget, restore, standing  # as connect.control, from serve.py
except ImportError:
    try:
        import budget  # beside this file, as the hook has it
        import restore
        import standing
    except ImportError:
        budget = _beside("budget")
        restore = _beside("restore")
        standing = _beside("standing")

try:
    from . import carry_on  # never stop at a limit: carrying a conversation on in the other agent
except ImportError:
    try:
        import carry_on
    except ImportError:
        carry_on = _beside("carry_on")

try:
    from . import live, switches  # over an agent's shoulder (connect/live.py), and each feature on or off
except ImportError:
    try:
        import live
        import switches
    except ImportError:
        live = _beside("live")
        switches = _beside("switches")

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
JSON = "application/json; charset=utf-8"
WATCHED = 20  # seconds: a page in use says so every few, so older than this, nobody is there to answer
MAX_TEXT = 2000
KEY = re.compile(r"^cc-[A-Za-z0-9]{1,12}$")  # a conversation, as the feed names it (claude_code.key_of)
ASK_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")
KEEP_RUNS = 30
PROVE = os.path.join(HERE, "prove.py")
ROUTINES = os.path.join(HERE, "routines.py")
ROUTINE = re.compile(r"^rt-[a-z0-9-]{1,60}$")  # a routine, as connect/routines.py names it
MEMORY_MOST = 100  # decisions kept at most
MEMORY_TEXT = 300  # characters in one
PARTS = ("live", "replies", "questions", "review_together", "hold")  # working beside your agents: a switch each
QUESTIONS_KEPT = 12 * 3600  # seconds a question is kept
HOLD_STALE = 15 * 60  # a hold asked for that never reached a step goes after this long
QUESTION_STATES = ("waiting", "open", "window")  # still to answer: the hook waits for it; the turn ended on it; asked in its window
WALK = ("Walk me through your changes so far, file by file: for each file you changed, say in a sentence or two what you "
        "changed and why. Keep it brief, and change nothing while you do.")


def seconds_from(name, usual, least=0.05, most=3600):
    """A time in seconds from the environment, for the tests and for anyone who wants another, within limits."""
    try:
        return max(least, min(most, float(os.environ.get(name) or usual)))
    except ValueError:
        return usual


def hold_seconds():
    """How long a hold lasts at most: ten minutes, or ARNHEIM_HOLD_MOST seconds."""
    return seconds_from("ARNHEIM_HOLD_MOST", 600)


def nobody_seconds():
    """How long a hold lasts once nobody is using the building: two minutes, or ARNHEIM_HOLD_NOBODY seconds."""
    return seconds_from("ARNHEIM_HOLD_NOBODY", 120)


def hook_seconds():
    """The longest one hook waits in one go, under Claude Code's and Codex's own ten-minute limit for a hook: a hold
    that lasts longer goes on at the agent's next step. ARNHEIM_HOOK_MOST seconds changes it."""
    return seconds_from("ARNHEIM_HOOK_MOST", 570, most=580)


def wait_seconds():
    """How long a permission request waits for your answer in the building: two minutes, or
    ARNHEIM_CONTROL_WAIT seconds. Claude Code shows nothing else meanwhile."""
    try:
        return max(5, min(550, int(os.environ.get("ARNHEIM_CONTROL_WAIT") or 120)))
    except ValueError:
        return 120


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


def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def check_of(floor):
    """A floor's check (connect/prove.py), as data/company.json gives it: {"run": [the command and its
    arguments], "label": what to call it, "folder": where to run it (the floor's first folder if left out),
    "timeout": seconds}, or just the list. None if it has none, or its folder isn't on this computer."""
    given = floor.get("check") if isinstance(floor, dict) else None
    if isinstance(given, list):
        given = {"run": given}
    if not isinstance(given, dict):
        return None
    run = given.get("run")
    if not isinstance(run, list) or not 0 < len(run) <= 64 or not all(isinstance(arg, str) and arg for arg in run):
        return None
    folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
    where = given.get("folder") or (folders[0] if isinstance(folders, list) and folders else None)
    if not isinstance(where, str) or not where:
        return None
    path = os.path.realpath(os.path.expanduser(where))
    if not os.path.isdir(path):
        return None
    try:
        wait = int(given.get("timeout") or 600)
    except (TypeError, ValueError):
        wait = 600
    return {"run": list(run), "folder": path, "timeout": max(1, min(3600, wait)), "label": one_line(given.get("label") or "Its check", 60)}


def check_for(project, data=DATA):
    """The check of the floor whose project (or label) this is, or None."""
    company = read(os.path.join(data, "company.json")) or {}
    for floor in company.get("floors") or []:
        if isinstance(floor, dict) and project and str(floor.get("project") or floor.get("label") or "") == project:
            return check_of(floor)
    return None


def brief(data, text, floor, more="", ask=False):
    """What a new agent is handed: the job in your words, where it was started from, and what counts as done, and
    with `ask`, to ask rather than guess (connect/claude_code.py brings its questions to the building).
    The company's memory reaches it through the hook as it starts."""
    company = read(os.path.join(data, "company.json")) or {}
    check = check_for(floor["project"], data)
    done = (f"When you finish, Arnheim runs {check['label'][:1].lower() + check['label'][1:] if check['label'][1:2].islower() else check['label']} "
            f"({' '.join(check['run'])}) on your work, and it only counts as done if that passes, so run it yourself first. "
            if check else "")
    return (f"{text[:1].upper() + text[1:]}\n\n"
            f"You were started from Arnheim, the building that shows {one_line(company.get('company') or 'the company', 60)}'s work, "
            f"{more or 'by the person you work for'}, on the {floor['label']} floor, in its folder. {done}"
            + ("Ask rather than guess on anything that matters: ask with your question tool if you have one, or end your "
               "turn with the question, and the person can answer you from the building. " if ask else "")
            + "When you have finished, say plainly what you did and how you checked it.")


def floors_of(data=DATA):
    """Each floor that names a folder on this computer: its project, its label, and the folder an
    agent starts in (its first)."""
    company = read(os.path.join(data, "company.json")) or {}
    out = []
    for floor in company.get("floors") or []:
        if not isinstance(floor, dict):
            continue
        folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
        for folder in folders if isinstance(folders, list) else []:
            path = os.path.realpath(os.path.expanduser(str(folder)))
            if os.path.isdir(path):
                project = str(floor.get("project") or floor.get("label") or floor.get("id") or "")
                check = check_of(floor)
                out.append({"project": project, "label": str(floor.get("label") or project), "floor": str(floor.get("id") or ""), "folder": path,
                            "check": check and check["label"]})
                break
    return out


def folders_of(project, data=DATA):
    """The folders of the floor whose project (or label) this is, as data/company.json names them, that are on this
    computer: the only folders git diff ever runs in."""
    company = read(os.path.join(data, "company.json")) or {}
    for floor in company.get("floors") or []:
        if isinstance(floor, dict) and project and str(floor.get("project") or floor.get("label") or "") == project:
            folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
            found = [os.path.realpath(os.path.expanduser(str(f))) for f in folders if isinstance(f, str) and f] if isinstance(folders, list) else []
            return [f for f in dict.fromkeys(found) if os.path.isdir(f)]
    return []


def question_view(row):
    """A question as the page gets it (docs: the contract for the page)."""
    return {k: row.get(k) for k in ("id", "key", "kind", "text", "questions", "said", "at", "until", "state", "project", "agent", "title")}


def hold_view(row):
    return {k: row.get(k) for k in ("state", "asked_at", "since", "until", "why", "ended_at")} if isinstance(row, dict) else None


def prove_later(project, data=DATA, also=None):
    """Starts connect/prove.py for a floor in the background, and gives back at once."""
    args = [sys.executable, PROVE, project] + (["--also", also] if also else [])
    return subprocess.Popen(args, cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            env=dict(os.environ, ARNHEIM_DATA=data), close_fds=True, start_new_session=hasattr(os, "setsid"))


def memory(data=DATA):
    """The company's memory, data/memory.json: the decisions every agent is told, oldest first."""
    rows = (read(os.path.join(data, "memory.json")) or {}).get("memory")
    return [row for row in rows if isinstance(row, dict) and str(row.get("text") or "").strip()] if isinstance(rows, list) else []


def told(rows, new=False):
    """The company's memory, as an agent is handed it."""
    said = " ".join(f"({i}) {one_line(row['text'], MEMORY_TEXT)}" for i, row in enumerate(rows, 1))
    when = "made new standing decisions since you started" if new else "keep standing decisions"
    return (f"The people you work for {when}, in Arnheim, the building that shows their company's work. "
            f"Follow them unless they tell you otherwise: {said}")


PATCHED = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+?)\s*$|^\*\*\* Move to: (.+?)\s*$", re.M)


def patched(given):
    """The files a Codex patch changes (its apply_patch tool), as the patch names them, in order."""
    given = given if isinstance(given, dict) else {}
    patch = given.get("command") or given.get("patch") or given.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    return list(dict.fromkeys(a or b for a, b in PATCHED.findall(str(patch))))


def describe(tool, given):
    """What a permission is for, in one line: the command, the file or the address."""
    given = given if isinstance(given, dict) else {}
    if tool == "apply_patch":  # Codex's edits: the files, never the whole patch
        files = patched(given)
        return one_line(f"apply_patch: change {', '.join(files)}" if files else "apply_patch: change files", 300)
    for field in ("command", "file_path", "notebook_path", "url", "query", "path", "pattern", "description"):
        if isinstance(given.get(field), str) and given[field].strip():
            return one_line(f"{tool}: {given[field]}", 300)
    return one_line(f"{tool}: {json.dumps(given, ensure_ascii=False)}" if given else tool, 300)


def quoted(rows):
    said = [one_line(row.get("text"), MAX_TEXT) for row in rows]
    words = f'"{said[0]}"' if len(said) == 1 else " ".join(f'({i}) "{text}"' for i, text in enumerate(said, 1))
    return words, "this message" if len(said) == 1 else "these messages"


def message(rows, stopping=False):
    """Your messages, as Claude Code is handed them."""
    words, what = quoted(rows)
    when = "Before you stop: the person you are working for" if stopping else "While you worked, the person you are working for"
    return (f"{when} sent you {what} from Arnheim, the building that shows their company's work: {words}. "
            "Take it into account, and reply to it in your next message.")


def held_message(rows, before_step=False):
    """Your messages while you hold an agent, as it is handed them: it answers, and is held again at its next step."""
    words, what = quoted(rows)
    out = (f"The person you are working for is holding you at this step from Arnheim, the building that shows their company's "
           f"work, to talk it through, and sent you {what}: {words}. Reply to them in a sentence or two, then go on to your "
           "next step: Arnheim holds you there again until they say carry on.")
    return out + (" This step was not run: make it again if it still fits what they said." if before_step else "")


# Why a hold ended, as the agent is told (await_hold).
HOLD_ENDS = {
    "carry on": ("The person you are working for said carry on, from Arnheim, the building. Go on with your work in the "
                 "direction they gave you, keeping what you have done."),
    "ten minutes": ("You have been held for 10 minutes, the longest a hold lasts in Arnheim, the building, so go on with your "
                    "work, taking into account anything the person said while you were held."),
    "nobody": ("Nobody has used Arnheim, the building, for 2 minutes, so your hold has ended. Go on with your work, taking "
               "into account anything the person said while you were held."),
    "off": "Holding was switched off in Arnheim, the building, so go on with your work.",
}
STILL_HELD = ("The person you are working for is still holding you from Arnheim, the building. Don't go on yet: make this "
              "same step again, and Arnheim holds you there until they say carry on.")


def answered_words(got):
    """An answer from the building, in words: {"text"} as said, or {"answers"} as each question and its answer."""
    if not isinstance(got, dict):
        return ""
    if isinstance(got.get("answers"), dict):
        if len(got["answers"]) == 1:
            return one_line(next(iter(got["answers"].values())), 500)
        return "; ".join(f"{one_line(q, 200)}: {one_line(a, 500)}" for q, a in got["answers"].items())
    return one_line(got.get("text"), MAX_TEXT)


class Box:
    """data/control/: your messages, Claude Code's permission requests and your answers, and
    requests to stop. Claude Code's side reads it through the hook, the page's through Control."""

    def __init__(self, data=DATA):
        self.root = os.path.join(data, "control")

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    # Someone is using the building: its page says so every few seconds while they walk, or have
    # touched it in the last two minutes (src/control.js). A page left open on its own doesn't count.
    def watch(self):
        os.makedirs(self.root, exist_ok=True)
        with open(self.path("watched"), "w") as handle:
            handle.write(str(time.time()))

    def watched(self):
        try:
            return time.time() - os.path.getmtime(self.path("watched")) < WATCHED
        except OSError:
            return False

    # What you say to a conversation, for it to read at its next step.
    def post(self, key, text, mid=None):
        os.makedirs(self.path("inbox"), exist_ok=True)
        row = {"id": mid or secrets.token_hex(6), "text": text, "at": time.time()}
        fd = os.open(self.path("inbox", key + ".jsonl"), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, (json.dumps(row, ensure_ascii=False) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        return row["id"]

    def waiting(self, key):
        try:
            return os.path.getsize(self.path("inbox", key + ".jsonl"))
        except OSError:
            return 0

    def take(self, key):
        """The conversation's waiting messages, oldest first, each handed over once."""
        path = self.path("inbox", key + ".jsonl")
        mine = f"{path}.{os.getpid()}.taken"
        try:
            os.rename(path, mine)  # whoever renames it first has them
        except OSError:
            return []
        try:
            with open(mine, encoding="utf-8") as handle:
                lines = handle.read().splitlines()
        finally:
            gone(mine)
        rows = []
        for raw in lines:
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if isinstance(row, dict) and str(row.get("text") or "").strip():
                rows.append(row)
        return rows

    # A permission a conversation is waiting for, and the one answer to it.
    def ask(self, key, tool, what, until, more=None):
        """A request waiting for your answer. `more`: how often you allowed it before on its floor ("before"),
        whether it may be allowed for good ("standable"), and its floor ("project"; connect/standing.py)."""
        aid = secrets.token_urlsafe(12)
        row = {**(more or {}), "id": aid, "key": key, "tool": tool, "what": what, "at": time.time(), "until": until}
        write(self.path("asks", aid + ".json"), row)
        return aid

    def ask_row(self, aid):
        """A request still waiting for an answer, or None."""
        if not isinstance(aid, str) or not ASK_ID.match(aid):
            return None
        row = read(self.path("asks", aid + ".json"))
        return row if row and float(row.get("until") or 0) > time.time() and not os.path.exists(self.path("answers", aid + ".json")) else None

    def asks(self):
        """The requests still waiting for an answer, oldest first."""
        try:
            names = os.listdir(self.path("asks"))
        except OSError:
            return []
        now = time.time()
        out = []
        for name in names:
            if not name.endswith(".json"):
                continue
            row = read(self.path("asks", name))
            until = float((row or {}).get("until") or 0)
            if row and until > now and not os.path.exists(self.path("answers", name)):
                out.append(row)
            elif until < now - 60:  # left behind by a hook that was cut short
                gone(self.path("asks", name))
                gone(self.path("answers", name))
        return sorted(out, key=lambda row: row.get("at") or 0)

    def answer(self, aid, behavior):
        """Answers a request that is still waiting, once. False for any other."""
        if behavior not in ("allow", "deny") or not isinstance(aid, str) or not ASK_ID.match(aid):
            return False
        row = read(self.path("asks", aid + ".json"))
        if not row or float(row.get("until") or 0) < time.time():
            return False
        os.makedirs(self.path("answers"), exist_ok=True)
        try:
            fd = os.open(self.path("answers", aid + ".json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"id": aid, "behavior": behavior, "at": time.time()}, handle)
        return True

    def answered(self, aid):
        row = read(self.path("answers", aid + ".json"))
        return row.get("behavior") if row and row.get("behavior") in ("allow", "deny") else None

    def close(self, aid):
        gone(self.path("asks", aid + ".json"))
        gone(self.path("answers", aid + ".json"))

    # Stopping a conversation at its next step.
    def stop(self, key):
        os.makedirs(self.path("stop"), exist_ok=True)
        with open(self.path("stop", key), "w") as handle:
            handle.write(str(time.time()))

    # Every agent paused at once, from the building, until you resume them.
    def pause(self):
        write(self.path("paused.json"), {"at": time.time()})

    def resume(self):
        gone(self.path("paused.json"))

    def paused(self):
        """When every agent was paused, or None."""
        at = (read(self.path("paused.json")) or {}).get("at")
        return at if isinstance(at, (int, float)) else None

    # A floor's agents allowed past today's budget: as much again, each time you let them.
    def allowances(self, day):
        given = read(self.path("budget.json")) or {}
        extra = given.get("extra") if given.get("day") == day else None
        return {k: v for k, v in extra.items() if isinstance(v, int) and v > 0} if isinstance(extra, dict) else {}

    def allow_more(self, project, day):
        extra = self.allowances(day)
        extra[project] = extra.get(project, 0) + 1
        write(self.path("budget.json"), {"day": day, "extra": extra})
        return extra[project]

    def stopping(self, key, keep=False):
        path = self.path("stop", key)
        if not os.path.exists(path):
            return False
        if not keep:
            gone(path)
        return True

    def locked(self, name):
        """One writer at a time, between the hooks and serve.py, for questions or holds."""
        os.makedirs(self.root, exist_ok=True)
        return live._Lock(self.path(f".{name}.lock"))

    # Questions an agent asked you (connect/claude_code.py): Claude Code's AskUserQuestion, or a turn that ended
    # with a question. "waiting": the hook waits for your answer now; "open": the turn ended on it; "window": it
    # asked in its own window instead; "answered" and "done" once answered, here or there.
    def question(self, key, kind, text, questions=None, until=None, more=None):
        qid = secrets.token_urlsafe(12)
        row = {**(more or {}), "id": qid, "key": key, "kind": kind, "text": text, "questions": questions or [], "at": time.time(),
               "until": until, "state": "waiting" if until else ("window" if kind == "choices" else "open")}
        with self.locked("questions"):
            for old in self.question_rows():  # what it asked before has moved on
                if old.get("key") == key and old.get("state") in QUESTION_STATES:
                    old["state"] = "done"
                    write(self.path("questions", old["id"] + ".json"), old)
            write(self.path("questions", qid + ".json"), row)
        return qid

    def question_rows(self):
        try:
            names = os.listdir(self.path("questions"))
        except OSError:
            return []
        now = time.time()
        out = []
        for name in names:
            if not name.endswith(".json") or name.endswith(".answer.json"):
                continue
            row = read(self.path("questions", name))
            if not row or now - float(row.get("at") or 0) > QUESTIONS_KEPT:
                gone(self.path("questions", name))
                gone(self.path("questions", name[:-5] + ".answer.json"))
                continue
            out.append(row)
        return sorted(out, key=lambda row: row.get("at") or 0)

    @staticmethod
    def shown_state(row, now=None):
        """A question's state as it stands: one the hook stopped waiting for (it was cut short) is open, or in the
        agent's window."""
        state = row.get("state")
        if state == "waiting" and float(row.get("until") or 0) < (now or time.time()) - 5:
            return "window" if row.get("kind") == "choices" else "open"
        return state

    def question_row(self, qid):
        if not isinstance(qid, str) or not ASK_ID.match(qid):
            return None
        return read(self.path("questions", qid + ".json"))

    def questions(self, key=None):
        """The questions still to answer, oldest first, each with its state as it stands."""
        now = time.time()
        out = []
        for row in self.question_rows():
            row["state"] = self.shown_state(row, now)
            if row["state"] in QUESTION_STATES and (key is None or row.get("key") == key):
                out.append(row)
        return out

    def reply(self, qid, answer):
        """Your answer to a question: "now" when its hook is waiting and takes it back to the agent, "later" when it
        isn't (the caller sends it as a message), or None when it is answered already or gone."""
        with self.locked("questions"):
            row = self.question_row(qid)
            if not row or self.shown_state(row) not in QUESTION_STATES:
                return None
            if row.get("state") == "waiting" and float(row.get("until") or 0) > time.time():
                os.makedirs(self.path("questions"), exist_ok=True)
                try:
                    fd = os.open(self.path("questions", qid + ".answer.json"), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    return None
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump({**answer, "at": time.time()}, handle, ensure_ascii=False)
                said = "now"
            else:
                said = "later"
            row.update(state="answered", answered_at=time.time(), answered=one_line(answered_words(answer), 300))
            write(self.path("questions", qid + ".json"), row)
        return said

    def replied(self, qid):
        return read(self.path("questions", qid + ".answer.json"))

    def settle(self, qid, state):
        """The hook stops waiting: your answer if it came just now, else the question becomes `state` ("open" or
        "window", or "answered" when the hook had it another way). Gives the answer or None."""
        with self.locked("questions"):
            got = self.replied(qid)
            gone(self.path("questions", qid + ".answer.json"))
            row = self.question_row(qid)
            if row and row.get("state") == "waiting":
                row.update(state="answered" if got else state, until=None)
                write(self.path("questions", qid + ".json"), row)
        return got

    def close_questions(self, key, kinds=("choices", "words"), state="done"):
        """Its questions have been answered in its own window, or it has moved on."""
        with self.locked("questions"):
            for row in self.question_rows():
                if row.get("key") == key and row.get("kind") in kinds and row.get("state") in QUESTION_STATES:
                    row.update(state=state, until=None)
                    write(self.path("questions", row["id"] + ".json"), row)

    # Holding an agent at its next step to talk it through (await_hold): "asked" until a step comes, "held" while
    # it waits there, "ended" (with why) until the agent has been told.
    def hold_row(self, key):
        row = read(self.path("holds", key + ".json")) if isinstance(key, str) and KEY.match(key) else None
        if row and row.get("state") == "asked" and time.time() - float(row.get("asked_at") or 0) > HOLD_STALE:
            gone(self.path("holds", key + ".json"))
            return None
        return row

    def holds(self):
        try:
            names = os.listdir(self.path("holds"))
        except OSError:
            return {}
        rows = (self.hold_row(name[:-5]) for name in names if name.endswith(".json"))
        return {row["key"]: row for row in rows if row and row.get("key")}

    def hold(self, key):
        with self.locked("holds"):
            row = self.hold_row(key)
            if row and row.get("state") in ("asked", "held"):
                return row
            row = {"key": key, "state": "asked", "asked_at": time.time()}
            write(self.path("holds", key + ".json"), row)
        return row

    def change_hold(self, key, **fields):
        with self.locked("holds"):
            row = self.hold_row(key)
            if row and row.get("state") == "held":
                row.update(fields)
                write(self.path("holds", key + ".json"), row)
            return row

    def go_on(self, key):
        """Carry on: "held" when a held agent is told at once or at its next step, "asked" when it never got
        as far as a step (nothing to tell), or None when it isn't held."""
        with self.locked("holds"):
            row = self.hold_row(key)
            if not row or row.get("state") not in ("asked", "held"):
                return None
            if row["state"] == "asked":
                gone(self.path("holds", key + ".json"))
                return "asked"
            row.update(state="ended", why="carry on", ended_at=time.time())
            write(self.path("holds", key + ".json"), row)
            return "held"

    def end_hold(self, key, why=None):
        """Ends a hold from the hook's side and tells it once: why it ended, for the one step that tells the agent,
        or None for any other step (another told it already)."""
        with self.locked("holds"):
            row = self.hold_row(key)
            if not row or row.get("state") not in ("asked", "held", "ended"):
                return None
            gone(self.path("holds", key + ".json"))
            return row.get("why") if row["state"] == "ended" else why


def await_answer(box, key, tool, what, more=None):
    """For the hook: shows a permission request in the building, if someone is using it, and waits
    for your answer there. Gives "allow", "deny", "stop" (deny and stop the conversation), or None: no
    answer, so Claude Code asks as it always does."""
    if not box.watched():
        return None
    until = time.time() + wait_seconds()
    aid = box.ask(key, tool, what, until, more)
    try:
        while time.time() < until:
            got = box.answered(aid)
            if got:
                return got
            if box.stopping(key):
                return "stop"
            if not box.watched():  # nobody is using the building now
                return None
            time.sleep(0.25)
        return None
    finally:
        box.close(aid)


def await_question(box, qid, key, until, tick=0.25, clock=time.time, sleep=time.sleep):
    """For the hook, while someone is using the building: waits for your answer to a question an agent asked.
    Gives ("answer", {"answers"} or {"text"}), ("words", rows) for a message you sent it meanwhile, which answers
    it, ("stop", None) when you stopped it, or (None, None): no answer by `until`, or nobody there any more, so it
    asks in its own window as it always did, or the question waits as a card. It never waits past `until`."""
    while clock() < until:
        got = box.replied(qid)
        if got:
            return "answer", got
        if box.stopping(key, keep=True):
            return "stop", None
        rows = box.take(key)
        if rows:
            return "words", rows
        if not box.watched():
            break
        sleep(tick)
    return None, None


def await_hold(box, key, most=None, nobody=None, budget=None, tick=0.25, on=lambda: True, clock=time.time, sleep=time.sleep,
               held=None):
    """For the hook, at an agent's next step while you hold it from the building: waits there, without ending its
    turn, until something happens. Gives:

    - ("words", rows): your messages, to hand over now; it is held again at its next step;
    - ("carry on" | "ten minutes" | "nobody" | "off", []): the hold has ended, and why, for this step to tell it;
    - ("stopped", []): you stopped it;
    - ("still", []): this step waited as long as one hook may (hook_seconds) and it is still held;
    - ("gone", []): another of its steps, run at the same time, handed over or told it;
    - None: it isn't held.

    A hold lasts `most` seconds from the step it first held at (ten minutes), and `nobody` seconds once nobody is
    using the building (two minutes). Times are injectable, for the tests. `held(row)` is told the hold as it
    waits, for the agent's screen."""
    most = hold_seconds() if most is None else most
    nobody = nobody_seconds() if nobody is None else nobody
    budget = hook_seconds() if budget is None else budget
    started = clock()
    with box.locked("holds"):
        row = box.hold_row(key)
        if row is None:
            return None
        if row.get("state") == "asked":
            row.update(state="held", since=started, until=started + most, handed=0)
            write(box.path("holds", key + ".json"), row)
    if row.get("state") == "ended":
        why = box.end_hold(key)
        return (why, []) if why else ("gone", [])
    if held:
        held(row)
    handed = row.get("handed", 0)
    checked = started
    while True:
        now = clock()
        if box.stopping(key, keep=True):
            box.end_hold(key, "stopped")
            return "stopped", []
        rows = box.take(key)
        if rows:
            box.change_hold(key, handed=handed + 1)
            return "words", rows
        row = box.hold_row(key)
        if row is None:
            return "gone", []
        if row.get("state") == "ended":
            why = box.end_hold(key)
            return (why, []) if why else ("gone", [])
        if row.get("handed", 0) != handed:
            return "gone", []
        if now >= float(row.get("until") or 0):
            why = box.end_hold(key, "ten minutes")
            return (why, []) if why else ("gone", [])
        if box.watched():
            if row.get("unwatched_since"):
                box.change_hold(key, unwatched_since=None)
        elif not row.get("unwatched_since"):
            box.change_hold(key, unwatched_since=now)
        elif now - float(row["unwatched_since"]) >= nobody:
            why = box.end_hold(key, "nobody")
            return (why, []) if why else ("gone", [])
        if now - checked >= 2:
            checked = now
            if not on():
                why = box.end_hold(key, "off")
                return (why, []) if why else ("gone", [])
        if now - started >= budget:
            return "still", []
        sleep(tick)


class Refused(Exception):
    """A request the building can't carry out, in words for the person who made it."""


class Control:
    """The page's side: answers /control/ requests (handle), and looks after the agents started
    from the building, each a `claude -p` in its floor's folder, with your own Claude Code
    settings, as if you had started it there yourself."""

    def __init__(self, data=DATA, claude=None):
        self.data = data
        self.box = Box(data)
        self.lv = live.Live(data)  # each conversation's screen and your messages' progress (connect/live.py)
        self.token = secrets.token_urlsafe(24)
        self.claude = list(claude) if claude else shlex.split(os.environ.get("ARNHEIM_CLAUDE") or "claude")
        self.codex = shlex.split(os.environ.get("ARNHEIM_CODEX") or "codex")  # for carrying on in Codex (connect/carry_on.py)
        self.lock = threading.Lock()
        self.going_back = threading.Lock()  # one restore at a time, apart from the lock every request takes
        self.runs = {}
        self.procs = {}
        self.load()

    # ---------- requests ----------

    def handle(self, method, name, body=b"", token=""):
        """One request under /control/: (status, content type, bytes, extra headers). Every request
        but `token` needs the token, in the X-Arnheim-Control header. `state` is what waits; `here` is
        the same, from a page someone is using, so permission requests wait for them."""
        def answer(code, data):
            return code, JSON, json.dumps(data, ensure_ascii=False).encode("utf-8"), {}

        if name == "token":
            return answer(200, {"on": True, "token": self.token}) if method == "GET" else answer(405, {"error": "Use GET."})
        if not isinstance(token, str) or not hmac.compare_digest(token.encode(), self.token.encode()):
            return answer(403, {"error": "This page can't control anything. Reload it."})
        if name in ("state", "here"):
            if method != "GET":
                return answer(405, {"error": "Use GET."})
            if name == "here":
                self.box.watch()
            return answer(200, self.state())
        if method != "POST":
            return answer(405, {"error": "Use POST."})
        try:
            given = json.loads((body or b"{}").decode("utf-8"))
        except (UnicodeDecodeError, ValueError):
            return answer(400, {"error": "That wasn't JSON."})
        if not isinstance(given, dict):
            return answer(400, {"error": "That wasn't a JSON object."})
        try:
            if name == "say":
                return answer(200, self.say(given.get("key"), given.get("text")))
            if name == "answer":
                if not self.box.answer(given.get("id"), given.get("behavior")):
                    raise Refused("That request isn't waiting any more: it was answered, or Claude Code asked there instead.")
                return answer(200, {"ok": True})
            if name == "always":
                return answer(200, self.always(given.get("id")))
            if name == "unalways":
                if not standing.remove(self.data, given.get("id")):
                    raise Refused("That isn't one of the commands allowed for good.")
                return answer(200, {"ok": True})
            if name == "start":
                return answer(200, self.start(given.get("project"), given.get("text")))
            if name == "stop":
                return answer(200, self.stop(given.get("key")))
            if name == "prove":
                return answer(200, self.prove(given.get("key")))
            if name == "pause":
                self.box.pause()
                return answer(200, {"ok": True, "paused": True})
            if name == "resume":
                self.box.resume()
                return answer(200, {"ok": True, "paused": False})
            if name == "allow_more":
                return answer(200, self.allow_more(given.get("project")))
            if name == "remember":
                return answer(200, self.remember(given.get("text")))
            if name == "forget":
                return answer(200, self.forget(given.get("id")))
            if name == "run_routine":
                return answer(200, self.run_routine(given.get("key")))
            if name == "restore":
                return answer(200, self.restore(given.get("id")))
            if name == "carry_on":
                return answer(200, self.carry_on(given))
            # Working beside your agents (docs/connect.md, "Work beside your agents")
            if name == "live":
                return answer(200, self.live_of(given.get("key")))
            if name == "changes":
                return answer(200, self.changes(given.get("key")))
            if name == "reply_question":
                return answer(200, self.reply_question(given))
            if name == "comment":
                return answer(200, self.comment(given))
            if name == "walk_through":
                return answer(200, self.walk_through(given.get("key")))
            if name == "hold":
                return answer(200, self.hold(given.get("key")))
            if name == "go_on":
                return answer(200, self.go_on(given.get("key")))
        except Refused as why:
            return answer(400, {"error": str(why)})
        return answer(404, {"error": "No such request."})

    def state(self):
        with self.lock:
            runs = sorted(self.runs.values(), key=lambda run: run.get("at") or 0, reverse=True)
            runs = [{k: run.get(k) for k in ("key", "project", "title", "state", "said", "answered", "at")} for run in runs[:KEEP_RUNS]]
        return {
            "on": True,
            "agents": carry_on.installed(self.claude, self.codex),  # which agents a conversation can carry on in
            "carried": sorted(carry_on.carried(self.data)),
            "wait": wait_seconds(),
            "asks": [{k: row.get(k) for k in ("id", "key", "tool", "what", "at", "until", "before", "standable", "project")} for row in self.box.asks()],
            "always": standing.rows(self.data),
            "runs": runs,
            "projects": [{k: f[k] for k in ("project", "label", "floor", "check")} for f in self.floors()],
            "paused": self.box.paused(),
            "allowed": self.box.allowances(budget.local_day()),
            **self.beside(),
        }

    def beside(self):
        """What state adds for working beside your agents: which parts are on, the questions waiting on you, the
        holds, and each conversation's line from data/live/index.json (for a phone, which can't read that file)."""
        parts = {name: switches.on(name, self.data) for name in PARTS}
        try:
            questions = [question_view(row) for row in self.box.questions()] if parts["questions"] else []
        except Exception:  # a question that can't be read never costs the rest
            questions = []
        holds = {k: hold_view(row) for k, row in self.box.holds().items()}
        return {"parts": parts, "questions": questions, "holds": holds, "live": self.lv.index() if parts["live"] else {}}

    def part(self, name):
        if not switches.on(name, self.data):
            label = next((s[2] for s in switches.SWITCHES if s[0] == name), name)
            raise Refused(f"{label} is switched off. Switch it on in Settings, under Switches.")

    def always(self, aid):
        """Allows a waiting request now, and its exact command on its floor from now on (connect/standing.py)."""
        row = self.box.ask_row(aid)
        if not row:
            raise Refused("That request isn't waiting any more: it was answered, or the agent asked there instead.")
        project, tool, command = row.get("project"), row.get("tool"), row.get("command")
        if not standing.can_stand(tool, command):
            raise Refused("Only a plain test, check or build command, or one that only looks, can be allowed for good. This one asks each time.")
        if standing.times(self.data, project, tool, command) < standing.OFFER_AFTER:
            raise Refused(f"Allow it {standing.OFFER_AFTER} times on this floor first: then it can be allowed for good.")
        if not self.box.answer(aid, "allow"):
            raise Refused("That request isn't waiting any more: it was answered, or the agent asked there instead.")
        try:
            kept = standing.add(self.data, project, tool, command)
        except ValueError as why:  # allowed this once, as asked; it asks again next time
            raise Refused(f"Allowed this once. {why}")
        return {"ok": True, "always": kept}

    # ---------- talking, starting and stopping ----------

    def say(self, key, text, via="message", taken_words=None):
        """Sends a conversation your words: `sent` is "resumed" for an agent started here that had finished (it
        carries on with them now) or "queued" for its next step. With Replies straight away on, it also answers at
        once, in its own words (`reply`), says when it will read them (`when`, connect/live.py's instant), and your
        message shows as queued, taken and answered (data/live/)."""
        key = self.conversation(key)
        text = self.words(text)
        replies = switches.on("replies", self.data)
        mid = secrets.token_hex(6)

        def noted(sent, project):
            """Its reply straight away, and your message on its screen, before the agent can take it."""
            if not replies:
                return {}
            try:
                said = self.instant(key, sent)
                self.lv.posted(key, mid, text, said["reply"], sent, via, taken_words, project=project)
                return said
            except Exception:  # the message is on its way whatever the reply's trouble
                return {}
        with self.lock:
            run = self.runs.get(key)
            if run and run.get("sid") and run.get("folder") and not self.alive(run):
                # An agent started here that has finished: it carries on with what you said.
                said = noted("resumed", run.get("project"))
                self.box.stopping(key)  # an old request to stop isn't for this new turn
                self.spawn(run, ["--resume", run["sid"]], text, answering=mid)
                return {"id": mid, "sent": "resumed", **said}
        if self.box.waiting(key) > 64_000:
            raise Refused("It has a lot waiting for it already. Let it catch up first.")
        said = noted("queued", self.project_of(key))
        return {"id": self.box.post(key, text, mid), "sent": "queued", **said}

    def instant(self, key, sent):
        """The agent's reply the moment you send it something, built from what the building sees: what it is doing now
        and for how long, a permission or question it waits on, a hold, every agent paused, or finished."""
        if sent == "resumed":  # under the lock: nothing more to look at
            said = live.instant(None, False, sent)
            return {"reply": said["words"], "when": said["when"]}
        asks = [row for row in self.box.asks() if row.get("key") == key]
        now = time.time()
        asking = any(q.get("state") == "waiting" and float(q.get("until") or 0) > now for q in self.box.questions(key))
        said = live.instant(self.lv.read(key), self.working(key), sent, permission=asks[0].get("what") if asks else None,
                            asking=asking, hold=self.box.hold_row(key), paused=bool(self.box.paused()), now=now)
        return {"reply": said["words"], "when": said["when"]}

    # ---------- working beside your agents ----------

    def known(self, key):
        """A conversation the building knows, or one it has a screen for."""
        if isinstance(key, str) and KEY.match(key) and self.lv.read(key) is not None:
            return key
        return self.conversation(key)

    def live_of(self, key):
        """One conversation's screen (data/live/<key>.json), its questions waiting on you and its hold: for the page,
        and for a phone, which can't read data/live/ itself."""
        key = self.known(key)
        return {"key": key, "on": switches.on("live", self.data), "live": self.lv.read(key),
                "questions": [question_view(row) for row in self.box.questions(key)] if switches.on("questions", self.data) else [],
                "hold": hold_view(self.box.hold_row(key))}

    def changes(self, key):
        """Its changes so far, file by file, from its own steps; and, for each of its floor's folders kept in git,
        everything not yet committed there, by anyone. The folders come from data/company.json alone."""
        self.part("live")
        key = self.known(key)
        doc = self.lv.read(key) or {}
        project = self.project_of(key) or doc.get("project")
        floor = next((f for f in floors_of(self.data) if f["project"] == project), None)
        folders = folders_of(project, self.data)
        git = []
        for i, folder in enumerate(folders[:4]):
            got = live.git_diff(folder)
            name = (floor or {}).get("label") or project or "its floor"
            got["label"] = (f"Everything not yet committed in {name}'s folder{f' ({i + 1})' if len(folders) > 1 else ''}, by anyone: "
                            "not only this agent's changes.")
            git.append(got)
        return {"key": key, "project": project, "files": live.by_file(doc), "git": git}

    def reply_question(self, given):
        """Your answer to a question an agent asked: {"id", "answers": {question: answer}} for one with choices, or
        {"id", "text"} in your own words. Handed back at once while its hook waits; else sent as a message, which an
        agent started here resumes with, and any other is handed at its next step."""
        self.part("questions")
        row = self.box.question_row(given.get("id"))
        if not row or self.box.shown_state(row) not in QUESTION_STATES:
            raise Refused("That question isn't waiting any more: it was answered, or the agent moved on.")
        answers = given.get("answers")
        if answers is not None:
            asked = [q.get("question") for q in row.get("questions") or [] if isinstance(q, dict)]
            if row.get("kind") != "choices" or not isinstance(answers, dict) or set(answers) != set(asked):
                raise Refused("Answer each of its questions, by the question's own words.")
            clean = {}
            for question, picked in answers.items():
                if isinstance(picked, list) and picked and all(isinstance(p, str) for p in picked):
                    picked = ", ".join(p.strip() for p in picked)
                if not isinstance(picked, str) or not picked.strip() or len(picked) > 500:
                    raise Refused("Each answer is one of its choices, or your own words, under 500 characters.")
                clean[question] = picked.strip()
            answer = {"answers": clean}
        else:
            answer = {"text": self.words(given.get("text"))}
        if row.get("state") != "waiting":
            self.conversation(row["key"])  # sent as a message: it must still be in the building
        got = self.box.reply(row["id"], answer)
        if got == "now":
            if switches.on("replies", self.data):
                self.lv.edit(row["key"], lambda doc: doc.update(asking=None))
            return {"ok": True, "sent": "now", "reply": "Thanks, that's what I needed. I'm carrying on with it now."}
        if got == "later":
            asked = one_line(row.get("text"), 200)
            out = self.say(row["key"], f'About your question ("{asked}"): {one_line(answered_words(answer), 1500)}', via="answer",
                           taken_words="I've got your answer to my question, and I'm on it.")
            return {"ok": True, **out}
        raise Refused("That question isn't waiting any more: it was answered, or the agent moved on.")

    def comment(self, given):
        """A note on one changed line: {"key", "file", "line", "text" (the line as it reads), "words" (yours), and
        "side": "old" for a line the change took out, numbered as the file was}. It reaches the agent as one message
        tied to that file, line and text."""
        self.part("review_together")
        key = self.conversation(given.get("key"))
        file, line, text, side = given.get("file"), given.get("line"), given.get("text"), given.get("side")
        if not isinstance(file, str) or not file.strip() or len(file) > 300 or "\n" in file:
            raise Refused("Say which file.")
        if line is not None and (isinstance(line, bool) or not isinstance(line, int) or not 0 < line < 10_000_000):
            raise Refused("A line is a number from 1.")
        if text is not None and (not isinstance(text, str) or len(text) > 2000):
            raise Refused("The line's text is too long.")
        if side not in (None, "new", "old"):
            raise Refused('A line is on the "new" side of a change, or the "old".')
        words = self.words(given.get("words"))
        where = f"{one_line(file, 300)}, line {line}" if line else one_line(file, 300)
        if side == "old":
            where += " as it was before your change"
        shown = f' ("{one_line(text, 300)}")' if isinstance(text, str) and text.strip() else ""
        return self.say(key, f"About your change to {where}{shown}: {words}", via="comment",
                        taken_words=f"I've got your note on {where}, and I'm on it.")

    def walk_through(self, key):
        """Asks the agent to explain its changes file by file, briefly. Its answer comes back as any reply does."""
        self.part("review_together")
        return self.say(key, WALK, via="walk", taken_words="I've got your request to walk you through my changes, and I'm on it.")

    def hold(self, key):
        """Holds an agent at its next step, without ending its turn (await_hold), until you say carry on."""
        self.part("hold")
        key = self.conversation(key)
        if not self.working(key):
            raise Refused("It isn't at work now, so there's nothing to hold. Send it a message instead.")
        row = self.box.hold(key)
        view = hold_view(row)
        try:
            self.lv.edit(key, lambda doc: doc.update(hold=view))
        except OSError:
            pass
        said = "I'm holding, as you asked." if row.get("state") == "held" else "Okay, I'll hold at my next step."
        return {"ok": True, "hold": view, "reply": said}

    def go_on(self, key):
        """Carry on: a held agent goes on, told why, keeping what it has done."""
        key = self.known(key)
        was = self.box.go_on(key)
        if was is None:
            raise Refused("It isn't held.")
        try:
            self.lv.edit(key, lambda doc: doc.update(hold=None))
        except OSError:
            pass
        return {"ok": True, "was": was, "reply": "Okay, carrying on." if was == "held" else "Okay, I'll carry on: I hadn't stopped yet."}

    def start(self, project, text):
        text = self.words(text)
        floor = next((f for f in self.floors() if f["project"] == project), None)
        if not floor:
            raise Refused("That project has no folder on this computer. Give its floor a folder in data/company.json.")
        sid = str(uuid.uuid4())
        key = "cc-" + sid.replace("-", "")[:12]
        run = {"key": key, "sid": sid, "project": floor["project"], "folder": floor["folder"], "title": one_line(text[:1].upper() + text[1:], 70), "said": "", "at": time.time()}
        with self.lock:
            self.spawn(run, ["--session-id", sid], self.brief(text, floor))
        return {"key": key, "project": floor["project"]}

    def brief(self, text, floor):
        return brief(self.data, text, floor, ask=switches.on("questions", self.data))

    def stop(self, key):
        key = self.conversation(key)
        self.box.stop(key)  # wherever it runs, the hook stops it at its next step
        with self.lock:
            run = self.runs.get(key)
            if run and self.alive(run):  # one started here stops now
                run["stopping"] = True
                self.send(run, signal.SIGINT)
                threading.Timer(6, self.send, args=(run, getattr(signal, "SIGTERM", signal.SIGINT))).start()
        return {"ok": True}

    def run_routine(self, key):
        """Runs one of the company's routines now, in the background (connect/routines.py)."""
        rows = (read(os.path.join(self.data, "feeds", "routines.json")) or {}).get("routines") or []
        row = next((r for r in rows if isinstance(r, dict) and isinstance(key, str) and ROUTINE.match(key) and r.get("id") == key), None)
        if not row:
            raise Refused("There's no such routine. Routines are listed under each floor in data/company.json.")
        try:
            proc = subprocess.Popen([sys.executable, ROUTINES, "--run", key], cwd=HERE, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, env=dict(os.environ, ARNHEIM_DATA=self.data), close_fds=True,
                                    start_new_session=hasattr(os, "setsid"))
        except OSError as error:
            raise Refused(f"It didn't start ({error.strerror or error}).")
        threading.Thread(target=proc.wait, daemon=True).start()  # so it leaves nothing behind when it ends
        return {"ok": True, "routine": one_line(row.get("label") or key, 60)}

    def prove(self, key):
        """Runs the conversation's floor's check again on its work, in the background (connect/prove.py)."""
        key = self.conversation(key)
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        talk = next((c for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id") == key), None)
        with self.lock:
            project = (talk or {}).get("project") or (self.runs.get(key) or {}).get("project")
        check = check_for(project, self.data) if project else None
        if not check:
            raise Refused('Its floor has no check to run. Give it one in data/company.json (docs/connect.md, "Done means proven").')
        try:
            proc = prove_later(project, self.data, also=key)
        except OSError as error:
            raise Refused(f"The check didn't start ({error.strerror or error}).")
        threading.Thread(target=proc.wait, daemon=True).start()  # so it leaves nothing behind when it ends
        return {"ok": True, "check": check["label"]}

    def allow_more(self, project):
        """Lets a floor's agents spend as much again as their budget, today."""
        company = read(os.path.join(self.data, "company.json")) or {}
        if not isinstance(project, str) or not budget.budget_of(company, project):
            raise Refused("That floor has no budget.")
        with self.lock:
            times = self.box.allow_more(project, budget.local_day())
        return {"ok": True, "project": project, "times": times + 1}

    # ---------- restore points ----------

    def restore(self, pid):
        """Puts a floor's files back as they were at a restore point (connect/restore.py), unless an agent sharing
        that folder is at work or waiting on you mid-turn. A restore point of how they are now is taken first, so
        this can be undone too."""
        if not isinstance(pid, str) or not restore.POINT.match(pid):
            raise Refused("That isn't a restore point.")
        point = next((p for p in restore.read_points(self.data) if p.get("id") == pid), None)
        if not point:
            raise Refused("That restore point isn't kept any more.")
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        asking = {row.get("key") for row in self.box.asks()}
        held = restore.busy(point, feed.get("conversations") or [], asking, self.data)
        if held:
            raise Refused(f"An agent on {' and '.join(held)} is at work or waiting on you, in the same folder. Let it finish or stop it first, then go back.")
        if not self.going_back.acquire(blocking=False):
            raise Refused("Going back to another restore point is under way. Try again in a moment.")
        try:
            done = restore.go_back(point, self.data)
        except ValueError as why:
            raise Refused(str(why))
        finally:
            self.going_back.release()
        return {"ok": True, **done}

    # ---------- the company's memory ----------

    def remember(self, text):
        """Adds a decision to data/memory.json. Every agent that starts from now is told it, and those at
        work are told it with your next message to them (connect/claude_code.py)."""
        text = " ".join(str(text or "").split())
        if not text:
            raise Refused("Say what to remember first.")
        if len(text) > MEMORY_TEXT:
            raise Refused(f"That's too long to remember: keep it under {MEMORY_TEXT} characters.")
        with self.lock:
            rows = memory(self.data)
            if any(row["text"].strip().lower() == text.lower() for row in rows):
                raise Refused("That's remembered already.")
            if len(rows) >= MEMORY_MOST:
                raise Refused(f"The memory holds {MEMORY_MOST} decisions. Forget one first.")
            row = {"id": "m-" + secrets.token_hex(4), "text": text, "at": time.time()}
            self.keep_memory(rows + [row])
        return row

    def forget(self, mid):
        with self.lock:
            rows = memory(self.data)
            kept = [row for row in rows if row.get("id") != mid]
            if len(kept) == len(rows):
                raise Refused("That isn't in the memory any more.")
            self.keep_memory(kept)
        return {"ok": True}

    def keep_memory(self, rows):
        write(os.path.join(self.data, "memory.json"), {
            "about": "The decisions every Claude Code agent in this company is told (docs/connect.md, \"Company memory\"). Yours to edit.",
            "memory": rows,
        })

    # ---------- the agents started here ----------

    def spawn(self, run, extra, text, answering=None):
        """Starts `claude -p` in the run's folder, with the words on stdin. Under the lock."""
        if run.get("agent") == "Codex":  # one carried on in Codex: started and resumed Codex's way
            return self.spawn_codex(run, text, resume=extra[1] if extra[:1] == ["--resume"] else None, answering=answering)
        os.makedirs(self.box.path("runs"), exist_ok=True)
        log = open(self.box.path("runs", run["key"] + ".log"), "ab")  # what Claude Code says went wrong, if anything
        args = self.claude + ["-p", "--output-format", "stream-json", "--verbose"] + extra
        try:
            proc = subprocess.Popen(args, cwd=run["folder"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=log,
                                    start_new_session=hasattr(os, "setsid"))
        except OSError as error:
            log.close()
            raise Refused(f"Claude Code didn't start ({error.strerror or error}). Is its claude command installed? ARNHEIM_CLAUDE can name another.")
        try:
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        run.update(state="working", pid=proc.pid, at=time.time(), stopping=False)
        self.runs[run["key"]] = run
        self.procs[run["key"]] = proc
        self.save(run)
        threading.Thread(target=self.follow, args=(run, proc, log, answering), daemon=True).start()

    def follow(self, run, proc, log, answering):
        """Reads what the agent says as it goes, and keeps its last words."""
        said = ""
        try:
            for raw in proc.stdout:
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if not isinstance(event, dict):
                    continue
                if event.get("type") == "assistant":
                    content = (event.get("message") or {}).get("content") or []
                    words = " ".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text").strip()
                    said = words or said
                elif event.get("type") == "result" and isinstance(event.get("result"), str):
                    said = event["result"] or said
        except (OSError, ValueError):
            pass
        finally:
            proc.wait()
            proc.stdout.close()
            log.close()
        with self.lock:
            run["state"] = "stopped" if run.get("stopping") else "done" if proc.returncode == 0 else "failed"
            run.update(said=one_line(said, 1200), at=time.time(), pid=None)
            if answering:
                run["answered"] = answering
            if self.procs.get(run["key"]) is proc:
                del self.procs[run["key"]]
            self.save(run)
        self.answered(run, answering, said)

    def answered(self, run, answering, said):
        """An agent started here has finished its turn: its last words answer what you sent it, if its hook didn't
        say so already."""
        if answering and said:
            try:
                self.lv.answered(run["key"], said)
            except Exception:
                pass

    # ---------- carrying on in Codex at a limit (connect/carry_on.py) ----------

    def carry_on(self, given):
        """Carries a conversation on in the other agent, Claude Code or Codex, when its plan's limit has run out or soon
        will: a new agent on the same floor, handed the page's hand-over. Once for each conversation."""
        try:
            return carry_on.start(self, given)
        except ValueError as why:
            raise Refused(str(why))

    def spawn_codex(self, run, text, resume=None, answering=None):
        """Starts Codex without a window (`codex exec --json`) in the run's folder, with the words on stdin, or carries its
        thread on with your next message. Codex's hooks show it on its floor, as any Codex conversation. Under the lock."""
        os.makedirs(self.box.path("runs"), exist_ok=True)
        log = open(self.box.path("runs", run["key"] + ".log"), "ab")  # what Codex says went wrong, if anything
        try:
            proc = subprocess.Popen(carry_on.codex_args(self.codex, resume), cwd=run["folder"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                    stderr=log, start_new_session=hasattr(os, "setsid"))
        except OSError as error:
            log.close()
            raise Refused(f"Codex didn't start ({error.strerror or error}). Is its codex command installed? ARNHEIM_CODEX can name another.")
        try:
            proc.stdin.write(text.encode("utf-8"))
            proc.stdin.close()
        except OSError:
            pass
        run.update(state="working", pid=proc.pid, at=time.time(), stopping=False, agent="Codex")
        self.runs[run["key"]] = run
        self.procs[run["key"]] = proc
        self.save(run)
        threading.Thread(target=self.follow_codex, args=(run, proc, log, answering), daemon=True).start()

    def follow_codex(self, run, proc, log, answering):
        """Reads Codex's events as it goes: its thread's id, which names the conversation, and its last words."""
        said = ""
        try:
            for raw in proc.stdout:
                try:
                    got = carry_on.codex_event(json.loads(raw))
                except ValueError:
                    continue
                if got and got[0] == "thread":
                    self.rekey(run, got[1])
                elif got:
                    said = got[1] or said
        except (OSError, ValueError):
            pass
        finally:
            proc.wait()
            proc.stdout.close()
            log.close()
        with self.lock:
            run["state"] = "stopped" if run.get("stopping") else "done" if proc.returncode == 0 else "failed"
            run.update(said=one_line(said, 1200), at=time.time(), pid=None)
            if answering:
                run["answered"] = answering
            if self.procs.get(run["key"]) is proc:
                del self.procs[run["key"]]
            self.save(run)
        self.answered(run, answering, said)

    def rekey(self, run, thread):
        """Codex names its thread once it starts: the run takes the key its hooks give that conversation, so the building
        shows it once, and stopping or talking to it there reaches this run."""
        key = carry_on.key_of(thread)
        with self.lock:
            old = run["key"]
            run["sid"] = thread
            if key != old and KEY.match(key) and key not in self.runs:
                proc = self.procs.pop(old, None)
                self.runs.pop(old, None)
                run["key"] = key
                self.runs[key] = run
                if proc is not None:
                    self.procs[key] = proc
                try:
                    os.replace(self.box.path("runs", old + ".log"), self.box.path("runs", key + ".log"))
                except OSError:
                    pass
                gone(self.box.path("runs", old + ".json"))
            self.save(run)

    def alive(self, run):
        proc = self.procs.get(run["key"])
        if proc is not None:
            return proc.poll() is None
        pid = run.get("pid")
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def send(self, run, sig):
        if not self.alive(run):
            return
        try:
            if hasattr(os, "killpg"):
                os.killpg(run["pid"], sig)  # it runs in a process group of its own, with its tools
            else:
                os.kill(run["pid"], sig)
        except OSError:
            pass

    def save(self, run):
        write(self.box.path("runs", run["key"] + ".json"), {k: v for k, v in run.items() if k != "stopping"})

    def load(self):
        """The agents started here before, including any still at work after a restart."""
        try:
            names = sorted(os.listdir(self.box.path("runs")))
        except OSError:
            return
        found = [run for run in (read(self.box.path("runs", n)) for n in names if n.endswith(".json")) if run and KEY.match(str(run.get("key")))]
        found.sort(key=lambda run: run.get("at") or 0, reverse=True)
        for run in found[KEEP_RUNS:]:
            gone(self.box.path("runs", run["key"] + ".json"))
            gone(self.box.path("runs", run["key"] + ".log"))
        for run in found[:KEEP_RUNS]:
            if run.get("state") == "working" and not self.alive(run):
                run.update(state="done", pid=None)
            self.runs[run["key"]] = run

    # ---------- what the requests may name ----------

    def floors(self):
        return floors_of(self.data)

    def working(self, key):
        """Whether a conversation the building knows is at work now: one started here that is still
        running, or one the Claude Code feed says is working."""
        with self.lock:
            run = self.runs.get(key)
            if run and self.alive(run):
                return True
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        return any(isinstance(c, dict) and c.get("id") == key and c.get("working") for c in feed.get("conversations") or [])

    def project_named(self, name):
        """The project of the floor with this label, id or project name in data/company.json, or None."""
        company = read(os.path.join(self.data, "company.json")) or {}
        for floor in company.get("floors") or []:
            if isinstance(floor, dict) and name and name in (floor.get("label"), floor.get("id"), floor.get("project")):
                return str(floor.get("project") or floor.get("label") or floor.get("id") or "")
        return None

    def project_of(self, key):
        """The project a conversation the building knows is on, or None."""
        with self.lock:
            run = self.runs.get(key)
            if run:
                return run.get("project")
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        talk = next((c for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id") == key), None)
        return (talk or {}).get("project")

    def conversation(self, key):
        """A conversation the building knows: in the Claude Code feed, or started here."""
        if not isinstance(key, str) or not KEY.match(key):
            raise Refused("No such conversation.")
        if key in self.runs:
            return key
        feed = read(os.path.join(self.data, "feeds", "claude-code.json")) or {}
        if any(isinstance(c, dict) and c.get("id") == key for c in feed.get("conversations") or []):
            return key
        raise Refused("That conversation has left the building.")

    @staticmethod
    def words(text):
        text = str(text or "").strip()
        if not text:
            raise Refused("Say something first.")
        if len(text) > MAX_TEXT:
            raise Refused(f"That's too long: keep it under {MAX_TEXT} characters.")
        return text
