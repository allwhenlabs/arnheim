"""Never stop at a limit: carry a conversation on in the other agent (docs/connect.md, "Carry on at a limit").

The loudest complaint about every coding agent is reaching the plan's limit without warning, and the top reason people
keep both Claude Code and Codex is to switch to the other when one runs out. When a conversation's agent will reach its
5-hour or weekly limit within about half an hour at this pace, or has reached it, and the other agent is here with room
left, Needs you offers to carry that conversation on in the other one (src/carry-on.js). The page writes the hand-over:
what the conversation was for, the latest request, its task list, the files it changed and its last words.

With control on, Carry on starts the other agent on the same floor, in the floor's folder, handed that hand-over with
where it was started from and the floor's check (connect/control.py's brief): Codex as `codex exec --json`, Claude Code
as `claude -p`, as any agent started from the building. A first agent still at work is stopped at its next step, so the
two never change the same files. data/control/carry-on.json keeps which conversations were carried on, so a second press
starts nothing. Standard library only.
"""
import json
import os
import re
import secrets
import shutil
import threading
import time
import uuid

AGENTS = ("Claude Code", "Codex")
MOST = 6000  # characters in a hand-over at most
AGAIN = 6 * 3600  # seconds: a conversation carried on this lately isn't carried on again
SANDBOX = "workspace-write"  # Codex may change files in the floor's folder, without the network, and nothing outside it


def _switches():
    """connect/switches.py, however this file was loaded: as part of the package, beside it, or by its path alone."""
    try:
        from . import switches  # as connect.carry_on
        return switches
    except ImportError:
        pass
    try:
        import switches  # beside this file, as the hook has it
        return switches
    except ImportError:
        import importlib.util
        spec = importlib.util.spec_from_file_location("arnheim_switches", os.path.join(os.path.dirname(os.path.realpath(__file__)), "switches.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def other(agent):
    """The agent a conversation carries on in: Codex for Claude Code's, Claude Code for Codex's."""
    return "Codex" if agent == "Claude Code" else "Claude Code"


def here(command):
    """Whether a command (its words, as ARNHEIM_CLAUDE or ARNHEIM_CODEX give them) can be run on this computer."""
    return bool(command) and bool(shutil.which(command[0]))


def installed(claude, codex):
    """Which agents this computer can start: {"Claude Code": bool, "Codex": bool}."""
    return {"Claude Code": here(claude), "Codex": here(codex)}


def words(text):
    """The page's hand-over, checked: some words, and not too many."""
    text = str(text or "").strip()
    if not text:
        raise ValueError("There is no hand-over to give it.")
    if len(text) > MOST:
        raise ValueError(f"That hand-over is too long: keep it under {MOST} characters.")
    return text


def in_git(folder):
    """Whether a folder is in a git repository: Codex runs only there, to keep its changes undoable."""
    path = os.path.realpath(folder)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def codex_args(codex, resume=None):
    """How Codex is started without a window: exec with JSON events, allowed to change files in its folder, the words on
    stdin ("-"). With `resume`, its thread carries on with your next message instead."""
    return list(codex) + ["exec", "--json", "--sandbox", SANDBOX] + (["resume", str(resume)] if resume else []) + ["-"]


def codex_event(event):
    """One of codex exec's JSON events, as the building needs it: ("thread", its id) once it starts, ("said", words) for
    each of its messages, ("failed", why) when a turn fails, or None for anything else."""
    if not isinstance(event, dict):
        return None
    kind = event.get("type")
    if kind == "thread.started" and event.get("thread_id"):
        return "thread", str(event["thread_id"])
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    if kind == "item.completed" and item.get("type") == "agent_message" and isinstance(item.get("text"), str):
        return "said", item["text"]
    if kind in ("turn.failed", "error"):
        error = event.get("error") if isinstance(event.get("error"), dict) else {}
        why = error.get("message") or event.get("message")
        return ("failed", str(why)) if why else None
    return None


def last_words(path, most=65536):
    """The last thing the agent said in a Claude Code transcript, read from its end, or "" (a turn cut off by a limit
    never reaches the Stop hook that would have said it)."""
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - most))
            lines = handle.read().decode("utf-8", "replace").splitlines()
    except (OSError, TypeError, ValueError):
        return ""
    for raw in reversed(lines):
        try:
            row = json.loads(raw)
        except ValueError:
            continue
        if not isinstance(row, dict) or row.get("type") != "assistant" or row.get("isApiErrorMessage"):
            continue
        content = (row.get("message") or {}).get("content") if isinstance(row.get("message"), dict) else None
        said = " ".join(b.get("text") or "" for b in content if isinstance(b, dict) and b.get("type") == "text").strip() if isinstance(content, list) else ""
        if said:
            return said
    return ""


def _path(data):
    return os.path.join(data, "control", "carry-on.json")


def carried(data, now=None):
    """The conversations carried on lately: {key: {"key", "to", "at"}}."""
    now = now or time.time()
    try:
        with open(_path(data), encoding="utf-8") as handle:
            rows = json.load(handle).get("rows")
    except (OSError, ValueError, AttributeError):
        return {}
    return {r["key"]: r for r in rows if isinstance(r, dict) and r.get("key") and now - float(r.get("at") or 0) < AGAIN} if isinstance(rows, list) else {}


def note(data, key, to, now=None):
    """Keeps that a conversation was carried on, and in which agent."""
    now = now or time.time()
    rows = [r for r in carried(data, now).values() if r["key"] != key] + [{"key": key, "to": to, "at": round(now, 1)}]
    path = _path(data)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = f"{path}.{os.getpid()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump({"about": "Conversations carried on in the other agent at a limit (connect/carry_on.py). Safe to delete.", "rows": rows},
                  handle, ensure_ascii=False, indent=1)
    os.replace(part, path)


def _title(text):
    first = " ".join(text.splitlines()[0].split()) if text.strip() else ""
    return first if len(first) <= 70 else first[:69].rstrip(" ,;:") + "…"


def start(control, given):
    """Carries a conversation on in the other agent: {"key", "to", "text"} from the page, where text is its hand-over.
    Gives {"key", "project", "agent", "stopped"}. ValueError, in words for the person, when it can't."""
    if not _switches().on("carry_on", control.data):
        raise ValueError("Carrying on at a limit is switched off, in Settings under Switches.")
    key = control.conversation(given.get("key"))
    try:
        with open(os.path.join(control.data, "feeds", "claude-code.json"), encoding="utf-8") as handle:
            talks = json.load(handle).get("conversations") or []
    except (OSError, ValueError, AttributeError):
        talks = []
    talk = next((c for c in talks if isinstance(c, dict) and c.get("id") == key), None) or {}
    with control.lock:
        run = dict(control.runs.get(key) or {})
    source = talk.get("agent") or run.get("agent") or "Claude Code"
    if source not in AGENTS:
        raise ValueError(f"{source} can't hand over to another agent here: only Claude Code and Codex carry on for each other.")
    to = other(source)
    if given.get("to") not in (None, to):
        raise ValueError(f"It runs in {source}, so it carries on in {to}.")
    floor = next((f for f in control.floors() if f["project"] == (talk.get("project") or run.get("project"))), None)
    if not floor:
        raise ValueError("Its floor has no folder on this computer. Give it a folder in data/company.json.")
    if not installed(control.claude, control.codex)[to]:
        name = "ARNHEIM_CODEX" if to == "Codex" else "ARNHEIM_CLAUDE"
        raise ValueError(f"{to} isn't on this computer, or isn't on its PATH. {name} can name its command.")
    with STARTING:  # two quick presses start one agent: the look and the note are one step
        return _start(control, given, key, talk, run, source, to, floor)


STARTING = threading.Lock()


def _start(control, given, key, talk, run, source, to, floor):
    done = carried(control.data).get(key)
    if done:
        raise ValueError(f"It was carried on in {done.get('to') or to} already. Look for it on {floor['label']}.")
    text = words(given.get("text"))
    if to == "Codex" and not in_git(floor["folder"]):
        raise ValueError(f"Codex works only in a project kept in git, and {floor['label']}'s folder isn't. Copy the hand-over, under What Codex is told, and paste it into Codex yourself.")
    brief = control.brief(text, floor)
    run_new = {"project": floor["project"], "folder": floor["folder"], "title": _title(text), "said": "", "at": time.time()}
    with control.lock:
        if to == "Codex":
            run_new.update(key="cc-" + secrets.token_hex(6), sid=None, agent="Codex")  # until Codex names its thread
            control.spawn_codex(run_new, brief)
        else:
            sid = str(uuid.uuid4())
            run_new.update(key="cc-" + sid.replace("-", "")[:12], sid=sid)
            control.spawn(run_new, ["--session-id", sid], brief)
    working = bool(talk.get("working")) or bool(run and control.alive(run))
    if working:  # the first stops at its next step, so the two never change the same files
        control.stop(key)
    note(control.data, key, to)
    return {"ok": True, "key": run_new["key"], "project": floor["project"], "agent": to, "stopped": working}


def key_of(thread):
    """The key Arnheim gives a conversation from its session id (connect/claude_code.py's key_of)."""
    return "cc-" + re.sub(r"[^A-Za-z0-9]", "", str(thread))[:12]
