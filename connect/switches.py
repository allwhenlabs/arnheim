"""The switches: each of Arnheim's features on or off, from the Company page (docs/connect.md, "Switches").

Each switch is kept in data/serve.json, beside the answer connect/setup.py keeps there (whether you answer your
agents from the building), so it holds for every start. The hooks read it at each event, and serve.py as it
runs, so a change works at once. A word given to serve.py as it starts (--control, --no-control, --brain,
--routines, --pings, --no-git) holds for that start, and the page shows that switch as set by it. What isn't
here stays in the terminal on purpose: phones (--remote), the network (--lan, --share) and starting at login
(--always). The talking switches are this device's own, in its browser (src/features.js).

Standard library only.
"""

import json
import os

# (name, group, label, what it does, on unless switched off)
SWITCHES = (
    ("control", "agents", "Answer agents from the building",
     "Allow or Deny their permission requests, send them messages, and start and stop them, from this page on this "
     "computer. Off: each agent asks in its own window, as usual.", False),
    ("handovers", "agents", "Hand-overs",
     "A new conversation on a floor is told what the others there finished lately. Off: nothing is noted or told.", True),
    ("memory", "agents", "The company's memory",
     "Every agent is told what you asked the building to remember. Off: no agent is told, and the list is kept.", True),
    ("howtos", "agents", "How-tos",
     "Every agent is told, as it starts, which of the company's how-tos cover its floor.", True),
    ("always", "agents", "Always allow",
     "Commands you allowed for good on a floor run there without asking. Off: each one asks again, and the list is kept.", True),
    ("checks", "agents", "Prove the work",
     "A floor's check runs each time an agent there changes files, so the work shows as proven or not. A floor's "
     "review line runs its check either way.", True),
    ("review", "agents", "Review line",
     "On a floor with a review line, work is checked and read before it reaches you.", True),
    ("budget", "agents", "Budget brake",
     "An agent past its floor's budget for the day stops at its next step, and you are asked once.", True),
    ("restore", "agents", "Restore points",
     "Before an agent changes files in a project kept in git, the building keeps a way back.", True),
    ("clash", "agents", "Two agents, one file",
     "An agent is warned when another conversation changed the same file in the last two hours.", True),
    ("brain", "running", "Receptionist and assistant think with Claude",
     "They answer through your own Claude Code, on your own plan. Off: they answer from the building's facts alone.", False),
    ("routines", "running", "Routines",
     "Each floor's routines in data/company.json run when they are due.", False),
    ("pings", "running", "Pings to your phone",
     "The morning brief, and decisions that wait on you, at the times \"pings\" in data/company.json gives.", False),
    ("git", "running", "Look in project folders",
     "Every minute: each floor's changes not yet committed, and its open pull requests.", True),
    ("updates", "running", "Look for a newer Arnheim",
     "Once a day, ask GitHub whether a newer Arnheim is out, and say so on the Overview. Nothing about you is sent.", True),
    ("forecast", "page", "Your plan",
     "The Overview's card that says when you'd reach your plan's limits. The receptionist still answers if you ask.", True),
)
NAMES = tuple(s[0] for s in SWITCHES)
DEFAULTS = {s[0]: s[4] for s in SWITCHES}


def path(data):
    return os.path.join(data, "serve.json")


def saved(data):
    """Everything in data/serve.json, as it is: {} when it is missing or isn't a JSON object."""
    try:
        with open(path(data), encoding="utf-8-sig") as handle:
            got = json.load(handle)
    except Exception:  # missing, unreadable, or too deep to read: every switch at its usual setting
        return {}
    return got if isinstance(got, dict) else {}


def on(name, data, kept=None):
    """Whether a switch is on: what you chose, or its default. A name that isn't a switch is off."""
    if name not in DEFAULTS:
        return False
    value = (saved(data) if kept is None else kept).get(name)
    return value if isinstance(value, bool) else DEFAULTS[name]


class _Locked:
    """One change at a time to data/serve.json from the page (connect/setup.py reads it again just before it writes)."""

    def __init__(self, data):
        os.makedirs(data, exist_ok=True)
        self.handle = open(os.path.join(data, "serve.lock"), "a")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


def save(name, value, data):
    """Keeps one switch, leaving everything else in the file as it was. Gives the file's new contents."""
    if name not in DEFAULTS or not isinstance(value, bool):
        raise ValueError(f"There is no switch called {name!r}.")
    with _Locked(data):
        kept = {**saved(data), name: value}
        part = f"{path(data)}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(kept, handle, indent=1)
            handle.write("\n")
        os.replace(part, path(data))
    return kept


def restore(name, before, data):
    """Puts one switch back as it was: `before` as saved() had it, or taken out when it wasn't there."""
    if isinstance(before, bool):
        return save(name, before, data)
    with _Locked(data):
        kept = saved(data)
        kept.pop(name, None)
        part = f"{path(data)}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(kept, handle, indent=1)
            handle.write("\n")
        os.replace(part, path(data))
    return kept


def listing(data, locked=None):
    """The switches as the page shows them: [{name, group, label, about, on, set_by}], where set_by is the
    word serve.py started with that holds this switch for now, or None when the page can change it."""
    locked = locked or {}
    kept = saved(data)
    rows = []
    for name, group, label, about, _ in SWITCHES:
        held = locked.get(name)
        rows.append({"name": name, "group": group, "label": label, "about": about,
                     "on": held[0] if held else on(name, data, kept), "set_by": held[1] if held else None})
    return rows
