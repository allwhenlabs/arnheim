#!/usr/bin/env python3
"""The chain of command and office hours (docs/connect.md, steps 26 and 27).

The chain of command. When an agent asks you something (Claude Code's question tool, or a turn that ends with a
question), the hook (connect/claude_code.py) asks this deputy for its floor's lead first: is it already settled?
Settled means a decision you made before clearly answers it:

- the same question, on the same floor, answered with Remember my answer ticked (data/control/decisions.json, for this
  computer only; never one with a secret in it, or about what is never answered for you), or
- a decision in the company's memory (data/memory.json) or one you remembered, whose words share at least two words
  that carry meaning with the question and its options (src/memory.js's decidedFor, kept in step below) and that
  names exactly one of its options, not after "never" or "not".

With the brain switched on (connect/brain.py), the lead may also judge whether one of those decisions answers it,
and must quote it word for word; a quote that isn't one of your decisions, or an answer that isn't one of the
options, answers nothing. Without the brain, an open question (a turn that ends with one) is answered only when
the same question was answered before.

Never answered for you: anything about secrets, money, deleting, pushing, publishing or sending; a question no
decision answers; a kind of question you marked Always ask me; a decision you undid for that kind of question.
Permissions are never answered here: only Always allow's exact commands run without asking (connect/standing.py).

Each answer it gives is kept in data/control/answered/ for Needs you's "Answered for you", with Undo, which tells the
agent you changed it and marks that decision as not for that kind of question again.

Learning from your corrections (switch "learn", on unless you switch it off). After an Undo, the building asks once, in
the same place: "Should the leads stop answering this kind of question for you?" Yes keeps that kind of question in
always_ask, with the words it came from; No says nothing more, and it never asks again about that decision (kept in
declined). The second time an answer from the same decision is undone, the decision is set aside without asking (a
not_for mark for every question) and the page says so, with Undo. Show me's Not quite asks the same of a kind of
change: "Should Show me ask you before calling this kind of change done?" Yes keeps it in always_ask, marked "show":
work of that kind that the building starts on that floor isn't counted done (its ready task stays open and the floor's
next one waits) until you say Looks good. Nothing is learned from words with a password, token or key in them
(connect/intake.py's has_secret).

Office hours. With the switch on, and while nobody is using the building outside the times you chose (13:00 and
18:00 unless you choose others, each open for half an hour, or a sitting you opened): an agent's question tool is
answered at once that you are away until the next one, and it is kept for the sitting; a turn that ends with a
question waits as a card, as it always does; a permission request asks in the agent's own window, as it always does,
and is listed for the sitting. Urgent things still reach you at once: a permission that reaches something private or
deletes in bulk, an agent close to its plan's limit, an agent asking the same thing a second time, and a question
about secrets, money, deleting, pushing, publishing or sending (never told you are away: it waits for you as a card).

Standard library only, and it runs on Python 3.9.
"""
import datetime
import json
import os
import re
import secrets
import shlex
import subprocess
import tempfile
import threading
import time

try:
    from . import switches  # as connect.deputy, from serve.py
except ImportError:
    try:
        import switches  # beside this file, as the hook has it
    except ImportError:  # loaded by its path alone (python3 -I)
        import importlib.util
        _spec = importlib.util.spec_from_file_location("arnheim_switches", os.path.join(os.path.dirname(os.path.realpath(__file__)), "switches.py"))
        switches = importlib.util.module_from_spec(_spec)
        _spec.loader.exec_module(switches)

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
DECISIONS_MOST = 200
ANSWERED_KEPT = 48 * 3600  # Answered for you, two days back
PARKED_KEPT = 48 * 3600  # what waited for office hours
ANSWERED_SHOWN = 30
TEXT = 300
ID = re.compile(r"^[a-z]-[0-9a-f]{8}$")
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{8,40}$")


def one_line(text, most=TEXT):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


# ---------- words: src/memory.js's decidedFor, in Python (kept in step; tests/test_chain.py runs both) ----------

SKIP = frozenset([
    'the', 'and', 'for', 'are', 'but', 'not', 'you', 'all', 'any', 'can', 'had', 'her', 'was', 'one', 'our', 'out',
    'has', 'have', 'his', 'how', 'its', 'may', 'new', 'now', 'old', 'see', 'two', 'way', 'who', 'did', 'get', 'got', 'let', 'say',
    'she', 'too', 'use', 'that', 'this', 'with', 'from', 'they', 'them', 'then', 'than', 'there', 'their', 'what', 'when', 'where',
    'which', 'while', 'will', 'would', 'should', 'could', 'shall', 'into', 'onto', 'about', 'your', 'yours', 'just', 'like', 'want',
    'need', 'needs', 'does', 'done', 'doing', 'make', 'made', 'some', 'every', 'each', 'also', 'only', 'very', 'more', 'most', 'been',
    'being', 'were', 'here', 'okay', 'yes', 'please', 'never', 'always', 'before', 'after', 'again', 'first', 'next', 'last', 'one',
    'it’s', "it's", 'i’m', "i'm", 'do', 'is', 'to', 'of', 'in', 'on', 'at', 'or', 'an', 'a', 'we', 'i', 'me', 'my', 'be', 'so', 'if'])
WORD = re.compile(r"[a-z][a-z’'-]+")
THRESHOLD = 2  # decidedFor's: at least this many words that carry meaning in common


def stem(word):
    return re.sub(r"(?:ing|ed|es|s)$", "", word) or word


def words(text):
    """The words that carry meaning, stemmed, as src/memory.js has them."""
    return {stem(w) for w in WORD.findall(str(text or "").lower()) if len(w) > 2 and w not in SKIP}


def decided_for(question, rows, most=2):
    """src/memory.js's decidedFor: the decisions that share at least THRESHOLD words that carry meaning with the
    question, most shared first, at most `most`."""
    asked = words(question)
    if not asked:
        return []
    scored = [(len(words(r.get("text")) & asked), r) for r in rows if isinstance(r, dict)]
    found = [pair for pair in scored if pair[0] >= THRESHOLD]
    found.sort(key=lambda pair: -pair[0])  # stable, as JavaScript's sort is
    return [r for _, r in found[:most]]


def norm(text):
    """A question as compared with another: its letters and numbers only, in lower case."""
    return " ".join(re.findall(r"[a-z0-9]+", str(text or "").lower()))


def same_kind(a, b):
    """Two questions of the same kind: the same words, or at least THRESHOLD words that carry meaning in common."""
    return bool(norm(a)) and (norm(a) == norm(b) or len(words(a) & words(b)) >= THRESHOLD)


# Show me's kind of change: words every change's title has, left out before the titles are compared
CHANGE_SKIP = frozenset(stem(w) for w in (
    "change", "changes", "changed", "changing", "add", "adds", "added", "adding", "fix", "fixes", "fixed", "fixing",
    "update", "updates", "updated", "updating", "make", "makes", "making", "page", "pages"))
CHANGE_THRESHOLD = 3


def same_change(a, b):
    """Two Show me titles of the same kind of change, `a` the rule's: the same words, or at least CHANGE_THRESHOLD words
    that carry meaning in common, leaving out the words every change has (change, add, fix, update, make, page). Stricter
    than a kind of question: "Change the heading colour on the home page" and "Add a search box to the home page" share
    only "home". A rule with fewer such words needs them all, and never fewer than two: "Fix the login form" holds
    "Make the login form wider"."""
    if not norm(a):
        return False
    if norm(a) == norm(b):
        return True
    rule = words(a) - CHANGE_SKIP
    return len(rule & (words(b) - CHANGE_SKIP)) >= max(2, min(CHANGE_THRESHOLD, len(rule)))


# What is never answered for you, whatever was decided: secrets, money, deleting, pushing, publishing, sending.
NEVER = re.compile(
    r"\b(?:secrets?|passwords?|passphrases?|passcodes?|tokens?|api[ _-]?keys?|private[ _-]?keys?|keys?|credentials?|ssh|"
    r"env|log[ -]?ins?|sign[ -]?ins?|2fa|otp|"
    r"money|pay|pays|paid|paying|payments?|prices?|pricing|costs?|charge[sd]?|charging|billing|bills?|invoices?|refunds?|"
    r"purchas\w*|buy\w*|bought|subscri\w*|credit|debit|bank\w*|transfer\w*|wallets?|crypto\w*|"
    r"delet\w*|remov\w*|drop|drops|dropped|dropping|wip\w*|eras\w*|destroy\w*|purg\w*|truncat\w*|rm|reset\w*|overwrit\w*|force\w*|"
    r"push\w*|merg\w*|deploy\w*|releas\w*|publish\w*|ship\w*|launch\w*|go[ -]live|"
    r"send\w*|sent|e-?mails?|mail\w*|messag\w*|post|posts|posting|posted|tweet\w*|notif\w*|invit\w*|announc\w*|"
    r"sudo|chmod|chown)\b|[$£€¥]", re.I)


def never(*texts):
    """Whether any of these words is one the chain never answers."""
    return any(NEVER.search(str(t or "")) for t in texts)


NEVER_URGENT = "It is about secrets, money, deleting, pushing, publishing or sending."


def never_asked(questions):
    """Whether what an agent asks touches secrets, money, deleting, pushing, publishing or sending: any question, its
    header, or an option's label or description. Never answered for you, and never told you are away: it waits for you."""
    for q in questions or []:
        if not isinstance(q, dict):
            continue
        options = [f'{o.get("label") or ""} {o.get("description") or ""}' for o in q.get("options") or [] if isinstance(o, dict)]
        if never(q.get("question"), q.get("header"), *options):
            return True
    return False


NOT_BEFORE = re.compile(r"\b(?:never|not|no|don'?t|do not|avoid|instead of|rather than|without|stop|nor)\b[^.;!?]{0,24}$", re.I)


def chosen_option(text, labels):
    """The one option a decision names, and not after "never" or "not": the label, or None for none or several."""
    picked = []
    said = str(text or "")
    for label in labels:
        label = str(label or "").strip()
        if not label:
            continue
        for m in re.finditer(r"(?<![\w-])" + re.escape(label) + r"(?![\w-])", said, re.I):
            if not NOT_BEFORE.search(said[max(0, m.start() - 30):m.start()]):
                picked.append(label)
                break
    return picked[0] if len(picked) == 1 else None


# ---------- one writer at a time ----------

class _Locked:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.handle = open(path, "a")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


def _read(path):
    try:
        with open(path, encoding="utf-8-sig") as handle:
            got = json.load(handle)
        return got if isinstance(got, dict) else None
    except (OSError, ValueError):
        return None


def _write(path, doc):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    part = f"{path}.{os.getpid()}.{threading.get_ident()}.part"
    with open(part, "w", encoding="utf-8") as handle:
        json.dump(doc, handle, ensure_ascii=False, indent=1)
    os.replace(part, path)


def day_of(at):
    """A date as the page says it: 18 Nov."""
    try:
        d = datetime.datetime.fromtimestamp(float(at))
    except (TypeError, ValueError, OverflowError, OSError):
        return "an earlier day"
    return f"{d.day} {d.strftime('%b')}"


# ---------- the decisions the chain answers from: data/control/decisions.json ----------

# In data/control/, which serve.py keeps to this computer: never to a paired phone or a view-only link, as your words in
# an answer might be anything. Kept in data/decisions.json before; moved here the first time it is read.
OLD_DECISIONS = "decisions.json"
# What decisions.json keeps: your remembered answers, what you always answer yourself (and, marked "show", the kinds of
# change Show me asks you about first), the decisions undone for a kind of question (or set aside for all of them),
# and the corrections you said No to learning from.
LISTS = ("decisions", "always_ask", "not_for", "declined")


def decisions_path(data):
    return os.path.join(data, "control", "decisions.json")


def _lock_path(data):
    return os.path.join(data, "control", "decisions.lock")


def _moved_in(data):
    """data/decisions.json, from before, moved into data/control/ once: its rows join any kept there already."""
    old = os.path.join(data, OLD_DECISIONS)
    if not os.path.isfile(old):
        return
    with _Locked(_lock_path(data)):
        if not os.path.isfile(old):
            return  # another process moved it
        new = decisions_path(data)
        if not os.path.isfile(new):
            os.replace(old, new)
        else:
            was, now = _read(old) or {}, _read(new) or {}
            for name in LISTS:
                rows = now.get(name) if isinstance(now.get(name), list) else []
                have = {r.get("id") for r in rows if isinstance(r, dict)}
                before = was.get(name) if isinstance(was.get(name), list) else []
                extra = [r for r in before if isinstance(r, dict) and r.get("id") and r.get("id") not in have]
                now[name] = extra + rows
            _write(new, now)
            os.remove(old)
        try:
            os.remove(os.path.join(data, "decisions.lock"))  # the old lock beside it
        except OSError:
            pass


def read_decisions(data):
    try:
        _moved_in(data)
    except OSError:
        pass  # read from where it is next time
    return _decisions_now(data)


def _decisions_now(data):
    doc = _read(decisions_path(data)) or {}
    out = {}
    for name in LISTS:
        rows = doc.get(name)
        out[name] = [r for r in rows if isinstance(r, dict) and r.get("id")] if isinstance(rows, list) else []
    return out


def _change_decisions(data, change):
    read_decisions(data)  # moved in from data/decisions.json first, if it is still there
    with _Locked(_lock_path(data)):
        doc = _decisions_now(data)
        out = change(doc)
        _write(decisions_path(data), {
            "about": "What the floors' leads answer from for you (docs/connect.md, \"A chain of command\"): your answers with Remember my "
                     "answer ticked, what you asked to be asked about always, decisions undone for a kind of question or set aside, "
                     "and the corrections you said No to learning from. Yours to edit.",
            **doc})
        return out


def new_id(letter):
    return f"{letter}-{secrets.token_hex(4)}"


REMEMBER_SECRET = "It looks like it has a password, token or key in it, so I won't remember it."
REMEMBER_NEVER = ("It's about secrets, money, deleting, pushing, publishing or sending, which you always answer yourself, so I "
                  "won't remember it.")
_live = None


def _secret_spans(text):
    """connect/live.py's secret_spans, loaded when first wanted (the hook loads this file by its path alone)."""
    global _live
    if _live is None:
        try:
            from . import live as found  # as connect.deputy, from serve.py
        except ImportError:
            try:
                import live as found  # beside this file
            except ImportError:
                import importlib.util
                spec = importlib.util.spec_from_file_location("arnheim_live", os.path.join(HERE, "live.py"))
                found = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(found)
        _live = found
    return _live.secret_spans(text)


def unrememberable(*texts):
    """Why an answer can't be remembered, in plain words, or None: a password, token or key in the question or the
    answer (as the building finds them anywhere; a scanner that fails counts as one), or anything the leads never answer
    for you (never)."""
    for text in texts:
        try:
            if _secret_spans(str(text or "")):
                return REMEMBER_SECRET
        except Exception:
            return REMEMBER_SECRET
    return REMEMBER_NEVER if never(*texts) else None


def remember_answer(data, project, question, answer, options=None, header=None, kind="choices", key=None):
    """Keeps your answer to a question, so the same question on the same floor is answered with it next time. Never one
    with a secret in it, or about something the leads never answer (unrememberable)."""
    question, answer = one_line(question), one_line(answer, 500)
    if not question or not answer:
        raise ValueError("A question and its answer are needed.")
    why = unrememberable(question, answer, header, *(options or []))
    if why:
        raise ValueError(why)
    row = {"id": new_id("d"), "project": project, "kind": kind, "question": question, "header": one_line(header, 40) or None,
           "options": [one_line(o, 80) for o in (options or []) if str(o or "").strip()][:8], "answer": answer, "at": round(time.time(), 1)}

    def change(doc):
        kept = [r for r in doc["decisions"] if not (r.get("project") == project and norm(r.get("question")) == norm(question))]
        if len(kept) >= DECISIONS_MOST:
            raise ValueError(f"The leads keep {DECISIONS_MOST} decisions at most. Remove one in Settings first.")
        doc["decisions"] = kept + [row]
        doc["always_ask"] = [r for r in doc["always_ask"] if r.get("show") or not (r.get("project") in (None, project) and same_kind(r.get("question"), question))]
        return row
    return _change_decisions(data, change)


def ask_always(data, project, question, came_from=None, show=False):
    """Marks a kind of question as one the leads never answer for you. `came_from`: the words it was learned from (an
    Undo, or Show me's Not quite), kept beside it. `show`: a kind of change Show me asks you about before it is counted
    done, which the leads' answers leave alone."""
    question = one_line(question)
    if not question:
        raise ValueError("Say which question.")
    came_from = one_line(came_from, 600) or None
    if came_from and has_secret(came_from, question):
        raise ValueError(REMEMBER_SECRET)
    row = {"id": new_id("a"), "project": project, "question": question, "at": round(time.time(), 1)}
    if came_from:
        row["from"] = came_from
    if show:
        row["show"] = True

    def change(doc):
        doc["always_ask"] = [r for r in doc["always_ask"]
                             if not (bool(r.get("show")) == bool(show) and r.get("project") == project and norm(r.get("question")) == norm(question))] + [row]
        if not show:
            doc["decisions"] = [r for r in doc["decisions"] if not (r.get("project") == project and norm(r.get("question")) == norm(question))]
        return row
    return _change_decisions(data, change)


def forget(data, did):
    """Takes out a decision you remembered, an Always ask me, or an undo's mark. False when there is none by that id."""
    if not isinstance(did, str) or not ID.match(did):
        return False

    def change(doc):
        before = sum(len(doc[n]) for n in doc)
        for name in doc:
            doc[name] = [r for r in doc[name] if r.get("id") != did]
        return sum(len(doc[n]) for n in doc) < before
    return _change_decisions(data, change)


def not_for(data, decision, question, project):
    """An undo: this decision is not the answer to this kind of question again."""
    row = {"id": new_id("n"), "decision": decision, "question": one_line(question), "project": project, "at": round(time.time(), 1)}

    def change(doc):
        doc["not_for"] = (doc["not_for"] + [row])[-DECISIONS_MOST:]
        return row
    return _change_decisions(data, change)


def memory_rows(data):
    doc = _read(os.path.join(data, "memory.json")) or {}
    rows = doc.get("memory")
    return [r for r in rows if isinstance(r, dict) and str(r.get("text") or "").strip()] if isinstance(rows, list) else []


def decision_views(data):
    """The decisions the leads answer from, and what you always want asked, as Settings lists them."""
    doc = read_decisions(data)
    return {"decisions": [{k: r.get(k) for k in ("id", "project", "question", "answer", "at")} for r in doc["decisions"]][::-1],
            "always_ask": [{**{k: r.get(k) for k in ("id", "project", "question", "at", "from")}, "show": bool(r.get("show"))}
                           for r in doc["always_ask"]][::-1],
            "set_aside": [{k: r.get(k) for k in ("id", "decision", "text", "at")} for r in doc["not_for"] if r.get("all")][::-1]}


# ---------- is it settled? ----------

def _excluded(doc, decision_id, question, project):
    """Undone for this kind of question, or set aside for every question (undone twice)."""
    return any(n.get("decision") == decision_id and n.get("project") in (None, project)
               and (n.get("all") or same_kind(n.get("question"), question)) for n in doc["not_for"])


def candidates(data, question, project, doc=None, mem=None):
    """The decisions whose words could answer a question: the company's memory and your remembered answers, as
    {id, text, at, source}, those undone for this kind of question left out."""
    doc = doc if doc is not None else read_decisions(data)
    mem = memory_rows(data) if mem is None else mem
    rows = [{"id": r.get("id"), "text": one_line(r.get("text")), "at": r.get("at"), "source": "memory"} for r in mem]
    rows += [{"id": r["id"], "text": one_line(f"Asked '{r.get('question')}': {r.get('answer')}"), "at": r.get("at"), "source": "answer",
              "answer": r.get("answer")} for r in doc["decisions"] if r.get("project") in (None, project)]
    return [r for r in rows if r["text"] and not _excluded(doc, r["id"], question, project)]


def settle_one(data, kind, project, q, doc, mem, judge=None):
    """One question, settled: {"question", "answer", "from": {id, text, at, source}, "how"}, or None."""
    question = q.get("question") or ""
    labels = [o.get("label") for o in q.get("options") or [] if isinstance(o, dict) and o.get("label")]
    if kind == "choices" and not labels:
        return None
    multi = q.get("multiSelect") is True
    # the same question, on this floor, answered with Remember my answer ticked
    for r in reversed(doc["decisions"]):
        if r.get("project") not in (None, project) or norm(r.get("question")) != norm(question):
            continue
        if _excluded(doc, r["id"], question, project):
            break
        answer = str(r.get("answer") or "")
        if kind == "choices":
            same_options = sorted(norm(o) for o in r.get("options") or []) == sorted(norm(o) for o in labels)
            label = next((x for x in labels if norm(x) == norm(answer)), None)
            if label and not multi:
                answer = label
            elif not same_options:
                break  # the options have changed since: not clearly the same question
        if answer and not never(answer):
            return {"question": question, "answer": answer, "how": "same",
                    "from": {"id": r["id"], "text": one_line(f"Asked '{r.get('question')}': {r.get('answer')}"), "at": r.get("at"), "source": "answer"}}
        break
    found = candidates(data, question, project, doc, mem)
    words_of = " ".join([question, str(q.get("header") or "")] + labels)
    near = decided_for(words_of, found, most=3)
    if kind == "choices" and not multi:
        for r in near:  # a rule of yours, in the company's memory, that names one of its options
            if r.get("source") != "memory":
                continue  # an answer to another question is the lead's to judge, never a word match's
            label = chosen_option(r["text"], labels)
            if label and not never(r["text"], label):
                return {"question": question, "answer": label, "how": "rule", "from": r}
    if judge and near:
        got = judge(question, labels if kind == "choices" else [], near, project)
        if got:
            row, answer = got
            if not never(row["text"], answer):
                return {"question": question, "answer": answer, "how": "lead", "from": row}
    return None


def settle(data, kind, project, questions, judge=None):
    """Whether what an agent asks is already settled. `kind` is "choices" (the question tool: each question with its
    options) or "words" (a turn that ended with a question: [{"question"}]). Gives {"answers": [one for each question,
    in order], "how"} when every one of them is, else None."""
    if not project or not questions:
        return None
    if never_asked(questions):  # anything that touches secrets, money, deleting, pushing, publishing or sending: always you
        return None
    doc = read_decisions(data)
    if any(not a.get("show") and a.get("project") in (None, project) and same_kind(a.get("question"), q.get("question"))
           for a in doc["always_ask"] for q in questions):
        return None
    mem = memory_rows(data)
    answers = []
    for q in questions:
        got = settle_one(data, kind, project, q, doc, mem, judge)
        if not got:
            return None
        answers.append(got)
    return {"answers": answers, "how": answers[0]["how"]}


def said_from(row):
    """Where an answer came from, as the person reads it: 'your decision on 18 Nov: "..."'."""
    source = "your answer" if row.get("source") == "answer" else "your decision"
    return f'{source} on {day_of(row.get("at"))}: "{one_line(row.get("text"), 200)}"'


def to_agent(settled):
    """What the agent is told beside the answers: who answered, from which decision, and that Undo may follow."""
    parts = []
    for a in settled["answers"]:
        f = a["from"]
        parts.append(f'"{one_line(a["question"], 160)}": {one_line(a["answer"], 200)}, from their decision on {day_of(f.get("at"))}: '
                     f'"{one_line(f.get("text"), 200)}"')
    return ("Arnheim, the building, answered for the person you are working for, from what they decided before: " + "; ".join(parts)
            + ". Go on with that. If they change it, Arnheim tells you before your next step.")


def answer_with_note(a):
    """One answer as the question tool hands it back: the answer, then where it came from."""
    f = a["from"]
    return f'{a["answer"]} (answered by Arnheim from the person\'s decision on {day_of(f.get("at"))}: "{one_line(f.get("text"), 200)}")'


# ---------- the brain's judgement (with the brain switched on) ----------

JUDGE_SECONDS = 45


def brain_on(data):
    return switches.on("brain", data)


def run_claude(system, prompt, seconds=JUDGE_SECONDS):
    """One answer from Claude, through your own Claude Code: no tools, no settings (so none of your hooks), no MCP
    servers, nothing kept. ARNHEIM_CLAUDE names another command, ARNHEIM_BRAIN_MODEL another model."""
    command = shlex.split(os.environ.get("ARNHEIM_CLAUDE") or "claude")
    model = os.environ.get("ARNHEIM_BRAIN_MODEL") or "sonnet"
    args = command + ["-p", "--model", model, "--effort", "low", "--output-format", "text", "--system-prompt", system,
                      "--tools", "", "--setting-sources", "", "--strict-mcp-config", "--no-session-persistence"]
    env = dict(os.environ, ARNHEIM_REVIEWER="1")  # never a conversation of its own in the building
    done = subprocess.run(args, input=prompt, capture_output=True, text=True, timeout=seconds, env=env, cwd=tempfile.gettempdir())
    return done.stdout if done.returncode == 0 else ""


JUDGE = ("You are the lead of a floor in Arnheim, the building that shows a company's work. An agent on your floor asked the "
         "person you work for a question. You may answer it for them only from a decision they made before, and only if that "
         "decision clearly answers this very question. Reply with exactly two lines and nothing else:\n"
         "QUOTE: the decision's words, copied exactly\nANSWER: the answer\n"
         "When the question has options, the answer is one option's label, copied exactly. If no decision clearly answers it, "
         "or you are unsure, reply with just: NONE")


def brain_judge(question, labels, rows, project, run=None):
    """The lead's judgement, with the brain on: (the decision it quoted, the answer), or None. The quote must be one of
    `rows` word for word, and for a question with options the answer one of them."""
    listed = "\n".join(f"({i}) {r['text']} (decided on {day_of(r.get('at'))})" for i, r in enumerate(rows, 1))
    options = "\n".join(f"- {label}" for label in labels)
    prompt = (f"The question: {one_line(question)}\n" + (f"Its options:\n{options}\n" if labels else "It has no options.\n")
              + f"The person's decisions:\n{listed}\n")
    try:
        said = (run or run_claude)(JUDGE, prompt)
    except Exception:  # no Claude Code, too slow, or anything else: nothing is answered
        return None
    quote = answer = None
    for raw in str(said or "").splitlines():
        m = re.match(r"^\s*(QUOTE|ANSWER)\s*:\s*(.+?)\s*$", raw)
        if m and m.group(1) == "QUOTE":
            quote = m.group(2).strip().strip('"“”')
        elif m:
            answer = m.group(2).strip().strip('"“”')
    if not quote or not answer:
        return None
    row = next((r for r in rows if " ".join(r["text"].split()).lower() == " ".join(quote.split()).lower()), None)
    if row is None:
        return None
    if labels:
        answer = next((x for x in labels if norm(x) == norm(answer)), None)
        if not answer:
            return None
    return row, one_line(answer, TEXT)


# ---------- Answered for you: data/control/answered/ ----------

def answered_dir(data):
    return os.path.join(data, "control", "answered")


def log_answered(data, key, project, title, agent, kind, settled):
    aid = secrets.token_urlsafe(9)
    row = {"id": aid, "key": key, "project": project, "title": one_line(title, 120), "agent": agent, "kind": kind,
           "answers": [{"question": one_line(a["question"]), "answer": one_line(a["answer"], 500), "how": a["how"],
                        "from": {k: a["from"].get(k) for k in ("id", "text", "at", "source")}} for a in settled["answers"]],
           "at": round(time.time(), 2), "undone": False, "seen": False}
    _write(os.path.join(answered_dir(data), aid + ".json"), row)
    return aid


def answered_rows(data, now=None):
    """What the leads answered for you, newest first, two days back."""
    now = now or time.time()
    try:
        names = os.listdir(answered_dir(data))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(answered_dir(data), name)
        row = _read(path)
        if not row or now - float(row.get("at") or 0) > ANSWERED_KEPT:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        out.append(row)
    return sorted(out, key=lambda r: -float(r.get("at") or 0))


def answered_row(data, aid):
    if not isinstance(aid, str) or not FILE_ID.match(aid):
        return None
    return _read(os.path.join(answered_dir(data), aid + ".json"))


def answered_view(row, learn=None):
    """One answer as the page shows it, under Answered for you. `learn`: learning's question or set-aside, if any."""
    answers = row.get("answers") or []
    first = answers[0] if answers else {}
    return {"id": row.get("id"), "key": row.get("key"), "title": row.get("title"), "project": row.get("project"), "agent": row.get("agent"),
            "question": "; ".join(a.get("question") or "" for a in answers), "answer": "; ".join(a.get("answer") or "" for a in answers),
            "from": said_from(first.get("from") or {}), "from_id": (first.get("from") or {}).get("id"), "how": first.get("how"),
            "at": row.get("at"), "undone": bool(row.get("undone")), "seen": bool(row.get("seen")), "learn": learn}


UNDONE = "don't take that earlier decision as the answer"


def undo(data, aid, words=None):
    """Undo: the answer's decisions are not for that kind of question again. Gives (the row, the message for the agent).
    With the learn switch on, the second Undo of an answer from the same decision sets that decision aside for every
    question (set_aside), unless a password, token or key is in what it would learn from."""
    row = answered_row(data, aid)
    if not row:
        raise ValueError("That answer isn't kept any more.")
    if row.get("undone"):
        raise ValueError("That was undone already.")
    said = one_line(words, 1500) if str(words or "").strip() else UNDONE
    learn = learn_on(data)
    # whatever the switch: learning switched on later still never asks about it (no_learning)
    secret = has_secret(*_learn_texts(row, None if said == UNDONE else said))
    aside = None
    for a in row.get("answers") or []:
        f = a.get("from") or {}
        if f.get("id"):
            got = _undone(data, f, a.get("question"), row.get("project"), twice=learn and not secret and aside is None)
            aside = aside or got
    row.update(undone=True, undone_at=round(time.time(), 2), words=None if said == UNDONE else said, seen=True)
    if secret:
        row["no_learning"] = True  # never learned from: nothing is asked about it either
    if aside:
        row["set_aside"] = aside["id"]
    _write(os.path.join(answered_dir(data), aid + ".json"), row)
    asked = "; ".join(f'"{one_line(a.get("question"), 160)}"' for a in row.get("answers") or [])
    gave = "; ".join(f'"{one_line(a.get("answer"), 160)}"' for a in row.get("answers") or [])
    message = (f"The person changed this: {said}. It is about your question {asked}, which Arnheim, the building, answered for them "
               f"with {gave} from an earlier decision.")
    if said == UNDONE:
        message += " Ask them again if you still need to know, or carry on without it."
    return row, message


def _learn_texts(row, words=None):
    """What learning from an undone answer would keep or ask about: your words, and each question, answer and decision."""
    texts = [words if words is not None else row.get("words")]
    for a in row.get("answers") or []:
        texts += [a.get("question"), a.get("answer"), (a.get("from") or {}).get("text")]
    return texts


def _undone(data, frm, question, project, twice=False):
    """An undo's mark for one decision and this kind of question; and with `twice`, when an answer from the same
    decision was undone before, the decision set aside for every question. Gives the set-aside mark, or None."""
    row = {"id": new_id("n"), "decision": frm["id"], "question": one_line(question), "project": project, "at": round(time.time(), 1)}

    def change(doc):
        before = [n for n in doc["not_for"] if n.get("decision") == frm["id"] and not n.get("all")]
        aside = None
        if twice and before and not any(n.get("decision") == frm["id"] and n.get("all") for n in doc["not_for"]):
            aside = {"id": new_id("n"), "decision": frm["id"], "all": True, "question": "", "project": None,
                     "text": one_line(frm.get("text"), 300), "at": round(time.time(), 1)}
        doc["not_for"] = (doc["not_for"] + [row] + ([aside] if aside else []))[-DECISIONS_MOST:]
        return aside
    return _change_decisions(data, change)


def seen(data, ids):
    """Glanced at in a sitting: answered for you, or put aside for office hours."""
    done = 0
    for one in ids if isinstance(ids, list) else []:
        for path in (os.path.join(answered_dir(data), f"{one}.json"), os.path.join(parked_dir(data), f"{one}.json")):
            if isinstance(one, str) and FILE_ID.match(one) and os.path.isfile(path):
                row = _read(path)
                if row is not None and not row.get("seen"):
                    row["seen"] = True
                    _write(path, row)
                    done += 1
    return done


# ---------- learning from your corrections (switch "learn"; docs/connect.md, "The building learns from your corrections") ----------

LEARN_ASK = "Should the leads stop answering this kind of question for you?"
SHOW_ASK = "Should Show me ask you before calling this kind of change done?"
SET_ASIDE = ("That's the second time an answer from this decision was undone, so the leads have set it aside: they won't "
             "answer from it again.")
LEARN_KEPT = ANSWERED_KEPT  # a correction from the last two days is asked about, never an older one
_door = None
_secret_seen = {}


def learn_on(data):
    return switches.on("learn", data)


def has_secret(*texts):
    """Whether any of these words has a password, token or key in it: connect/intake.py's has_secret, the front door's own
    check for words the person typed, loaded when first wanted. A check that can't run counts as yes."""
    global _door
    said = [str(t or "") for t in texts if str(t or "").strip()]
    if not said:
        return False
    key = "\x00".join(said)
    if key in _secret_seen:
        return _secret_seen[key]
    try:
        if _door is None:
            try:
                from . import intake as found  # as connect.deputy, from serve.py
            except ImportError:
                try:
                    import intake as found  # beside this file
                except ImportError:
                    import importlib.util
                    spec = importlib.util.spec_from_file_location("arnheim_intake", os.path.join(HERE, "intake.py"))
                    found = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(found)
            _door = found
        got = any(_door.has_secret(t) for t in said)
    except Exception:
        return True
    if len(_secret_seen) > 500:
        _secret_seen.clear()
    _secret_seen[key] = got
    return got


def _declined(doc, project, question, decision=None, show=False):
    """You said No to learning from this before: about this decision, or (Show me) this kind of change on this floor."""
    for r in doc["declined"]:
        if show and r.get("show") and r.get("project") == project and same_change(r.get("question"), question):
            return True
        if not show and not r.get("show") and decision and r.get("decision") == decision:
            return True
    return False


def _kept_already(doc, project, question, show=False):
    alike = same_change if show else same_kind
    return any(bool(a.get("show")) == bool(show) and a.get("project") in (None, project) and alike(a.get("question"), question)
               for a in doc["always_ask"])


def learning(data, row, doc=None, now=None):
    """What Answered for you says about an answer you undid: {"ask": LEARN_ASK} once, while it may still be learned from;
    {"set_aside": id, "said": SET_ASIDE} when that Undo set its decision aside (until you put it back); else None."""
    if not isinstance(row, dict) or not row.get("undone"):
        return None
    doc = doc if doc is not None else read_decisions(data)
    if row.get("set_aside"):
        kept = any(n.get("id") == row["set_aside"] and n.get("all") for n in doc["not_for"])
        return {"set_aside": row["set_aside"], "said": SET_ASIDE} if kept else None
    now = now or time.time()
    if not learn_on(data) or row.get("learned") or row.get("no_learning") or now - float(row.get("undone_at") or 0) > LEARN_KEPT:
        return None
    if has_secret(*_learn_texts(row)):
        return None  # never from a secret, whenever it was undone
    first = (row.get("answers") or [{}])[0]
    if _declined(doc, row.get("project"), first.get("question"), decision=(first.get("from") or {}).get("id")):
        return None
    if _kept_already(doc, row.get("project"), first.get("question")):
        return None
    return {"ask": LEARN_ASK}


def learn_from_undo(data, aid, yes):
    """Your Yes or No to LEARN_ASK. Yes: that kind of question always comes to you, kept with the words it came from;
    No: nothing more, and never asked again about that decision. Gives the always_ask row for Yes, else None."""
    row = answered_row(data, aid)
    if not row or not row.get("undone"):
        raise ValueError("That answer isn't kept any more.")
    if not (learning(data, row) or {}).get("ask"):
        raise ValueError("There's nothing to ask about that one any more.")
    first = (row.get("answers") or [{}])[0]
    question, frm = first.get("question"), first.get("from") or {}
    kept = None
    if yes:
        words = f'You undid "{one_line(first.get("answer"), 120)}", answered from {said_from(frm)}, on {day_of(row.get("undone_at"))}'
        if row.get("words"):
            words += f': "{one_line(row["words"], 300)}"'
        kept = ask_always(data, row.get("project"), question, came_from=words)
    else:
        decline(data, row.get("project"), question, decision=frm.get("id"))
    row["learned"] = "yes" if yes else "no"
    _write(os.path.join(answered_dir(data), aid + ".json"), row)
    return kept


def decline(data, project, question, decision=None, show=False):
    """No to learning: never asked again about this decision, or (Show me) this kind of change on this floor. Never keeps
    a question with a password, token or key in it: gives None and keeps nothing."""
    if has_secret(question):
        return None
    row = {"id": new_id("q"), "project": project, "question": one_line(question), "at": round(time.time(), 1)}
    if decision:
        row["decision"] = decision
    if show:
        row["show"] = True

    def change(doc):
        doc["declined"] = (doc["declined"] + [row])[-DECISIONS_MOST:]
        return row
    return _change_decisions(data, change)


def put_back(data, aid):
    """Undo of a set-aside: the decision is answered from again (its marks for the kinds of question undone stay)."""
    row = answered_row(data, aid)
    aside = (row or {}).get("set_aside")
    if not aside or not forget(data, aside):
        raise ValueError("That decision isn't set aside any more.")
    return row


def show_learning(data, show, doc=None, now=None):
    """What a Show me card you said Not quite to asks: {"ask": SHOW_ASK} once, while it may be learned from, else None."""
    if not isinstance(show, dict) or show.get("state") != "again" or not learn_on(data):
        return None
    now = now or time.time()
    title, project = show.get("title"), show.get("project")
    if not title or not project or now - float(show.get("decided_at") or 0) > LEARN_KEPT:
        return None
    doc = doc if doc is not None else read_decisions(data)
    if _declined(doc, project, title, show=True) or _kept_already(doc, project, title, show=True):
        return None
    if has_secret(title, show.get("words")):
        return None
    return {"ask": SHOW_ASK}


def learn_from_show(data, show, yes):
    """Your Yes or No to SHOW_ASK, for a card you said Not quite to. Yes: Show me asks you about that kind of change on
    that floor before it is counted done (looks_first), kept with your words; No: never asked again about it."""
    if not (show_learning(data, show) or {}).get("ask"):
        raise ValueError("There's nothing to ask about that one any more.")
    title, project = show.get("title"), show.get("project")
    if not yes:
        decline(data, project, title, show=True)
        return None
    words = f'You said Not quite to "{one_line(title, 120)}" on {day_of(show.get("decided_at"))}'
    if show.get("words"):
        words += f': "{one_line(show["words"], 300)}"'
    return ask_always(data, project, title, came_from=words, show=True)


def looks_first(data, project, title, doc=None):
    """The kind of change on this floor that Show me asks you about before it is counted done, matching this work's
    title: its always_ask row, or None."""
    if not project or not str(title or "").strip():
        return None
    doc = doc if doc is not None else read_decisions(data)
    return next((a for a in reversed(doc["always_ask"]) if a.get("show") and a.get("project") in (None, project)
                 and same_change(a.get("question"), title)), None)


# ---------- office hours ----------

DEFAULT_TIMES = ("13:00", "18:00")
TIMES_MOST = 4
WINDOW = 30 * 60  # each office hour is open this long, and a sitting opened now too
CLOCK = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
AWAY = ("The person is away until {until} (office hours). If one option is clearly safe and easy to change later, take it and say "
        "which you took; otherwise put this aside, carry on with work that doesn't depend on it, and if there is none, finish your "
        "turn saying what you need.")


def clean_times(given):
    """Up to four times a day, as "HH:MM", in order. ValueError for anything else."""
    if not isinstance(given, list) or not 0 < len(given) <= TIMES_MOST:
        raise ValueError(f"Choose from one to {TIMES_MOST} times a day, such as 13:00.")
    out = []
    for t in given:
        m = CLOCK.match(str(t or "").strip())
        if not m:
            raise ValueError(f'"{one_line(t, 20)}" isn\'t a time of day. Write it as 13:00.')
        out.append(f"{int(m.group(1)):02d}:{m.group(2)}")
    return sorted(set(out))


def office_times(data):
    try:
        return clean_times(switches.saved(data).get("office_times"))
    except ValueError:
        return list(DEFAULT_TIMES)


def save_times(data, times):
    """Keeps the times beside the switches, in data/serve.json, leaving the rest as it was."""
    times = clean_times(times)
    with switches._Locked(data):
        kept = {**switches.saved(data), "office_times": times}
        path = switches.path(data)
        part = f"{path}.{os.getpid()}.part"
        with open(part, "w", encoding="utf-8") as handle:
            json.dump(kept, handle, indent=1)
            handle.write("\n")
        os.replace(part, path)
    return times


def office_path(data):
    return os.path.join(data, "control", "office.json")


def open_until(data):
    at = (_read(office_path(data)) or {}).get("open_until")
    return float(at) if isinstance(at, (int, float)) else 0.0


def open_sitting(data, now=None):
    now = now or time.time()
    _write(office_path(data), {**(_read(office_path(data)) or {}), "open_until": now + WINDOW, "opened_at": now})
    return now + WINDOW


def close_sitting(data, now=None):
    _write(office_path(data), {**(_read(office_path(data)) or {}), "open_until": 0, "closed_at": now or time.time()})


def _starts(data, now):
    """Each office hour's start, yesterday, today and tomorrow, as epochs."""
    base = datetime.datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    for days in (-1, 0, 1):
        for t in office_times(data):
            h, m = (int(x) for x in t.split(":"))
            out.append((base + datetime.timedelta(days=days, hours=h, minutes=m)).timestamp())
    return sorted(out)


def office_open(data, now=None):
    """Within an office hour's half hour, or a sitting opened from the page."""
    now = now or time.time()
    return open_until(data) > now or any(s <= now < s + WINDOW for s in _starts(data, now))


def next_office(data, now=None):
    now = now or time.time()
    return next((s for s in _starts(data, now) if s > now), None)


def until_words(data, now=None):
    """The next office hour, as the agent is told it: "13:00", or "13:00 tomorrow"."""
    now = now or time.time()
    at = next_office(data, now)
    if at is None:
        return "the next office hour"
    when = datetime.datetime.fromtimestamp(at)
    words_ = when.strftime("%H:%M")
    return words_ if when.date() == datetime.datetime.fromtimestamp(now).date() else f"{words_} tomorrow"


def away(data, watched, now=None):
    """Whether what an agent asks waits for office hours: the switch on, nobody using the building, and no office hour
    or sitting open."""
    return switches.on("office_hours", data) and not watched and not office_open(data, now)


def away_words(data, now=None):
    return AWAY.format(until=until_words(data, now))


# ---------- what waited for office hours: data/control/parked/ ----------

def parked_dir(data):
    return os.path.join(data, "control", "parked")


def park(data, kind, key, project, title, agent, text, questions=None, tool=None, what=None, urgent=None):
    """Keeps what an agent asked while you were away, for the sitting: a question it was told to put aside, or a
    permission it asked for in its own window."""
    pid = secrets.token_urlsafe(9)
    row = {"id": pid, "kind": kind, "key": key, "project": project, "title": one_line(title, 120), "agent": agent, "text": one_line(text),
           "questions": questions or [], "tool": tool, "what": one_line(what), "urgent": urgent, "at": round(time.time(), 2),
           "state": "parked", "seen": False}
    _write(os.path.join(parked_dir(data), pid + ".json"), row)
    return pid


def parked_rows(data, now=None):
    now = now or time.time()
    try:
        names = os.listdir(parked_dir(data))
    except OSError:
        return []
    out = []
    for name in names:
        if not name.endswith(".json"):
            continue
        path = os.path.join(parked_dir(data), name)
        row = _read(path)
        if not row or now - float(row.get("at") or 0) > PARKED_KEPT:
            try:
                os.remove(path)
            except OSError:
                pass
            continue
        out.append(row)
    return sorted(out, key=lambda r: float(r.get("at") or 0))


def parked_row(data, pid):
    if not isinstance(pid, str) or not FILE_ID.match(pid):
        return None
    return _read(os.path.join(parked_dir(data), pid + ".json"))


def change_parked(data, pid, **fields):
    row = parked_row(data, pid)
    if row:
        row.update(fields)
        _write(os.path.join(parked_dir(data), pid + ".json"), row)
    return row


def parked_view(row):
    return {k: row.get(k) for k in ("id", "kind", "key", "project", "title", "agent", "text", "questions", "tool", "what", "urgent", "at", "state")}


def moved_on(data, key):
    """The agent went on: a permission it asked for in its own window while you were away was answered there."""
    if not os.path.isdir(parked_dir(data)):
        return
    for row in parked_rows(data):
        if row.get("key") == key and row.get("kind") == "permission" and row.get("state") == "parked":
            change_parked(data, row["id"], state="moved on")


def asked_before(data, key, question, hours=12, rows=None):
    """Whether this conversation asked the same kind of thing earlier and was told to put it aside."""
    now = time.time()
    rows = parked_rows(data) if rows is None else rows
    return any(r.get("key") == key and r.get("kind") == "question" and now - float(r.get("at") or 0) < hours * 3600
               and same_kind(r.get("text"), question) for r in rows)


# Urgent: what reaches you at once even outside office hours.
PRIVATE = re.compile(r"(?:^|[\\/\s~])(?:[^\\/\s]*\.env\w*|\.ssh|\.aws|\.gnupg|\.netrc|\.npmrc|\.pypirc|\.pgpass|\.docker|\.kube|\.git-credentials|"
                     r"\.config[\\/]gh|keychains?|id_(?:rsa|dsa|ecdsa|ed25519)|[^\\/\s]*\.(?:pem|key|p8|p12|pfx|keystore|jks|ppk|gpg|asc|kdbx|ovpn)\b|"
                     r"login data|cookies(?![\w.-])|[^\\/\s]*(?:credential|secret|password|passwd|token|api[_-]?key|service[_-]?account)|"
                     r"[^\\/\s]*_history\b)", re.I)  # src/queue.js's SECRET
PUSHY = re.compile(r"\b(?:git\s+push|npm\s+publish|yarn\s+publish|pnpm\s+publish|twine\s+upload|gh\s+release|deploy\w*|"
                   r"rm\s+-\w*[rf]|sudo|curl\b[^|]*\|\s*(?:ba|z)?sh)\b", re.I)


def high_risk(tool, what, command=None, risky=None):
    """Why a permission request is urgent, or None: it reaches something that may be private, or deletes or overwrites
    files in bulk, pushes, publishes or deploys."""
    what = str(what or "")
    if tool not in ("WebFetch", "WebSearch") and PRIVATE.search(what):
        return "It reaches something that may be private."
    if tool == "Bash" and (PUSHY.search(str(command or what)) or (risky and risky(command or what))):
        return "It could delete, overwrite or send things."
    return None


def near_limit(data, agent, now=None, at=90.0):
    """Whether the agent's plan is nearly at its limit, as its last reading says (connect/usage.py's feeds/usage.json)."""
    now = now or time.time()
    doc = _read(os.path.join(data, "feeds", "usage.json")) or {}
    mine = (doc.get("sources") or {}).get(agent) if isinstance(doc.get("sources"), dict) else None
    for rows in (mine.values() if isinstance(mine, dict) else []):
        last = rows[-1] if isinstance(rows, list) and rows and isinstance(rows[-1], dict) else None
        try:
            used = float(last.get("used")) if last else 0.0
            resets = float(last.get("resets_at") or 0) if last else 0.0
            fresh = now - float(last.get("at") or 0) < 3600 if last else False
        except (TypeError, ValueError):
            continue
        if fresh and used >= at and (not resets or resets > now):
            return True
    return False


def office_view(data, now=None):
    """Office hours as the page gets them: {on, times, open, next, until, parked}."""
    now = now or time.time()
    rows = parked_rows(data, now) if os.path.isdir(parked_dir(data)) else []
    return {"on": switches.on("office_hours", data), "times": office_times(data), "open": office_open(data, now),
            "open_until": open_until(data) if open_until(data) > now else None, "next": next_office(data, now),
            "until": until_words(data, now), "parked": sum(1 for r in rows if not r.get("seen"))}
