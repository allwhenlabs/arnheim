#!/usr/bin/env python3
"""OpenAI's Codex CLI in the building (docs/connect.md, "Codex").

Codex has hooks like Claude Code's, by the same names: it runs a command at each moment (a conversation
starting, your message, each step, a permission it asks for, a turn ending, you stopping it) and hands it
what happened as JSON on stdin. connect/setup.py adds this file to them, in ~/.codex/hooks.json:

    {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}], ...}}

and Codex runs new hooks only once you trust them (type /hooks in Codex). Each event goes on to
connect/claude_code.py, marked as Codex's, so a Codex conversation is in the building just as a Claude
Code one is: someone at work while it works, amber while it waits for your permission, what it said last,
its plan, what it spends, and, with control on, your answers and messages from the building.

Older Codex, without hooks, runs a program only when a turn ends: its `notify` setting, in
~/.codex/config.toml (`notify = ["python3", "/path/to/arnheim/connect/codex.py"]`), which hands it one
JSON argument. That still shows the conversation, finished and waiting for your next step, through
connect/agents.py. Once Codex has run Arnheim's hooks lately (they note it in data/feeds/codex-hooks), notify
stays quiet, so nothing is told twice; until then, an older Codex, or a newer one whose hooks aren't
trusted yet, still shows through notify.

It never troubles Codex: any trouble goes to data/feeds/claude-code.log. Standard library only.
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, HERE)
import agents  # noqa: E402  (beside this file)
import claude_code  # noqa: E402


def codex_home():
    return os.path.expanduser(os.environ.get("CODEX_HOME") or os.path.join("~", ".codex"))


HEARD_FOR = 12 * 3600  # hooks heard this recently: notify stays quiet


def heard_path():
    return os.path.join(claude_code.DATA, "feeds", "codex-hooks")


def hooks_ran():
    """Notes that Codex ran Arnheim's hooks just now."""
    path = heard_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(f"Codex ran Arnheim's hooks at {time.strftime('%Y-%m-%d %H:%M:%S')}. Safe to delete.\n")


def hooked(now=None):
    """Whether Codex has run Arnheim's hooks lately, so notify would tell the building twice. Hooks written
    but never run (an older Codex, or new hooks not trusted yet) don't count."""
    try:
        return (now or time.time()) - os.path.getmtime(heard_path()) < HEARD_FOR
    except OSError:
        return False


def heard(given):
    """Shows one notification from Codex's notify setting. Gives back the conversation's key, or None."""
    if not isinstance(given, dict) or given.get("type") != "agent-turn-complete":
        return None
    session = given.get("thread-id") or given.get("session-id") or given.get("turn-id")
    if not session:
        return None
    asked = given.get("input-messages")
    first = asked[0] if isinstance(asked, list) and asked and isinstance(asked[0], str) else None
    return agents.report("Codex", session, given.get("cwd") or os.getcwd(), "finished",
                         str(given.get("last-assistant-message") or ""), title=first)


def respond(event):
    """One of Codex's hook events: what Codex should hear back, as connect/claude_code.py gives it, or None."""
    if not isinstance(event, dict) or not event.get("hook_event_name"):
        return None
    return claude_code.respond({**event, claude_code.AGENT: "Codex"})


def main():
    out = None
    try:
        if len(sys.argv) > 1:  # notify: a turn ended
            if not hooked():
                heard(json.loads(sys.argv[1]))
        else:  # a hook: what happened, on stdin
            raw = sys.stdin.read()
            try:
                hooks_ran()
            except OSError as error:
                claude_code.note(error)
            out = respond(json.loads(raw) if raw.strip() else {})
    except Exception as error:  # never trouble Codex: note it and carry on
        claude_code.note(error)
    if out:
        try:
            sys.stdout.write(json.dumps(out, ensure_ascii=False))
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
    sys.exit(0)


if __name__ == "__main__":
    main()
