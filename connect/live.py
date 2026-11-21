#!/usr/bin/env python3
"""Over an agent's shoulder: what it is doing now, the steps it has finished, the lines it has changed, its to-do
list, and how each message you sent it is getting on (docs/connect.md, "Work beside your agents").

The hook (connect/claude_code.py, which Codex's connect/codex.py hands its events to) keeps a file for each
conversation in data/live/, and a short index of them all, data/live/index.json:

- "now": the step under way, from PreToolUse, in plain words ("Running npm test"), and when it started;
- "steps": the last 200 finished steps, each with its kind, plain words and the files it touched;
- "changes": the lines each change took out and put in, as hunks: Claude Code's Edit, MultiEdit, Write and
  NotebookEdit, and Codex's apply_patch, read from the patch itself;
- "todos": the to-do list, done items included, so it ticks off;
- "messages": what you sent it from the building: queued, then taken (and when), then answered, with the reply
  it gave straight away.

They hold lines of your projects' code and the commands agents run, so serve.py serves data/live/ to this
computer only (NEVER_AWAY): never over --lan, --share or a view-only link. A paired phone reads it only through
/control/ (connect/control.py), while this computer lets it control agents. Anything that looks like a secret
(connect/secret_scan.py) is hidden before it is kept, and every part has a size limit. Standard library only.
"""
import difflib
import json
import os
import re
import subprocess
import threading
import time


def _beside(name):
    """A module beside this file, loaded by its path: for a server that loads this file by its path alone."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("arnheim_" + name, os.path.join(os.path.dirname(os.path.realpath(__file__)), name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    from . import secret_scan  # as connect.live, from serve.py
except ImportError:
    try:
        import secret_scan  # beside this file, as the hook has it
    except ImportError:
        secret_scan = _beside("secret_scan")

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
KEY = re.compile(r"^cc-[A-Za-z0-9]{1,12}$")  # a conversation, as the feed names it (claude_code.key_of)
STEPS_KEPT = 200  # finished steps kept for each conversation
HUNKS_KEPT = 200  # changes kept for each conversation, the newest
HUNK_LINES = 80  # lines in one change at most
GIT_HUNK_LINES = 200  # the same, for git diff
LINE_CHARS = 400  # characters in one line at most
STEP_HUNKS = 20  # changes kept from one step at most
STEP_FILES = 20  # files named by one step at most
WORDS = 160  # characters in a step's words
MESSAGES_KEPT = 40
MESSAGE_CHARS = 2000
FILE_MOST = 600_000  # bytes in one conversation's file at most: its oldest changes go first, then its oldest steps
READ_MOST = 2_000_000  # the biggest file read to find where a change landed, or to compare a whole file written
BEFORE_MOST = 400_000  # the biggest file kept as it was before a Write, to compare with what was written
BEFORE_KEPT = 900  # seconds a copy from before a Write is kept, for a step that never ran (sweep)
DIFF_LINES = 6000  # files longer than this are shown whole, not compared line by line
GIT_MOST = 400_000  # characters of git diff read at most
GIT_WAIT = 15  # seconds git may take
UNTRACKED_MOST = 50
KEEP = 12 * 3600  # a conversation not heard from for this long has gone, as the feed has it
HIDDEN = "[hidden]"
NEW_FILE = "\0new"  # a Write's file didn't exist before it


# ---------- words ----------

def one_line(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def home_less(text):
    """This computer's home folder written as ~, so a step's words never name it."""
    home = os.path.expanduser("~")
    return text.replace(home, "~") if len(home) > 1 and home != "~" else text


# A quoted value given to a name in code: password = "...", "api_key": "...", token => '...'
CODE_ASSIGN = re.compile(r"""([A-Za-z_][A-Za-z0-9_.\-]*)["']?\s*(?:=>|:=|:|=)\s*["']([^"'\n]{6,300})["']""")
# The same unquoted, as settings files write it: password: ..., db.password=..., client_secret = ...
PLAIN_ASSIGN = re.compile(r"""(?<![A-Za-z0-9_.\-])([A-Za-z_][A-Za-z0-9_.\-]*)[ \t]*(?:=>|:=|:|=)[ \t]*(?!["'])([^\s"',;]{6,300})""")
# A MySQL password given straight after -p, as in mysql -u root -pXXXX
MYSQL_P = re.compile(r"""\b(?:mysql|mysqldump|mysqladmin|mysqlimport|mysqlshow|mysqlcheck)\b[^\n]*?\s-p([^\s'"]+)""")


def secret_spans(text):
    """Where the secrets are in a piece of text: what secret_scan finds, and quoted values given to names that say
    they are secret. [(start, end)], merged. Raises if the scanner fails."""
    spans = [(h.start, h.end) for h in secret_scan.text_hits(text)]
    for m in CODE_ASSIGN.finditer(text):
        if secret_scan.named_hit(m.group(1), m.group(2)):
            spans.append((m.start(2), m.end(2)))
    for m in PLAIN_ASSIGN.finditer(text):
        if not re.search(r"[()\[\]{}]", m.group(2)) and secret_scan.named_hit(m.group(1), m.group(2)):  # never a call in code
            spans.append((m.start(2), m.end(2)))
    for m in MYSQL_P.finditer(text):
        spans.append((m.start(1), m.end(1)))
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def redact(text):
    """The text with every secret in it hidden. A scanner that fails hides the whole text."""
    text = str(text if text is not None else "")
    if not text.strip():
        return text
    try:
        spans = secret_spans(text)
    except Exception:
        return HIDDEN
    out, last = [], 0
    for start, end in spans:
        out.append(text[last:start])
        out.append(HIDDEN)
        last = end
    out.append(text[last:])
    return "".join(out)


def redact_lines(lines):
    """The same for the lines of a change, scanned together so a secret over several lines (a private key) is
    found, and given back as the same number of lines."""
    if not lines:
        return []
    joined = "\n".join(lines)
    try:
        spans = secret_spans(joined)
    except Exception:
        return [HIDDEN if line.strip() else line for line in lines]
    if not spans:
        return list(lines)
    out, at = [], 0
    for line in lines:
        end_of = at + len(line)
        parts, last = [], at
        for start, end in spans:
            if end <= at or start >= end_of:
                continue
            s, e = max(start, at), min(end, end_of)
            parts.append(joined[last:s])
            parts.append(HIDDEN)
            last = e
        parts.append(joined[last:end_of])
        out.append("".join(parts))
        at = end_of + 1
    return out


def clean(text, most=WORDS):
    """Words a person reads: one line, the home folder as ~, secrets hidden, cut to `most`."""
    return one_line(redact(home_less(one_line(text, most * 4))), most)


def shown(path, cwd):
    """A file as a path inside the conversation's folder, never this computer's own folders."""
    path = str(path or "")
    if not path:
        return ""
    folder = os.path.realpath(os.path.expanduser(str(cwd))) if cwd else ""
    full = os.path.realpath(os.path.join(folder, os.path.expanduser(path)) if folder else os.path.expanduser(path))
    if folder and full.startswith(folder.rstrip(os.sep) + os.sep):
        return os.path.relpath(full, folder).replace(os.sep, "/")
    return os.path.basename(full)


def full_path(path, cwd):
    path = os.path.expanduser(str(path or ""))
    if not path:
        return ""
    return os.path.realpath(os.path.join(os.path.expanduser(str(cwd or "")), path) if cwd and not os.path.isabs(path) else path)


def first_lower(text):
    return text[:1].lower() + text[1:] if text[1:2].islower() or len(text) < 2 else text


def listed(files):
    """src/a.js, src/b.js and 2 more."""
    files = [f for f in files if f]
    if not files:
        return "files"
    if len(files) == 1:
        return files[0]
    if len(files) == 2:
        return f"{files[0]} and {files[1]}"
    return f"{files[0]}, {files[1]} and {len(files) - 2} more"


PATCH_FILE = re.compile(r"^\*\*\* (Add|Update|Delete) File: (.+?)\s*$")
PATCH_MOVE = re.compile(r"^\*\*\* Move to: (.+?)\s*$")
SHELLS = ("Bash", "exec_command", "shell", "local_shell", "container.exec", "unified_exec")


def patch_text(given):
    """A Codex patch, as its apply_patch tool is handed it."""
    given = given if isinstance(given, dict) else {}
    patch = given.get("command") or given.get("patch") or given.get("input") or ""
    if isinstance(patch, list):
        patch = "\n".join(str(part) for part in patch)
    return str(patch)


def command_of(given):
    command = (given or {}).get("command") if isinstance(given, dict) else None
    if isinstance(command, list):
        command = " ".join(str(part) for part in command)
        if command.startswith(("bash -lc ", "bash -c ", "sh -c ", "zsh -lc ")):  # Codex wraps a command in a shell
            command = command.split(" ", 2)[2]
    return str(command or "")


def what(tool, given, cwd=None):
    """A step in plain words: (kind, what it is doing, what it did, [files]). Kinds: read, search, command, edit,
    write, web, helper, plan, ask, other."""
    tool = str(tool or "a tool")
    g = given if isinstance(given, dict) else {}

    def at(field):
        return shown(g.get(field), cwd)

    def words(kind, doing, did, files=()):
        files = [f for f in files if f][:STEP_FILES]
        return kind, clean(doing), clean(did), files

    if tool == "Read":
        p = at("file_path")
        return words("read", f"Reading {p}", f"Read {p}", [p])
    if tool in ("Edit", "MultiEdit"):
        p = at("file_path")
        return words("edit", f"Editing {p}", f"Edited {p}", [p])
    if tool == "Write":
        p = at("file_path")
        return words("write", f"Writing {p}", f"Wrote {p}", [p])
    if tool == "NotebookEdit":
        p = at("notebook_path")
        return words("edit", f"Editing the notebook {p}", f"Edited the notebook {p}", [p])
    if tool == "apply_patch":
        files = [shown(f, cwd) for f, _, _ in parse_patch(patch_text(g))]
        return words("edit", f"Changing {listed(files)}", f"Changed {listed(files)}", files)
    if tool in SHELLS:
        command = command_of(g)
        return words("command", f"Running {command}" if command else "Running a command", f"Ran {command}" if command else "Ran a command")
    if tool == "Grep":
        where = f" in {at('path')}" if g.get("path") else ""
        return words("search", f'Searching for "{one_line(g.get("pattern"), 60)}"{where}', f'Searched for "{one_line(g.get("pattern"), 60)}"{where}')
    if tool == "Glob":
        return words("search", f"Looking for files matching {one_line(g.get('pattern'), 60)}", f"Looked for files matching {one_line(g.get('pattern'), 60)}")
    if tool == "WebFetch":
        host = re.sub(r"^[a-z]+://", "", str(g.get("url") or "")).split("/")[0]
        return words("web", f"Reading the web page {host}", f"Read the web page {host}")
    if tool == "WebSearch":
        return words("web", f'Searching the web for "{one_line(g.get("query"), 60)}"', f'Searched the web for "{one_line(g.get("query"), 60)}"')
    if tool in ("Agent", "Task"):
        about = one_line(g.get("description") or g.get("subagent_type") or "a job", 80)
        return words("helper", f"Asking a helper: {about}", f"Asked a helper: {about}")
    if tool in ("TodoWrite", "TaskCreate", "TaskUpdate", "TaskList", "TaskGet", "update_plan"):
        return words("plan", "Updating my to-do list", "Updated my to-do list")
    if tool == "ExitPlanMode":
        return words("plan", "Showing you my plan", "Showed you my plan")
    if tool == "AskUserQuestion":
        questions = g.get("questions") if isinstance(g.get("questions"), list) else []
        first = questions[0].get("question") if questions and isinstance(questions[0], dict) else ""
        return words("ask", f"Asking you: {one_line(first, 100)}" if first else "Asking you something",
                     f"Asked you: {one_line(first, 100)}" if first else "Asked you something")
    if tool.startswith("mcp__"):
        parts = tool.split("__")
        name, server = (parts[2] if len(parts) > 2 else parts[-1]).replace("_", " "), parts[1] if len(parts) > 1 else ""
        return words("other", f"Using {name} from {server}", f"Used {name} from {server}")
    return words("other", f"Using {tool}", f"Used {tool}")


# ---------- changes, as hunks ----------

def capped(hunk, most_lines=HUNK_LINES):
    """A change as it is kept: its lines cut to size, each line cut and with secrets hidden, and how many lines it
    put in and took out, counted before any were cut."""
    lines = [[str(s), str(t)] for s, t in hunk.get("lines") or [] if s in ("+", "-", " ")]
    hunk["added"] = sum(1 for s, _ in lines if s == "+")
    hunk["removed"] = sum(1 for s, _ in lines if s == "-")
    cut = len(lines) > most_lines
    lines = lines[:most_lines]
    texts = redact_lines([t if len(t) <= LINE_CHARS else t[: LINE_CHARS - 1] + "…" for _, t in lines])
    hunk["lines"] = [[s, t] for (s, _), t in zip(lines, texts)]
    hunk["cut"] = bool(cut or hunk.get("cut"))
    for field in ("start", "old_start"):
        if not isinstance(hunk.get(field), int) or hunk[field] < 1:
            hunk[field] = None
    return hunk


def split_lines(text):
    text = str(text or "")
    return text.split("\n")[:-1] if text.endswith("\n") else text.split("\n") if text else []


def compared(before, after):
    """Line by line: [{"old_start", "start", "lines"}], each with three lines either side."""
    a, b = split_lines(before), split_lines(after)
    if len(a) > DIFF_LINES or len(b) > DIFF_LINES:
        return None
    out = []
    for group in difflib.SequenceMatcher(None, a, b, autojunk=len(a) + len(b) > 2000).get_grouped_opcodes(3):
        lines = []
        for tag, a1, a2, b1, b2 in group:
            if tag == "equal":
                lines += [[" ", x] for x in a[a1:a2]]
                continue
            if tag in ("replace", "delete"):
                lines += [["-", x] for x in a[a1:a2]]
            if tag in ("replace", "insert"):
                lines += [["+", x] for x in b[b1:b2]]
        out.append({"old_start": group[0][1] + 1, "start": group[0][3] + 1, "lines": lines})
    return out


def read_text(path, most=READ_MOST):
    """A text file's words, or None: missing, too big, or not text."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > most:
            return None
        with open(path, "rb") as handle:
            raw = handle.read(most + 1)
    except OSError:
        return None
    if b"\0" in raw[:8192]:
        return None
    return raw.decode("utf-8", "replace")


def located(text, block):
    """The line (from 1) where these lines first stand together in a file's text, or None."""
    if text is None or not block or not any(line.strip() for line in block):
        return None
    lines = split_lines(text)
    first, n = block[0], len(block)
    for i, line in enumerate(lines):
        if line == first and lines[i:i + n] == block:
            return i + 1
    return None


def whole(path, content, kind):
    """A file shown whole: every line put in."""
    return [{"file": path, "kind": kind, "start": 1, "old_start": None, "lines": [["+", x] for x in split_lines(content)]}]


def from_structured(path, patch):
    """Claude Code's own record of an edit (the tool's response, structuredPatch): exact line numbers."""
    out = []
    for h in patch:
        if not isinstance(h, dict) or not isinstance(h.get("lines"), list):
            return None
        lines = [[str(x)[:1], str(x)[1:]] for x in h["lines"] if isinstance(x, str) and str(x)[:1] in ("+", "-", " ")]
        out.append({"file": path, "kind": "edit", "start": h.get("newStart"), "old_start": h.get("oldStart"), "lines": lines})
    return out


def from_strings(path, old, new, now_text):
    """An edit from what it replaced and what with, placed in the file as it is now if it can be found."""
    found = compared(old, new) or []
    start = located(now_text, split_lines(new))
    for h in found:
        h.update(file=path, kind="edit", old_start=None, start=(start + h["start"] - 1) if start else None)
    return found


def parse_patch(text):
    """A Codex patch (its apply_patch format): [(file, op, {"to": new name or None, "hunks": [[sign, line], ...]})]."""
    files, cur, hunk = [], None, None
    for raw in str(text or "").split("\n"):
        raw = raw[:-1] if raw.endswith("\r") else raw
        m = PATCH_FILE.match(raw)
        if m:
            cur = {"to": None, "hunks": []}
            files.append((m.group(2), m.group(1).lower(), cur))
            hunk = None
            continue
        if raw.startswith("*** End Patch"):
            cur = hunk = None
            continue
        if raw.startswith(("*** Begin Patch", "*** End of File")) or cur is None:
            continue
        m = PATCH_MOVE.match(raw)
        if m:
            cur["to"] = m.group(1)
            continue
        op = files[-1][1]
        if raw.startswith("@@") and op == "update":
            hunk = []
            cur["hunks"].append(hunk)
            continue
        if op == "delete":
            continue
        if hunk is None:
            hunk = []
            cur["hunks"].append(hunk)
        if op == "add":
            if raw.startswith("+"):
                hunk.append(["+", raw[1:]])
        elif raw[:1] in ("+", "-", " "):
            hunk.append([raw[:1], raw[1:]])
        elif raw == "":
            hunk.append([" ", ""])
    return files


def from_patch(given, cwd):
    out = []
    for name, op, part in parse_patch(patch_text(given)):
        path = shown(name, cwd)
        if op == "add":
            lines = [x for h in part["hunks"] for x in h]
            out.append({"file": path, "kind": "add", "start": 1, "old_start": None, "lines": lines})
        elif op == "delete":
            out.append({"file": path, "kind": "delete", "start": None, "old_start": None, "lines": []})
        else:
            landed = full_path(part["to"] or name, cwd)
            text = read_text(landed)
            for lines in part["hunks"] or [[]]:
                block = [t for s, t in lines if s in (" ", "+")]
                h = {"file": path, "kind": "edit", "start": located(text, block), "old_start": None, "lines": lines}
                if part["to"]:
                    h["to"] = shown(part["to"], cwd)
                out.append(h)
    return out


def hunks_of(event, before=None):
    """The changes one finished step made, as hunks, or []. `before` is a Write's file as it was (or NEW_FILE)."""
    tool = event.get("tool_name")
    g = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    response = event.get("tool_response") if isinstance(event.get("tool_response"), dict) else {}
    cwd = event.get("cwd")
    found = None
    if tool in ("Edit", "MultiEdit", "Write"):
        path = shown(g.get("file_path"), cwd)
        patch = response.get("structuredPatch")
        if isinstance(patch, list) and patch:
            found = from_structured(path, patch)
        if found is None and tool == "Write":
            content = g.get("content") if isinstance(g.get("content"), str) else ""
            if response.get("type") == "create" or before == NEW_FILE:
                found = whole(path, content, "add")
            elif isinstance(before, str):
                found = compared(before, content)
                for h in found or []:
                    h.update(file=path, kind="edit")
            if found is None:
                found = whole(path, content, "whole")  # its file as it was couldn't be read: all of it, marked so
        elif found is None:
            now_text = read_text(full_path(g.get("file_path"), cwd))
            edits = g.get("edits") if tool == "MultiEdit" and isinstance(g.get("edits"), list) else [g]
            found = []
            for edit in edits:
                if isinstance(edit, dict) and isinstance(edit.get("new_string"), str):
                    found += from_strings(path, edit.get("old_string") or "", edit["new_string"], now_text)
    elif tool == "NotebookEdit":
        path = shown(g.get("notebook_path"), cwd)
        mode = str(g.get("edit_mode") or "replace")
        lines = [] if mode == "delete" else [["+", x] for x in split_lines(g.get("new_source"))]
        found = [{"file": path, "kind": "notebook", "start": None, "old_start": None, "lines": lines,
                  "cell": one_line(g.get("cell_id"), 40) or None, "mode": mode if mode in ("replace", "insert", "delete") else "replace"}]
    elif tool == "apply_patch":
        found = from_patch(g, cwd)
    return [capped(h) for h in (found or [])]


# ---------- a Write's file as it was ----------

def stash_name(event):
    import hashlib
    tool_id = str(event.get("tool_use_id") or "")
    path = full_path((event.get("tool_input") or {}).get("file_path") if isinstance(event.get("tool_input"), dict) else "", event.get("cwd"))
    return hashlib.sha256(f"{event.get('session_id')}\0{tool_id}\0{path}".encode("utf-8", "replace")).hexdigest()[:32]


# ---------- the files ----------

class _Lock:
    """One writer at a time: the hooks of several steps, and serve.py, can write at once."""

    def __init__(self, path):
        self.path = path

    def __enter__(self):
        self.handle = open(self.path, "a")
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:  # Windows has no flock: a clash there costs one update at most
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


def read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            got = json.load(handle)
    except (OSError, ValueError):
        return None
    return got if isinstance(got, dict) else None


def write_json(path, data):
    """Whole, and readable by you alone, so the page never reads half a file."""
    part = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, separators=(",", ":"))
    os.replace(part, path)


def took_words(seconds):
    s = max(0, int(seconds or 0))
    if s < 5:
        return "a few seconds"
    if s < 60:
        return f"{s} seconds"
    m = s // 60
    return "a minute" if m == 1 else f"{m} minutes"


def note_words(text):
    """What a message was about, in a few words, for "I've got your note about ..."."""
    words = one_line(text, 400).split()
    short = " ".join(words[:7])
    return short + ("…" if len(words) > 7 else "")


ABOUT = ("What one conversation is doing, the steps it finished, the lines it changed, its to-do list and your messages "
         "to it (connect/live.py). Only for this computer and paired phones that control agents. Safe to delete.")


class Live:
    """data/live/: each conversation's file, and the index of them all."""

    def __init__(self, data=DATA):
        self.data = data
        self.root = os.path.join(data, "live")

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def read(self, key):
        if not isinstance(key, str) or not KEY.match(key):
            return None
        return read_json(self.path(key + ".json"))

    def index(self):
        got = read_json(self.path("index.json")) or {}
        rows = got.get("conversations")
        return rows if isinstance(rows, dict) else {}

    def edit(self, key, change, project=None, agent=None, now=None):
        """Changes one conversation's file under its lock: change(doc), then the index. Gives the file as written,
        or None for a key that isn't a conversation's."""
        if not isinstance(key, str) or not KEY.match(key):
            return None
        now = time.time() if now is None else now
        os.makedirs(self.root, mode=0o700, exist_ok=True)
        with _Lock(self.path(f".{key}.lock")):
            doc = self.read(key) or {"about": ABOUT, "key": key, "state": "working", "now": None, "steps": [], "changes": [],
                                     "todos": [], "messages": [], "hold": None, "asking": None, "n": 0}
            if project:
                doc["project"] = project
            if agent:
                doc["agent"] = agent
            if change(doc) is False:
                return doc
            doc["at"] = round(now, 2)
            fit(doc)
            write_json(self.path(key + ".json"), doc)
        self.list_it(key, doc, now)
        return doc

    def list_it(self, key, doc, now):
        """The index: a line for each conversation, and the files of those gone for twelve hours taken away."""
        with _Lock(self.path(".index.lock")):
            rows = self.index()
            rows[key] = summary(doc)
            for old in [k for k, row in rows.items() if not isinstance(row, dict) or now - float(row.get("at") or 0) > KEEP]:
                rows.pop(old, None)
                for name in (old + ".json", f".{old}.lock"):
                    try:
                        os.remove(self.path(name))
                    except OSError:
                        pass
            write_json(self.path("index.json"), {"about": "Each conversation's line, for the building (connect/live.py). Safe to delete.",
                                                 "at": round(now, 2), "conversations": rows})

    # ---------- the hook's side: steps ----------

    def begin(self, event, project, agent, now=None):
        """PreToolUse: the step under way. Before a Write, the file as it was, to compare with what is written."""
        now = time.time() if now is None else now
        tool = event.get("tool_name")
        kind, doing, _, files = what(tool, event.get("tool_input"), event.get("cwd"))
        if tool == "Write":
            self.stash(event)

        def change(doc):
            doc.update(state="working", now={"kind": kind, "tool": str(tool or ""), "words": doing, "files": files,
                                             "started_at": round(now, 2), "id": one_line(event.get("tool_use_id"), 80) or None})
        return self.edit(_key(event), change, project, agent, now)

    def finish(self, event, project, agent, now=None):
        """PostToolUse: a finished step, its changes and the to-do list."""
        now = time.time() if now is None else now
        tool = event.get("tool_name")
        g = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        kind, _, did, files = what(tool, g, event.get("cwd"))
        before = self.unstash(event) if tool == "Write" else None
        self.sweep()
        hunks = hunks_of(event, before)
        tool_id = one_line(event.get("tool_use_id"), 80) or None

        def change(doc):
            n = int(doc.get("n") or 0) + 1
            was = doc.get("now") if isinstance(doc.get("now"), dict) else {}
            started = was.get("started_at") if (tool_id and was.get("id") == tool_id) or (not tool_id and was.get("tool") == tool) else None
            response = event.get("tool_response")
            failed = isinstance(response, dict) and (response.get("interrupted") is True or response.get("is_error") is True)
            step = {"id": f"s{n}", "at": round(now, 2), "kind": kind, "tool": str(tool or ""), "words": did, "files": files,
                    "took": round(now - float(started), 1) if started else None, "failed": failed,
                    "hunks": len(hunks), "added": sum(h["added"] for h in hunks), "removed": sum(h["removed"] for h in hunks)}
            if len(hunks) > STEP_HUNKS:
                step["more"] = len(hunks) - STEP_HUNKS
            doc["n"] = n
            doc["steps"] = (doc.get("steps") or []) + [step]
            doc["changes"] = (doc.get("changes") or []) + [dict(h, step=step["id"], at=step["at"]) for h in hunks[:STEP_HUNKS]]
            todos(doc, tool, g)
            if tool == "AskUserQuestion":
                doc["asking"] = None
            doc.update(state="working", now={"kind": "thinking", "tool": "", "words": "Thinking about the next step", "files": [],
                                             "started_at": round(now, 2), "id": None})
        return self.edit(_key(event), change, project, agent, now)

    def moment(self, key, state, kind=None, words=None, project=None, agent=None, now=None, **more):
        """Anything else: thinking about your message, waiting for a permission, asking you, held, finished."""
        now = time.time() if now is None else now

        def change(doc):
            doc["state"] = state
            doc["now"] = {"kind": kind, "tool": "", "words": clean(words), "files": [], "started_at": round(now, 2), "id": None} if kind else None
            doc.update(more)
        return self.edit(key, change, project, agent, now)

    def todo_event(self, key, task_id, title=None, done=False, project=None, agent=None, now=None):
        """A task made or finished (Claude Code's TaskCreated and TaskCompleted)."""
        tid = one_line(task_id, 40)

        def change(doc):
            rows = [t for t in doc.get("todos") or [] if isinstance(t, dict)]
            row = next((t for t in rows if t.get("id") == f"t{tid}"), None)
            if row is None:
                row = {"id": f"t{tid}", "title": clean(title or "A task", 90), "state": "open"}
                rows.append(row)
            if done:
                row["state"] = "done"
            doc["todos"] = rows[-60:]
        return self.edit(key, change, project, agent, now)

    def stash(self, event):
        """Keeps the file a Write is about to replace, to compare with what it writes, if it is small and text."""
        g = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        path = full_path(g.get("file_path"), event.get("cwd"))
        if not path:
            return
        folder = self.path("before")
        os.makedirs(folder, mode=0o700, exist_ok=True)
        name = os.path.join(folder, stash_name(event))
        if not os.path.exists(path):
            text = NEW_FILE
        else:
            text = read_text(path, BEFORE_MOST)
            if text is None:
                return
        fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        self.sweep()

    def sweep(self, most=BEFORE_KEPT):
        """Copies left by a step that never ran (turned down, or its permission denied) go after a while: longer than
        any hook waits, so a step still waiting keeps its own."""
        folder = self.path("before")
        now = time.time()
        try:
            for other in os.listdir(folder):
                full = os.path.join(folder, other)
                if now - os.path.getmtime(full) > most:
                    os.remove(full)
        except OSError:
            pass

    def unstash(self, event):
        name = self.path("before", stash_name(event))
        try:
            with open(name, encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            return None
        finally:
            try:
                os.remove(name)
            except OSError:
                pass
        return text

    # ---------- messages ----------

    def posted(self, key, mid, text, reply=None, sent="queued", via="message", taken_words=None, project=None, now=None):
        """A message you sent it: queued for its next step, or taken at once (an agent started here, resumed)."""
        now = time.time() if now is None else now

        def change(doc):
            row = {"id": mid, "text": redact(one_line(text, MESSAGE_CHARS)), "at": round(now, 2), "via": via,
                   "state": "taken" if sent == "resumed" else "queued", "sent": sent, "reply": reply,
                   "taken_words": taken_words or f'I\'ve got your note about "{redact(note_words(text))}" and I\'m on it.'}
            if sent == "resumed":
                row["taken_at"] = round(now, 2)
            doc["messages"] = [m for m in doc.get("messages") or [] if isinstance(m, dict)][-(MESSAGES_KEPT - 1):] + [row]
        return self.edit(key, change, project, None, now)

    def taken(self, key, ids, mark=None, now=None):
        """The hook handed these messages to the agent. `mark` stands for the last thing it had said then, so what it
        says next can be known for its answer (replied)."""
        ids = {str(i) for i in ids if i}
        if not ids or not self.read(key):
            return None
        now = time.time() if now is None else now

        def change(doc):
            hit = False
            for m in doc.get("messages") or []:
                if isinstance(m, dict) and m.get("id") in ids and m.get("state") == "queued":
                    m.update(state="taken", taken_at=round(now, 2))
                    hit = True
            if hit:
                doc["said_mark"] = mark
            return hit
        return self.edit(key, change, now=now)

    def replied(self, key, said, mark):
        """What the agent has said since it was handed your messages, mid-turn: their answer, if it is new."""
        doc = self.read(key)
        if not said or not doc or mark == doc.get("said_mark") or not any(
                isinstance(m, dict) and m.get("state") == "taken" for m in doc.get("messages") or []):
            return None
        return self.answered(key, said)

    def answered(self, key, words, now=None):
        """What the agent said next answers the messages it was handed."""
        doc = self.read(key)
        if not doc or not any(isinstance(m, dict) and m.get("state") == "taken" for m in doc.get("messages") or []):
            return None
        now = time.time() if now is None else now
        said = clean(words, 600)

        def change(doc):
            for m in doc.get("messages") or []:
                if isinstance(m, dict) and m.get("state") == "taken":
                    m.update(state="answered", answered_at=round(now, 2), answer=said or None)
        return self.edit(key, change, now=now)


def _key(event):
    return "cc-" + re.sub(r"[^A-Za-z0-9]", "", str(event.get("session_id") or ""))[:12]


def todos(doc, tool, g):
    """The to-do list from TodoWrite (the whole list each time), Codex's update_plan, or TaskUpdate (one task)."""
    rows = [t for t in doc.get("todos") or [] if isinstance(t, dict)]
    states = {"pending": "open", "in_progress": "working", "completed": "done"}
    if tool in ("TodoWrite", "update_plan"):
        listed = g.get("todos") if tool == "TodoWrite" else g.get("plan")
        if isinstance(listed, list):
            rows = [t for t in rows if not str(t.get("id", "")).startswith("todo")]
            for i, todo in enumerate(listed[:60]):
                if isinstance(todo, dict) and todo.get("status") in states:
                    rows.append({"id": f"todo{i}", "title": clean(todo.get("content") or todo.get("step"), 90), "state": states[todo["status"]]})
    elif tool == "TaskUpdate":
        tid = one_line(g.get("taskId") or g.get("task_id"), 40)
        row = next((t for t in rows if t.get("id") == f"t{tid}"), None) if tid else None
        if tid and row is None and g.get("status") != "deleted":
            row = {"id": f"t{tid}", "title": clean(g.get("subject") or "A task", 90), "state": "open"}
            rows.append(row)
        if row is not None:
            if g.get("status") == "deleted":
                rows.remove(row)
            elif g.get("status") in states:
                row["state"] = states[g["status"]]
            if g.get("subject"):
                row["title"] = clean(g["subject"], 90)
    doc["todos"] = rows[-60:]


def fit(doc):
    """The size limits: the last steps, changes and messages, and the whole file under FILE_MOST."""
    doc["steps"] = [s for s in doc.get("steps") or [] if isinstance(s, dict)][-STEPS_KEPT:]
    doc["changes"] = [h for h in doc.get("changes") or [] if isinstance(h, dict)][-HUNKS_KEPT:]
    doc["messages"] = [m for m in doc.get("messages") or [] if isinstance(m, dict)][-MESSAGES_KEPT:]
    size = len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    while size > FILE_MOST and (doc["changes"] or doc["steps"]):
        drop = doc["changes"] if doc["changes"] else doc["steps"]
        gone = drop[: max(1, len(drop) // 4)]
        del drop[: len(gone)]
        size -= sum(len(json.dumps(x, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) + 1 for x in gone)


def summary(doc):
    """A conversation's line in the index: enough for its desk monitor and its card."""
    steps = doc.get("steps") or []
    last = steps[-1] if steps else None
    todo_rows = [t for t in doc.get("todos") or [] if isinstance(t, dict)]
    changes = [h for h in doc.get("changes") or [] if isinstance(h, dict)]
    messages = [m for m in doc.get("messages") or [] if isinstance(m, dict)]
    return {
        "project": doc.get("project"), "agent": doc.get("agent"), "state": doc.get("state"), "at": doc.get("at"),
        "now": doc.get("now"),
        "last": {k: last.get(k) for k in ("words", "at", "kind", "files")} if last else None,
        "todos": {"done": sum(1 for t in todo_rows if t.get("state") == "done"), "all": len(todo_rows),
                  "working": next((t.get("title") for t in todo_rows if t.get("state") == "working"), None)},
        "changed": {"files": len({h.get("file") for h in changes if h.get("file")}), "added": sum(int(h.get("added") or 0) for h in changes),
                    "removed": sum(int(h.get("removed") or 0) for h in changes)},
        "messages": [{k: m.get(k) for k in ("id", "state", "at", "taken_at", "answered_at", "reply", "taken_words", "via")} for m in messages[-5:]],
        "hold": doc.get("hold"), "hold_ended": doc.get("hold_ended"), "asking": doc.get("asking"),
    }


def by_file(doc):
    """Its changes so far, file by file, in the order it first changed each: [{file, added, removed, hunks}]."""
    files = {}
    for h in doc.get("changes") or []:
        if not isinstance(h, dict) or not h.get("file"):
            continue
        row = files.setdefault(h["file"], {"file": h["file"], "added": 0, "removed": 0, "hunks": []})
        row["added"] += int(h.get("added") or 0)
        row["removed"] += int(h.get("removed") or 0)
        row["hunks"].append(h)
    return list(files.values())


# ---------- what it says straight away ----------

def instant(doc, working, sent, permission=None, asking=False, hold=None, paused=False, now=None):
    """What an agent says the moment you send it a message, in its own words, from what the building can see:
    {"words", "when"}. `when` says when it will read the message: "now", "next_step", "after_permission",
    "as_answer", "when_resumed" or "next_turn"."""
    now = time.time() if now is None else now
    doc = doc or {}
    if sent == "resumed":
        return {"words": "Got it. I'd finished, so I'm starting again on this now.", "when": "now"}
    if paused:
        return {"words": "Got it. Every agent is paused from the building, so I'll read this once you resume us.", "when": "when_resumed"}
    state = (hold or {}).get("state") if isinstance(hold, dict) else None
    if state == "held":
        return {"words": "Got it. I'm holding, as you asked, so this reaches me straight away.", "when": "now"}
    if asking:
        return {"words": "Got it. I'm waiting for your answer to my question, so I'll take this as the answer.", "when": "as_answer"}
    if permission:
        return {"words": f"Got it. I'm waiting for your permission first ({clean(permission, 80)}). I'll read this at my next step, once that's answered.",
                "when": "after_permission"}
    if state == "asked":
        return {"words": "Got it. I'll hold at my next step, and this reaches me there.", "when": "next_step"}
    if not working:
        return {"words": "Got it. I've finished for now, so I'll read this when I next start work: the next time you send me "
                         "something in my own window.", "when": "next_turn"}
    step = doc.get("now") if isinstance(doc.get("now"), dict) else None
    if step and step.get("kind") not in (None, "thinking") and step.get("words"):
        since = took_words(now - float(step.get("started_at") or now))
        return {"words": f"Got it. I'm {first_lower(step['words'])} right now, {since} in. I'll pick this up as soon as that's done.",
                "when": "next_step"}
    return {"words": "Got it. I'm between steps, so I'll read this at my next one, in a moment.", "when": "next_step"}


# ---------- git diff of a floor's folder ----------

GIT_FILE = re.compile(r"^diff --git a/(.*?) b/(.*)$")
GIT_HUNK = re.compile(r"^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def git_run(folder, words, most=GIT_MOST, wait=GIT_WAIT):
    """(return code, output, cut) for git with fixed words in a folder from company.json, never through a shell,
    taking no locks and never asking for anything. None when git can't start."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C", "GIT_PAGER": "cat"}
    args = ["git", "-C", folder, "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", *words]
    try:
        proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
    except OSError:
        return None
    timer = threading.Timer(wait, proc.kill)
    timer.start()
    try:
        out = proc.stdout.read(most + 1)
        cut = len(out) > most
        if cut:
            proc.kill()
        proc.stdout.close()
        code = proc.wait()
    finally:
        timer.cancel()
    return (0 if cut else code), out[:most].decode("utf-8", "replace"), cut


def parse_git(text):
    """git diff's output as [{file, hunks}], in the same shape as an agent's changes."""
    files, hunk = [], None
    for raw in text.split("\n"):
        m = GIT_FILE.match(raw)
        if m:
            files.append({"file": m.group(2), "hunks": []})
            hunk = None
            continue
        if not files:
            continue
        m = GIT_HUNK.match(raw)
        if m:
            hunk = {"file": files[-1]["file"], "kind": "edit", "old_start": int(m.group(1)), "start": int(m.group(2)), "lines": []}
            files[-1]["hunks"].append(hunk)
            continue
        if hunk is not None and raw[:1] in ("+", "-", " "):
            hunk["lines"].append([raw[:1], raw[1:]])
        elif raw.startswith("Binary files"):
            files[-1]["binary"] = True
    for f in files:
        f["hunks"] = [capped(h, GIT_HUNK_LINES) for h in f["hunks"]]
        f["added"] = sum(h["added"] for h in f["hunks"])
        f["removed"] = sum(h["removed"] for h in f["hunks"])
    return files


def git_diff(folder, most=GIT_MOST, wait=GIT_WAIT):
    """Everything not yet committed in a floor's folder, by anyone: {"files", "untracked", "cut", "note"}, or
    {"note"} alone when it isn't a git repository. Only for a folder company.json names."""
    inside = git_run(folder, ["rev-parse", "--is-inside-work-tree"], 1000, wait)
    if inside is None:
        return {"files": [], "untracked": [], "cut": False, "note": "git isn't installed here, so only the agent's own changes show."}
    if inside[0] != 0 or inside[1].strip() != "true":
        return {"files": [], "untracked": [], "cut": False, "note": "This floor's folder isn't kept in git, so only the agent's own changes show."}
    note = None
    got = git_run(folder, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "HEAD", "--", "."], most, wait)
    if got is None or got[0] != 0:  # no commit yet: the changes waiting to be committed, and those not yet added
        got = git_run(folder, ["diff", "--no-color", "--no-ext-diff", "--no-textconv", "--", "."], most, wait)
        note = "This repository has no commits yet, so these are the changes not yet added."
    if got is None or got[0] != 0:
        return {"files": [], "untracked": [], "cut": False, "note": "git couldn't show the changes here."}
    untracked = git_run(folder, ["ls-files", "--others", "--exclude-standard", "--", "."], 64_000, wait)
    new = [redact(one_line(x, 300)) for x in (untracked[1].splitlines() if untracked and untracked[0] == 0 else []) if x.strip()]
    return {"files": parse_git(got[1]), "untracked": new[:UNTRACKED_MOST], "untracked_more": max(0, len(new) - UNTRACKED_MOST),
            "cut": got[2], "note": note}
