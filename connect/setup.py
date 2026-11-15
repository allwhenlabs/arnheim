#!/usr/bin/env python3
"""Connects Arnheim to your own work in one step.

  python3 connect/setup.py                 find your projects, make your building, connect Claude Code
  python3 connect/setup.py --yes           the same, taking every suggestion without asking
  python3 connect/setup.py --folder PATH   use this project folder instead of looking (give it again for more)
  python3 connect/setup.py --undo          take Arnheim's hooks out of Claude Code's settings again

It finds the folders your recent Claude Code and Codex conversations ran in, from the first lines of
each conversation's file (which name its folder), never from what was said in it. Each project
becomes a floor. It writes them to data/company.json, or adds them to the one there, and adds
Arnheim's hooks to Claude Code's settings (docs/connect.md, steps 1, 2 and 4), keeping a copy of each
file before it changes it. It asks before it changes anything, never changes your projects' files,
and running it twice changes nothing the second time. Standard library only, Python 3.7 or newer.
"""
import argparse
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.realpath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(ROOT, "data")
SCRIPT = os.path.join(HERE, "claude_code.py")
WINDOWS = os.name == "nt"
MOST = 12  # projects suggested at most, newest first

# Claude Code's moments that Arnheim hears (docs/connect.md, step 2), and the permission request that
# control answers (step 4). Without --control, nobody is waiting in the building, so a permission
# request is passed straight back and Claude Code asks as it always does.
EVENTS = ("SessionStart", "UserPromptSubmit", "PostToolUse", "Notification", "Stop", "TaskCreated",
          "TaskCompleted", "SessionEnd", "PermissionRequest")
TIMEOUTS = {"PermissionRequest": 150}
FEEDS = ["feeds/claude-code.json", "feeds/agents.json", "feeds/projects.json"]
ROOMS = [
    {"id": "work", "label": "Work", "about": "Tasks, and what an agent is waiting on you for. A desk glows amber when it needs you."},
    {"id": "conversations", "label": "Conversations", "about": "Claude Code conversations, a seat each. Someone sits in it while the agent works."},
    {"id": "code", "label": "Code", "about": "Unsaved changes as crates, and open pull requests as books."},
]
LOBBY = {
    "id": "front", "label": "Front of house",
    "about": "Where you come in. The receptionist sits at the desk and answers questions about the whole company.",
    "rooms": [
        {"id": "websites", "label": "Websites", "about": "Your websites, on a wall of screens. The receptionist sits at the desk here."},
        {"id": "email", "label": "Email", "about": "Your email addresses, as pigeonholes. Nothing here reads an inbox."},
        {"id": "social", "label": "Social media", "about": "Your social media accounts, a signboard each."},
        {"id": "domains", "label": "Domains", "about": "Your domain names, as brass plaques."},
    ],
}
RECEPTIONIST = {"name": "Iris", "title": "Receptionist", "voice": "af_heart",
                "look": {"skin": "#a26b48", "hair": "#2b1d18", "coat": "#5b3b5e", "shirt": "#f2ead8", "accent": "#d9b26a", "earrings": "studs"}}
ASSISTANT = {"name": "Wren", "title": "Your assistant", "voice": "bf_emma",
             "look": {"skin": "#deaa82", "hair": "#5a3926", "style": "bun", "coat": "#a8752b", "shirt": "#f4ecdf", "accent": "#e8c27a"}}
PYTHON = re.compile(r"^(python[\d.]*w?|py)(\.exe)?$", re.I)  # what runs Arnheim's connector in a hook
CATCH_ALL = (None, "", "*")  # a hook group's matcher that lets every tool, or every start, through


class Refused(Exception):
    """Something this can't safely go on with, in words for the person running it. Nothing was changed."""


def home():
    return os.path.realpath(os.path.expanduser("~"))


def claude_home():
    return os.path.expanduser(os.environ.get("CLAUDE_CONFIG_DIR") or os.path.join("~", ".claude"))


def codex_home():
    return os.path.expanduser(os.environ.get("CODEX_HOME") or os.path.join("~", ".codex"))


def shown(path):
    """A path as a person would write it: inside Arnheim's folder from there, else ~ for the home folder."""
    full, mine, here = os.path.realpath(path), home(), os.path.realpath(ROOT)
    if inside(full, here):
        return os.path.relpath(full, here).replace(os.sep, "/")
    return "~" + full[len(mine):] if full == mine or full.startswith(mine + os.sep) else full


def interpreter():
    """This Python, by the name that stays the same when it is upgraded (Homebrew's python3, say, rather
    than its python3.14), when that name leads to this same Python; else by its own path."""
    mine = os.path.realpath(sys.executable)
    for name in ("python3", "python"):
        found = shutil.which(name)
        if found and os.path.isabs(found) and os.path.realpath(found) == mine:
            return found
    return sys.executable


def inside(path, folder):
    path, folder = os.path.normcase(path), os.path.normcase(folder)
    return path != folder and path.startswith(folder.rstrip(os.sep) + os.sep)


# ---------- finding your projects ----------

def first_cwd(path, lines=40, most=1 << 20):
    """The folder a conversation ran in, from the first lines of its file only (a megabyte at most)."""
    read = 0
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            for _ in range(lines):
                row = handle.readline(max(1, most - read))
                if not row:
                    break
                read += len(row)
                try:
                    entry = json.loads(row)
                except ValueError:
                    entry = None
                if isinstance(entry, dict):
                    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
                    cwd = entry.get("cwd") or payload.get("cwd")
                    if isinstance(cwd, str) and cwd.strip():
                        return cwd
                if read >= most:
                    break
    except OSError:
        return None
    return None


def newest(paths, count):
    """The newest files first, with when each last changed."""
    dated = []
    for path in paths:
        try:
            dated.append((os.stat(path).st_mtime, path))
        except OSError:
            continue
    return sorted(dated, reverse=True)[:count]


def conversations():
    """(folder, when) for recent Claude Code and Codex conversations, newest first."""
    found = {}

    def seen(cwd, at):
        if cwd and at > found.get(cwd, 0):
            found[cwd] = at

    projects = os.path.join(claude_home(), "projects")
    try:
        names = os.listdir(projects)
    except OSError:
        names = []
    for name in names:  # one folder per place Claude Code ran; its newest conversation names it
        folder = os.path.join(projects, name)
        try:
            files = [os.path.join(folder, f) for f in os.listdir(folder) if f.endswith(".jsonl")]
        except OSError:
            continue
        for at, path in newest(files, 3):
            cwd = first_cwd(path)
            if cwd:
                seen(cwd, at)
                break
    sessions = os.path.join(codex_home(), "sessions")
    files = []
    for top, _dirs, names in os.walk(sessions):
        files.extend(os.path.join(top, f) for f in names if f.endswith(".jsonl"))
    for at, path in newest(files, 300):
        seen(first_cwd(path), at)
    return sorted(found.items(), key=lambda pair: -pair[1])


def root_of(folder):
    """The project a folder belongs to, and whether it is a git repository: the nearest folder above it
    (or itself) that git keeps, a git worktree counting as its main repository. Never the home folder
    or anything above it."""
    mine = home()
    here = path = os.path.realpath(os.path.expanduser(folder))
    while True:
        if path == mine or inside(mine, path) or os.path.dirname(path) == path:
            return here, False
        git = os.path.join(path, ".git")
        if os.path.isdir(git):
            return path, True
        if os.path.isfile(git):
            try:
                with open(git, encoding="utf-8", errors="replace") as handle:
                    pointer = handle.read(4096).strip()
            except OSError:
                pointer = ""
            target = pointer[len("gitdir:"):].strip() if pointer.startswith("gitdir:") else ""
            main = re.split(r"[\\/]\.git[\\/]worktrees[\\/]", target)
            if len(main) == 2:
                repo = os.path.realpath(os.path.join(path, main[0]))
                if os.path.isdir(repo):
                    return repo, True
            return path, True
        path = os.path.dirname(path)


def too_wide(path):
    """The home folder, a folder above it, or the top of a disk: never one project."""
    mine = home()
    return path == mine or inside(mine, path) or os.path.dirname(path) == path


def not_a_project(path):
    """Places that hold work but aren't a project: the home folder and above, temporary folders, and
    application or hidden folders in the home folder."""
    mine = home()
    if too_wide(path):
        return True
    if inside(path, mine):
        parts = os.path.relpath(path, mine).split(os.sep)
        return parts[0] in ("Library", "AppData") or any(p.startswith(".") for p in parts)
    temps = {tempfile.gettempdir(), "/tmp", "/var/tmp", "/var/folders"}
    return any(path == t or inside(path, t) for t in {os.path.realpath(t) for t in temps})


def find_projects(found=None):
    """[{folder, repo, at}] newest first: each recent conversation's project, if its folder is still there.
    A folder inside a repository folds into that repository; a plain folder that holds several projects
    is left out, since its projects are listed themselves."""
    roots = {}
    for cwd, at in (conversations() if found is None else found):
        if not os.path.isdir(os.path.expanduser(cwd)):
            continue  # moved or deleted since
        folder, repo = root_of(cwd)
        if not_a_project(folder):
            continue
        if folder not in roots or at > roots[folder]["at"]:
            roots[folder] = {"folder": folder, "repo": repo or roots.get(folder, {}).get("repo", False), "at": at}
    gone = set()
    for outer in sorted(roots, key=len):
        for inner in roots:
            if inner in gone or outer in gone or not inside(inner, outer):
                continue
            if roots[outer]["repo"]:
                roots[outer]["at"] = max(roots[outer]["at"], roots[inner]["at"])
                gone.add(inner)
            else:
                gone.add(outer)
    return sorted((p for f, p in roots.items() if f not in gone), key=lambda p: -p["at"])


# ---------- the building ----------

def label_of(folder):
    name = os.path.basename(os.path.normpath(folder)) or folder
    words = re.sub(r"[-_.]+", " ", name).strip() or name
    return (words[:1].upper() + words[1:])[:40]


def id_of(label, taken):
    base = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")[:32] or "project"
    floor, n = base, 2
    while floor in taken:
        floor, n = f"{base}-{n}", n + 1
    taken.add(floor)
    return floor


def written(folder):
    """A floor's folder as company.json keeps it: ~/... inside the home folder, so it reads as docs/connect.md writes it."""
    mine = home()
    if inside(folder, mine):
        return "~/" + os.path.relpath(folder, mine).replace(os.sep, "/")
    return folder


def floor_folders(floor):
    if not isinstance(floor, dict):
        return []
    folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
    return [os.path.realpath(os.path.expanduser(str(f))) for f in folders] if isinstance(folders, list) else []


def read_json(path, what):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            return json.load(handle)
    except FileNotFoundError:
        return None
    except ValueError as error:
        where = f" (line {error.lineno}, column {error.colno})" if hasattr(error, "lineno") else ""
        raise Refused(f"{what} isn't valid JSON{where}: {getattr(error, 'msg', error)}. Fix it, or move it somewhere "
                      "else, and run this again. Nothing was changed.")
    except OSError as error:
        raise Refused(f"{what} can't be read: {error.strerror or error}. Nothing was changed.")


def plan_company(folders, name):
    """(the company to write or None if nothing changes, [floors added], [folders already on a floor], whether it is new)."""
    path = os.path.join(DATA, "company.json")
    company = read_json(path, shown(path))
    new = company is None
    if new:
        company = {"company": name, "about": "Each floor is one of your projects.", "founder": {},
                   "receptionist": RECEPTIONIST, "assistant": ASSISTANT, "feeds": [], "rooms": ROOMS,
                   "floors": [], "lobby": LOBBY}
    if not isinstance(company, dict) or not isinstance(company.get("floors", []), list):
        raise Refused(f"{shown(path)} should be one object with a \"floors\" list. Fix it and run this again. Nothing was changed.")
    if company.get("sample"):
        raise Refused(f"{shown(path)} is still the made-up company: it says \"sample\". To start your own instead, move the "
                      "data folder somewhere else and run this again. If it is yours now, take out the \"sample\" line "
                      "first. Nothing was changed.")
    floors = company.setdefault("floors", [])
    taken = {str(f.get("id")) for f in [*floors, company.get("lobby"), company.get("basement")] if isinstance(f, dict)}
    rooms = company.get("rooms") if isinstance(company.get("rooms"), list) else []
    shared = {"work", "conversations", "code"} <= {r.get("id") for r in rooms if isinstance(r, dict)}
    there = [f for floor in floors for f in floor_folders(floor)]
    added, already = [], []
    for folder in folders:
        if any(folder == f or inside(folder, f) for f in there):
            already.append(folder)
            continue
        label = label_of(folder)
        floor = {"id": id_of(label, taken), "label": label, "about": f"The project in {written(folder)}.", "folder": written(folder)}
        if not shared:
            floor["rooms"] = ROOMS
        floors.append(floor)
        there.append(folder)
        added.append(floor)
    feeds = company.get("feeds") if isinstance(company.get("feeds"), list) else []
    missing = [f for f in FEEDS if f not in feeds]
    if not added and not missing:
        return None, added, already, new
    company["feeds"] = feeds + missing
    return company, added, already, new


# ---------- Claude Code's settings ----------

def hook_command(exe=None, script=None, windows=WINDOWS):
    """The command Claude Code runs: this Python and this copy's connector, quoted for its shell."""
    exe, script = exe or interpreter(), script or SCRIPT
    if windows:  # forward slashes in double quotes, as Git Bash (which Claude Code runs hooks with there) and cmd read them
        return " ".join('"%s"' % p.replace("\\", "/") for p in (exe, script))
    return " ".join(shlex.quote(p) for p in (exe, script))


def connector_of(command):
    """The connector a hook command runs, as written, if it is Arnheim's (any copy): a Python running
    connect/claude_code.py, with or without anything after it. Else None."""
    if not isinstance(command, str) or "claude_code.py" not in command:
        return None
    for text in (command, command.replace("\\", "/")):  # as written, then with Windows' backslashes as slashes
        try:
            words = shlex.split(text, posix=not WINDOWS)
        except ValueError:
            words = text.split()
        words = [w.strip("'\"") for w in words]
        for n, word in enumerate(words[1:], 1):
            path = word.replace("\\", "/")
            if (path == "connect/claude_code.py" or path.endswith("/connect/claude_code.py")) and \
                    any(PYTHON.match(os.path.basename(w.replace("\\", "/"))) for w in words[:n]):
                return word
    return None


def absolute(path):
    return os.path.isabs(os.path.expanduser(path)) or bool(re.match(r"^[A-Za-z]:[\\/]", path))


def same_file(a, b):
    norm = lambda p: os.path.normcase(os.path.realpath(os.path.expanduser(p.replace("/", os.sep) if WINDOWS else p)))
    return norm(a) == norm(b)


def settings_path():
    return os.path.join(claude_home(), "settings.json")


def read_settings():
    path = settings_path()
    settings = read_json(path, shown(path))
    if settings is None:
        return path, None
    if not isinstance(settings, dict):
        raise Refused(f"{shown(path)} should be one object, between {{ and }}. Fix it and run this again. Nothing was changed.")
    hooks = settings.get("hooks", {})
    if not isinstance(hooks, dict) or any(not isinstance(v, list) for v in hooks.values()):
        raise Refused(f"In {shown(path)}, \"hooks\" should be an object of lists, as Claude Code's docs show. Fix it and "
                      "run this again. Nothing was changed.")
    return path, settings


def plan_hooks(settings):
    """(the settings to write or None, [events added], [(event, command) replaced]). This copy's hook only
    for some tools (a matcher), or by a relative path that works in one folder only, is replaced by one for
    everything. Refuses when another copy of Arnheim already has hooks there."""
    settings = json.loads(json.dumps(settings or {}))
    hooks = settings.setdefault("hooks", {})
    command, added, replaced, others = hook_command(), [], [], set()
    for event in EVENTS:
        groups, covered = [], False
        for group in hooks.get(event, []):
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                groups.append(group)
                continue
            kept = []
            for hook in group["hooks"]:
                found = connector_of(hook.get("command") if isinstance(hook, dict) else None)
                if not found:
                    kept.append(hook)
                elif absolute(found) and not same_file(found, SCRIPT):
                    others.add(found)
                    kept.append(hook)
                elif absolute(found) and group.get("matcher") in CATCH_ALL:
                    covered = True
                    kept.append(hook)
                else:
                    replaced.append((event, hook["command"]))
            if kept or not group["hooks"]:
                groups.append(group if len(kept) == len(group["hooks"]) else {**group, "hooks": kept})
        if not covered:
            hook = {"type": "command", "command": command}
            if event in TIMEOUTS:
                hook["timeout"] = TIMEOUTS[event]
            groups.append({"hooks": [hook]})
            added.append(event)
        if event in hooks or groups:
            hooks[event] = groups
    if others:
        raise Refused("Claude Code already tells another copy of Arnheim what happens, at " + ", ".join(sorted(others))
                      + ". Run python3 connect/setup.py --undo to take those hooks out, then run this again here. Nothing was changed.")
    return (settings if added or replaced else None), added, replaced


def connected_by_hand(folders):
    """The projects' own .claude/settings.json files that already run Arnheim's hooks: with these added
    too, Claude Code would tell the building everything twice in those projects."""
    found = []
    for folder in folders:
        path = os.path.join(folder, ".claude", "settings.json")
        try:
            with open(path, encoding="utf-8-sig") as handle:
                hooks = json.load(handle).get("hooks")
        except (OSError, ValueError, AttributeError):
            continue
        if isinstance(hooks, dict) and any(
                isinstance(h, dict) and connector_of(h.get("command"))
                for groups in hooks.values() if isinstance(groups, list)
                for g in groups if isinstance(g, dict) and isinstance(g.get("hooks"), list)
                for h in g["hooks"]):
            found.append(path)
    return found


def take_out(settings):
    """(the settings without any of Arnheim's hooks, [(event, command) taken out]). Everything else stays."""
    settings = json.loads(json.dumps(settings))
    hooks = settings.get("hooks") or {}
    taken = []
    for event in list(hooks):
        kept_groups, here = [], len(taken)
        for group in hooks[event]:
            if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                kept_groups.append(group)
                continue
            kept = []
            for hook in group["hooks"]:
                if isinstance(hook, dict) and connector_of(hook.get("command")):
                    taken.append((event, hook["command"]))
                else:
                    kept.append(hook)
            if len(kept) == len(group["hooks"]):
                kept_groups.append(group)  # none of Arnheim's in it: as it was
            elif kept:
                kept_groups.append({**group, "hooks": kept})
        if len(taken) == here:
            continue  # nothing of Arnheim's under this event: left exactly as it was
        if kept_groups:
            hooks[event] = kept_groups
        else:
            del hooks[event]
    if "hooks" in settings and not hooks and taken:
        del settings["hooks"]
    return settings, taken


# ---------- writing ----------

def stamp():
    return time.strftime("%Y%m%d-%H%M%S")


def keep_copy(path, into):
    """A copy of a file before it changes, in the folder given, with its permissions. Gives its path."""
    os.makedirs(into, exist_ok=True)
    name, ext = os.path.splitext(os.path.basename(path))
    copy = os.path.join(into, f"{name}.before-arnheim-{stamp()}{ext}")
    n = 2
    while os.path.exists(copy):
        copy = os.path.join(into, f"{name}.before-arnheim-{stamp()}-{n}{ext}")
        n += 1
    shutil.copy2(path, copy)
    return copy


def indent_of(path):
    """How a JSON file is indented, so a rewrite keeps its look: a tab, a number of spaces, or None for one line."""
    try:
        with open(path, encoding="utf-8-sig") as handle:
            text = handle.read(1 << 20)
    except OSError:
        return 2
    found = re.search(r"\n([ \t]+)\S", text)
    if not found:
        return None if text.strip() and "\n" not in text.strip() else 2
    return "\t" if found.group(1).startswith("\t") else len(found.group(1))


def write_all(changes, copies):
    """Writes every file, or none: each is written whole beside itself first (through a link, to what it
    links to, keeping its permissions), and a copy of each in `copies` (path to the folder it goes in) is
    kept, before any file is replaced. Gives {path: its copy}. Anything that fails leaves nothing behind."""
    made, folders, kept, staged, done = [], [], {}, [], []
    try:
        for path, folder in copies.items():
            if not os.path.isdir(folder):
                folders.append(folder)
            kept[path] = keep_copy(os.path.realpath(path), folder)
            made.append(kept[path])
        for path, value in changes:
            real = os.path.realpath(path)
            os.makedirs(os.path.dirname(real), exist_ok=True)
            part = f"{real}.{os.getpid()}.part"
            made.append(part)
            with open(part, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=indent_of(real))
                handle.write("\n")
            if os.path.exists(real):
                shutil.copymode(real, part)
            staged.append((part, real))
        for part, real in staged:
            before = next((kept[p] for p in kept if os.path.realpath(p) == real), None)
            os.replace(part, real)
            done.append((real, before))
    except OSError as error:
        for real, before in reversed(done):  # put back what was already replaced
            try:
                shutil.copy2(before, real) if before else os.remove(real)
            except OSError:
                pass
        for path in made:
            try:
                os.remove(path)
            except OSError:
                pass
        for folder in folders:
            try:
                os.rmdir(folder)  # a copies folder this made, now empty again
            except OSError:
                pass
        where = shown(error.filename) if getattr(error, "filename", None) else "a file"
        raise Refused(f"{where} can't be written: {error.strerror or error}. Nothing was changed.")
    return kept


# ---------- talking to you ----------

def ago(at, now=None):
    days = int(((now or time.time()) - at) // 86400)
    return "today" if days < 1 else "yesterday" if days == 1 else f"{days} days ago"


def ask(question, default=""):
    try:
        said = input(question).strip()
    except EOFError:
        raise Refused("Stopped before changing anything.")
    return said or default


def pick(found):
    """The projects you choose from those found: Enter takes them all; numbers take some; a path adds one."""
    chosen = list(found)
    while True:
        said = ask("Press Enter to give each of these a floor, or type the numbers you want (like 1 3), or a folder to add: ")
        if not said:
            return chosen
        if re.fullmatch(r"[\d\s,]+", said):
            numbers = [int(n) for n in re.findall(r"\d+", said)]
            wrong = [n for n in numbers if not 1 <= n <= len(found)]
            if wrong:
                print(f"There is no {wrong[0]} in the list. Try again.")
                continue
            return [found[n - 1] for n in dict.fromkeys(numbers)]
        folder = os.path.realpath(os.path.expanduser(said.strip("'\"")))
        if not os.path.isdir(folder) or too_wide(folder):
            print(f"There is no folder at {said}. Try again." if not os.path.isdir(folder) else
                  f"{said} holds everything, not one project. Give a project's own folder.")
            continue
        found.append({"folder": folder, "repo": os.path.isdir(os.path.join(folder, ".git")), "at": time.time()})
        chosen = list(found)
        listing(found)


def listing(projects):
    width = max([len(label_of(p["folder"])) for p in projects] + [4])
    for n, p in enumerate(projects, 1):
        print(f"  {n:>2}. {label_of(p['folder']):<{width}}  {shown(p['folder'])}  ({ago(p['at'])})")


def claude_code_here():
    return bool(shutil.which("claude")) or os.path.isdir(claude_home())


def undo():
    path, settings = read_settings()
    if settings is None:
        print(f"There are no Claude Code settings at {shown(path)}, so there is nothing to take out.")
        return 0
    out, taken = take_out(settings)
    if not taken:
        print(f"Claude Code's settings ({shown(path)}) have none of Arnheim's hooks: nothing changed.")
    else:
        copy = write_all([(path, out)], {path: os.path.dirname(os.path.realpath(path))})[path]
        print(f"Took Arnheim's hooks out of {shown(path)}:")
        commands = {}
        for event, command in taken:
            commands.setdefault(command, []).append(event)
        for command, events in commands.items():
            print(f"  {command}")
            print(f"    for {', '.join(events)}")
        print(f"Every other setting and hook in it is as it was. The file as it was before is at {shown(copy)}.")
    print("Your building, data/company.json, is left as it is. Delete the data folder to go back to the made-up company.")
    return 0


def setup(args):
    if args.folder:
        projects = []
        for given in args.folder:
            folder = os.path.realpath(os.path.expanduser(given))
            if not os.path.isdir(folder):
                raise Refused(f"There is no folder at {given}. Nothing was changed.")
            if too_wide(folder):
                raise Refused(f"{given} holds everything, not one project. Give a project's own folder. Nothing was changed.")
            projects.append({"folder": folder, "repo": os.path.isdir(os.path.join(folder, ".git")), "at": time.time()})
    else:
        print("Looking for the projects you have worked on with Claude Code or Codex...")
        projects = find_projects()[:MOST]
        if projects:
            print(f"Found {len(projects)}, the most recent first:")
            listing(projects)
        else:
            print("Found none: no recent conversation ran in a project folder that is still there.")
        if not args.yes:
            projects = pick(projects) if projects else []
            while not projects:
                said = ask("Type a project's folder to give it a floor, or press Enter to stop: ")
                if not said:
                    raise Refused("Stopped before changing anything.")
                folder = os.path.realpath(os.path.expanduser(said.strip("'\"")))
                if too_wide(folder):
                    print(f"{said} holds everything, not one project. Give a project's own folder.")
                elif os.path.isdir(folder):
                    projects.append({"folder": folder, "repo": os.path.isdir(os.path.join(folder, ".git")), "at": time.time()})
                else:
                    print(f"There is no folder at {said}. Try again.")
    company_path = os.path.join(DATA, "company.json")
    if not projects and not os.path.exists(company_path):
        raise Refused("There is no project to give a floor. Name one: python3 connect/setup.py --folder ~/code/my-project")
    name = args.name or ("My company" if args.yes or os.path.exists(company_path)
                         else ask("What should your building be called? (Enter for \"My company\") ", "My company"))
    company, added, already, new = plan_company([p["folder"] for p in projects], name)
    hooks_on = not args.no_hooks and claude_code_here()
    settings_file, settings = read_settings() if hooks_on else (settings_path(), None)
    new_settings, events, replaced = plan_hooks(settings) if hooks_on else (None, [], [])
    twice = connected_by_hand([p["folder"] for p in projects]) if new_settings else []

    print()
    if not company and not new_settings:
        for folder in already:
            print(f"  {shown(folder)} already has a floor.")
        print("Everything is already set up: nothing changed.")
        return 0
    print("This will:")
    if company and new:
        print(f"  - write {shown(company_path)}: a building called \"{company['company']}\" with a floor for each of "
              f"these {len(added)} projects, and a receptionist, Iris, at the front desk")
    elif company and added:
        print(f"  - add {len(added)} floor{'s' if len(added) != 1 else ''} to {shown(company_path)}, after keeping a copy in data/backups/")
    elif company:
        print(f"  - add the connectors' files to \"feeds\" in {shown(company_path)}, after keeping a copy in data/backups/")
    if new_settings:
        print(f"  - add Arnheim's hooks to Claude Code's settings, {shown(settings_file)}"
              f"{', after keeping a copy beside it' if settings is not None else ''}. They tell the building when a "
              "conversation starts, works, needs you and finishes. They change nothing Claude does unless you start "
              "Arnheim with --control")
    for event, command in replaced:
        print(f"  - replace Arnheim's {event} hook there, which runs only for some tools or only from one folder: {command}")
    print("  It never changes your projects' files.")
    for path in twice:
        print(f"  Note: {shown(path)} runs Arnheim's hooks too, so Claude Code would tell the building everything twice "
              "in that project. Take them out of that file afterwards: this only changes your own settings.")
    if not args.yes and ask("Go ahead? [Y/n] ", "y").lower() not in ("y", "yes"):
        raise Refused("Stopped before changing anything.")

    print()
    changes = ([(company_path, company)] if company else []) + ([(settings_file, new_settings)] if new_settings else [])
    copies = {}
    if company and not new:
        copies[company_path] = os.path.join(DATA, "backups")
    if new_settings and settings is not None:
        copies[settings_file] = os.path.dirname(os.path.realpath(settings_file))
    kept = write_all(changes, copies)
    if company:
        copy = kept.get(company_path)
        print(f"Wrote {shown(company_path)}{f' (as it was before: {shown(copy)})' if copy else ''}:")
        for floor in added:
            print(f"  + {floor['label']}  {floor['folder']}")
        for folder in already:
            print(f"  {shown(folder)} already had a floor.")
    if new_settings:
        copy = kept.get(settings_file)
        print(f"Added to {shown(settings_file)}{f' (as it was before: {shown(copy)})' if copy else ''}, for "
              f"{', '.join(events) or 'the hooks it replaced'}:")
        print(f"  {hook_command()}")
        if (settings or {}).get("disableAllHooks") is True:
            print("  Note: this file says \"disableAllHooks\": true, so Claude Code runs none of them until you take that out.")
        if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
            print("  Note: you ran this with a virtual environment's Python, which the hooks now use. Keep that environment, "
                  "or run this again with your system's Python.")
    elif hooks_on:
        print(f"Claude Code's settings ({shown(settings_file)}) already have Arnheim's hooks.")
    elif not args.no_hooks:
        print("Claude Code doesn't seem to be on this computer (there is no claude command and no ~/.claude folder), so no "
              "hooks were added. Install it from https://claude.com/claude-code, then run python3 connect/setup.py again.")
    print()
    print(f"Next: {'py' if WINDOWS else 'python3'} serve.py, then open http://127.0.0.1:8740 (already running? Reload the page).")
    print("Conversations you start in these folders from now on show in the building. To have it prove an agent's work by "
          "running a project's tests, give its floor a check (docs/connect.md, step 5).")
    print("To take the hooks out again: python3 connect/setup.py --undo")
    return 0


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")  # a folder's name the console can't show never stops it
        except (AttributeError, ValueError):
            pass
    parser = argparse.ArgumentParser(description="Connects Arnheim to your own projects and Claude Code, in one step.")
    parser.add_argument("--yes", action="store_true", help="take every suggestion without asking")
    parser.add_argument("--folder", action="append", metavar="PATH", help="use this project folder instead of looking (give it again for more)")
    parser.add_argument("--name", help="what the building is called, if it is new (My company if left out)")
    parser.add_argument("--no-hooks", action="store_true", help="only make the building: leave Claude Code's settings alone")
    parser.add_argument("--undo", action="store_true", help="take Arnheim's hooks out of Claude Code's settings")
    args = parser.parse_args(argv)
    try:
        return undo() if args.undo else setup(args)
    except Refused as why:
        print(why, file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
