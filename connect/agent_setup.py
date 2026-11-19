#!/usr/bin/env python3
"""Sets your agents up well, both at once (docs/connect.md, step 23).

connect/setup.py offers this once it has connected your projects (`--well` does it without asking), and
the page offers it in Connect my agents and in Settings, through serve.py's /setup/. For each project it
looks at a few of the project's own files (never .env, keys or anything private) to say what it is: its
language, package manager, how its tests run, how it builds, and its main folders. Then it offers five
things, each shown before anything changes:

1. One instructions file both agents read. Codex reads AGENTS.md; Claude Code reads CLAUDE.md, which can
   bring another file in with an `@path` line. With neither, it writes a short AGENTS.md from what it found
   and a CLAUDE.md that is only `@AGENTS.md`. With AGENTS.md alone, it adds that CLAUDE.md. With CLAUDE.md
   alone, nothing in the project changes: Codex is told to read CLAUDE.md where a folder has no AGENTS.md
   (project_doc_fallback_filenames, in its config.toml). With both and neither bringing in the other, it
   offers one line, `@AGENTS.md`, at the end of CLAUDE.md.
2. The floor's check (connect/prove.py), from the project's own test command, only when it is sure of it.
3. Claude Code's deny rules for .env files, keys and the folders that hold your logins, in your own
   settings, once for every project. Codex's only way is a beta permission profile that replaces its
   whole sandbox, so that stays yours to choose.
4. Claude Code may run the check without asking: one exact rule in the project's own
   .claude/settings.local.json, kept out of git by the repository's .git/info/exclude. Codex runs it in
   its sandbox without asking already, and its rules would take a command out of that sandbox.
5. The same MCP servers in both, through each agent's own command, for servers that carry no keys.

Everything it changes is written down in data/.secrets/agent-setup.json (never served, readable by you
alone), with each file as it was, so
`python3 connect/setup.py --undo` and the page's Undo put each file back byte for byte. A file changed
since only loses what this added. Running it again changes nothing. It never runs Claude Code or Codex
themselves, only their `mcp` commands when you choose to share servers. Standard library only.
"""
import base64
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time

try:
    from . import secret_scan, standing  # as connect.agent_setup, from serve.py
except ImportError:
    import secret_scan  # beside this file, as connect/setup.py has it
    import standing

RECORD = os.path.join(".secrets", "agent-setup.json")  # in the data folder: what this changed, and each file as it was
# The record holds whole copies of agents' settings files, which can hold tokens, so it lives in data/.secrets/:
# a hidden folder serve.py never serves (to this computer, a phone, --lan or --share), readable by you alone.
ABOUT = ("What setting your agents up well changed, with each file as it was, so Undo can put it back "
         "(connect/agent_setup.py). Undo deletes it.")
ITEMS = ("instructions", "check", "allow")  # each project's own; secrets and mcp are once for everyone
CHECK_LABEL = "The tests"
PLACEHOLDER = "no test specified"  # npm init's test script, which only fails
SKIP = {"node_modules", "vendor", "dist", "build", "target", "out", "coverage", "venv", "env", "__pycache__",
        "Pods", "DerivedData", "obj", "tmp", "temp", "logs"}
MOST_FOLDERS = 8
NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")  # an MCP server name both agents take as it is
TIMEOUT = 30  # seconds for each git or mcp command

# Claude Code's deny rules (code.claude.com/docs/en/permissions, "Read and Edit"). A plain name matches at any
# depth under the folder Claude works in; ~/ is the home folder. A Read rule also stops Edit and Write there.
DENY = [
    "Read(**/.env)", "Read(**/.env.*)",
    "Read(**/*.pem)", "Read(**/*.key)", "Read(**/*.p12)", "Read(**/*.pfx)",
    "Read(**/id_rsa*)", "Read(**/id_ed25519*)", "Read(**/id_ecdsa*)",
    "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(~/.gnupg/**)", "Read(~/.config/gcloud/**)", "Read(~/.azure/**)",
    "Read(~/.kube/**)", "Read(~/.docker/config.json)", "Read(~/.netrc)", "Read(~/.npmrc)", "Read(~/.pypirc)",
    "Read(~/.git-credentials)", "Read(~/.config/gh/hosts.yml)", "Read(~/.codex/auth.json)",
]
LOCAL = os.path.join(".claude", "settings.local.json")
FALLBACK_KEY = "project_doc_fallback_filenames"
FALLBACK_NOTE = "# Arnheim: Codex reads CLAUDE.md in a folder that has no AGENTS.md (connect/agent_setup.py)"


# ---------- small helpers ----------

def read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def read_text(path, most=400_000):
    raw = read_bytes(path)
    return None if raw is None else raw[:most].decode("utf-8", "replace")


def sha(raw):
    return hashlib.sha256(raw or b"").hexdigest()


def write_bytes(path, raw):
    """Writes a whole file beside itself and moves it into place (through a link, to what it links to),
    keeping its permissions. Gives the folders it had to make, so undo can take them away again."""
    real = os.path.realpath(path)
    made, folder = [], os.path.dirname(real)
    while not os.path.isdir(folder):
        made.append(folder)
        folder = os.path.dirname(folder)
    for folder in reversed(made):
        os.mkdir(folder)
    part = f"{real}.{os.getpid()}.part"
    with open(part, "wb") as handle:
        handle.write(raw)
    if os.path.exists(real):
        shutil.copymode(real, part)
    os.replace(part, real)
    return made


def remove(path, made=()):
    try:
        os.remove(os.path.realpath(path))
    except OSError:
        pass
    for folder in made:  # deepest first, as they were made
        try:
            os.rmdir(folder)
        except OSError:
            pass


def dumped(value, indent):
    return (json.dumps(value, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")


def command_text(run):
    return " ".join(shlex.quote(w) for w in run)


def run_quiet(args, cwd=None):
    """(exit code, what it printed), or (None, why) when it couldn't start. Never a shell."""
    try:
        done = subprocess.run(args, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=TIMEOUT)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        return None, str(getattr(error, "strerror", None) or error)
    return done.returncode, (done.stdout or "") + (done.stderr or "")


def has_git(folder):
    return os.path.exists(os.path.join(folder, ".git"))


# ---------- what the project is ----------

def load_json(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def make_targets(folder):
    for name in ("GNUmakefile", "makefile", "Makefile"):
        text = read_text(os.path.join(folder, name), 200_000)
        if text is not None:
            return set(re.findall(r"^([A-Za-z0-9_.-]+)\s*:(?!=)", text, re.M))
    return set()


def main_folders(folder):
    """The project's main folders: those git keeps at its top, or else the plain folders there."""
    names = []
    if has_git(folder):
        code, said = run_quiet(["git", "-C", folder, "ls-tree", "-d", "--name-only", "HEAD"])
        if code == 0:
            names = [n.strip() for n in said.splitlines() if n.strip()]
    if not names:
        try:
            names = [n for n in os.listdir(folder) if os.path.isdir(os.path.join(folder, n))]
        except OSError:
            names = []
    # Only plain names: they go into AGENTS.md, which agents read as instructions, so a name can't carry words in.
    return sorted(n for n in names if re.match(r"^[\w][\w.+-]{0,63}$", n) and n not in SKIP)[:MOST_FOLDERS]


def python_tests(folder):
    """How a Python project runs its tests, when it says so: pytest's own settings, or unittest's files."""
    pyproject = read_text(os.path.join(folder, "pyproject.toml")) or ""
    setup_cfg = read_text(os.path.join(folder, "setup.cfg")) or ""
    tox = read_text(os.path.join(folder, "tox.ini")) or ""
    if ("[tool.pytest" in pyproject or "[tool:pytest]" in setup_cfg or "[pytest]" in tox
            or os.path.isfile(os.path.join(folder, "pytest.ini"))
            or os.path.isfile(os.path.join(folder, "conftest.py"))
            or os.path.isfile(os.path.join(folder, "tests", "conftest.py"))):
        return "pytest"
    tests = os.path.join(folder, "tests")
    try:
        files = [f for f in os.listdir(tests) if f.startswith("test") and f.endswith(".py")]
    except OSError:
        return None
    said = "".join(read_text(os.path.join(tests, f), 20_000) or "" for f in files[:20])
    if files and re.search(r"^\s*import unittest|^\s*from unittest\b", said, re.M) and "pytest" not in said:
        return "unittest"
    return None


def detect(folder):
    """What the project is, from its own files: {languages, managers, test, build, lint, folders}. Each
    command is a list, or None when the files don't say it plainly. Nothing is guessed."""
    exists = lambda *p: os.path.exists(os.path.join(folder, *p))
    langs, managers, test, build, lint = [], [], None, None, None

    def add(where, word):
        if word and word not in where:
            where.append(word)

    targets = make_targets(folder)
    if "test" in targets:
        test = ["make", "test"]
    if "build" in targets:
        build = ["make", "build"]
    package = load_json(os.path.join(folder, "package.json"))
    if package is not None:
        deps = {**(package.get("dependencies") or {}), **(package.get("devDependencies") or {})} \
            if isinstance(package.get("dependencies") or {}, dict) and isinstance(package.get("devDependencies") or {}, dict) else {}
        add(langs, "TypeScript" if exists("tsconfig.json") or "typescript" in deps else "JavaScript")
        tool = ("pnpm" if exists("pnpm-lock.yaml") else "yarn" if exists("yarn.lock")
                else "bun" if exists("bun.lockb") or exists("bun.lock") else "npm")
        add(managers, tool)
        scripts = package.get("scripts") if isinstance(package.get("scripts"), dict) else {}
        said = scripts.get("test")
        if test is None and isinstance(said, str) and said.strip() and PLACEHOLDER not in said:
            test = ["bun", "run", "test"] if tool == "bun" else [tool, "test"]
        run = lambda name: [tool, name] if tool == "yarn" else [tool, "run", name]
        if build is None and isinstance(scripts.get("build"), str) and scripts["build"].strip():
            build = run("build")
        if isinstance(scripts.get("lint"), str) and scripts["lint"].strip():
            lint = run("lint")
    if any(exists(f) for f in ("pyproject.toml", "setup.py", "setup.cfg", "requirements.txt", "Pipfile")):
        add(langs, "Python")
        tool = ("uv" if exists("uv.lock") else "Poetry" if exists("poetry.lock")
                else "Pipenv" if exists("Pipfile") else "pip" if exists("requirements.txt") else None)
        add(managers, tool)
        kind = python_tests(folder)
        if test is None and kind == "pytest":
            test = {"uv": ["uv", "run", "pytest"], "Poetry": ["poetry", "run", "pytest"],
                    "Pipenv": ["pipenv", "run", "pytest"]}.get(tool, ["python3", "-m", "pytest"])
        elif test is None and kind == "unittest":
            test = ["python3", "-m", "unittest", "discover", "-s", "tests"]
    simple = [("go.mod", "Go", "Go modules", ["go", "test", "./..."], ["go", "build", "./..."]),
              ("Cargo.toml", "Rust", "Cargo", ["cargo", "test"], ["cargo", "build"]),
              ("Package.swift", "Swift", "Swift Package Manager", ["swift", "test"], ["swift", "build"]),
              ("mix.exs", "Elixir", "Mix", ["mix", "test"], ["mix", "compile"])]
    for marker, lang, tool, tests, builds in simple:
        if exists(marker):
            add(langs, lang)
            add(managers, tool)
            test, build = test or tests, build or builds
    gradle = next((f for f in ("build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle") if exists(f)), None)
    if gradle:
        add(langs, "Kotlin" if gradle.endswith(".kts") or exists("src", "main", "kotlin") else "Java")
        add(managers, "Gradle")
        runner = "./gradlew" if exists("gradlew") else "gradle"
        test, build = test or [runner, "test"], build or [runner, "build"]
    if exists("pom.xml"):
        add(langs, "Java")
        add(managers, "Maven")
        runner = "./mvnw" if exists("mvnw") else "mvn"
        test, build = test or [runner, "test"], build or [runner, "package"]
    if exists("Gemfile"):
        add(langs, "Ruby")
        add(managers, "Bundler")
        if test is None and (exists(".rspec") or exists("spec")):
            test = ["bundle", "exec", "rspec"]
    try:
        top = os.listdir(folder)
    except OSError:
        top = []
    if any(f.endswith((".sln", ".csproj")) for f in top):
        add(langs, "C#")
        add(managers, ".NET")
        test, build = test or ["dotnet", "test"], build or ["dotnet", "build"]
    deno = load_json(os.path.join(folder, "deno.json")) or load_json(os.path.join(folder, "deno.jsonc"))
    if deno is not None:
        add(langs, "TypeScript")
        add(managers, "Deno")
        if test is None and isinstance(deno.get("tasks"), dict) and "test" in deno["tasks"]:
            test = ["deno", "task", "test"]
    if exists("CMakeLists.txt"):
        add(langs, "C or C++")
        add(managers, "CMake")
    return {"languages": langs, "managers": managers, "test": test, "build": build, "lint": lint,
            "folders": main_folders(folder)}


def agents_text(label, found):
    """A short AGENTS.md: only what the project's own files say, and the one rule that makes done mean proven."""
    lines = [f"# {label}", "",
             "Instructions for the coding agents that work here. Codex reads this file, and Claude Code reads it "
             "through CLAUDE.md. Arnheim wrote it from the project's own files: change anything that isn't right.", ""]
    facts = []
    if found["languages"]:
        facts.append(f"- Language: {', '.join(found['languages'])}")
    if found["managers"]:
        facts.append(f"- Package manager: {', '.join(found['managers'])}")
    if found["folders"]:
        facts.append("- Main folders: " + ", ".join(f"`{f}/`" for f in found["folders"]))
    if facts:
        lines += ["## The project", ""] + facts + [""]
    commands = [(name, found[key]) for name, key in (("Test", "test"), ("Build", "build"), ("Lint", "lint")) if found[key]]
    if commands:
        lines += ["## Commands", ""] + [f"- {name}: `{command_text(run)}`" for name, run in commands] + [""]
    if found["test"]:
        lines += ["## Before you say it is done", "",
                  f"Run `{command_text(found['test'])}` and say whether it passed. A change counts as done only once it does.", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


# ---------- 1. one instructions file ----------

def plain_text(text):
    """Markdown without its code: Claude Code reads no @import inside code spans or fenced blocks."""
    text = re.sub(r"^(```|~~~).*?^\1[^\n]*$", "", text, flags=re.M | re.S)
    return re.sub(r"`[^`\n]*`", "", text)


def brings_in(text, name, prefix=""):
    """Whether a file's text brings in `name` with an @path line, as Claude Code reads it."""
    return bool(re.search(r"(?:^|\s)@(?:\./)?" + re.escape(prefix + name) + r"(?=\s|$)", plain_text(text or "")))


def codex_config(tool):
    return os.path.join(tool.codex_home(), "config.toml")


def top_level(text):
    """The part of a TOML file before its first table, where a top-level key must go."""
    found = re.search(r"^[ \t]*\[", text, re.M)
    return text[:found.start()] if found else text


def fallback_state(text):
    """Codex's project_doc_fallback_filenames: ("done", None) when it names CLAUDE.md, ("add", (line, new line))
    when one plain line can name it too, ("new", None) when it isn't set, or ("odd", None) when it is set in a
    way this won't touch."""
    head = top_level(text)
    if re.search(rf"""^[ \t]*(?:"{FALLBACK_KEY}"|'{FALLBACK_KEY}')\s*=""", head, re.M):
        return "odd", None  # written quoted: adding the plain key beside it would set it twice, and Codex would refuse the file
    if not re.search(rf"^[ \t]*{FALLBACK_KEY}\s*=", head, re.M):
        return "new", None
    found = re.search(rf"^([ \t]*{FALLBACK_KEY}\s*=\s*)\[(.*)\]([ \t]*(?:#.*)?)$", head, re.M)
    if not found:
        return "odd", None
    try:
        names = json.loads("[" + found.group(2) + "]")
    except ValueError:
        return "odd", None
    if not all(isinstance(n, str) for n in names):
        return "odd", None
    if "CLAUDE.md" in names:
        return "done", None
    return "add", (found.group(0), found.group(1) + json.dumps(names + ["CLAUDE.md"]) + found.group(3))


def fallback_change(raw):
    """(Codex's config.toml naming CLAUDE.md as a fallback, as bytes; what to write down to take exactly that out
    again), or (None, None) when it names it already or can't be changed safely. A new key goes at the very top,
    before any table, where TOML wants it."""
    text = (raw or b"").decode("utf-8", "replace")
    state, lines = fallback_state(text)
    if state == "add":
        return text.replace(lines[0], lines[1], 1).encode("utf-8"), {"lines": list(lines)}
    if state != "new":
        return None, None
    bom = "﻿" if text.startswith("﻿") else ""
    block = f'{FALLBACK_NOTE}\n{FALLBACK_KEY} = ["CLAUDE.md"]\n' + ("\n" if text[len(bom):].strip() else "")
    return (bom + block + text[len(bom):]).encode("utf-8"), {"block": block}


def plan_instructions(folder, label, found, tool):
    agents, claude = os.path.join(folder, "AGENTS.md"), os.path.join(folder, "CLAUDE.md")
    inner = os.path.join(folder, ".claude", "CLAUDE.md")
    has_agents, has_claude, has_inner = os.path.isfile(agents), os.path.isfile(claude), os.path.isfile(inner)
    item = {"id": "instructions", "changes": []}
    if not has_agents and not has_claude and not has_inner:
        text = agents_text(label, found)
        item.update(state="todo", says="Write AGENTS.md from what the project's files say, and a CLAUDE.md that brings it in, so both agents read the same instructions.")
        item["changes"] = [{"file": agents, "how": "new", "text": text},
                           {"file": claude, "how": "new", "text": "@AGENTS.md\n"}]
        return item
    if has_agents and not has_claude and not has_inner:
        item.update(state="todo", says="Add a CLAUDE.md that brings in your AGENTS.md, so Claude Code reads the same instructions as Codex.")
        item["changes"] = [{"file": claude, "how": "new", "text": "@AGENTS.md\n"}]
        return item
    mine, prefix = (claude, "") if has_claude else (inner, "../")
    if has_agents:
        if os.path.realpath(mine) == os.path.realpath(agents) or brings_in(read_text(mine), "AGENTS.md", prefix) \
                or brings_in(read_text(agents), "CLAUDE.md"):
            item.update(state="done", says="Both agents read the same instructions: CLAUDE.md brings in AGENTS.md.")
            return item
        before = read_text(mine) or ""
        line = ("\n" if before and not before.endswith("\n") else "") + ("\n" if before.strip() else "") + f"@{prefix}AGENTS.md\n"
        item.update(state="todo", says=f"Your CLAUDE.md and AGENTS.md say different things. Add one line, @{prefix}AGENTS.md, at the end of "
                    "CLAUDE.md, so Claude Code reads both. Nothing else in either file changes.")
        item["changes"] = [{"file": mine, "how": "append", "text": line}]
        return item
    if has_inner and not has_claude:
        item.update(state="none", says="Codex can't read .claude/CLAUDE.md. Move it to CLAUDE.md in the project's own folder, then set up again.")
        return item
    if not tool.codex_here():
        item.update(state="done", says="Claude Code reads your CLAUDE.md. Codex isn't on this computer, so there is nothing to share yet.")
        return item
    config = codex_config(tool)
    state, _ = fallback_state(read_text(config) or "")
    if state == "done":
        item.update(state="done", says="Both agents read your CLAUDE.md: Codex reads it where a folder has no AGENTS.md.")
        return item
    if state == "odd":
        item.update(state="none", says=f"Add \"CLAUDE.md\" to {FALLBACK_KEY} in {tool.shown(config)} yourself, so Codex reads your CLAUDE.md.")
        return item
    _, extra = fallback_change(read_bytes(config))
    imports = " Codex reads it as it is: files it brings in with @ stay Claude Code's." if re.search(r"(?:^|\s)@\S", plain_text(read_text(claude) or "")) else ""
    item.update(state="todo", says="Have Codex read your CLAUDE.md where a folder has no AGENTS.md: one line in Codex's own settings, "
                f"and nothing in your project changes.{imports}")
    item["changes"] = [{"file": config, "how": "fallback", "text": extra["block"].rstrip("\n") + "\n" if "block" in extra else extra["lines"][1] + "\n"}]
    return item


# ---------- 2. the floor's check ----------

def floor_for(folder, company, tool):
    for floor in (company or {}).get("floors") or []:
        if isinstance(floor, dict) and folder in tool.floor_folders(floor)[:1]:
            return floor
    for floor in (company or {}).get("floors") or []:
        if isinstance(floor, dict) and any(folder == f or tool.inside(folder, f) for f in tool.floor_folders(floor)):
            return floor
    return None


def check_run(floor):
    given = floor.get("check") if isinstance(floor, dict) else None
    run = given.get("run") if isinstance(given, dict) else given
    return list(run) if isinstance(run, list) and run and all(isinstance(w, str) and w for w in run) else None


def plan_check(folder, found, company, tool, given=None):
    """The check as it will be: the floor's own, or what was found, or what you typed (`given`, a list; [] for none)."""
    floor = floor_for(folder, company, tool)
    had = check_run(floor)
    item = {"id": "check", "changes": [], "run": None}
    if had:
        item.update(state="done", run=had, says=f"Done means proven: its check is {command_text(had)}.")
        return item
    run = found["test"] if given is None else given
    if not run:
        item.update(state="none", says="No test command Arnheim is sure of. Type one, and an agent's work counts as done only once it passes.")
        return item
    item.update(state="todo", run=list(run), says=f"Done means proven: run {command_text(run)} after an agent changes files, and "
                "count the work as done only once it passes.")
    item["changes"] = [{"file": os.path.join(tool.DATA, "company.json"), "how": "check",
                        "text": json.dumps({"check": {"run": list(run), "label": CHECK_LABEL}})}]
    return item


# ---------- 3. secrets kept from Claude Code ----------

def permissions_of(settings):
    """(permissions, why not): the settings' permissions object, or why it can't be added to."""
    perms = settings.get("permissions", {})
    if not isinstance(perms, dict):
        return None, "\"permissions\" isn't an object"
    for key in ("allow", "deny"):
        if key in perms and not isinstance(perms[key], list):
            return None, f"\"permissions\".\"{key}\" isn't a list"
    return perms, None


def plan_secrets(tool):
    item = {"id": "secrets", "changes": [],
            "codex": "Codex can't be kept from these files yet without also stopping your tests reading .env, so its "
                     "settings stay as they are (docs/connect.md, step 23)."}
    if not tool.claude_code_here():
        item.update(state="none", says="Claude Code isn't on this computer.")
        return item
    path = tool.settings_path()
    try:
        _, settings = tool.read_settings(path)
    except tool.Refused as why:
        item.update(state="none", says=str(why))
        return item
    perms, odd = permissions_of(settings or {})
    if odd:
        item.update(state="none", says=f"In {tool.shown(path)}, {odd}, so nothing was added.")
        return item
    missing = [r for r in DENY if r not in (perms.get("deny") or [])]
    if not missing:
        item.update(state="done", says="Claude Code's own tools won't open .env files, keys, ~/.ssh, ~/.aws and the like.")
        return item
    item.update(state="todo", rules=missing,
                says="Claude Code's own tools won't open .env files, keys, ~/.ssh, ~/.aws and the like, in any project "
                     f"({len(missing)} rules in {tool.shown(path)}). A script it runs can still read them.")
    item["changes"] = [{"file": path, "how": "deny", "text": "\n".join(missing) + "\n"}]
    return item


# ---------- 4. the safe allow list ----------

def settings_allow(path):
    settings = load_json(path)
    perms = (settings or {}).get("permissions")
    allow = perms.get("allow") if isinstance(perms, dict) else None
    return allow if isinstance(allow, list) else []


def exclude_path(folder):
    """The repository's own ignore file that is never committed (.git/info/exclude), when settings.local.json
    isn't ignored yet; else None. The folder can be anywhere in a repository, its top or a subfolder."""
    code, said = run_quiet(["git", "-C", folder, "rev-parse", "--is-inside-work-tree"])
    if code != 0 or said.strip() != "true":
        return None
    code, said = run_quiet(["git", "-C", folder, "check-ignore", "-q", LOCAL.replace(os.sep, "/")])
    if code != 1:  # 0 ignored already; anything else, git can't tell
        return None
    code, said = run_quiet(["git", "-C", folder, "rev-parse", "--git-path", "info/exclude"])
    if code != 0 or not said.strip():
        return None
    path = said.strip().splitlines()[0]
    return os.path.normpath(path if os.path.isabs(path) else os.path.join(folder, path))


def exclude_line(folder):
    """settings.local.json's line for the exclude file, from the repository's top: a project in a subfolder of a bigger
    repository (apps/web, say) gets /apps/web/.claude/settings.local.json, which matches that file and no other."""
    code, said = run_quiet(["git", "-C", folder, "rev-parse", "--show-prefix"])
    prefix = said.strip().splitlines()[0] if code == 0 and said.strip() else ""
    return secret_scan._exclude_line(prefix + LOCAL.replace(os.sep, "/"))


def plan_allow(folder, check, tool):
    item = {"id": "allow", "changes": [],
            "codex": "Codex already runs a project's check without asking, so its settings stay as they are."}
    run = check.get("run")
    if not run:
        item.update(state="none", says="With a check, Claude Code can run it without asking.")
        return item
    command = " ".join(run)
    if not standing.can_stand("Bash", command):
        item.update(state="none", says=f"{command_text(run)} keeps asking: only a plain test, check or build command can run without asking.")
        return item
    rule = f"Bash({command})"
    local = os.path.join(folder, LOCAL)
    places = (local, os.path.join(folder, ".claude", "settings.json"), tool.settings_path())
    if any(rule in settings_allow(p) for p in places):
        item.update(state="done", rule=rule, says=f"Claude Code runs {command} without asking.")
        return item
    settings = load_json(local)
    if os.path.exists(local) and (settings is None or permissions_of(settings)[1]):
        item.update(state="none", says=f"{tool.shown(local)} isn't as Claude Code's docs show, so nothing was added.")
        return item
    item.update(state="todo", rule=rule, says=f"Claude Code runs {command} without asking, here only. Everything else still asks.")
    item["changes"] = [{"file": local, "how": "allow", "text": rule + "\n"}]
    exclude = exclude_path(folder)
    if exclude:
        item["changes"].append({"file": exclude, "how": "exclude", "text": exclude_line(folder) + "\n"})
    return item


# ---------- 5. the same MCP servers in both ----------

def claude_json():
    given = os.environ.get("CLAUDE_CONFIG_DIR")
    return os.path.join(os.path.expanduser(given), ".claude.json") if given else os.path.join(os.path.expanduser("~"), ".claude.json")


def claude_servers(folders):
    """{name: (its settings, where)}: Claude Code's MCP servers in your user scope ("user") and the projects'
    .mcp.json (the folder). Only your user scope's are shared; a project's count only as already there."""
    out = {}
    for path, where in [(claude_json(), "user")] + [(os.path.join(f, ".mcp.json"), f) for f in folders]:
        servers = (load_json(path) or {}).get("mcpServers")
        for name, spec in (servers.items() if isinstance(servers, dict) else []):
            if isinstance(spec, dict):
                out.setdefault(name, (spec, where))
    return out


def codex_servers(tool):
    """{name: its settings}: read with tomllib, or by simple_servers on Python 3.10 and older."""
    text = (read_text(codex_config(tool)) or "").lstrip("﻿")  # a file some editors start with a mark TOML doesn't take
    try:
        import tomllib
    except ImportError:
        tomllib = None
    if tomllib:
        try:
            servers = tomllib.loads(text).get("mcp_servers")
        except ValueError:
            servers = None
        if isinstance(servers, dict):
            return {n: s for n, s in servers.items() if isinstance(s, dict)}
        return {}
    return simple_servers(text)


TABLE = re.compile(r'^[ \t]*\[[ \t]*mcp_servers\.(?:"([^"]+)"|([A-Za-z0-9_-]+))((?:\.[^\]]+)?)[ \t]*\][ \t]*(?:#.*)?$')
KEY = re.compile(r'^[ \t]*([A-Za-z0-9_-]+)[ \t]*=[ \t]*(.*?)[ \t]*$')


def simple_servers(text):
    """Codex's MCP servers for a Python without tomllib: each [mcp_servers.NAME] table's plain keys, read when they
    are basic strings or lists of them (the usual command and args). A key it can't read, an inline table, or a
    table under the server's own (its env and the like) leaves the server marked so it is never copied as plain:
    {"unread": True}, or {"env": True} when it carries settings of its own."""
    servers, name, open_list = {}, None, None
    for line in text.splitlines():
        if open_list is not None:  # a list that goes on over lines
            open_list[1].append(line)
            if "]" in line.split("#", 1)[0]:
                key, parts = open_list
                open_list = None
                put(servers[name], key, " ".join(parts))
            continue
        head = TABLE.match(line)
        if head:
            name = head.group(1) or head.group(2)
            servers.setdefault(name, {})
            if head.group(3):  # [mcp_servers.NAME.env] and the like: settings of its own
                servers[name]["env"] = True
                name = None
            continue
        if re.match(r'^[ \t]*\[', line):
            name = None
            continue
        if name is None or not line.strip() or line.lstrip().startswith("#"):
            continue
        found = KEY.match(line)
        if not found:
            servers[name]["unread"] = True
            continue
        key, value = found.groups()
        if value.startswith("[") and "]" not in value.split("#", 1)[0]:
            open_list = (key, [value])
            continue
        put(servers[name], key, value)
    return servers


def put(spec, key, value):
    """One key = value of a server's table, when the value is a basic string or a list of them, true or false."""
    value = re.sub(r'[ \t]+#[^"\]]*$', "", value).strip()  # a comment after the value
    if value in ("true", "false"):
        spec[key] = value == "true"
        return
    if value.startswith("{"):
        spec[key] = True  # an inline table: env = { ... } and the like
        return
    try:
        got = json.loads(re.sub(r",\s*\]$", "]", value))  # TOML's basic strings read as JSON's; a last comma doesn't
    except ValueError:
        spec["unread"] = True
        return
    if isinstance(got, str) or (isinstance(got, list) and all(isinstance(x, str) for x in got)):
        spec[key] = got
    else:
        spec["unread"] = True


def carries_key(spec):
    """Whether a key sits in a server's command, its words or its address (--api-key KEY, ?token=KEY and the
    like), as the secrets check sees one: such a server is never copied, or shown."""
    words = [spec.get("command"), spec.get("url"), *(spec.get("args") if isinstance(spec.get("args"), list) else [])]
    words = [w for w in words if isinstance(w, str)]
    return bool(words) and any(secret_scan.text_hits(text) for text in (" ".join(words), *words))


def why_by_hand(spec):
    """Why a server is left for the person to add, in words."""
    if not isinstance(spec, dict) or spec.get("unread"):
        return "Arnheim couldn't read all of how it is set up."
    return "it has keys or settings of its own, and Arnheim never copies those."


def keyless(spec):
    """A server's plain form when it carries nothing private or particular (no env, headers, sign-in or folder of
    its own): {"command", "args"} or {"url"}; else None."""
    if not isinstance(spec, dict):
        return None
    private = ("env", "headers", "oauth", "env_vars", "http_headers", "env_http_headers", "bearer_token_env_var", "auth",
               "headersHelper", "http_headers_helper", "cwd", "unread")
    if any(spec.get(k) for k in private) or carries_key(spec):
        return None
    if isinstance(spec.get("command"), str) and spec["command"].strip() and spec.get("type", "stdio") == "stdio":
        args = spec.get("args") or []
        if isinstance(args, list) and all(isinstance(a, str) for a in args):
            return {"command": spec["command"], "args": list(args)}
    if isinstance(spec.get("url"), str) and re.match(r"^https?://", spec["url"]) and spec.get("type", "http") in ("http", "streamable-http"):
        return {"url": spec["url"]}
    return None


def claude_command():
    return shlex.split(os.environ.get("ARNHEIM_CLAUDE") or "claude")


def claude_found():
    first = claude_command()[:1]
    return bool(first) and (os.path.isabs(first[0]) and os.path.exists(first[0]) or bool(shutil.which(first[0])))


def plan_mcp(folders, tool):
    item = {"id": "mcp", "changes": [], "to_codex": [], "to_claude": [], "by_hand": []}
    codex = shutil.which("codex") if tool.codex_here() else None
    if not codex or not claude_found():
        item.update(state="none", says="Sharing MCP servers needs both Claude Code's claude and Codex's codex commands on this computer.")
        return item
    mine, theirs = claude_servers(folders), codex_servers(tool)
    for name, (spec, where) in sorted(mine.items()):
        if name in theirs or where != "user":
            continue  # a project's .mcp.json servers wait for your OK in that project: never Codex's for every folder
        plain = keyless(spec) if NAME.match(name) else None
        (item["to_codex"] if plain else item["by_hand"]).append({"name": name, "to": "Codex", **({"plain": plain} if plain else {}),
                                                                "why": why_by_hand(spec)})
    for name, spec in sorted(theirs.items()):
        if name in mine or (isinstance(spec, dict) and spec.get("enabled") is False):
            continue  # one switched off in Codex isn't one to share
        plain = keyless(spec) if NAME.match(name) else None
        (item["to_claude"] if plain else item["by_hand"]).append({"name": name, "to": "Claude Code", **({"plain": plain} if plain else {}),
                                                                 "why": why_by_hand(spec)})
    for row in item["to_codex"]:
        p = row["plain"]
        row["command"] = ["codex", "mcp", "add", row["name"]] + (["--url", p["url"]] if "url" in p else ["--", p["command"], *p["args"]])
    for row in item["to_claude"]:
        p = row["plain"]
        spec = {"type": "http", "url": p["url"]} if "url" in p else {"type": "stdio", "command": p["command"], "args": p["args"]}
        row["command"] = ["claude", "mcp", "add-json", "--scope", "user", row["name"], json.dumps(spec)]
    adds = item["to_codex"] + item["to_claude"]
    hand = " ".join(f"Add {r['name']} to {r['to']} yourself: {r['why']}" for r in item["by_hand"])
    if not adds:
        item.update(state="done" if not hand else "none",
                    says="Claude Code and Codex have the same MCP servers set up for every project." if not hand and (mine or theirs) else
                    "Neither agent has MCP servers yet." if not hand else hand)
        return item
    words = [f"{', '.join(r['name'] for r in item['to_codex'])} to Codex"] if item["to_codex"] else []
    words += [f"{', '.join(r['name'] for r in item['to_claude'])} to Claude Code"] if item["to_claude"] else []
    item.update(state="todo", says="Add " + ", and ".join(words) + ", with each agent's own command, for every project."
                + (f" {hand}" if hand else ""))
    item["changes"] = [{"file": None, "how": "command", "text": command_text(r["command"])} for r in adds]
    return item


# ---------- the whole plan ----------

def plan(folders, tool, checks=None):
    """What setting your agents up well would do, changing nothing: {"projects": [{folder, label, found, items}],
    "secrets": item, "mcp": item}. Each item has an id, a state (todo, done or none), what it means in words
    (says) and, when todo, its exact changes. `checks` gives a project's check as you typed it: {folder: [words]}."""
    company = None
    try:
        company = tool.read_json(os.path.join(tool.DATA, "company.json"), "data/company.json")
    except tool.Refused:
        company = None
    projects = []
    for folder in folders:
        folder = os.path.realpath(folder)
        floor = floor_for(folder, company, tool)
        label = str(floor.get("label")) if isinstance(floor, dict) and floor.get("label") else tool.label_of(folder)
        found = detect(folder)
        check = plan_check(folder, found, company, tool, (checks or {}).get(folder))
        items = [plan_instructions(folder, label, found, tool), check, plan_allow(folder, check, tool)]
        projects.append({"folder": folder, "label": label, "floor": floor.get("id") if isinstance(floor, dict) else None,
                         "found": found, "items": items})
    return {"projects": projects, "secrets": plan_secrets(tool), "mcp": plan_mcp(folders, tool)}


def shown_plan(p, tool):
    """The plan as the page shows it: paths as a person writes them (~ for the home folder), nothing private."""
    def item_out(item):
        out = {k: item[k] for k in ("id", "state", "says") if k in item}
        out.update({k: item[k] for k in ("codex", "rule") if k in item})
        if "run" in item:
            out["run"] = command_text(item["run"]) if item["run"] else ""
        out["changes"] = [{"file": tool.shown(c["file"]) if c["file"] else None, "how": c["how"], "text": c["text"]} for c in item["changes"]]
        return out
    return {"projects": [{"folder": tool.shown(x["folder"]), "label": x["label"], "floor": x["floor"],
                          "found": {k: x["found"][k] for k in ("languages", "managers", "folders")},
                          "items": [item_out(i) for i in x["items"]]} for x in p["projects"]],
            "secrets": item_out(p["secrets"]), "mcp": item_out(p["mcp"])}


def lines_of(p, tool):
    """The plan in words for the terminal: what will happen, one line each."""
    out = []
    for x in p["projects"]:
        todo = [i for i in x["items"] if i["state"] == "todo"]
        if todo:
            out.append(f"  {x['label']} ({tool.shown(x['folder'])}):")
            out += [f"    - {i['says']}" for i in todo]
    once = [i for i in (p["secrets"], p["mcp"]) if i["state"] == "todo"]
    if once:
        out.append("  For every project, once:")
        out += [f"    - {i['says']}" for i in once]
    return out


def to_do(p):
    return [i for x in p["projects"] for i in x["items"] if i["state"] == "todo"] + \
        [i for i in (p["secrets"], p["mcp"]) if i["state"] == "todo"]


# ---------- the record, and doing it ----------

def record_path(tool):
    return os.path.join(tool.DATA, RECORD)


def private_folder(tool):
    """data/.secrets, made readable by you alone."""
    folder = os.path.dirname(record_path(tool))
    if not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
        os.chmod(folder, 0o700)  # makedirs alone leaves the mode to the umask
    return folder


def read_record(tool):
    got = load_json(record_path(tool)) or {}
    done = got.get("done")
    return [e for e in done if isinstance(e, dict)] if isinstance(done, list) else []


def write_record(tool, entries):
    path = record_path(tool)
    if not entries:
        remove(path)
        try:
            os.rmdir(os.path.dirname(path))  # data/.secrets, when nothing else is kept there
        except OSError:
            pass
        return
    private_folder(tool)
    part = f"{path}.{os.getpid()}.part"
    with os.fdopen(os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w", encoding="utf-8") as handle:
        json.dump({"about": ABOUT, "done": entries}, handle, ensure_ascii=False, indent=1)
    os.chmod(part, 0o600)  # an old part file keeps its own mode through os.open
    os.replace(part, path)


def change_file(tool, entries, what, path, after_of, project=None, **extra):
    """Changes one file to after_of(its bytes now, or None), and writes down what it was, at once, so a change
    is never left unrecorded. Gives the entry, or None when nothing changed."""
    before = read_bytes(path)
    after = after_of(before)
    if after is None or after == before:
        return None
    made = write_bytes(path, after)
    entry = {"what": what, "file": os.path.realpath(path), "before": None if before is None else base64.b64encode(before).decode(),
             "after": sha(after), "made": made, "project": project, "at": round(time.time(), 1), **extra}
    entries.append(entry)
    write_record(tool, entries)
    return entry


def json_after(add_to, indent_from):
    """A JSON settings file's bytes with rules added to permissions.<key>: (key, rules)."""
    key, rules = add_to

    def after(raw):
        settings = json.loads(raw.decode("utf-8-sig")) if raw else {}
        perms = settings.setdefault("permissions", {})
        have = perms.setdefault(key, [])
        missing = [r for r in rules if r not in have]
        if not missing:
            return raw
        have.extend(missing)
        return dumped(settings, indent_from(raw))
    return after


def indent_from_raw(raw):
    if not raw:
        return 2
    found = re.search(rb"\n([ \t]+)\S", raw)
    if not found:
        return None if raw.strip() and b"\n" not in raw.strip() else 2
    return "\t" if found.group(1).startswith(b"\t") else len(found.group(1))


def do_project(x, chosen, tool, entries, say):
    folder = x["folder"]
    for item in x["items"]:
        if item["state"] != "todo" or item["id"] not in chosen:
            continue
        if item["id"] == "instructions":
            for c in item["changes"]:
                if c["how"] == "new":
                    if change_file(tool, entries, "new", c["file"], lambda raw, t=c["text"]: t.encode("utf-8") if raw is None else None, folder):
                        say(f"Wrote {tool.shown(c['file'])}.")
                elif c["how"] == "append":
                    if change_file(tool, entries, "append", c["file"], lambda raw, t=c["text"]: (raw or b"") + t.encode("utf-8"), folder, added=c["text"]):
                        say(f"Added one line to {tool.shown(c['file'])}: {c['text'].strip()}")
                elif c["how"] == "fallback":
                    _, extra = fallback_change(read_bytes(c["file"]))
                    if extra and change_file(tool, entries, "fallback", c["file"], lambda raw: fallback_change(raw)[0], None, **extra):
                        say(f"Codex now reads CLAUDE.md where a folder has no AGENTS.md ({tool.shown(c['file'])}).")
        elif item["id"] == "check":
            company = os.path.join(tool.DATA, "company.json")
            check = {"run": item["run"], "label": CHECK_LABEL}
            floor_id = x["floor"]

            def with_check(raw, check=check, floor_id=floor_id):
                data = json.loads(raw.decode("utf-8-sig")) if raw else None
                floor = next((f for f in (data or {}).get("floors") or [] if isinstance(f, dict) and f.get("id") == floor_id), None)
                if floor is None or floor.get("check"):
                    return None
                floor["check"] = check
                return dumped(data, indent_from_raw(raw))
            if floor_id and change_file(tool, entries, "check", company, with_check, folder, floor=floor_id, added=check):
                say(f"Its check is {command_text(item['run'])}: done means proven on {x['label']}.")
            elif not floor_id:
                say(f"{x['label']} has no floor yet, so its check wasn't set.")
        elif item["id"] == "allow":
            for c in item["changes"]:
                if c["how"] == "allow":
                    if change_file(tool, entries, "allow", c["file"], json_after(("allow", [item["rule"]]), indent_from_raw), folder, added=[item["rule"]],
                                   fresh=not os.path.exists(c["file"])):
                        say(f"Claude Code runs {item['rule'][5:-1]} without asking in {x['label']} ({tool.shown(c['file'])}).")
                elif c["how"] == "exclude":
                    def with_line(raw, line=c["text"]):
                        text = (raw or b"").decode("utf-8", "replace")
                        return (text + ("\n" if text and not text.endswith("\n") else "") + line).encode("utf-8")
                    before = read_text(c["file"]) or ""
                    added = ("\n" if before and not before.endswith("\n") else "") + c["text"]
                    change_file(tool, entries, "append", c["file"], with_line, folder, added=added)
                    if run_quiet(["git", "-C", folder, "check-ignore", "-q", LOCAL.replace(os.sep, "/")])[0] != 0:
                        say(f"Git still sees {LOCAL} in {x['label']}: add it to that repository's .gitignore yourself.")


def do_mcp(item, tool, entries, say):
    config = codex_config(tool)
    before = read_bytes(config)
    added = []
    for row in item["to_codex"]:
        codex = shutil.which("codex")
        code, said = run_quiet([codex] + row["command"][1:]) if codex else (None, "codex isn't here")
        if code == 0:
            added.append(row["name"])
            say(f"Added the MCP server {row['name']} to Codex." if row["name"] in codex_servers(tool) else
                f"Codex said it added the MCP server {row['name']}, but its config.toml doesn't show it yet.")
        else:
            say(f"Couldn't add {row['name']} to Codex: {(said or '').strip()[:200] or 'it gave no reason'}.")
    after = read_bytes(config)
    if added or after != before:  # written down whenever the file changed, so Undo can always put it back
        names = added
        entries.append({"what": "mcp-codex", "file": os.path.realpath(config), "before": None if before is None else base64.b64encode(before).decode(),
                        "after": sha(after), "made": [], "names": names, "at": round(time.time(), 1)})
        write_record(tool, entries)
    for row in item["to_claude"]:
        code, said = run_quiet(claude_command() + row["command"][1:])
        if code == 0:
            entries.append({"what": "mcp-claude", "file": None, "names": [row["name"]], "at": round(time.time(), 1)})
            write_record(tool, entries)
            say(f"Added the MCP server {row['name']} to Claude Code, for every project.")
        else:
            say(f"Couldn't add {row['name']} to Claude Code: {(said or '').strip()[:200] or 'it gave no reason'}.")


def apply(choice, tool, say=print):
    """Does what was chosen, fresh from the files as they are now. `choice`: {"projects": [{"folder", "items": [ids],
    "check": [words] or None}], "secrets": bool, "mcp": bool}. Each change is written down as it is made; if a file
    can't be written, this run's changes are taken back and it raises tool.Refused. Gives the number of changes."""
    wanted = {os.path.realpath(p["folder"]): p for p in choice.get("projects") or []}
    checks = {f: p["check"] for f, p in wanted.items() if p.get("check") is not None}
    p = plan(list(wanted), tool, checks)
    entries = read_record(tool)
    start = len(entries)
    try:
        for x in p["projects"]:
            do_project(x, set(wanted[x["folder"]].get("items") or []), tool, entries, say)
        if choice.get("secrets") and p["secrets"]["state"] == "todo":
            path = tool.settings_path()
            if change_file(tool, entries, "deny", path, json_after(("deny", p["secrets"]["rules"]), indent_from_raw), None,
                           added=p["secrets"]["rules"], fresh=not os.path.exists(path)):
                say(f"Claude Code's own tools won't open .env files, keys, ~/.ssh, ~/.aws and the like ({tool.shown(path)}).")
    except (OSError, ValueError) as error:
        for entry in reversed(entries[start:]):
            take_back(entry, tool, lambda *_: None)
        write_record(tool, entries[:start])
        where = tool.shown(error.filename) if getattr(error, "filename", None) else "a file"
        raise tool.Refused(f"{where} can't be written: {getattr(error, 'strerror', None) or error}. Nothing was changed.")
    if choice.get("mcp") and p["mcp"]["state"] == "todo":
        do_mcp(p["mcp"], tool, entries, say)  # last: each agent's own command, each on its own
    return len(entries) - start


# ---------- taking it back ----------

def drop_rules(raw, entry):
    """A JSON settings file without the rules this added, when they are still there."""
    try:
        settings = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return None
    key = "deny" if entry["what"] == "deny" else "allow"
    perms = settings.get("permissions") if isinstance(settings, dict) else None
    have = perms.get(key) if isinstance(perms, dict) else None
    if not isinstance(have, list) or not any(r in have for r in entry.get("added") or []):
        return None
    perms[key] = [r for r in have if r not in entry["added"]]
    if not perms[key]:
        del perms[key]
    if not perms:
        del settings["permissions"]
    if entry.get("fresh") and not settings:
        return b""
    return dumped(settings, indent_from_raw(raw))


def drop_check(raw, entry):
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except ValueError:
        return None
    floor = next((f for f in data.get("floors") or [] if isinstance(f, dict) and f.get("id") == entry.get("floor")), None)
    if floor is None or floor.get("check") != entry.get("added"):
        return None
    del floor["check"]
    return dumped(data, indent_from_raw(raw))


def drop_text(raw, entry):
    text = raw.decode("utf-8", "replace")
    if entry["what"] == "append":
        at = text.rfind(entry.get("added") or "\0")
        return None if at < 0 else (text[:at] + text[at + len(entry["added"]):]).encode("utf-8")
    if entry.get("lines"):  # a line this added a name to
        old, new = entry["lines"]
        return text.replace(new, old, 1).encode("utf-8") if new in text else None
    block = entry.get("block") or "\0"
    at = text.find(block)
    return None if at < 0 else (text[:at] + text[at + len(block):]).encode("utf-8")


TARGETED = {"deny": drop_rules, "allow": drop_rules, "check": drop_check, "append": drop_text, "fallback": drop_text}


def take_back(entry, tool, say):
    """Puts back one change: the file as it was when it hasn't changed since; else only what this added; else
    it is left, and says so. Gives True when nothing of it is left."""
    what, path = entry.get("what"), entry.get("file")
    if what == "mcp-claude":
        done = all(run_quiet(claude_command() + ["mcp", "remove", "--scope", "user", n])[0] == 0 for n in entry.get("names") or [])
        say(f"Took the MCP server {', '.join(entry.get('names') or [])} out of Claude Code." if done else
            f"Couldn't take {', '.join(entry.get('names') or [])} out of Claude Code: claude mcp remove --scope user <name> does it.")
        return done
    now = read_bytes(path) if path else None
    before = base64.b64decode(entry["before"]) if entry.get("before") is not None else None
    if now is not None and sha(now) == entry.get("after"):
        if before is None:
            remove(path, entry.get("made") or [])
        else:
            write_bytes(path, before)
        say(f"Put {tool.shown(path)} back as it was." if before is not None else f"Took away {tool.shown(path)}, which setting up made.")
        return True
    if now is None:  # gone since: nothing of it is left but a folder it made, if that is empty now
        if before is None:
            remove(path, entry.get("made") or [])
        return True
    if what == "mcp-codex":
        codex = shutil.which("codex")
        done = bool(codex) and all(run_quiet([codex, "mcp", "remove", n])[0] == 0 for n in entry.get("names") or [])
        say(f"Took the MCP server {', '.join(entry['names'])} out of Codex." if done else
            f"Couldn't take {', '.join(entry['names'])} out of Codex: codex mcp remove <name> does it.")
        return done
    fix = TARGETED.get(what)
    after = fix(now, entry) if fix else None
    if after is not None:
        if after == b"" and entry.get("fresh"):
            remove(path, entry.get("made") or [])
        else:
            write_bytes(path, after)
        say(f"Took out of {tool.shown(path)} only what setting up added: it changed since.")
        return True
    say(f"Left {tool.shown(path)} as it is: it changed since, so it is yours now.")
    return True


def undo(tool, say=print):
    """Takes back everything setting your agents up well did, newest first. Gives how many changes it took back."""
    entries = read_record(tool)
    if not entries:
        return 0
    say("Setting your agents up well, taken back:")
    kept = []
    for entry in reversed(entries):
        try:
            take_back(entry, tool, lambda line: say(f"  {line}"))
        except OSError as error:  # kept, so the next undo tries again
            kept.insert(0, entry)
            say(f"  {tool.shown(entry.get('file') or '')} can't be written: {error.strerror or error}. Undo again to try once more.")
    write_record(tool, kept)
    return len(entries) - len(kept)


# ---------- for connect/setup.py, in the terminal ----------

def offer(tool, folders, args, say=print, ask_yes=None):
    """Asks once whether to set your agents up well too, after showing what it would do. `--well` says yes
    without asking, `--no-well` no; `--yes` alone leaves it, as it promised never to change your projects' files."""
    if getattr(args, "no_well", False) or not folders:
        return 0
    p = plan(folders, tool)
    if not to_do(p):
        say("Your agents are set up well in these projects already.")
        return 0
    say("Set your agents up well too? This would, each a step you can take back with --undo:")
    for line in lines_of(p, tool):
        say(line)
    if p["secrets"]["state"] == "todo":
        say(f"  ({p['secrets']['codex']})")
    if not getattr(args, "well", False):
        if args.yes:
            say("To do it: python3 connect/setup.py --well")
            return 0
        if not (ask_yes or tool.ask_yes)("Set your agents up well too? [Y/n] "):
            say("Left as it was. To do it later: python3 connect/setup.py --well")
            return 0
    choice = {"projects": [{"folder": x["folder"], "items": list(ITEMS)} for x in p["projects"]], "secrets": True, "mcp": True}
    made = apply(choice, tool, say=lambda line: say(f"  {line}"))
    say(f"Set your agents up well: {made} change{'s' if made != 1 else ''}. python3 connect/setup.py --undo takes them back too.")
    return made
