"""Arnheim that keeps running: started by itself when you log in, and again if it stops with an error, so
closing the terminal doesn't close the building (README, "Start"). `python3 serve.py --always` sets it up
and starts it; `python3 serve.py --always off` stops it and takes it out.

On a Mac it is a launch agent, ~/Library/LaunchAgents/local.arnheim.serve.plist, run by launchd for you
alone; on Linux a systemd user service, ~/.config/systemd/user/arnheim.service. Each runs this copy's
serve.py with the same Python, the switches you gave and the PATH you had, so git, gh and claude are found
as in your terminal, and keeps what it prints in a log (~/Library/Logs/arnheim.log, or the journal).
Nothing else on the computer changes. Windows isn't covered yet. Standard library only.
"""
import os
import plistlib
import subprocess
import sys

LABEL = "local.arnheim.serve"
UNIT = "arnheim.service"


class Unsupported(Exception):
    """This computer has no way here to start Arnheim at login, in words."""


def kind(platform=None):
    platform = platform or sys.platform
    return "mac" if platform == "darwin" else "linux" if platform.startswith("linux") else None


def path_of(platform=None):
    """Where the login item is kept, or None where there is none."""
    k = kind(platform)
    if k == "mac":
        return os.path.join(os.path.expanduser("~"), "Library", "LaunchAgents", LABEL + ".plist")
    if k == "linux":
        config = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
        return os.path.join(config, "systemd", "user", UNIT)
    return None


def log_of(platform=None):
    return os.path.join(os.path.expanduser("~"), "Library", "Logs", "arnheim.log") if kind(platform) == "mac" else None


def installed(platform=None):
    path = path_of(platform)
    return bool(path) and os.path.isfile(path)


def quoted(word):
    """One word for a systemd ExecStart line: in double quotes when it has a space or a quote. ExecStart
    expands $ and % specifiers, so each is doubled."""
    if word and not any(c in word for c in ' \t"\'\\$%'):
        return word
    return '"' + word.replace("\\", "\\\\").replace('"', '\\"').replace("$", "$$").replace("%", "%%") + '"'


def plain_path(path):
    """A folder for WorkingDirectory=, which takes the rest of the line as it is, quotes and all: only %
    specifiers are expanded there, so % is doubled."""
    return path.replace("%", "%%")


def env_word(assignment):
    """One Environment= assignment, in double quotes: systemd reads backslash escapes and % specifiers in it,
    but never expands $ there."""
    return '"' + assignment.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def content(command, root, env_path, platform=None):
    """The login item's file, as bytes: it runs `command` (a list) in `root`, with `env_path` as PATH."""
    if kind(platform) == "mac":
        log = log_of(platform)
        return plistlib.dumps({
            "Label": LABEL,
            "ProgramArguments": list(command),
            "WorkingDirectory": root,
            "EnvironmentVariables": {"PATH": env_path, "PYTHONUNBUFFERED": "1", "ARNHEIM_ALWAYS": "1"},
            "RunAtLoad": True,
            "KeepAlive": {"SuccessfulExit": False},  # again if it stops with an error, never after Ctrl-C or --always off
            "ThrottleInterval": 60,
            "ProcessType": "Interactive",
            "StandardOutPath": log,
            "StandardErrorPath": log,
        })
    if kind(platform) == "linux":
        if any("\n" in w or "\r" in w for w in [*command, root, env_path]):
            raise Unsupported("A folder or PATH with a line break in its name can't go in a systemd unit. Keep this window "
                              "open with python3 serve.py instead.")
        return ("[Unit]\nDescription=Arnheim, the building\n\n[Service]\n"
                f"ExecStart={' '.join(quoted(w) for w in command)}\n"
                f"WorkingDirectory={plain_path(root)}\n"
                f"Environment={env_word('PATH=' + env_path)}\nEnvironment=PYTHONUNBUFFERED=1\nEnvironment=ARNHEIM_ALWAYS=1\n"
                "Restart=on-failure\nRestartSec=60\n\n[Install]\nWantedBy=default.target\n").encode("utf-8")
    raise Unsupported("Starting Arnheim when you log in works on a Mac and on Linux for now. Keep this window open, or start "
                      "it from your computer's own list of things to start at login.")


def commands_on(path, platform=None):
    """What starts the login item now, after any copy of it already running is stopped."""
    if kind(platform) == "mac":
        domain = f"gui/{os.getuid()}"
        return [["launchctl", "bootout", f"{domain}/{LABEL}"], ["launchctl", "bootstrap", domain, path]]
    return [["systemctl", "--user", "daemon-reload"], ["systemctl", "--user", "enable", "--now", UNIT],
            ["systemctl", "--user", "restart", UNIT]]


def commands_off(platform=None):
    if kind(platform) == "mac":
        return [["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"]]
    return [["systemctl", "--user", "disable", "--now", UNIT]]


def stop_running(run=subprocess.run, platform=None):
    """Stops the login item's copy if it runs, leaving its file: so the port is free again."""
    if not installed(platform):
        return
    for command in commands_off(platform):
        run(command, capture_output=True, text=True)


def turn_on(command, root, env_path=None, run=subprocess.run, platform=None):
    """Writes the login item and starts it. Gives its path. Raises Unsupported, or OSError when it can't be
    written, or RuntimeError when the computer won't start it (with its words)."""
    path = path_of(platform)
    data = content(command, root, env_path or os.environ.get("PATH", "/usr/bin:/bin"), platform)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if kind(platform) == "mac":
        os.makedirs(os.path.dirname(log_of(platform)), exist_ok=True)
    part = f"{path}.{os.getpid()}.part"
    with open(part, "wb") as handle:
        handle.write(data)
    os.replace(part, path)
    steps = commands_on(path, platform)
    for n, step in enumerate(steps):
        done = run(step, capture_output=True, text=True)
        stopping_first = kind(platform) == "mac" and n == 0  # nothing to stop the first time: that's fine
        if done.returncode != 0 and not stopping_first:
            raise RuntimeError((done.stderr or done.stdout or "").strip() or f"{' '.join(step)} didn't work")
    return path


def turn_off(run=subprocess.run, platform=None):
    """Stops the login item and takes it out. Gives its path, or None when there was none."""
    path = path_of(platform)
    if not path or not os.path.isfile(path):
        return None
    for command in commands_off(platform):
        run(command, capture_output=True, text=True)
    os.remove(path)
    if kind(platform) == "linux":
        run(["systemctl", "--user", "daemon-reload"], capture_output=True, text=True)
    return path
