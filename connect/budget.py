"""A budget per floor, with a brake (docs/connect.md, "A budget per floor").

What each Claude Code conversation spends, counted from its own transcript as the hook runs
(connect/claude_code.py): the new tokens of each reply, that is what Claude read fresh, wrote to its
cache, and wrote back. Re-reading its cache is left out: that is the same context again. A reply is
logged once for each of its parts, so each is counted once, by its id, on the day it was written.
A Codex conversation's transcript keeps a running total instead: what it read fresh and wrote, and the
growth of that total is counted.

A floor in data/company.json can give its agents a budget for a day, in new tokens ("budget":
2000000), or the company can give every floor one. When a floor's agents pass it, the hook stops the
one at work at its next step, once, and asks you whether they may go on ("Let them go on" in the
building gives them as much again, for today). Standard library only.
"""
import datetime
import json
import os

COUNTED = ("input_tokens", "cache_creation_input_tokens", "output_tokens")
FIRST_READ = 64 * 1024 * 1024  # a transcript met for the first time is read from at most this far back
MIDWAY = "midway"  # read part way through with no running total seen yet (a Codex transcript)


def local_day(stamp=None):
    """The day on this computer's clock, as 2026-11-12: now, or when an ISO time was."""
    if stamp:
        try:
            return datetime.datetime.fromisoformat(str(stamp).replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.datetime.now().strftime("%Y-%m-%d")


def new_tokens(path, read, limits=None):
    """New tokens in a transcript since it was last read: ({day: tokens}, where it has been read to).
    `read` is what this gave back last time ({"path", "at", "last"}), or {}. A dict given as `limits` gets
    the plan's limits a Codex transcript reported last, if it did (connect/usage.py)."""
    read = read if isinstance(read, dict) and read.get("path") == path else {}
    try:
        size = os.path.getsize(path)
    except (OSError, TypeError, ValueError):
        return {}, read
    start = read.get("at") if isinstance(read.get("at"), int) else 0
    last = read.get("last")
    if start > size:  # a new file under the old name
        start, last = 0, None
    if not start and size > FIRST_READ:
        start = size - FIRST_READ
    spent = {}
    midway = bool(start and not read)  # met for the first time, part way through
    with open(path, "rb") as handle:
        handle.seek(start)
        if midway:
            start += len(handle.readline())  # from the start of a whole line
        for raw in handle:
            if not raw.endswith(b"\n"):
                break  # still being written: read it next time
            start += len(raw)
            if b'"token_count"' in raw:  # Codex's transcript: a running total after each reply
                found = codex_total(raw)
                if found is None:
                    continue
                total, when, said = found
                if limits is not None and isinstance(said, dict):
                    limits.clear()
                    limits.update(said)
                if total is None:
                    continue
                before = last if isinstance(last, int) and not isinstance(last, bool) else None
                if before is None and (midway or last == MIDWAY):
                    last = total
                    continue  # what came before this point isn't counted, as for Claude Code
                last = total
                n = max(0, total - (before or 0))
                if n:
                    day = local_day(when)
                    spent[day] = spent.get(day, 0) + n
                continue
            if b'"usage"' not in raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            message = row.get("message") if isinstance(row, dict) and row.get("type") == "assistant" else None
            if not isinstance(message, dict) or not isinstance(message.get("usage"), dict):
                continue
            if message.get("id") and message["id"] == last:
                continue  # another part of the reply just counted
            last = message.get("id")
            n = 0
            for key in COUNTED:
                try:
                    n += max(0, int(message["usage"].get(key) or 0))
                except (TypeError, ValueError):
                    pass
            day = local_day(row.get("timestamp"))
            spent[day] = spent.get(day, 0) + n
    if midway and last is None:
        last = MIDWAY  # met part way through, with no total yet: the next one is where counting starts
    return spent, {"path": path, "at": start, "last": last}


def codex_total(raw):
    """From one of a Codex transcript's token counts: (the new tokens it has spent in all, that is what it read
    fresh, not from its cache, and what it wrote, or None when it doesn't say; when; the plan's limits it
    reports, or None). None for any other line."""
    try:
        row = json.loads(raw)
    except ValueError:
        return None
    payload = row.get("payload") if isinstance(row, dict) and row.get("type") == "event_msg" else None
    if not isinstance(payload, dict) or payload.get("type") != "token_count":
        return None
    said = payload.get("rate_limits") if isinstance(payload.get("rate_limits"), dict) else None
    info = payload.get("info")
    total = info.get("total_token_usage") if isinstance(info, dict) else None
    if not isinstance(total, dict):
        return None, row.get("timestamp"), said
    try:
        fresh = max(0, int(total.get("input_tokens") or 0) - int(total.get("cached_input_tokens") or 0))
        return fresh + max(0, int(total.get("output_tokens") or 0)), row.get("timestamp"), said
    except (TypeError, ValueError):
        return None


def budget_of(company, project):
    """A floor's budget for a day in new tokens, or the company's for every floor, or None."""
    floors = company.get("floors") if isinstance(company, dict) else None
    floor = next((f for f in floors or [] if isinstance(f, dict) and str(f.get("project") or f.get("label") or "") == project), None)
    for given in ((floor or {}).get("budget"), company.get("budget") if isinstance(company, dict) else None):
        if isinstance(given, (int, float)) and not isinstance(given, bool) and given > 0:
            return int(given)
    return None


def spent_today(talks, project, day, ended=None):
    """What a floor's conversations have spent on `day`, with what those that left the feed today spent
    (`ended`, the feed's, from leave())."""
    total = 0
    for c in talks:
        spent = c.get("spent") if isinstance(c, dict) and c.get("project") == project else None
        if isinstance(spent, dict) and spent.get("day") == day and isinstance(spent.get("tokens"), int):
            total += spent["tokens"]
    if isinstance(ended, dict) and ended.get("day") == day and isinstance(ended.get("talks"), dict):
        for t in ended["talks"].values():
            if isinstance(t, dict) and t.get("project") == project and isinstance(t.get("tokens"), int):
                total += t["tokens"]
    return total


def leave(feed, talks, day):
    """Conversations leaving the feed (ended, or not heard from for long): what each spent today, and how
    far its transcript was read, kept in the feed's "ended" for the day, so the floor's total still counts
    them and one that comes back carries on from there (come_back)."""
    ended = feed.get("ended") if isinstance(feed.get("ended"), dict) and feed["ended"].get("day") == day else {}
    kept = dict(ended["talks"]) if isinstance(ended.get("talks"), dict) else {}
    for c in talks:
        spent = c.get("spent") if isinstance(c.get("spent"), dict) else {}
        tokens = spent.get("tokens") if spent.get("day") == day and isinstance(spent.get("tokens"), int) else 0
        if c.get("id") and tokens > 0:
            kept[c["id"]] = {"project": c.get("project"), "tokens": tokens, "read": c.get("read")}
    feed["ended"] = {"day": day, "talks": kept}


def come_back(feed, key, day):
    """A conversation back in the feed today: what it had spent and read when it left, or None."""
    ended = feed.get("ended") if isinstance(feed.get("ended"), dict) and feed["ended"].get("day") == day else None
    talks = ended.get("talks") if ended and isinstance(ended.get("talks"), dict) else {}
    back = talks.pop(key, None)
    return back if isinstance(back, dict) else None


def tokens(n):
    """1,200,000 as 1.2 million, for people."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}".rstrip("0").rstrip(".") + " million"
    if n >= 1000:
        return f"{round(n / 1000)} thousand"
    return str(n)
