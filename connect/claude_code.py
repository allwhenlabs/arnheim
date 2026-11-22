#!/usr/bin/env python3
"""Arnheim's Claude Code connector: a hook that shows each Claude Code conversation in the building.

OpenAI's Codex CLI has the same hooks, by the same names, and connect/codex.py hands each of its events
here marked as Codex's: everything below holds for a Codex conversation too, its edits (apply_patch) and
its plan (update_plan) included.

Claude Code runs it at the moments docs/connect.md lists, and hands it what happened as JSON on
stdin. It finds the floor whose "folder" (in data/company.json) holds the conversation's folder, and
keeps data/feeds/claude-code.json up to date for the page, which reads it every few seconds:

- a seat in that floor's Conversations room for each conversation, with someone in it while
  Claude works, and a blue light once Claude has finished and it is your turn;
- an amber desk while Claude waits for your permission or an answer, which the receptionist lists under
  "Needs you";
- a desk for each task on Claude's task list, someone at it while it is being done;
- what the conversation says if you stand at its seat on a walk: the last thing Claude said.

It keeps a title for each conversation (its own, or the first line of your first message), the
first sentences of the last thing Claude said, your latest message's first words and task titles,
all in data/, on this computer. Any trouble goes to data/feeds/claude-code.log, and Claude carries on.

It hands every conversation in the company's folders the company's how-tos for its floor as it starts
(data/company.json's "howtos", docs/data.md), to read before work one of them covers. It also hands it
the company's memory as it starts (data/memory.json:
the decisions you asked the building to remember), and one at work the decisions made since, with your
next message to it.

It counts what each conversation spends each day, in new tokens, from its own transcript. When a
floor's agents pass the floor's budget for the day (connect/budget.py), it stops the one at work at its
next step, once, and asks you in the building whether they may go on. Paused from the building, every
conversation stops at its next step, and a message you send one in Claude Code waits until you resume.

With a PreToolUse hook too, it takes a restore point of the project's files before the first file a
conversation changes after each message you send it, and before any command that deletes or overwrites
files in bulk, so you can go back from the building (connect/restore.py).

It keeps a short log of each day's moments for the building's replay: when each conversation started
work, which files it changed (as paths inside its floor's folder), what it asked, and when it finished
or stopped (data/feeds/history/, a file a day, kept for a week).

When two conversations change the same file within two hours, the one that just did is told who
else is changing it, so it can check their work first, and the building shows the pair.

When a conversation changes files and its floor names a check (docs/connect.md, "Done means proven"), it
starts that check in the background as the turn ends (connect/prove.py), and the building shows whether
the work is proven. On a floor with a review line, it holds the turn instead while the check and a reader
look at the work (connect/review.py), and sends it back to Claude with the reason if it isn't ready.

With control switched on (serve.py --control, and connect/control.py), it also hands Claude what you
say to it in the building, before its next step (PreToolUse, as added context: after a step it would sit in
the tool's output, which Claude rightly takes no instructions from), or as its turn ends; while the building is open, it shows a permission
Claude asks for there and waits a while for your answer; and it stops Claude when you ask. Otherwise
it prints nothing, so Claude Code goes on as if it weren't there. Standard library only.

Working beside your agents (docs/connect.md, "Work beside your agents"), each part a switch:

- it keeps each conversation's screen in data/live/ (connect/live.py): the step under way, the steps it
  finished, the lines it changed and its to-do list, and how each message you sent is getting on;
- a question Claude asks with its AskUserQuestion tool comes to the building first: while someone is using
  it, the hook waits a while for your answer and hands it back as the tool's answers (PreToolUse,
  permissionDecision "allow" with updatedInput, as Claude Code's hooks docs give for this tool); and a turn
  that ends with a question waits a while for your answer the same way, then goes on with it (Stop,
  "block"). With no answer, or nobody there, Claude asks in its own window as it always did, and the
  question waits as a card;
- a hold from the building keeps it before its next step, without ending its turn, handing over what you
  say, until you say carry on, ten minutes pass, or nobody has used the building for two minutes.
"""
import datetime
import hashlib
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import budget  # noqa: E402  (beside this file: what each conversation spends)
import control  # noqa: E402  (beside this file: what the building has for Claude Code)
import restore  # noqa: E402  (beside this file: restore points before an agent changes files)
import standing  # noqa: E402  (beside this file: commands you allow for good)
import usage  # noqa: E402  (beside this file: your plan's limits, for the forecast)
import handover  # noqa: E402  (beside this file: finished work, handed to the next agent on a floor)
import switches  # noqa: E402  (beside this file: each feature on or off, data/serve.json)
import carry_on  # noqa: E402  (beside this file: carrying a conversation on in the other agent at a limit)
import live  # noqa: E402  (beside this file: each conversation's screen, for this computer and paired phones)
import deputy  # noqa: E402  (beside this file: the chain of command and office hours)
import show  # noqa: E402  (beside this file: Show me, pictures of finished work)

DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
FEED = os.path.join(DATA, "feeds", "claude-code.json")
LOG = os.path.join(DATA, "feeds", "claude-code.log")
KEEP = 12 * 3600  # a conversation not heard from for this long has gone
ASKS = {"permission_prompt", "elicitation_dialog", "agent_needs_input"}  # Claude waits for you to decide
CHANGES = {"Edit", "MultiEdit", "Write", "NotebookEdit", "apply_patch"}  # tools that change files (apply_patch is Codex's): then its floor's check is due
AGENT = "arnheim_agent"  # set by another agent's connector on the events it hands on (connect/codex.py): who it is
NEW = "A new conversation"
# A prompt Claude Code was handed by something else, not typed by the person: a helper's report, another
# session's message, a notice. It is never "what you asked", and never a conversation's title.
HANDED = re.compile(r"^\s*<(?:agent-message|task-notification|side-sessions-event|system-reminder|ci-monitor-event|local-command-[\w-]+|command-[\w-]+)\b")
CLASH = 2 * 3600  # seconds: two conversations changing one file this close together may trip over each other
FILES_KEPT = 30
HISTORY = os.path.join(DATA, "feeds", "history")
HISTORY_DAYS = 7
HISTORY_MOST = 5000  # moments in a day at most
COUNT = {"PostToolUse", "Stop", "UserPromptSubmit", "SubagentStop", "SessionEnd", "PreCompact"}  # moments its spending is counted


def line(text, most):
    """One line of plain words, at most `most` characters, cut at a word."""
    text = " ".join(re.sub(r"```.*?```", " ", str(text or ""), flags=re.S).split())
    if len(text) <= most:
        return text
    cut = text.rfind(" ", 0, most - 1)
    return text[: cut if cut > most // 2 else most - 1].rstrip(" ,;:") + "…"


def sentences(text, most=300):
    """The first whole sentences of what Claude said, up to about `most` characters."""
    text = line(text, 4000)
    out = ""
    for part in re.findall(r"[^.!?]+[.!?]+[\"')\]]*\s*|[^.!?]+$", text):
        if out and len(out) + len(part) > most:
            break
        out += part
    return line(out or text, most)


def project_for(cwd):
    """The project of the floor whose folder holds cwd (the deepest, if folders nest), or None."""
    try:
        with open(os.path.join(DATA, "company.json"), encoding="utf-8-sig") as handle:
            company = json.load(handle)
    except (OSError, ValueError):
        return None
    here = os.path.realpath(os.path.expanduser(str(cwd or "")))
    best = None
    for floor in company.get("floors") or []:
        if not isinstance(floor, dict):
            continue
        folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
        for folder in folders if isinstance(folders, list) else []:
            root = os.path.realpath(os.path.expanduser(str(folder)))
            inside = here == root or here.startswith(root.rstrip(os.sep) + os.sep)
            if inside and (best is None or len(root) > len(best[0])):
                best = (root, floor.get("project") or floor.get("label"))
    return best[1] if best else None


class Lock:
    """One writer at a time: Claude Code runs hooks for several conversations at once."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.handle = open(self.path, "a")
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:  # Windows has no flock; a clash there costs one update at most
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()  # closing lets go of the lock


def key_of(event):
    return "cc-" + re.sub(r"[^A-Za-z0-9]", "", str(event["session_id"]))[:12]


def changed_paths(event):
    """The files a step changed, as the tool named them: Claude Code's edits name one, Codex's apply_patch
    names each file in its patch."""
    given = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    if event.get("tool_name") == "apply_patch":
        return control.patched(given)[:FILES_KEPT]
    path = str(given.get("file_path") or given.get("notebook_path") or "")
    return [path] if path else []


def change(event, feed, project, now, extra=None):
    """What this event changes in the feed's conversations and tasks. `extra` says what the
    building's control did: handed over a message (heard), had Claude go on rather than stop
    (going_on), stopped it (stopped), or asks for your permission (asking); or that the
    conversation was started from the building (started_here), so it stays when it ends."""
    extra = extra or {}
    name = event.get("hook_event_name")
    key = key_of(event)
    talks = [c for c in feed.get("conversations") or [] if isinstance(c, dict)]
    tasks = [t for t in feed.get("tasks") or [] if isinstance(t, dict)]
    def old(c):
        try:
            return now - float(c.get("at") or 0) > KEEP
        except (TypeError, ValueError):
            return True

    gone = {c.get("id") for c in talks if old(c)}
    ends = name == "SessionEnd" and not extra.get("started_here")  # one started from the building stays, to talk to
    if ends:
        gone.add(key)
    day = budget.local_day()
    budget.leave(feed, [c for c in talks if c.get("id") in gone], day)  # what they spent today still counts
    talks = [c for c in talks if c.get("id") not in gone]
    tasks = [t for t in tasks if t.get("session") not in gone]
    if ends:
        return talks, tasks

    talk = next((c for c in talks if c.get("id") == key), None)
    if talk is None:
        talk = {"id": key, "project": project, "title": NEW, "working": False, "check": False, "says": {}}
        back = budget.come_back(feed, key, day)
        if back:  # one that left earlier today: its spending goes on from where it was
            talk.update(spent={"day": day, "tokens": back.get("tokens") or 0}, read=back.get("read"))
        talks.append(talk)
    talk.update(project=project, at=now)
    if event.get(AGENT):
        talk["agent"] = str(event[AGENT])
    if event.get("session_title"):
        talk["title"] = line(event["session_title"], 70)
    ask = f"{key}-ask"

    def task(tid, **fields):
        found = next((t for t in tasks if t.get("id") == tid), None)
        if found is None:
            found = {"id": tid, "session": key, "project": project}
            tasks.append(found)
        found.update(fields)

    def drop(tid):
        tasks[:] = [t for t in tasks if t.get("id") != tid]

    if name == "SessionEnd":
        talk.update(working=False)
    elif name == "SessionStart" and event.get("source") in (None, "startup", "clear"):
        talk.update(working=False, check=False)
        talk.pop("compacted", None)  # a fresh start: nothing shortened yet
    elif name == "SessionStart" and event.get("source") == "compact":  # its conversation was shortened to fit
        talk["compacted"] = int(talk.get("compacted") or 0) + 1
    elif name == "UserPromptSubmit":
        said = "" if HANDED.match(str(event.get("prompt") or "")) else line(event.get("prompt"), 100)
        if talk["title"] == NEW and said:  # its first paragraph: your words, before a brief the building added (Done when, ...)
            talk["title"] = line(re.split(r"\n[ \t]*\n", str(event.get("prompt") or "").strip(), maxsplit=1)[0], 70)
        talk.update(working=True, check=False, says={"now": f'I\'m working on what you asked: "{said}".' if said else "I'm working on it."},
                    asked=said, asked_at=now)
        talk.pop("review", None)  # a new piece of work: the review line starts afresh
        drop(ask)
        if said and not talk.get("first"):  # what the conversation was for, for a hand-over at a limit (connect/carry_on.py)
            talk["first"] = line(event.get("prompt"), 200)
    elif name == "PostToolUse" and extra.get("stopped"):
        talk.update(working=False, check=True, says={"now": "I stopped, as you asked.", "next": "It's your turn now."})
        drop(ask)
    elif name == "PostToolUse":
        talk.update(working=True, check=False)
        drop(ask)
        given = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        if event.get("tool_name") in CHANGES:
            talk["changed"] = now
            files = [f for f in talk.get("files") or [] if isinstance(f, dict)]
            for path in changed_paths(event):  # which files it changed lately, for clashes
                where = inside(path, event.get("cwd"))
                files = [f for f in files if f.get("path") != where] + [{"path": where, "at": now}]
            talk["files"] = files[-FILES_KEPT:]
        if event.get("tool_name") == "TaskUpdate":  # its own task list: in progress, done or deleted
            tid = given.get("taskId") or given.get("task_id")
            state = given.get("status")
            if tid and state in ("completed", "deleted"):
                drop(f"{key}-t{tid}")
            elif tid and state in ("in_progress", "pending"):
                task(f"{key}-t{tid}", status="working" if state == "in_progress" else "open")
        elif event.get("tool_name") in ("TodoWrite", "update_plan"):  # the older to-do list, or Codex's plan: the whole list each time
            tasks[:] = [t for t in tasks if not str(t.get("id", "")).startswith(f"{key}-todo")]
            listed = given.get("todos") if event.get("tool_name") == "TodoWrite" else given.get("plan")
            for i, todo in enumerate(listed if isinstance(listed, list) else []):
                if isinstance(todo, dict) and todo.get("status") in ("pending", "in_progress"):
                    task(f"{key}-todo{i}", title=line(todo.get("content") or todo.get("step"), 90),
                         status="working" if todo["status"] == "in_progress" else "open")
    elif name == "Notification":
        kind = event.get("notification_type")
        if kind in ASKS:
            message = line(event.get("message") or "Claude is waiting for you.", 90)
            talk.update(working=False, check=True)
            talk["says"] = {**talk.get("says", {}), "needs": f"{message}."}
            if kind == "permission_prompt":  # a permission, not a question: pings name only its kind (connect/ping.py)
                talk["says"].setdefault("permission", "")
            else:
                talk["says"].pop("permission", None)
            task(ask, title=f"{talk['title']}: {message}", status="needs_you", note=message)
        elif kind == "idle_prompt":
            talk.update(working=False, check=True)
    elif name == "PermissionRequest" and extra.get("standing"):  # a command you allowed for good: no wait
        talk.update(working=True, check=False)
        talk["asked_for"] = {"tool": str(event.get("tool_name") or ""), "what": extra.get("asking"), "standing": True}
    elif name == "PermissionRequest":
        message = line(f"I'm waiting for your permission: {extra.get('asking') or event.get('tool_name') or 'a tool'}", 140)
        talk["asked_for"] = {"tool": str(event.get("tool_name") or ""), "what": extra.get("asking"),
                             "command": standing.command_in(str(event.get("tool_name") or ""), event.get("tool_input"))}
        talk.update(working=False, check=True)
        talk["says"] = {**talk.get("says", {}), "needs": f"{message}.", "permission": str(event.get("tool_name") or "")}
        task(ask, title=line(f"{talk['title']}: {message}", 120), status="needs_you", note=message)
    elif name == "Stop" and extra.get("going_on"):  # it has your message to answer first
        said = sentences(event.get("last_assistant_message"))
        talk.update(working=True, check=False)
        if said:
            talk["says"] = {"now": said}
        drop(ask)
    elif name == "Stop":
        said = sentences(event.get("last_assistant_message"))
        talk.update(working=bool(event.get("background_tasks")), check=True,
                    says={"now": said or "I've finished for now.", "next": "It's your turn now."})
        if talk.get("heard"):  # what it just said answers your message
            talk["answered"] = talk.pop("heard")
        talk["stopped"] = now
        drop(ask)
    elif name == "StopFailure":  # Claude Code: the turn ended on an error from the API instead of Stop, a plan's limit among them
        error = line(event.get("last_assistant_message") or event.get("error") or "an error", 160)
        said = sentences(carry_on.last_words(event.get("transcript_path")))
        talk.update(working=False, check=True, stopped=now, says={"now": said or f"I stopped: {error.rstrip('.')}.", "next": "It's your turn now."})
        if event.get("error") == "rate_limit":  # the page offers to carry it on in Codex (src/carry-on.js)
            talk["limit"] = {"at": now, "said": error}
        drop(ask)
    elif name == "Interrupt":  # Codex: you stopped it there
        talk.update(working=False, check=True, says={"now": "I stopped, as you asked.", "next": "It's your turn now."})
        drop(ask)
    elif name == "TaskCreated" and event.get("task_id"):
        task(f"{key}-t{event['task_id']}", title=line(event.get("task_subject") or "A task", 90), status="open")
    elif name == "TaskCompleted" and event.get("task_id"):
        drop(f"{key}-t{event['task_id']}")
    if name in ("PostToolUse", "UserPromptSubmit", "Stop", "Interrupt", "SessionStart"):
        talk.pop("asked_for", None)  # what it asked for was run, or the moment for it has passed
    if extra.get("heard"):
        talk["heard"] = extra["heard"]
    if extra.get("memory_at"):
        talk["memory_at"] = extra["memory_at"]
    return talks, tasks


def read_feed(path=None):
    try:
        with open(path or FEED, encoding="utf-8") as handle:
            feed = json.load(handle)
    except (OSError, ValueError):
        feed = {}
    return feed if isinstance(feed, dict) else {}


def edit_feed(edit, path=None, about=None):
    """Changes the feed, one writer at a time: edit(feed) gives the new conversations and tasks, or None
    to leave it as it is. Another connector's feed can be named by `path`, with its own `about`."""
    path = path or FEED
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with Lock(path + ".lock"):
        feed = read_feed(path)
        out = edit(feed)
        if out is None:
            return
        talks, tasks = out
        out = {
            "about": about or "Kept up to date by connect/claude_code.py, from Claude Code's hooks (docs/connect.md). Safe to delete.",
            "conversations": talks,
            "tasks": tasks,
        }
        if isinstance(feed.get("ended"), dict):  # today's spending by conversations that have left (connect/budget.py)
            out["ended"] = feed["ended"]
        part = f"{path}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(out, handle, ensure_ascii=False, indent=1)
        os.replace(part, path)  # whole, so the page never reads half a file


def update(event, extra=None):
    """Keeps the feed up to date with this event. What the building's rules then ask of Claude Code:
    {"stop": why} to stop at this step (a budget passed, or every agent paused), or {}."""
    verdict = {}
    if not event.get("session_id"):
        return verdict
    project = project_for(event.get("cwd"))
    if not project and not os.path.isfile(FEED):
        return verdict  # a conversation in a folder no floor names: not part of this company

    def edit(feed):
        where = project
        if not where:  # one already in the building that has moved out of its folder stays where it was
            seat = next((c for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
            where = seat and seat.get("project")
            if not where:
                return None
        before = next((dict(c) for c in feed.get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
        talks, tasks = change(event, feed, where, time.time(), extra)
        talk = next((c for c in talks if c.get("id") == key_of(event)), None)
        asked = (before or {}).get("asked_for")
        ran = standing.command_in(str(event.get("tool_name") or ""), event.get("tool_input"))
        if event.get("hook_event_name") == "PostToolUse" and isinstance(asked, dict) and not asked.get("standing") \
                and asked.get("tool") == event.get("tool_name") and ran and asked.get("command") == ran:
            try:
                standing.record(DATA, where, asked["tool"], ran)  # you allowed this exact command, here or in the agent: it ran
            except Exception as error:  # remembering it never costs the feed
                note(error)
        if talk is not None:
            weigh(event, talk, talks, tasks, where, extra or {}, verdict, feed.get("ended"))
        if event.get("hook_event_name") == "Stop" and talk is not None and not (extra or {}).get("going_on"):
            hand_on(talk, where)
        try:
            if talk is not None or before is not None:  # one that ended has left the feed: log it as it was
                said = dict(extra or {})
                was = before or {}
                if was.get("check") and (was.get("says") or {}).get("needs") and talk is not None and talk.get("working"):
                    said["answered"] = True  # it waited on you, and went on: the wait ends here (src/waiting.js)
                day = budget.local_day()
                spent = {p: budget.spent_today(talks, p, day, feed.get("ended"))
                         for p in {c.get("project") for c in talks if c.get("project")} | {where}}
                log(event, talk if talk is not None else before, where, said, verdict, spent)
        except Exception as error:  # the replay's trouble never costs the feed
            note(error)
        return talks, tasks

    edit_feed(edit)
    return verdict


def hand_on(talk, project):
    """As a turn ends that changed files since your last message: a few lines of it, for the next agent to start
    on its floor (connect/handover.py)."""
    if not switches.on("handovers", DATA):
        return
    try:
        since = float(talk.get("asked_at") or 0)
        if not talk.get("changed") or float(talk["changed"]) < since:
            return
        files = [f.get("path") for f in talk.get("files") or [] if isinstance(f, dict) and float(f.get("at") or 0) >= since]
        handover.note(DATA, project, talk.get("id"), talk.get("title"), talk.get("asked"), (talk.get("says") or {}).get("now"),
                      [f for f in files if f], talk.get("agent") or "Claude Code")
    except Exception as error:  # the hand-over's trouble never costs the feed
        note(error)


def handed(event):
    """What a conversation starting afresh is handed of the others' finished work on its floor, or None."""
    if event.get("source") not in (None, "startup", "clear") or not switches.on("handovers", DATA):
        return None
    project = floor_of(event)
    if not project:
        return None
    talks = {c.get("id"): c for c in read_feed().get("conversations") or [] if isinstance(c, dict)}
    return handover.told(DATA, project, key_of(event), lambda k: ((talks.get(k) or {}).get("proof") or {}).get("state"))


def moment(event, talk, extra, verdict):
    """What this event was, for the day's replay: (kind, words), or None for nothing worth keeping."""
    name = event.get("hook_event_name")
    if verdict.get("stop") or extra.get("stopped") or name == "Interrupt":
        return "stopped", (talk.get("says") or {}).get("now") or "It stopped."
    if name == "UserPromptSubmit" and not extra.get("paused_prompt"):
        said = line(event.get("prompt"), 80)
        return "working", f'You asked: "{said}"' if said else "It started work."
    if name == "PostToolUse" and event.get("tool_name") in CHANGES:
        paths = [inside(p, event.get("cwd")) for p in changed_paths(event)]
        more = f" and {len(paths) - 1} more" if len(paths) > 1 else ""
        return "changed", paths[0] + more if paths else "a file"
    if name in ("PermissionRequest", "Notification") and (talk.get("says") or {}).get("needs"):
        return "asked", talk["says"]["needs"]
    if name == "Stop" and not extra.get("going_on"):
        return "finished", (talk.get("says") or {}).get("now") or "It finished."
    if name == "SessionEnd":
        return "left", "The conversation ended."
    if extra.get("answered"):
        return "answered", "It went on."
    return None


def inside(path, cwd):
    """A changed file as a path inside the floor's folder, never this computer's own folders."""
    folder = os.path.realpath(os.path.expanduser(str(cwd or "")))
    full = os.path.realpath(os.path.join(folder, os.path.expanduser(path)))
    if full.startswith(folder.rstrip(os.sep) + os.sep):
        return os.path.relpath(full, folder)
    return os.path.basename(full)


def log(event, talk, project, extra, verdict, spent=None):
    """Adds this event's moment to today's history, under the feed's lock, with what each floor's agents
    have spent today so far (for the weekly report, src/weekly.js)."""
    found = moment(event, talk, extra, verdict)
    if not found:
        return
    add_moment(talk, project, *found, spent=spent)


def add_moment(talk, project, kind, what, spent=None):
    """Adds a moment to today's history, for the replay. Any connector can (connect/agents.py). `spent`, tokens
    by project, keeps the day's highest for each."""
    now = time.time()
    day = budget.local_day()
    path = os.path.join(HISTORY, day + ".json")
    try:
        with open(path, encoding="utf-8") as handle:
            kept = json.load(handle)
        rows = kept.get("moments") or []
        had = kept.get("spent") if isinstance(kept.get("spent"), dict) else {}
    except (OSError, ValueError, AttributeError):
        rows, had = [], {}
    spent_now = dict(had)
    for p, tokens in (spent or {}).items():
        if isinstance(p, str) and isinstance(tokens, int) and tokens > (had.get(p) if isinstance(had.get(p), int) else -1):
            spent_now[p] = tokens
    key = talk.get("id")
    if kind == "changed" and any(r.get("key") == key and r.get("kind") == "changed" and r.get("what") == what and now - r.get("at", 0) < 300
                                 for r in rows[-40:]):
        return  # the same file again within five minutes: once is enough
    rows = (rows + [{"at": round(now, 1), "key": key, "project": project, "title": talk.get("title"), "kind": kind, "what": line(what, 160)}])[-HISTORY_MOST:]
    os.makedirs(HISTORY, exist_ok=True)
    part = f"{path}.{os.getpid()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump({"about": "The day's moments, for the building's replay and its history (docs/connect.md, \"Replay the day\"). Safe to delete.",
                   "moments": rows, "spent": spent_now}, handle, ensure_ascii=False)
    os.replace(part, path)
    oldest = (datetime.date.today() - datetime.timedelta(days=HISTORY_DAYS)).isoformat()
    for name in os.listdir(HISTORY):  # a week is kept
        if name.endswith(".json") and name[:10] < oldest:
            try:
                os.remove(os.path.join(HISTORY, name))
            except OSError:
                pass


def clash(talk, talks, project, now, mine=None):
    """The other conversations on this floor that changed a file this one just changed (`mine`, the files
    changed in this step, or else the last file it changed), within CLASH seconds: [(their title, the file)]."""
    files = talk.get("files") or []
    if not mine:
        mine = [files[-1].get("path")] if files and isinstance(files[-1], dict) and files[-1].get("path") else []
    out = []
    for c in talks:
        if c is talk or c.get("project") != project:
            continue
        for f in c.get("files") or []:
            if isinstance(f, dict) and f.get("path") in mine and now - float(f.get("at") or 0) < CLASH:
                out.append((c.get("title") or "another conversation", f["path"]))
    return out


def halt(talk, words):
    talk.update(working=False, check=True, says={"now": words, "next": "It's your turn now."})


def weigh(event, talk, talks, tasks, project, extra, verdict, ended=None):
    """What the conversation has spent today, its floor's budget, and every agent paused (connect/budget.py)."""
    name = event.get("hook_event_name")
    day = budget.local_day()
    if event.get("transcript_path") and name in COUNT:
        said = {}
        spent, talk["read"] = budget.new_tokens(event["transcript_path"], talk.get("read"), said)
        if said and event.get(AGENT) == "Codex":  # its plan's limits, as its record last said (connect/usage.py)
            try:
                usage.keep("Codex", usage.from_codex(said), DATA)
            except Exception as error:
                note(error)
        had = talk.get("spent") if isinstance(talk.get("spent"), dict) and talk["spent"].get("day") == day else {}
        talk["spent"] = {"day": day, "tokens": int(had.get("tokens") or 0) + spent.get(day, 0)}
    if extra.get("paused_prompt"):
        halt(talk, "Every agent is paused from the building. Resume them there, then send your message again.")
        return
    box = control.Box(DATA)
    tid = "budget-" + re.sub(r"[^A-Za-z0-9]+", "-", project).strip("-").lower()
    try:
        with open(os.path.join(DATA, "company.json"), encoding="utf-8-sig") as handle:
            per_day = budget.budget_of(json.load(handle), project)
    except (OSError, ValueError):
        per_day = None
    if not switches.on("budget", DATA):
        per_day = None  # the brake is switched off: nothing stops for a budget, nor asks
    limit = per_day * (1 + box.allowances(day).get(project, 0)) if per_day else None
    used = budget.spent_today(talks, project, day, ended)
    if not limit or used < limit:
        tasks[:] = [t for t in tasks if t.get("id") != tid]  # under budget again: nothing to ask
    if name == "PostToolUse" and event.get("tool_name") in CHANGES and switches.on("clash", DATA):
        others = clash(talk, talks, project, time.time(), [inside(p, event.get("cwd")) for p in changed_paths(event)])
        if others:
            who = ", ".join(f'"{title}"' for title, _ in others[:3])
            verdict["warn"] = (f"Arnheim, the building, saw that {who} also changed {others[0][1]} in the last two hours, in another "
                               "conversation. Look at what changed there before going on, so you don't undo each other's work.")
    if name == "PostToolUse" and talk.pop("heard_before_step", None):
        return  # your message went in just before this step: it answers you first, and stops at a later step if it must
    if name != "PostToolUse" or extra.get("heard") or extra.get("stopped"):
        return  # it stops only between steps, and never instead of handing over your message
    paused = box.paused()
    if paused and talk.get("paused") != paused:
        talk["paused"] = paused
        halt(talk, "I stopped: every agent is paused from the building.")
        verdict["stop"] = "Paused from Arnheim, the building: every agent is paused until the person you work for resumes them there."
    elif limit and used >= limit and talk.get("braked") != limit:
        talk["braked"] = limit
        halt(talk, f"I stopped: {project}'s agents have used today's budget.")
        tasks[:] = [t for t in tasks if t.get("id") != tid] + [{
            "id": tid, "project": project, "budget": project, "status": "needs_you",
            "title": f"{project}'s agents have used today's budget",
            "note": f"{budget.tokens(used)} new tokens of {budget.tokens(limit)}. Let them go on, or leave them until tomorrow.",
        }]
        verdict["stop"] = (f"Stopped by Arnheim, the building: {project}'s agents have used today's budget of {budget.tokens(limit)} "
                           "new tokens. Wait until the person you work for lets you go on.")


def due(talk):
    """Whether a conversation changed files that no check has covered since."""
    proof = talk.get("proof") if isinstance(talk.get("proof"), dict) else {}
    try:
        return float(talk.get("changed") or 0) > float(proof.get("at") or 0)
    except (TypeError, ValueError):
        return False


def prove(event):
    """As a turn ends: if the conversation changed files since its floor's check last ran, starts the
    check in the background (connect/prove.py). Claude Code doesn't wait for it."""
    if not switches.on("checks", DATA):
        return
    try:
        talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
        if talk and due(talk) and control.check_for(talk.get("project"), DATA):
            control.prove_later(talk["project"], DATA)
    except Exception as error:  # a check that can't start never troubles Claude Code
        note(error)


def edit_talk(event, change_it):
    """Changes one conversation in the feed: change_it(talk) under the feed's lock."""
    def edit(feed):
        talks = [c for c in feed.get("conversations") or [] if isinstance(c, dict)]
        talk = next((c for c in talks if c.get("id") == key_of(event)), None)
        if talk is None:
            return None
        change_it(talk)
        return talks, [t for t in feed.get("tasks") or [] if isinstance(t, dict)]
    edit_feed(edit)


def restore_point(event):
    """Before an agent changes files: a restore point (connect/restore.py), once after each message you send
    it, and before every command that deletes or overwrites files in bulk. Tried once a turn, so a folder
    that isn't in git, or one too big to save quickly, costs nothing more after the first try."""
    tool = event.get("tool_name")
    given = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    bulk = tool == "Bash" and restore.risky(given.get("command"))
    if (tool not in CHANGES and not bulk) or not switches.on("restore", DATA):
        return None
    project = project_for(event.get("cwd"))
    if not project:
        return None  # not this company's work
    key = key_of(event)
    talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key), None) or {}

    def number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0
    if not bulk and talk.get("restore_at") and number(talk.get("restore_at")) >= number(talk.get("asked_at")):
        return None  # one already since your last message
    asked = talk.get("asked")
    why = f"before: {line(given.get('command'), 70)}" if bulk else (f'before changing files for "{asked}"' if asked else "before changing files")
    now = time.time()
    try:
        return restore.take(event.get("cwd"), why, key=key, project=project, title=talk.get("title") or NEW, data=DATA, now=now)
    finally:
        edit_talk(event, lambda t: t.update(restore_at=round(now, 1)))


def review(event):
    """As a turn ends on a floor with a review line (connect/review.py): holds it while the floor's check and
    the reader look at what changed. What Claude Code hears back: the work sent back with the reason, or None,
    when it passed, failed as often as allowed (it reaches you anyway), or the floor has no line."""
    if not switches.on("review", DATA):
        return None
    try:
        import review as line  # noqa: E402  (beside this file; only when a turn ends)
        talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
        project = talk and talk.get("project")
        floor = project and line.floor_of(project, DATA)
        given = line.review_of(floor)
        if not given or not line.due(talk):
            return None
        check = control.check_of(floor)
        now = time.time()
        said = dict(talk.get("says") or {})
        before = dict(talk.get("review") or {}) if isinstance(talk.get("review"), dict) else {}
        until = now + (check["timeout"] if check else 0) + (given["timeout"] if given["read"] else 0)
        # who reads it, named on the page while it waits: Codex for Claude Code's work, and the other way round
        reads = {"reviewer": line.reviewer(given, line.writer_of(event, talk))[0]} if given["read"] else {}

        def held(t):
            t.update(working=True, check=False, says={"now": "The review line is checking my work before it reaches you."},
                     review={**before, "state": "reviewing", "at": now, "until": until, **reads})
            if check:
                t["proof"] = {"state": "checking", "check": check["label"], "at": now, "until": now + check["timeout"]}
        edit_talk(event, held)
        try:
            result = line.run(event, talk, project, DATA)
        except Exception as error:  # noted, and the work reaches you unreviewed rather than stuck
            note(error)
            result = None
        if result is None:
            result = {"state": "error", "by": "The review line", "said": "It met an error (see data/feeds/claude-code.log).", "at": now}
        why = result.get("why") or ""

        def done(t):
            t["review"] = {k: result[k] for k in ("state", "by", "said", "why", "times", "most", "at", "reviewer", "writer") if result.get(k) not in (None, "")}
            t["review"]["done"] = time.time()
            if result.get("proof"):
                t["proof"] = result["proof"]
            if result.get("tokens"):
                day = budget.local_day()
                had = t.get("spent") if isinstance(t.get("spent"), dict) and t["spent"].get("day") == day else {}
                t["spent"] = {"day": day, "tokens": int(had.get("tokens") or 0) + int(result["tokens"])}
            if result["state"] == "sent back":
                t.update(working=True, check=False, says={"now": f"The review line sent my work back, so I'm fixing it: {why.splitlines()[0] if why else ''}"})
                add_moment(t, project, "working", f"The review line sent it back: {why.splitlines()[0] if why else ''}")
            else:
                t.update(working=False, check=True, says=said)
                if result["state"] == "passed":
                    add_moment(t, project, "finished", f"It passed the review line ({result.get('by')}).")
                elif result["state"] == "failed":
                    add_moment(t, project, "finished", f"It reached you after failing the review line: {why.splitlines()[0] if why else ''}")
        edit_talk(event, done)
        return {"decision": "block", "reason": line.sent_back(result)} if result["state"] == "sent back" else None
    except Exception as error:  # the review line's trouble never keeps Claude from finishing
        note(error)
        return None


def note(error):
    """Trouble goes to the log, never to Claude Code."""
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        mode = "w" if os.path.isfile(LOG) and os.path.getsize(LOG) > 100_000 else "a"
        with open(LOG, mode, encoding="utf-8") as handle:
            handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {type(error).__name__}: {error}\n")
    except OSError:
        pass


def keep(event, extra=None):
    try:
        return update(event, extra)
    except Exception as error:  # the feed's trouble never costs Claude your message or answer
        note(error)
        return {}


def remembered(event, name):
    """The company's memory to hand this conversation now, as (words, when), or None: all of it as a
    conversation in the company's folders starts (or starts again after its context was compacted), and
    what was decided since it was last told when you send it a message."""
    if name not in ("SessionStart", "UserPromptSubmit") or not switches.on("memory", DATA):
        return None
    rows = control.memory(DATA)
    if not rows:
        return None
    talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
    if not project_for(event.get("cwd")) and not talk:
        return None  # not this company's work
    now = time.time()
    if name == "UserPromptSubmit":
        try:
            since = float((talk or {}).get("memory_at") or 0)
        except (TypeError, ValueError):
            since = 0
        rows = [row for row in rows if isinstance(row.get("at"), (int, float)) and row["at"] > since] if since else rows
        if not rows:
            return None
        return control.told(rows, new=bool(since)), now
    return control.told(rows), now


HOWTO_FILE = re.compile(r"^(?:[\w-]+/)*[\w-]+\.md$")
HOWTOS_TOLD = 20


def shelf(event):
    """The company's how-tos for this conversation's floor, and those for every floor, as an agent is handed them
    as it starts: each title with its file, to read before work it covers. None if there are none."""
    project = project_for(event.get("cwd"))
    if not project or not switches.on("howtos", DATA):
        return None
    try:
        with open(os.path.join(DATA, "company.json"), encoding="utf-8-sig") as handle:
            company = json.load(handle)
    except (OSError, ValueError):
        return None
    home = os.path.realpath(DATA)
    rows = []
    for item in company.get("howtos") or [] if isinstance(company, dict) else []:
        if not isinstance(item, dict) or item.get("project") not in (None, "", project):
            continue
        name, title = str(item.get("file") or ""), line(item.get("title"), 80)
        path = os.path.realpath(os.path.join(home, name))
        if title and HOWTO_FILE.match(name) and path.startswith(home + os.sep) and os.path.isfile(path):
            rows.append(f'"{title}" ({path})')
    if not rows:
        return None
    return ("The people you work for keep how-tos for their own ways of doing things, in Arnheim, the building that shows "
            "their company's work. Before you do something one of them covers, read it and follow it: " + "; ".join(rows[:HOWTOS_TOLD]) + ".")


def floor_of(event):
    """The floor a conversation is on: its folder's, or where it already sits in the building."""
    project = project_for(event.get("cwd"))
    if project:
        return project
    seat = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
    return seat.get("project") if seat else None


# ---------- working beside your agents (docs/connect.md, "Work beside your agents") ----------

def mark(said):
    """Stands for what an agent last said, without keeping it."""
    return hashlib.sha256(str(said or "").encode("utf-8", "replace")).hexdigest()[:16] if said else None


def last_said(event):
    """The last thing the agent said, from its transcript, mid-turn: Claude Code's own (Codex's reads as nothing)."""
    path = event.get("transcript_path")
    return carry_on.last_words(path) if isinstance(path, str) and path else ""


def watch(event):
    """Keeps the conversation's screen in the building up to date (connect/live.py), with Look over their shoulder
    on: the step under way, each step finished with its changes, waiting on you, finished. With Replies straight
    away on, what it said since it was handed your messages answers them."""
    name = event.get("hook_event_name")
    shoulder, replies = switches.on("live", DATA), switches.on("replies", DATA)
    if not shoulder and not replies:
        return
    key = key_of(event)
    lv = live.Live(DATA)
    doc = lv.read(key)
    if replies and doc and name in ("PreToolUse", "PostToolUse") and any(
            isinstance(m, dict) and m.get("state") == "taken" for m in doc.get("messages") or []):
        said = last_said(event)
        lv.replied(key, said, mark(said))
    if name == "Stop" and replies and doc:
        lv.answered(key, event.get("last_assistant_message"))  # its last words answer what it was handed
    if not shoulder:
        return
    project = project_for(event.get("cwd")) or (doc or {}).get("project")
    if not project:
        return  # not this company's work
    agent = event.get(AGENT) or "Claude Code"
    if name == "PreToolUse":
        lv.begin(event, project, agent)
    elif name == "PostToolUse":
        lv.finish(event, project, agent)
    elif name == "UserPromptSubmit":
        lv.moment(key, "working", "thinking", "Thinking about what you asked", project, agent, asking=None, hold=None)
    elif name == "PermissionRequest":
        lv.moment(key, "waiting", "waiting", f"Waiting for your permission: {control.describe(str(event.get('tool_name') or 'a tool'), event.get('tool_input'))}",
                  project, agent)
    elif name == "Notification" and event.get("notification_type") in ASKS:
        lv.moment(key, "waiting", "waiting", "Waiting for you in my own window", project, agent)
    elif name == "Stop":
        lv.moment(key, "finished", None, None, project, agent)
    elif name in ("StopFailure", "Interrupt"):
        lv.moment(key, "stopped", None, None, project, agent)
    elif name == "SessionEnd":
        lv.moment(key, "ended", None, None, project, agent, asking=None)
    elif name in ("TaskCreated", "TaskCompleted") and event.get("task_id"):
        lv.todo_event(key, event["task_id"], event.get("task_subject"), done=name == "TaskCompleted", project=project, agent=agent)


def took(event, rows):
    """Your messages were handed to the agent: on its screen they show as taken, and when."""
    if not rows or not switches.on("replies", DATA):
        return
    try:
        said = last_said(event)
        live.Live(DATA).taken(key_of(event), [row.get("id") for row in rows], mark(said))
    except Exception as error:  # the screen's trouble never costs the message
        note(error)


def heard_now(event, rows):
    """The feed: the conversation has your message, so its next words answer it. Handed over before a step, the
    budget's brake waits a step, so the agent can answer you before it stops (weigh)."""
    if rows:
        took(event, rows)
        before = {"heard_before_step": True} if event.get("hook_event_name") == "PreToolUse" else {}
        edit_talk(event, lambda t: t.update(heard=rows[-1].get("id"), **before))


def kept_questions(box):
    """Questions are kept for the building only where control has been used on this computer (data/control/)."""
    return os.path.isdir(box.root)


def seat_title(event):
    talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
    return (talk or {}).get("title") or NEW


# Why a step waits while the person holds an agent: their words come beside it as added context (see hold_here).
HELD_REASON = "Not run yet: the person you are working for is holding you here from Arnheim, the building. Read their words, given with this."


def stop_now(event, box, before_step=False):
    """Stopped from the building while it was held or asked: it stops now. Before a step, Codex, which takes no
    continue: false there, has the step turned down and stops at its next one."""
    reason = "Stopped from Arnheim, the building."
    key = key_of(event)
    deny = {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": reason}
    if before_step and event.get(AGENT) == "Codex":
        box.stop(key)
        return {"hookSpecificOutput": deny}
    box.stopping(key)  # spent here
    edit_talk(event, lambda t: halt(t, "I stopped, as you asked."))
    out = {"continue": False, "stopReason": reason}
    if before_step:  # continue: false alone doesn't stop the step about to run (Claude Code's hooks docs)
        out["hookSpecificOutput"] = deny
    return out


def clean_questions(given):
    """AskUserQuestion's questions as the building shows them, secrets hidden and cut to size, in their order."""
    out = []
    for q in given if isinstance(given, list) else []:
        if not isinstance(q, dict) or not isinstance(q.get("question"), str) or not q["question"].strip():
            return []
        options = [{"label": live.clean(o.get("label"), 80), "description": live.clean(o.get("description"), 200)}
                   for o in q.get("options") or [] if isinstance(o, dict) and isinstance(o.get("label"), str)][:8]
        out.append({"question": live.clean(q["question"], 300), "header": live.clean(q.get("header"), 40), "options": options,
                    "multiSelect": q.get("multiSelect") is True})
    return out[:6]


def ask_question(event, box):
    """Claude Code's AskUserQuestion, caught before it shows: the question and its choices go to the building, and
    while someone is using it the hook waits a while for your answer there. The answer goes back as Claude Code's
    hooks docs give for this tool: permissionDecision "allow" with updatedInput, its questions and an "answers"
    object from each question to the answer. Otherwise, or with no answer in time, Claude asks in its own window as
    it always did, and the question waits as a card in the building."""
    if not switches.on("questions", DATA) or not kept_questions(box):
        return None
    project = floor_of(event)
    given = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    shown = clean_questions(given.get("questions"))
    if not project or not shown or len(shown) != len(given.get("questions") or []):
        return None
    key = key_of(event)
    decided, urgent = chain_of_command(event, box, project, "choices", shown, given)  # settled already, or you are away
    if decided:
        return decided
    watched = box.watched()
    until = time.time() + control.wait_seconds() if watched else None
    qid = box.question(key, "choices", shown[0]["question"], shown, until,
                       {"project": project, "agent": event.get(AGENT) or "Claude Code", "title": seat_title(event), "urgent": urgent})
    if switches.on("live", DATA):
        live.Live(DATA).moment(key, "asking" if watched else "waiting", "ask", f"Asking you: {shown[0]['question']}", project,
                               asking={"id": qid, "kind": "choices", "text": shown[0]["question"]})
    if not watched:
        return None
    how, got = control.await_question(box, qid, key, until)
    late = box.settle(qid, "window" if how is None else "answered")
    if how is None and late:
        how, got = "answer", late
    original = [q["question"] for q in given["questions"]]
    if how == "words":
        heard_now(event, got)
        got = {"text": "; ".join(control.one_line(row.get("text"), control.MAX_TEXT) for row in got)}
    if how in ("answer", "words"):
        if isinstance(got.get("answers"), dict):  # keyed by the questions as shown: back to Claude's own words
            answers = {original[i]: str(got["answers"].get(q["question"], "")) for i, q in enumerate(shown)}
        elif len(original) == 1:
            answers = {original[0]: control.one_line(got.get("text"), control.MAX_TEXT)}  # as if typed under "Other"
        else:  # several questions, one answer in their own words: it stands for each (never as a hook error's reason)
            said = control.one_line(got.get("text"), control.MAX_TEXT)
            answers = {question: said for question in original}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                       "updatedInput": {**given, "answers": answers}}}
    if how == "stop":
        return stop_now(event, box, before_step=True)
    return None


# A sentence ends at . ! or ? before a space or the end: a dot inside colour.txt or v1.2 doesn't end one. One pass,
# each character taken by one branch, so no backtracking however long the words.
SENTENCE = re.compile(r"(?:[^.!?\n]|[.!?](?=[^\s.!?]))+[.!?]*")


def asked_in(text):
    """The question a turn ended with: the sentences ending in a question mark in its last two paragraphs (code left
    out, and a ? inside an address isn't one), as (the question, those paragraphs for context), or None."""
    text = re.sub(r"```.*?```", " ", str(text or "")[-6000:], flags=re.S).strip()
    paragraphs = [p for p in re.split(r"\n[ \t]*\n", text) if p.strip()][-2:]
    found = []
    for p in paragraphs:
        for m in SENTENCE.finditer(p):
            said, after = m.group(0).strip(" \t*_>-"), p[m.end():m.end() + 1]
            said = re.sub(r"\*\*|__|`", "", said)  # Markdown's bold and code marks, read aloud as nothing
            if said.endswith("?") and after in ("", " ", "\t", "\n", '"', "'", ")", "]", "*", "_") and len(said.split()) >= 2 \
                    and re.search(r"[A-Za-z]", said):
                found.append(said)
    if not found:
        return None
    return line(" ".join(found[-3:]), 300), line(" ".join(paragraphs), 600)


def stop_question(event, box):
    """A turn that ends by asking the person something: while someone is using the building, waits a while for the
    answer there and goes on with it (Stop, decision "block" with the answer as the reason). Otherwise it waits as a
    card, and answering it later reaches the agent as a message."""
    if not switches.on("questions", DATA) or not kept_questions(box):
        return None
    found = asked_in(event.get("last_assistant_message"))
    project = found and floor_of(event)
    if not project:
        return None
    question, context = found
    key = key_of(event)
    decided, urgent = chain_of_command(event, box, project, "words", [{"question": live.clean(question, 300)}])
    if decided:
        return decided
    watched = box.watched()
    until = time.time() + control.wait_seconds() if watched else None
    qid = box.question(key, "words", live.clean(question, 300), None, until,
                       {"project": project, "agent": event.get(AGENT) or "Claude Code", "title": seat_title(event), "said": live.clean(context, 600),
                        "urgent": urgent})
    if switches.on("live", DATA):
        live.Live(DATA).moment(key, "asking" if watched else "finished", "ask" if watched else None, f"Asking you: {question}", project,
                               asking={"id": qid, "kind": "words", "text": live.clean(question, 300)})
    if not watched:
        return None
    how, got = control.await_question(box, qid, key, until)
    late = box.settle(qid, "open" if how is None else "answered")
    if how is None and late:
        how, got = "answer", late
    if how == "stop":
        box.stopping(key)  # it stops here anyway: the request is spent
        return None
    if how == "words":
        heard_now(event, got)
        words = "; ".join(control.one_line(row.get("text"), control.MAX_TEXT) for row in got)
    elif how == "answer":
        words = control.answered_words(got)
    else:
        return None
    edit_talk(event, lambda t: t.update(working=True, check=False, says={"now": "I've got your answer, and I'm carrying on with it."}))
    if switches.on("live", DATA):
        live.Live(DATA).moment(key, "working", "thinking", "Thinking about your answer", project, asking=None)
    return {"decision": "block", "reason": f'The person you are working for answered your question from Arnheim, the building: "{words}". '
                                           "Carry on with that."}


def hold_here(event, box):
    """At an agent's step while you hold it from the building (connect/control.py, await_hold). Gives (how, words):
    ("context", words) to add to what it is handed; ("deny", words) to turn this step down, so it reads your words
    before it acts; ("block", words) to keep its turn from ending; ("stop", None) to stop it; or None."""
    key = key_of(event)
    name = event.get("hook_event_name")
    if not os.path.isfile(box.path("holds", key + ".json")):
        return None
    if not switches.on("hold", DATA):
        why = box.end_hold(key, "off")
        return ("context", control.HOLD_ENDS["off"]) if why and name != "Stop" else None
    shoulder = switches.on("live", DATA)
    lv = live.Live(DATA)
    project = floor_of(event)

    def held(row):  # on its screen: holding, since when and until when at most
        if shoulder and project:
            lv.moment(key, "held", "held", "Holding, as you asked", project, event.get(AGENT) or "Claude Code", hold=control.hold_view(row))
    got = control.await_hold(box, key, on=lambda: switches.on("hold", DATA), held=held)
    if got is None:
        return None
    how, rows = got
    if shoulder and project:
        ended = {"hold_ended": {"why": how, "at": round(time.time(), 2)}} if how in ("carry on", "ten minutes", "nobody", "off", "stopped") else {}
        if name == "Stop" and how not in ("words", "still"):  # its turn ends as it was going to
            lv.moment(key, "finished", None, None, project, hold=None, **ended)
        else:
            lv.moment(key, "working", "thinking", "Thinking about the next step", project, hold=control.hold_view(box.hold_row(key)), **ended)
    if how == "words":
        heard_now(event, rows)
        if name == "PreToolUse":
            return "deny", control.held_message(rows, before_step=True)
        return ("block" if name == "Stop" else "context"), control.held_message(rows)
    if how == "still":
        if name == "PreToolUse":
            return "deny", control.STILL_HELD
        if name == "Stop":
            return "block", "The person you are working for is still holding you from Arnheim, the building. Say in a sentence that you're waiting for them."
        return "context", "The person you are working for is still holding you from Arnheim, the building: your next step waits until they say carry on."
    if how == "stopped":
        return "stop", None
    words = control.HOLD_ENDS.get(how)
    if not words or name == "Stop":
        return None  # told by another step, or a turn ending as it was going to
    return "context", words


# ---------- a chain of command and office hours (connect/deputy.py; docs/connect.md, steps 26 and 27) ----------

def chain_of_command(event, box, project, kind, shown, given=None):
    """The one place where an agent asking you something is weighed before it waits for you: its question tool (kind
    "choices", `given` its input) or a turn that ends with a question ("words"). A permission it asks for is weighed in
    respond: only Always allow's exact commands go without you, and office hours list the rest (office_permission).

    First the floor's lead answers what you have settled already, and says from which decision (connect/deputy.py).
    Then, outside office hours with nobody in the building, the question tool hears that you are away until the next
    one, and the question waits for the sitting. Gives (what Claude Code hears back, or None; why it is urgent, or
    None: then it reaches you at once, and the page alerts you)."""
    key, agent, now = key_of(event), event.get(AGENT) or "Claude Code", time.time()
    try:
        if switches.on("chain", DATA):
            settled = deputy.settle(DATA, kind, project, shown, judge=deputy.brain_judge if deputy.brain_on(DATA) else None)
            if settled:
                deputy.log_answered(DATA, key, project, seat_title(event), agent, kind, settled)
                told = deputy.to_agent(settled)
                if switches.on("live", DATA):
                    live.Live(DATA).moment(key, "working", "thinking", "Answered from your decisions, and carrying on", project, agent, asking=None)
                if kind == "choices":
                    original = [q["question"] for q in given["questions"]]
                    answers = {original[i]: deputy.answer_with_note(a) for i, a in enumerate(settled["answers"])}
                    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                                   "updatedInput": {**given, "answers": answers}, "additionalContext": told}}, None
                edit_talk(event, lambda t: t.update(working=True, check=False, says={"now": "My lead answered from what you decided before, so I'm carrying on."}))
                return {"decision": "block", "reason": told}, None
        if not switches.on("office_hours", DATA) or box.watched() or deputy.office_open(DATA, now):
            return None, None  # in office hours, or someone is in the building: as it always was
        question = shown[0]["question"]
        urgent = None
        if deputy.asked_before(DATA, key, question) or any(
                row.get("key") == key and deputy.same_kind(row.get("text"), question) for row in box.question_rows()):
            urgent = "It asked the same thing a second time."
        elif deputy.near_limit(DATA, agent, now):
            urgent = "It is close to its plan's limit."
        elif deputy.never_asked(shown):  # secrets, money, deleting, pushing, publishing, sending: never "you're away"
            urgent = deputy.NEVER_URGENT
        if urgent or kind != "choices":
            return None, urgent  # a turn that ends with a question waits as a card, as it always did
        deputy.park(DATA, "question", key, project, seat_title(event), agent, question, questions=shown)
        words = deputy.away_words(DATA, now)
        if switches.on("live", DATA):
            live.Live(DATA).moment(key, "working", "thinking", f"Put my question aside until {deputy.until_words(DATA, now)} (office hours)",
                                   project, agent, asking=None)
        answers = {q["question"]: words for q in given["questions"]}
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                       "updatedInput": {**given, "answers": answers}}}, None
    except Exception as error:  # the chain's trouble never costs the question: it comes to you as it always did
        note(error)
        return None, None


def office_permission(event, box, project, tool, what, command):
    """Office hours: a permission asked for while you are away asks in the agent's own window, as it always did, and is
    listed for the sitting. One that reaches something private, deletes or sends things, or comes from an agent close to
    its plan's limit, is marked urgent: the page alerts you at once."""
    if not project or not switches.on("office_hours", DATA) or box.watched() or deputy.office_open(DATA):
        return None
    agent = event.get(AGENT) or "Claude Code"
    urgent = deputy.high_risk(tool, what, command, restore.risky) or (
        "It is close to its plan's limit." if deputy.near_limit(DATA, agent) else None)
    return deputy.park(DATA, "permission", key_of(event), project, seat_title(event), agent, what, tool=tool, what=what, urgent=urgent)


def night_run(event):
    """Whether this conversation is one of the night shift's runs at work (connect/night.py), so nobody is watching it.
    Only looked at while the night shift is switched on, and only then is its module loaded."""
    if not switches.on("night", DATA) or not os.path.isdir(os.path.join(DATA, "night")):
        return False
    import night  # noqa: E402  (beside this file: the night shift)
    return night.working_run(DATA, key_of(event))


def runs_a_command(event):
    """Whether a step runs a command: any tool handed one ("command", or Codex's "cmd"), whatever its name (Bash,
    Monitor, PowerShell, Codex's exec_command), as the night's rule reads it (connect/night.py, shell_command)."""
    given = event.get("tool_input")
    return isinstance(given, dict) and (given.get("command") is not None or given.get("cmd") is not None)


def night_rule(event):
    """A night run's step that pushes, publishes, deploys, sends, uploads, syncs, opens a pull request or deletes, or
    another server's tool that does more than read, is turned down here, whatever the person's own allow rules or
    permission mode would let through: nobody is watching it, and that waits for them (docs/connect.md, step 30).
    Gives PreToolUse's answer, or None."""
    tool = str(event.get("tool_name") or "")
    if not tool.startswith("mcp__") and not runs_a_command(event):
        return None
    if not night_run(event):
        return None
    import night  # noqa: E402
    why = night.step_refusal(tool, event.get("tool_input"))
    if not why:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny", "permissionDecisionReason": why}}


def before_step(event):
    """PreToolUse: the step under way is on its screen already (watch). Then the night shift's rule (a night run never
    pushes, sends or deletes), a question it asks you (AskUserQuestion), a hold from the building, and a restore point
    before it changes files."""
    box = control.Box(DATA)
    try:
        refused = night_rule(event)
    except Exception as error:  # the night's records can't be read: while it is on, a push or a bulk delete waits, to be safe
        note(error)
        refused = None
        try:
            given = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
            command = given.get("command") if given.get("command") is not None else given.get("cmd")
            command = " ".join(str(w) for w in command) if isinstance(command, (list, tuple)) else str(command or "")
            # Only for an agent started from the building (its record in data/control/runs), as every night run is: a
            # broken night file never turns down the person's own conversation.
            if (runs_a_command(event) and switches.on("night", DATA) and (deputy.PUSHY.search(command) or restore.risky(command))
                    and os.path.isfile(os.path.join(DATA, "control", "runs", key_of(event) + ".json"))):
                refused = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                                  "permissionDecisionReason": "Not run: the night shift's rules couldn't be read, so this step waits."}}
        except Exception as error_too:  # nothing more can be told: the step goes on to the rest of the hook
            note(error_too)
    if refused:
        return refused
    if event.get("tool_name") == "AskUserQuestion":
        try:
            return ask_question(event, box)
        except Exception as error:  # a question that can't reach the building is asked in its window
            note(error)
            return None
    out = None
    try:
        held = hold_here(event, box)
    except Exception as error:  # a hold's trouble never holds Claude up
        note(error)
        held = None
    if held and held[0] in ("deny", "stop"):
        try:  # a step that never runs leaves no copy of a file from before it (connect/live.py, stash)
            if event.get("tool_name") == "Write":
                live.Live(DATA).unstash(event)
        except Exception as error:
            note(error)
    if held and held[0] == "deny":
        # The person's words go in as added context, never as the reason a step was turned down: Claude Code shows that
        # reason as a hook error, and rightly won't take instructions from an error (seen with the real Claude Code).
        return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                       "permissionDecisionReason": HELD_REASON, "additionalContext": held[1]}}
    if held and held[0] == "stop":
        return stop_now(event, box, before_step=True)
    if held and held[0] == "context":
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": held[1]}}
    # Your messages reach Claude Code before its next step, as added context. Handed over after a step, they sit inside
    # the tool's output, and Claude Code rightly won't take instructions from a tool's output (seen with the real one).
    rows = []
    if event.get(AGENT) != "Codex":
        try:
            rows = box.take(key_of(event))
            heard_now(event, rows)
        except Exception as error:  # the mail's trouble never holds Claude up
            note(error)
    if rows:
        before = out["hookSpecificOutput"]["additionalContext"] if out else None
        out = {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                       "additionalContext": "\n\n".join(w for w in (before, control.message(rows)) if w)}}
    try:
        restore_point(event)
    except Exception as error:  # a restore point's trouble never holds Claude up
        note(error)
    # Show me (connect/show.py): the pictures from before, as its first change of a turn starts
    try:
        show_before(event)
    except Exception as error:  # a picture's trouble never holds Claude up
        note(error)
    return out


def respond(event):
    """Keeps the feed up to date, and gives what Claude Code should hear back, if anything: your
    messages from the building, your answer there to a permission or a question, a hold, or your
    request to stop. None means nothing: Claude Code carries on as usual."""
    name = event.get("hook_event_name")
    if not event.get("session_id") or os.environ.get("ARNHEIM_REVIEWER"):
        return None  # the review line's own reader is never a conversation of its own
    try:
        watch(event)
    except Exception as error:  # the screen's trouble never holds Claude up
        note(error)
    if name == "PreToolUse":
        return before_step(event)
    key = key_of(event)
    box = control.Box(DATA)
    if name in ("UserPromptSubmit", "SessionEnd") or (name == "PostToolUse" and event.get("tool_name") == "AskUserQuestion"):
        try:  # you answered in its own window, or it moved on: its questions in the building are done
            if os.path.isdir(box.path("questions")):
                box.close_questions(key, ("choices",) if name == "PostToolUse" else ("choices", "words"))
            if name != "PostToolUse" and os.path.isfile(box.path("holds", key + ".json")):
                box.end_hold(key, "moved on")  # a new message, or the end: a hold from before it (say, after Esc) ends
        except Exception as error:
            note(error)
    if name in ("PostToolUse", "UserPromptSubmit", "Stop", "SessionEnd"):
        try:  # it went on: what it asked in its own window while you were away was answered there (connect/deputy.py)
            deputy.moved_on(DATA, key)
        except Exception as error:
            note(error)
    if name == "PermissionRequest":
        tool = str(event.get("tool_name") or "a tool")
        what = control.describe(tool, event.get("tool_input"))
        project = floor_of(event)
        command = standing.command_in(tool, event.get("tool_input"))  # the exact words it would run, if a plain command
        always = switches.on("always", DATA)  # off: every request asks, and the standing allows are kept
        try:  # a night run never goes on a standing allow: nobody is watching it (connect/night.py)
            standing_allow = standing.allows(DATA, project, tool, command) if always and not night_run(event) else None
        except Exception as error:  # a standing allow that can't be read never allows anything
            note(error)
            standing_allow = None
        if standing_allow:  # you allowed this exact command on this floor for good (connect/standing.py)
            keep(event, {"asking": what, "standing": True})
            try:
                standing.used(DATA, standing_allow["id"])
            except Exception as error:  # counting it never stops the allow
                note(error)
            return {"hookSpecificOutput": {"hookEventName": name, "decision": {"behavior": "allow"}}}
        keep(event, {"asking": what})
        try:  # office hours: listed for the sitting, and urgent ones alert you (connect/deputy.py)
            office_permission(event, box, project, tool, what, command)
        except Exception as error:
            note(error)
        try:
            more = {"project": project, "before": standing.times(DATA, project, tool, command),
                    "standable": always and standing.can_stand(tool, command), "command": command}
        except Exception as error:
            note(error)
            more = {"project": project}
        got = control.await_answer(box, key, tool, what, more)
        if got == "allow":  # this one request, as it was shown: never a rule for later ones
            return {"hookSpecificOutput": {"hookEventName": name, "decision": {"behavior": "allow"}}}
        if got in ("deny", "stop"):
            decision = {"behavior": "deny", "message": "Denied from Arnheim, the building." if got == "deny" else "Stopped from Arnheim, the building."}
            if got == "stop" and event.get(AGENT) == "Codex":
                box.stop(key)  # Codex takes no interrupt here: it stops at its next step instead
            elif got == "stop":
                decision["interrupt"] = True
            return {"hookSpecificOutput": {"hookEventName": name, "decision": decision}}
        return None
    if name == "UserPromptSubmit" and box.paused() and (project_for(event.get("cwd")) or any(
            isinstance(c, dict) and c.get("id") == key for c in read_feed().get("conversations") or [])):
        keep(event, {"paused_prompt": True})
        return {"decision": "block", "reason": "Arnheim, the building, has paused every agent. Resume them there, then send this again."}
    stop = box.stopping(key) if name in ("PostToolUse", "UserPromptSubmit", "Stop") else False
    if stop and name in ("PostToolUse", "Stop", "UserPromptSubmit"):
        try:
            if os.path.isfile(box.path("holds", key + ".json")):
                box.end_hold(key, "stopped")  # stopped, or moved on: a hold ends with it
        except Exception as error:
            note(error)
    if stop and name == "PostToolUse":
        keep(event, {"stopped": True})
        return {"continue": False, "stopReason": "Stopped from Arnheim, the building."}
    # A new message from you, or a turn that ends anyway, spends a request to stop.
    # Before each step is where Claude Code gets your messages (before_step); after a step only Codex does.
    after_step = name == "PostToolUse" and event.get(AGENT) == "Codex"
    rows = box.take(key) if after_step or name == "UserPromptSubmit" or (name == "Stop" and not stop) else []
    took(event, rows)
    try:
        memo = remembered(event, name)
    except Exception as error:  # the memory's trouble never costs Claude your message
        note(error)
        memo = None
    told = {"memory_at": memo[1]} if memo else {}
    if not rows:
        extra = {"started_here": os.path.exists(box.path("runs", key + ".json"))} if name == "SessionEnd" else {}
        verdict = keep(event, {**extra, **told} or None)
        if verdict.get("stop"):
            return {"continue": False, "stopReason": verdict["stop"]}
        notice = None
        # A hold keeps Claude Code before its next step (before_step) or as its turn ends, where your words reach it;
        # after a step they would sit in the tool's output, so only Codex is held there.
        if (name == "Stop" or after_step) and not stop:
            try:
                held = hold_here(event, box)
            except Exception as error:  # a hold's trouble never holds Claude up
                note(error)
                held = None
            if held and held[0] == "stop":
                return stop_now(event, box) if name == "PostToolUse" else None
            if held and held[0] == "block":
                edit_talk(event, lambda t: t.update(working=True, check=False))
                return {"decision": "block", "reason": held[1]}
            if held and held[0] == "context":
                notice = held[1]
        if name == "Stop" and not stop:
            held = review(event)
            if held:
                return held
            try:
                asked = stop_question(event, box)
            except Exception as error:  # a question that can't reach the building waits in its window
                note(error)
                asked = None
            if asked:
                return asked
        if name == "Stop":
            prove(event)
        if name == "Stop" and not stop:
            show_after(event)  # Show me (connect/show.py): the pictures from after, in the background
        howtos = finished = None
        if name == "SessionStart":
            try:
                howtos = shelf(event)
            except Exception as error:  # the shelf's trouble never costs Claude its start
                note(error)
            try:
                finished = handed(event)
            except Exception as error:  # nor does the hand-over's
                note(error)
        words = "\n\n".join(w for w in (notice, howtos, finished, memo[0] if memo else None, verdict.get("warn")) if w)
        return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": words}} if words else None
    heard = rows[-1].get("id")
    if name == "Stop":
        keep(event, {"heard": heard, "going_on": True})
        return {"decision": "block", "reason": control.message(rows, stopping=True)}
    verdict = keep(event, {"heard": heard, **told})
    words = "\n\n".join(w for w in (control.message(rows), memo[0] if memo else None, verdict.get("warn")) if w)
    return {"hookSpecificOutput": {"hookEventName": name, "additionalContext": words}}


# ---------- Show me (connect/show.py; docs/connect.md, "Show me") ----------

def show_before(event):
    """As an agent starts its first change after your message, on a floor that says how to show its work: the pictures
    from before, taken now, within a short time limit (connect/show.py, before_seconds), so they show the work as it
    was. Once a turn: the agent waits a moment for them at that one step."""
    if event.get("tool_name") not in CHANGES or not switches.on("show_me", DATA):
        return
    project = floor_of(event)
    given = show.show_for(project, DATA) if project else None
    if not given:
        return
    talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None) or {}
    turn = show.turn_started(talk)
    if turn is None or talk.get("show_before") == turn:
        return  # no message known to start a turn, or taken already in this one
    edit_talk(event, lambda t: t.update(show_before=turn))
    show.before(DATA, key_of(event), project, turn, given)


def show_after(event):
    """As a turn finishes its work (Stop, no question waiting): when it changed files and its floor says how to show
    its work, the pictures from after are taken in the background, beside those from before (connect/show.py)."""
    if not switches.on("show_me", DATA):
        return
    try:
        talk = next((c for c in read_feed().get("conversations") or [] if isinstance(c, dict) and c.get("id") == key_of(event)), None)
        project = (talk or {}).get("project")
        if not talk or not project or not show.show_for(project, DATA):
            return
        if asked_in(event.get("last_assistant_message")):
            return  # it ends by asking you something: not finished yet
        turn = show.turn_of(talk)
        if turn is not None:
            show.after_later(DATA, talk["id"], project, turn)
    except Exception as error:  # a picture that can't be taken never troubles Claude Code
        note(error)


def main():
    out = None
    try:
        raw = sys.stdin.read()
        event = json.loads(raw) if raw.strip() else {}
        if isinstance(event, dict):
            out = respond(event)
    except Exception as error:  # never trouble Claude Code: note it and carry on
        note(error)
    if out:
        try:
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
