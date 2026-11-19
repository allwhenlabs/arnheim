"""Always allow what you always allow (docs/connect.md, "Always allow").

Every agent asks before it runs a command you haven't allowed, and asks again the next time. Arnheim
sees each request from every agent, Claude Code and Codex alike, and each one you allowed, here in the
building or in the agent's own window (the agent then went on and ran it). Once you have allowed the
same command on a floor twice, the next request for it offers "Always allow here": one press allows it
now, and from then on Arnheim's hook allows that exact command on that floor for every agent, without
asking you. Settings lists them, each with "Stop allowing".

Only a command from a short list can stand: running the project's tests, checks and builds (npm test,
pytest, cargo test, go test, make test and the like), and looking without changing anything (ls,
git status, git diff, git log and the like). It is matched on the exact words the agent sends, never a
pattern, one plain command at a time: nothing chained, piped or redirected, no quotes or variables,
nothing the agent asks to run outside its sandbox or in the background, and nothing that names
anything private or outside the project. A test or build runs the project's own code, as it does each time you allow it.
Reads, searches, file changes and web requests always ask.

data/control/allowed.json keeps what was allowed, two weeks back; data/control/always.json your standing
allows. Both stay on this computer. Standard library only.
"""
import json
import os
import re
import secrets
import time

HERE = os.path.dirname(os.path.realpath(__file__))
KEEP = 14 * 86400  # what was allowed is remembered this long
MOST = 2000
OFFER_AFTER = 2  # allowed this many times before: the next request offers to always allow it
TOOLS = ("Bash",)
PLAIN = re.compile(r"^[A-Za-z0-9_./:=@,+%-]+(?: [A-Za-z0-9_./:=@,+%-]+)*$")  # one command: no quotes, $, ;, &, |, <, >, \\, ~, *
FIELDS = {"command", "description", "timeout"}  # what a plain request carries; anything more set (sandbox off, background) asks
CHECKS = r"(?:test|tests|check|checks|lint|typecheck|type-check|build|verify)(?:[:._-][A-Za-z0-9:._-]+)?"
CHECK = re.compile(rf"^{CHECKS}$")
DIRTY = re.compile(r"deploy|release|publish|push|upload|install|clean|reset|delet|remov|rm|fix|format|write|migrat|seed|drop|"
                   r"prod|start|serve|sync|update|upgrade|stage|ship", re.I)  # a check's name that says it does more
# The programs a standing allow may run, each with what may follow it. A set: names, paths and test filters
# (no "=", no "://", no leading "-"), and only the flags in the set ("-N" lets through -5, -20 and the like).
# "checks": a test, check or build name first (test, lint, build:web; never lint:fix), then names only.
# A dict: subcommands. ("one", flags): nothing, or exactly one of those flags.
NAMES = frozenset()
SCRIPTS = {"run": "checks", "run-script": "checks", "test": frozenset({"--silent", "--"}), "t": frozenset({"--silent", "--"})}
PYTEST = frozenset({"-q", "-v", "-vv", "-x", "-s", "-l", "-k", "-m", "--lf", "--ff", "--sw", "--no-header", "--exitfirst", "--quiet", "--verbose"})
UNITTEST = frozenset({"-v", "-q", "-f", "-b", "-k", "discover", "-s", "-p", "-t"})
JEST = frozenset({"--ci", "--runInBand", "-i", "--passWithNoTests", "--silent", "run", "--bail"})
QUIET = frozenset({"-q", "--quiet", "-v", "--verbose"})
CARGO = frozenset({"--release", "--all", "--workspace", "--lib", "--tests", "--bins", "--all-targets", "--no-fail-fast", "-q", "-v",
                   "-p", "--package", "--locked", "--offline", "--frozen"})
GO = frozenset({"-v", "-race", "-short", "-count", "-run", "-cover", "-timeout", "-failfast"})
GIT_LOOK = frozenset({"--stat", "--shortstat", "--name-only", "--name-status", "--oneline", "--graph", "--decorate", "--all", "-p",
                      "--cached", "--staged", "--check", "-w", "-n", "-N", "-s", "--short", "-b", "--porcelain", "--abbrev-ref",
                      "--show-toplevel", "-m", "--others", "--exclude-standard", "--no-color", "--color"})
PROGRAMS = {
    "npm": SCRIPTS, "pnpm": {**SCRIPTS, "*": "checks"}, "yarn": {**SCRIPTS, "*": "checks"},
    "bun": {"test": frozenset({"--bail"}), "run": "checks"},
    "pytest": PYTEST, "py.test": PYTEST, "python": {"-m": {"pytest": PYTEST, "unittest": UNITTEST}},
    "python3": {"-m": {"pytest": PYTEST, "unittest": UNITTEST}},
    "jest": JEST, "vitest": JEST, "mocha": frozenset({"--bail"}), "tsc": frozenset({"--noEmit", "-p", "--project", "-b", "--build"}),
    "mypy": frozenset({"--strict", "-q"}), "pyright": NAMES, "flake8": NAMES, "pylint": NAMES, "rspec": frozenset({"--fail-fast"}),
    "phpunit": NAMES, "ctest": frozenset({"-V", "--output-on-failure"}), "eslint": frozenset({"--quiet", "--max-warnings"}),
    "ruff": {"check": frozenset({"-q"})}, "make": "checks-or-flags",
    "cargo": {"test": CARGO, "check": CARGO, "build": CARGO, "clippy": CARGO},
    "go": {"test": GO, "vet": NAMES, "build": frozenset({"-v", "-race"})},
    "swift": {"test": frozenset({"-c", "--parallel", "--filter"}), "build": frozenset({"-c"})},
    "dotnet": {"test": frozenset({"-c", "--configuration", "--no-restore", "--no-build", "--filter"}), "build": frozenset({"-c", "--configuration", "--no-restore"})},
    "mvn": {"test": frozenset({"-q", "-o", "-B"}), "verify": frozenset({"-q", "-o", "-B"}), "compile": frozenset({"-q", "-o", "-B"})},
    "./mvnw": {"test": frozenset({"-q", "-o", "-B"}), "verify": frozenset({"-q", "-o", "-B"}), "compile": frozenset({"-q", "-o", "-B"})},
    "gradle": {"test": frozenset({"--offline", "-q", "--info"}), "check": frozenset({"--offline", "-q"}), "build": frozenset({"--offline", "-q"})},
    "./gradlew": {"test": frozenset({"--offline", "-q", "--info"}), "check": frozenset({"--offline", "-q"}), "build": frozenset({"--offline", "-q"})},
    "ls": frozenset({"-l", "-a", "-la", "-al", "-lh", "-lah", "-alh", "-1", "-R", "-t", "-S", "-r", "-h", "-F"}), "pwd": NAMES,
    "wc": frozenset({"-l", "-w", "-c", "-m"}), "head": frozenset({"-n", "-N"}), "tail": frozenset({"-n", "-N"}), "cat": frozenset({"-n"}),
    "grep": frozenset({"-r", "-R", "-n", "-i", "-l", "-c", "-w", "-E", "-F", "-v", "-I", "-rn", "-rin", "-ri"}),
    "du": frozenset({"-s", "-h", "-sh", "-d"}), "df": frozenset({"-h"}),
    "git": {"status": GIT_LOOK, "diff": GIT_LOOK, "log": GIT_LOOK, "show": GIT_LOOK, "blame": frozenset({"-w"}), "ls-files": GIT_LOOK,
            "rev-parse": GIT_LOOK, "branch": ("one", frozenset({"-a", "-r", "-v", "-vv", "--list", "--show-current"}))},
}
NUMBER = re.compile(r"^-\d+$")


# What can never stand, checked as well: a command that deletes, moves, overwrites or changes owners, runs as
# someone else, reaches another machine, installs or publishes, or changes git's history.
NEVER = re.compile(
    r"(?:^|\s)(?:sudo|doas|su|pkexec|rm|rmdir|unlink|mv|cp|dd|shred|truncate|chmod|chown|kill|curl|wget|ssh|scp|rsync|nc|"
    r"eval|exec|source|xargs|open|install|uninstall|publish|deploy|release|push|reset|clean|rebase|merge|commit|tag|stash|"
    r"update-ref|reflog|filter-branch|gc|prune|send-email)(?:$|\s)", re.I)
PRIVATE = re.compile(r"(?:^|[\s/=])(?:~|\$HOME)?/?\.[A-Za-z0-9]|id_rsa|id_ed25519|\.pem\b|\.key\b|\.env\b|secret|"
                     r"password|passwd|token|credential|keychain|\.ssh\b|\.aws\b|\.gnupg\b|^/|\s/|\.\./", re.I)


def _dir(data):
    return os.path.join(data, "control")


def _read(path):
    try:
        with open(path, encoding="utf-8") as handle:
            got = json.load(handle)
    except (OSError, ValueError):
        return []
    rows = got.get("rows") if isinstance(got, dict) else None
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def _write(path, rows, about):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = f"{path}.{os.getpid()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump({"about": about, "rows": rows}, handle, ensure_ascii=False, indent=1)
    os.replace(part, path)


def command_in(tool, given):
    """The exact command a request runs, as the agent sent it, when it is a plain one; else None. A request with
    anything more set (outside the sandbox, in the background, another folder) is never a plain one."""
    if tool not in TOOLS or not isinstance(given, dict) or not isinstance(given.get("command"), str):
        return None
    if any(k not in FIELDS and given.get(k) not in (None, False, "", 0) for k in given):
        return None
    return given["command"]


def _check(name):
    return bool(CHECK.match(name)) and not DIRTY.search(name)


def _word_ok(word, flags):
    """One word after a program: a flag from its list, or a name, path or filter that isn't a flag."""
    if "=" in word or "://" in word or ".." in word.split("/"):  # nothing set by =, nothing online, nothing above the project
        return False
    if word.startswith("-") and word != "--":
        return word in flags or ("-N" in flags and bool(NUMBER.match(word)))
    return word != "--" or "--" in flags


def _fits(rule, words):
    """Whether the words after a program are what its rule lets through."""
    if isinstance(rule, frozenset):
        return all(_word_ok(w, rule) for w in words)
    if isinstance(rule, tuple) and rule[0] == "one":  # nothing, or exactly one of these flags and nothing after
        return not words or (len(words) == 1 and words[0] in rule[1])
    if rule == "checks":  # a script by its name, then names and filters only (after -- they reach the test runner)
        return bool(words) and _check(words[0]) and _fits(frozenset({"--silent", "--"}), words[1:])
    if rule == "checks-or-flags":  # make: its check targets and flags such as -j4 or -k, nothing else
        return bool(words) and all(_check(w) or re.match(r"^-(?:j\d*|k|s)$", w) for w in words) and any(_check(w) for w in words)
    if isinstance(rule, dict):
        if not words:
            return "" in rule
        sub = rule.get(words[0])
        if sub is not None:
            return _fits(sub, words[1:])
        return "*" in rule and _fits(rule["*"], words)
    return False


def can_stand(tool, command):
    """Whether this exact command may become a standing allow: one plain command from the short list."""
    if tool not in TOOLS or not isinstance(command, str) or not command or len(command) > 200 or not PLAIN.match(command):
        return False
    words = command.split(" ")
    if words[0] not in PROGRAMS or NEVER.search(command) or PRIVATE.search(" " + command):
        return False
    return _fits(PROGRAMS[words[0]], words[1:])


class _Locked:
    """One change at a time to the files here, across every hook and the server."""

    def __init__(self, data):
        os.makedirs(_dir(data), exist_ok=True)
        self.handle = open(os.path.join(_dir(data), "standing.lock"), "a")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


ABOUT_ALWAYS = "Your standing allows: exact commands Arnheim's hook allows on a floor without asking (connect/standing.py)."


def record(data, project, tool, command, now=None):
    """A command you allowed an agent on this floor: it went on and ran it."""
    if not project or not can_stand(tool, command):
        return
    now = now or time.time()
    path = os.path.join(_dir(data), "allowed.json")
    with _Locked(data):
        rows = [r for r in _read(path) if now - float(r.get("at") or 0) < KEEP]
        rows.append({"project": project, "tool": tool, "command": command, "at": round(now, 1)})
        _write(path, rows[-MOST:], "What you allowed your agents to run, two weeks back, to offer \"Always allow\" (connect/standing.py). Safe to delete.")


def times(data, project, tool, command, now=None):
    """How often you allowed this exact command on this floor in the last two weeks."""
    if not command:
        return 0
    now = now or time.time()
    return sum(1 for r in _read(os.path.join(_dir(data), "allowed.json"))
               if r.get("project") == project and r.get("tool") == tool and r.get("command") == command and now - float(r.get("at") or 0) < KEEP)


def rows(data):
    """Your standing allows, oldest first."""
    return [r for r in _read(os.path.join(_dir(data), "always.json"))
            if r.get("id") and r.get("project") and isinstance(r.get("command"), str) and r["command"]]


def allows(data, project, tool, command):
    """The standing allow that covers this exact command on this floor, or None. One written by hand is checked again."""
    if not project or not can_stand(tool, command):
        return None
    return next((r for r in rows(data) if r["project"] == project and r.get("tool") == tool and r["command"] == command), None)


def add(data, project, tool, command):
    """Makes a standing allow. Gives it, or raises ValueError in words when this can't stand."""
    if not project:
        raise ValueError("That request isn't from an agent on one of the building's floors.")
    if not can_stand(tool, command):
        raise ValueError("Only a plain test, check or build command, or one that only looks, can be allowed for good. This one asks each time.")
    with _Locked(data):
        kept = rows(data)
        found = next((r for r in kept if r["project"] == project and r.get("tool") == tool and r["command"] == command), None)
        if found:
            return found
        row = {"id": secrets.token_hex(6), "project": project, "tool": tool, "command": command, "what": f"{tool}: {command}",
               "at": round(time.time(), 1)}
        _write(os.path.join(_dir(data), "always.json"), kept + [row], ABOUT_ALWAYS)
        return row


def used(data, rid):
    """A standing allow just allowed a request: how often, and when last, for Settings."""
    with _Locked(data):
        kept = rows(data)
        row = next((r for r in kept if r.get("id") == rid), None)
        if row is None:
            return
        row["used"] = int(row.get("used") or 0) + 1
        row["last"] = round(time.time(), 1)
        _write(os.path.join(_dir(data), "always.json"), kept, ABOUT_ALWAYS)


def remove(data, rid):
    """Takes a standing allow out. False when there was none by that id."""
    with _Locked(data):
        kept = rows(data)
        left = [r for r in kept if r.get("id") != rid]
        if len(left) == len(kept):
            return False
        _write(os.path.join(_dir(data), "always.json"), left, ABOUT_ALWAYS)
        return True
