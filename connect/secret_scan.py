#!/usr/bin/env python3
"""The secrets check: passwords and tokens saved in your agents' settings, in each floor's folder.

  python3 connect/secret_scan.py          check every floor's folder now, and keep what it found for the page
  python3 connect/secret_scan.py --show   the same, and say here what it found (never the secrets themselves)

Claude Code's "Yes, and don't ask again" saves the command you allowed as a rule, word for word, so a command that
named a token or a password keeps it there; settings and MCP servers can hold keys too. For every floor in
data/company.json this reads the files agents keep their settings in, in the floor's folder and at the top of its
repository (where Claude Code now keeps its local file): .claude/settings.json, .claude/settings.local.json,
.mcp.json, .codex/config.toml and .codex/rules/*.rules. It finds what looks like a secret, and asks git how far
each has gone: pushed, committed, about to be committed, or kept out by git.

It never shows or keeps a secret, only its kind, the file and line, and a hint such as ghp_...1a2b. What it found goes
in data/.secrets/found.json, which serve.py never serves (a hidden folder); the page on this computer asks serve.py
for it (/secrets/). Take it out and Keep git out of it change one file each, keep a copy of it first in
data/.secrets/undo/ (for a week, readable by you alone) and can be undone byte for byte (docs/connect.md).
Standard library only, and git, run with fixed words and never through a shell.
"""
import argparse
import base64
import hashlib
import hmac
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
from json.decoder import scanstring

HERE = os.path.dirname(os.path.realpath(__file__))
DATA = os.environ.get("ARNHEIM_DATA") or os.path.join(os.path.dirname(HERE), "data")
KEEP_DAYS = 7  # how long a copy kept for Undo stays: it holds the secret, so not for ever
MOST_BYTES = 1 << 20  # settings files are small; anything bigger is left alone
MOST_COMMITS = 300  # how far back a file's history is read for the secret

# The files agents keep settings in, from a project's folder (Claude Code's and Codex's own docs).
FILES = ((".claude/settings.local.json", "json"), (".claude/settings.json", "json"), (".mcp.json", "json"),
         (".codex/config.toml", "toml"))
RULES = ".codex/rules"  # Codex's command rules, *.rules

# ---------- what a secret looks like ----------

# (kind, pattern whose first group is the part safe to show, what it is in words). Known formats, first.
FORMATS = tuple((kind, re.compile(pattern), words) for kind, pattern, words in (
    ("anthropic", r"\b(sk-ant-(?:[a-z]+\d*-)?)[A-Za-z0-9_\-]{20,}", "An Anthropic API key"),
    ("openai", r"\b(sk-(?!ant-)(?:proj-|svcacct-|admin-)?)[A-Za-z0-9_\-]{32,}", "An OpenAI API key"),
    ("github", r"\b(gh[pousr]_)[A-Za-z0-9]{36,251}\b", "A GitHub token"),
    ("github", r"\b(github_pat_)[A-Za-z0-9_]{50,}", "A GitHub token"),
    ("gitlab", r"\b(gl(?:pat|dt|rt|ptt|cbt|ft|imt|oas|soat)-)[A-Za-z0-9_\-]{20,}", "A GitLab token"),
    ("slack", r"\b(xox[abposre]-)[A-Za-z0-9\-]{10,}", "A Slack token"),
    ("slack", r"\b(xapp-)[0-9]-[A-Za-z0-9\-]{10,}", "A Slack token"),
    ("slack", r"(https://hooks\.slack\.com/)(?:services|workflows|triggers)/[A-Za-z0-9_/]{20,}", "A Slack webhook address"),
    ("aws", r"\b(A(?:KIA|SIA|BIA|CCA))[A-Z0-9]{16}\b", "An AWS access key"),
    ("google", r"\b(AIza)[A-Za-z0-9_\-]{35}(?![A-Za-z0-9_\-])", "A Google API key"),
    ("google", r"\b(GOCSPX-)[A-Za-z0-9_\-]{20,}", "A Google OAuth client secret"),
    ("google", r"\b(ya29\.)[A-Za-z0-9_\-]{30,}", "A Google access token"),
    ("stripe", r"\b((?:sk|rk)_(?:live|test)_)[A-Za-z0-9]{16,}", "A Stripe key"),
    ("stripe", r"\b(whsec_)[A-Za-z0-9+/=]{24,}", "A Stripe webhook secret"),
    ("huggingface", r"\b(hf_)[A-Za-z0-9]{30,}\b", "A Hugging Face token"),
    ("npm", r"\b(npm_)[A-Za-z0-9]{36}\b", "An npm token"),
    ("pypi", r"\b(pypi-)AgE[A-Za-z0-9_\-]{50,}", "A PyPI token"),
    ("sendgrid", r"\b(SG\.)[A-Za-z0-9_\-]{16,}\.[A-Za-z0-9_\-]{16,}", "A SendGrid key"),
    ("digitalocean", r"\b(do[opr]_v1_)[a-f0-9]{64}\b", "A DigitalOcean token"),
    ("groq", r"\b(gsk_)[A-Za-z0-9]{40,}\b", "A Groq API key"),
    ("xai", r"\b(xai-)[A-Za-z0-9]{60,}\b", "An xAI API key"),
    ("linear", r"\b(lin_api_)[A-Za-z0-9]{32,}\b", "A Linear API key"),
    ("notion", r"\b(ntn_)[A-Za-z0-9]{40,}\b", "A Notion token"),
    ("telegram", r"\b()[0-9]{8,10}:AA[A-Za-z0-9_\-]{33}\b", "A Telegram bot token"),
    ("jwt", r"\b(eyJ)[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}", "A signed login token (JWT)"),
))
PRIVATE_KEY = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY(?: BLOCK)?-----.*?(?:-----END [A-Z ]*PRIVATE KEY(?: BLOCK)?-----|$)", re.S)
BEARER = re.compile(r"\b[Bb]earer\s+([A-Za-z0-9._~+/\-]{20,}=*)")
BASIC = re.compile(r"\b[Bb]asic\s+([A-Za-z0-9+/]{8,}={0,2})(?![A-Za-z0-9+/=])")
URL_LOGIN = re.compile(r"\b[A-Za-z][A-Za-z0-9+.\-]{1,20}://([^\s:/?#@'\"`]+):([^\s/?#@'\"`]+)@")
CURL_USER = re.compile(r"(?:^|[\s'\"(])(?:-u|--user|--proxy-user)(?:\s+|=)['\"]?([^\s:'\"$]+):([^\s'\")]+)")
SECRET_FLAG = r"--?(?:password|passwd|token|api[-_]?key|apikey|access[-_]?token|auth[-_]?token|secret|client[-_]?secret|bearer)"
FLAG = re.compile(r"(?:^|[\s'\"(\[,])(" + SECRET_FLAG + r")(?:=|\s+)['\"]?([^\s'\"),\]]+)", re.I)
FLAG_ALONE = re.compile(SECRET_FLAG, re.I)
ASSIGNED = re.compile(r"(?:^|[\s;&|('\"`])(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|([^\s'\";&|)`]+))")
LONG = re.compile(r"(?<![A-Za-z0-9+/=_\-.])[A-Za-z0-9+/=_\-.]{32,}(?![A-Za-z0-9+/=_\-.])")

# Not secrets: references to one kept elsewhere ($TOKEN, ${TOKEN}, a password manager's address), and placeholders.
REFERENCE = re.compile(r"^\$|\$\{|\$\(|^%[A-Za-z_]+%$|\{\{|^<.*>$|^(?:op|vault|env|keychain|keyring|secretsmanager|ssm|file)://?"
                       r"|^arn:aws:(?:secretsmanager|ssm)", re.I)
PLACEHOLDER = re.compile(r"^(?:x+|\*+|\.+|-+|_+|0+|#+)$|^your[\s_\-]|example|placeholder|redacted|changeme|change[_\-]me"
                         r"|replace[_\-]?me|^(?:password|passwd|secret|token|apikey|api[_\-]key|none|null|nil|true|false|test"
                         r"|dummy|todo|tbd|empty|undefined|default|sample)$|\.\.\.|\u2026", re.I)
SECRET_WORDS = {"password": "A password", "passwd": "A password", "pwd": "A password", "pass": "A password",
                "passphrase": "A password", "secret": "A secret", "token": "A token", "apikey": "A key", "pat": "A token",
                "credential": "A credential", "credentials": "A credential"}
KEY_KINDS = {"api", "access", "secret", "private", "auth", "signing", "encryption", "master", "license", "account",
             "service", "admin", "subscription"}


class Hit:
    """One secret in one piece of text: what kind, its value, where in the text, and the part safe to show."""

    def __init__(self, kind, words, value, start, end, show="", password=False, pair=False):
        self.kind, self.words, self.value, self.start, self.end = kind, words, value, start, end
        self.show, self.password, self.pair = show, password, pair


def kinds_of(text):
    """How many of upper case, lower case and digits a value mixes: real keys mix them, words and names seldom do."""
    return sum(bool(re.search(p, text)) for p in (r"[a-z]", r"[A-Z]", r"[0-9]"))


def entropy(text):
    """Bits per character: about 4.5 for a random key of this length, under 4 for words and names."""
    counts = {}
    for c in text:
        counts[c] = counts.get(c, 0) + 1
    return -sum(n / len(text) * math.log2(n / len(text)) for n in counts.values()) if text else 0.0


def literal(value, least=6):
    """Whether a value is written out, as a secret would be, rather than a reference to one or a placeholder."""
    v = value.strip()
    if len(v) < least or "*" in v or "\n" in v or REFERENCE.search(v) or PLACEHOLDER.search(v):
        return False
    return not (v.startswith(("/", "~", "./", "../")) or re.match(r"^[A-Za-z]:\\", v))


def secret_name(name):
    """What a name such as GITHUB_TOKEN, db_password or apiKey says its value is, or None for any other name.
    Only the last word counts, so MAX_TOKENS, TOKEN_FILE and env_key name no secret."""
    parts = [p.lower() for p in re.split(r"[_\-.\s]+|(?<=[a-z0-9])(?=[A-Z])", name) if p]
    if not parts or {"public", "publishable", "pub", "anon"} & set(parts):
        return None
    if parts[-1] in SECRET_WORDS:
        return SECRET_WORDS[parts[-1]]
    if parts[-1] == "key" and len(parts) > 1 and parts[-2] in KEY_KINDS:
        return "A key"
    return None


def looks_random(text):
    """A long string with the mix and spread of a generated key, not a path, a hash, a name or words."""
    if len(text) < 32 or text.count("/") > 1 or text.count(".") > 2 or re.match(r"sha\d+-", text):
        return False
    if re.fullmatch(r"[0-9a-fA-F\-]+", text):  # commit ids, hashes and UUIDs are everywhere in commands
        return False
    if re.search(r"\.[A-Za-z]{1,5}$", text):  # a file's name
        return False
    parts = [p for p in re.split(r"[_\-./]", text) if p]
    if len(parts) >= 3 and sum(p.isalpha() for p in parts) * 3 >= len(parts) * 2:  # words joined up, as names are
        return False
    # Most of a name such as getUserAccountSettings2 is words; a generated key seldom has more than a few letters
    # in a row that read as one (measured: names 72% and up, keys well under 60%).
    if sum(len(w) for w in re.findall(r"[A-Z]?[a-z]{3,}", text)) >= 0.6 * len(text):
        return False
    return kinds_of(text) == 3 and entropy(text) >= (4.3 if len(text) < 48 else 4.1)


def named_hit(name, value):
    """A value given to a name that says it is secret (DB_PASSWORD, api_key): a Hit on the whole value, or None."""
    words = secret_name(name or "")
    if not words:
        return None
    password = words == "A password"
    if re.fullmatch(r"[A-Z][A-Z0-9_]{2,}", value):  # the name of a variable that holds it, as Codex's env_http_headers takes
        return None
    if not literal(value, 6 if password else 12) or (not password and kinds_of(value) < 2 and entropy(value) < 3.5):
        return None
    return Hit("named", words, value, 0, len(value), password=password)


def pair_hit(flag, value):
    """An argument after a flag that says it is secret (--token, then the token): a Hit on the value, or None."""
    if not FLAG_ALONE.fullmatch(flag.strip()):
        return None
    password = "pass" in flag.lower()
    if not literal(value, 6 if password else 12) or (not password and kinds_of(value) < 2):
        return None
    return Hit("flag", "A password" if password else "A token", value, 0, len(value), password=password, pair=True)


def text_hits(text):
    """The secrets in one piece of text (a rule, a command, a value), known formats first, then the rest."""
    hits = []

    def add(hit):
        if hit.value and not any(hit.start < h.end and h.start < hit.end for h in hits):
            hits.append(hit)

    for m in PRIVATE_KEY.finditer(text):
        add(Hit("private-key", "A private key", m.group(0), m.start(), m.end()))
    for kind, pattern, words in FORMATS:
        for m in pattern.finditer(text):
            body = m.group(0)[len(m.group(1)):]
            if kind == "openai" and kinds_of(body) < 3:  # sk- then words, such as sk-learn-model-..., is no key
                continue
            add(Hit(kind, words, m.group(0), m.start(), m.end(), show=m.group(1)))
    for m in BEARER.finditer(text):
        if kinds_of(m.group(1)) >= 2:
            add(Hit("bearer", "A bearer token", m.group(1), m.start(1), m.end(1)))
    for m in BASIC.finditer(text):
        try:
            login = base64.b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4), validate=True)
        except (ValueError, TypeError):
            continue
        if b":" in login and all(32 <= b < 127 for b in login):  # user:password, as a login header carries it
            add(Hit("basic", "A password in a login header", m.group(1), m.start(1), m.end(1), password=True))
    for pattern in (URL_LOGIN, CURL_USER):
        for m in pattern.finditer(text):
            if literal(m.group(2), 4):
                add(Hit("login", "A password in an address" if pattern is URL_LOGIN else "A password",
                        m.group(2), m.start(2), m.end(2), password=True))
    for m in FLAG.finditer(text):
        hit = pair_hit(m.group(1), m.group(2))
        if hit:
            add(Hit(hit.kind, hit.words, m.group(2), m.start(2), m.end(2), password=hit.password))
    for m in ASSIGNED.finditer(text):
        group = 2 if m.group(2) is not None else 3 if m.group(3) is not None else 4
        hit = named_hit(m.group(1), m.group(group))
        if hit:
            add(Hit(hit.kind, hit.words, m.group(group), m.start(group), m.end(group), password=hit.password))
    for m in LONG.finditer(text):
        if looks_random(m.group(0)):
            add(Hit("random", "Something that looks like a key", m.group(0), m.start(), m.end()))
    return sorted(hits, key=lambda h: h.start)


def hint(hit):
    """What the page may show of a secret: its kind's own start and its last four characters, or only its length
    for a password and anything short, so the secret itself can't be read from it."""
    if hit.kind == "private-key":
        return "a key block"
    if hit.password or len(hit.value) < 20:
        return "{} characters".format(len(hit.value))
    return "{}\u2026{}".format(hit.show, hit.value[-4:])


# ---------- reading the files, remembering where each value is ----------

_WS = re.compile(r"[ \t\n\r]*")
_OTHER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][-+]?\d+)?|true|false|null")


def parse_json(text):
    """A JSON text as nested nodes that remember where each value, and each object's member, starts and ends, so
    one rule can be taken out and every other byte left as it was."""
    node, end = _value(text, _WS.match(text, 0).end(), 0)
    if _WS.match(text, end).end() != len(text):
        raise ValueError("more after the end")
    return node


def _value(text, at, depth):
    if depth > 64 or at >= len(text):
        raise ValueError("too deep, or cut short")
    c = text[at]
    if c == '"':
        value, end = scanstring(text, at + 1)
        return {"t": "str", "s": at, "e": end, "v": value}, end
    if c in "{[":
        obj, close, items = c == "{", "}" if c == "{" else "]", []
        p = _WS.match(text, at + 1).end()
        if text.startswith(close, p):
            return {"t": "obj" if obj else "arr", "s": at, "e": p + 1, "items": items}, p + 1
        while True:
            start = p
            if obj:
                if not text.startswith('"', p):
                    raise ValueError("a name was expected")
                key, p = scanstring(text, p + 1)
                p = _WS.match(text, p).end()
                if not text.startswith(":", p):
                    raise ValueError("a colon was expected")
                p = _WS.match(text, p + 1).end()
            node, p = _value(text, p, depth + 1)
            items.append({"key": key, "s": start, "e": node["e"], "node": node} if obj else {"s": start, "e": node["e"], "node": node})
            p = _WS.match(text, p).end()
            if text.startswith(",", p):
                p = _WS.match(text, p + 1).end()
                continue
            if text.startswith(close, p):
                return {"t": "obj" if obj else "arr", "s": at, "e": p + 1, "items": items}, p + 1
            raise ValueError("a comma was expected")
    m = _OTHER.match(text, at)
    if not m:
        raise ValueError("not JSON")
    return {"t": "other", "s": at, "e": m.end()}, m.end()


def json_strings(node, path=()):
    """Every string value, as (path, node, its container, its place in it)."""
    for i, item in enumerate(node.get("items") or []):
        child = item["node"]
        where = path + ((item["key"],) if node["t"] == "obj" else (i,))
        if child["t"] == "str":
            yield where, child, node, i
        else:
            yield from json_strings(child, where)


def _vague(hits):
    """No hits, or only a long random string with nothing to say what it is."""
    return all(h.kind == "random" and h.start == 0 for h in hits)


def json_hits(text):
    """(hit, line, path) for each secret in a JSON settings file."""
    out = []
    for path, node, box, i in json_strings(parse_json(text)):
        hits = text_hits(node["v"])
        if _vague(hits):  # what its name, or the flag before it, says it is tells more than "looks like a key"
            hit = None
            if box["t"] == "obj":
                hit = named_hit(box["items"][i]["key"], node["v"])
            elif i > 0 and box["items"][i - 1]["node"]["t"] == "str":
                hit = pair_hit(box["items"][i - 1]["node"]["v"], node["v"])
            hits = [hit] if hit else hits
        line = text.count("\n", 0, node["s"]) + 1
        out.extend((hit, line, path) for hit in hits)
    return out


STRING = re.compile(r'"(?:[^"\\\n]|\\.)*"|\'[^\'\n]*\'')


def line_strings(line):
    """The quoted strings on one line of TOML or Codex's rules: (start, end, value), with escapes read."""
    for m in STRING.finditer(line):
        raw = m.group(0)
        value = raw[1:-1]
        if raw.startswith('"'):
            try:
                value = json.loads(raw)
            except ValueError:
                pass
        yield m.start(), m.end(), value


def lines_hits(text):
    """(hit, line, path) for each secret in .codex/config.toml or a .rules file, a line at a time: each quoted value,
    a name = "value" pair, a flag followed by its value, and anything secret in a comment."""
    out = []
    for n, line in enumerate(text.split("\n"), 1):
        found = list(line_strings(line))
        last_end = 0
        for k, (start, end, value) in enumerate(found):
            hits = text_hits(value)
            if _vague(hits):
                between = line[last_end:start]
                if k > 0 and re.fullmatch(r"\s*=\s*", between):  # "X-Api-Key" = "...", in an inline table
                    name = found[k - 1][2]
                else:
                    named = re.search(r"([A-Za-z0-9_\-]+)\s*=\s*$", between)
                    name = named.group(1) if named else None
                hit = named_hit(name, value) if name else None
                if not hit and k > 0 and re.fullmatch(r"\s*,\s*", line[found[k - 1][1]:start]):
                    hit = pair_hit(found[k - 1][2], value)
                hits = [hit] if hit else hits
            out.extend((hit, n, ()) for hit in hits)
            last_end = end
        comment = line.find("#", last_end)
        if comment >= 0:
            out.extend((hit, n, ()) for hit in text_hits(line[comment:]) if hit.kind not in ("named", "random"))
    return out


def file_hits(text, kind):
    return json_hits(text) if kind == "json" else lines_hits(text)


# ---------- taking a secret out of a file, and nothing else ----------

class Refused(Exception):
    """Something that can't be done safely, in words for the person who asked."""


def _cut(text, box, i, j):
    """The text without items i to j of a JSON object or list, with the commas and spaces between them, so the rest
    keeps its exact bytes."""
    items = box["items"]
    if i == 0 and j == len(items) - 1:
        return text[:box["s"] + 1] + text[box["e"] - 1:]
    if j < len(items) - 1:
        return text[:items[i]["s"]] + text[items[j + 1]["s"]:]
    return text[:items[i - 1]["e"]] + text[items[j]["e"]:]


def _takes_value(flag, value):
    """Whether one argument is a flag whose value is the next (--token, then the token), so both go together."""
    return flag.startswith("-") and "=" not in flag and not re.search(r"\s", flag) and not value.startswith("-")


LISTS = {"allow", "deny", "ask", "args"}  # lists of rules or words: one can go and the rest still make sense
MAPS = {"env", "headers", "environment", "http_headers", "env_http_headers"}  # names and values: one can go


def cuttable(where, box):
    """Whether the string at where can go on its own: an item of a list of rules or words, or a member of an env or
    headers map. A hook's command or a server's address can't: what was left would be broken."""
    owner = str(where[-2]) if len(where) >= 2 else ""
    return owner in (LISTS if box["t"] == "arr" else MAPS)


def json_without(text, value):
    """The JSON text without each rule or entry that holds the value: a list's item (with the flag before it, for an
    argument such as --token), or an object's member. Raises Refused when it can't."""
    for _ in range(200):
        root = parse_json(text)
        target = next(((where, node, box, i) for where, node, box, i in json_strings(root) if value in node["v"]), None)
        if target is None:
            return text
        where, node, box, i = target
        if not cuttable(where, box):
            raise Refused("taking it out would leave a hook or a server broken")
        first = i
        if box["t"] == "arr" and i > 0:
            before = box["items"][i - 1]["node"]
            if before["t"] == "str" and _takes_value(before["v"], node["v"]):
                first = i - 1
        text = _cut(text, box, first, i)
    raise Refused("it is in that file too many times")


def _balanced(text):
    """Whether brackets and quotes close as they open, line by line for quotes: enough to tell a cut went cleanly."""
    depth = 0
    for line in text.split("\n"):
        bare = STRING.sub('""', line).split("#", 1)[0]
        if bare.count('"') % 2 or bare.count("'") % 2:
            return False
        depth += bare.count("(") + bare.count("[") + bare.count("{") - bare.count(")") - bare.count("]") - bare.count("}")
        if depth < 0:
            return False
    return depth == 0


def toml_without(text, value):
    """.codex/config.toml without each line that holds the value: a name = "value" line, or a line that is one item of
    a list. Raises Refused for anything else, such as a value in the middle of a longer line."""
    lines = text.split("\n")
    kept, table = [], ""
    for line in lines:
        head = re.match(r"^\s*\[+\s*([^\]]+?)\s*\]+\s*(?:#.*)?$", line)
        if head:
            table = head.group(1)
        if value not in line:
            kept.append(line)
            continue
        bare = line.strip()
        name = re.match(r"^([A-Za-z0-9_\-.\"']+)\s*=", bare)
        whole = name and _balanced(line) and (table.split(".")[-1].strip('"\'') in MAPS
                                              or re.search(r"token|key|secret|password", name.group(1), re.I))
        if not whole:
            raise Refused("it sits in a setting that would be left broken, such as a server's command or its words")
        kept.append(None)
    out = "\n".join(line for line in kept if line is not None)
    if not _balanced(out):
        raise Refused("taking it out would leave the file broken")
    return out


def rules_without(text, value):
    """A Codex .rules file without each statement (a prefix_rule(...), say) that holds the value, whole lines only."""
    lines = text.split("\n")
    statements, start, depth = [], 0, 0
    for n, line in enumerate(lines):
        bare = STRING.sub('""', line).split("#", 1)[0]
        depth += bare.count("(") + bare.count("[") + bare.count("{") - bare.count(")") - bare.count("]") - bare.count("}")
        if depth <= 0:
            statements.append((start, n))
            start, depth = n + 1, 0
    if start < len(lines):
        raise Refused("the file doesn't close every bracket it opens")
    drop = set()
    for first, last in statements:
        if any(value in lines[k] for k in range(first, last + 1)):
            drop.update(range(first, last + 1))
    out = "\n".join(line for k, line in enumerate(lines) if k not in drop)
    if not _balanced(out):
        raise Refused("taking it out would leave the file broken")
    return out


def without(text, kind, rel, value):
    if kind == "json":
        new = json_without(text, value)
        json.loads(new)  # still JSON, or nothing changes
        return new
    return rules_without(text, value) if rel.endswith(".rules") else toml_without(text, value)


# ---------- git: how far the file, and the secret in it, have gone ----------

def git(words, folder, given=None, timeout=20):
    """(return code, output as bytes) for git with fixed words in a folder, never through a shell. It takes no locks,
    reads paths as written (check-ignore refuses that, and takes them as names anyway), runs no file-system monitor,
    and never stops to ask for anything."""
    env = {**os.environ, "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C"}
    if words[0] != "check-ignore":
        env["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        done = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.quotepath=off", *words], cwd=folder,
                              input=given, stdin=None if given is not None else subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=timeout, env=env)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 127, b""
    return done.returncode, done.stdout


def repo_top(folder):
    code, out = git(["rev-parse", "--show-toplevel"], folder)
    top = out.decode("utf-8", "replace").strip()
    return os.path.realpath(top) if code == 0 and top else None


def _blobs(top, rel, commits):
    """{commit: contents} of a file in each of those commits, read through two git processes, never one per commit."""
    if not commits:
        return {}
    code, out = git(["cat-file", "--batch-check"], top, "".join("{}:{}\n".format(c, rel) for c in commits).encode("utf-8"))
    rows = out.decode("utf-8", "replace").splitlines() if code == 0 else []
    blob_of = {}
    for commit, row in zip(commits, rows):
        parts = row.split()
        if len(parts) == 3 and parts[1] == "blob":
            blob_of[commit] = parts[0]
    unique = sorted(set(blob_of.values()))
    code, out = git(["cat-file", "--batch"], top, "".join(b + "\n" for b in unique).encode("ascii"))
    contents, at = {}, 0
    while code == 0 and at < len(out):
        head_end = out.find(b"\n", at)
        head = out[at:head_end].split()
        if head_end < 0 or len(head) != 3:
            break
        size = int(head[2])
        contents[head[0].decode("ascii")] = out[head_end + 1:head_end + 1 + size]
        at = head_end + 1 + size + 1
    return {c: contents.get(b, b"") for c, b in blob_of.items()}


class FileGit:
    """What git knows of one settings file: whether it is in a repository, tracked, ignored, and its committed copies."""

    def __init__(self, path, heads):
        self.path, self.top, self.rel = path, repo_top(os.path.dirname(path)), None
        self.tracked = self.ignored = False
        self.history = {}
        if not self.top:
            return
        self.rel = os.path.relpath(os.path.realpath(path), self.top).replace(os.sep, "/")
        code, out = git(["ls-files", "-z", "--", self.rel], self.top)
        self.tracked = code == 0 and bool(out.strip(b"\0"))
        if not self.tracked:
            self.ignored = git(["check-ignore", "-q", "--", self.rel], self.top)[0] == 0
            return
        if self.top not in heads:  # HEAD, if this repository has a commit yet, beside its branches, tags and remotes
            heads[self.top] = ["HEAD"] if git(["rev-parse", "--verify", "-q", "HEAD"], self.top)[0] == 0 else []
        code, out = git(["log", *heads[self.top], "--branches", "--tags", "--remotes", "--format=%H", "-n", str(MOST_COMMITS),
                         "--", self.rel], self.top)
        commits = out.decode("ascii", "replace").split() if code == 0 else []
        self.history = _blobs(self.top, self.rel, commits)

    def state(self, value):
        """(state, remote): pushed, committed, open (git would commit it), ignored, or outside (no git), and for
        pushed, "GitHub" when it went there."""
        if not self.top:
            return "outside", None
        if not self.tracked:
            return ("ignored" if self.ignored else "open"), None
        needles = {value.encode("utf-8", "surrogatepass"), json.dumps(value)[1:-1].encode("utf-8", "surrogatepass")}
        holding = [c for c, body in self.history.items() if any(n in body for n in needles)]
        if not holding:
            return "open", None
        code, out = git(["for-each-ref", "--format=%(refname)", *["--contains=" + c for c in holding], "refs/remotes/"], self.top)
        refs = out.decode("utf-8", "replace").split() if code == 0 else []
        if not refs:
            return "committed", None
        names = git(["remote"], self.top)[1].decode("utf-8", "replace").split()
        remote = max((n for n in names if refs[0].startswith("refs/remotes/{}/".format(n))), key=len, default=None)
        url = git(["remote", "get-url", remote], self.top)[1].decode("utf-8", "replace") if remote else ""
        return "pushed", ("GitHub" if "github.com" in url.lower() else None)


# ---------- the words ----------

ORDER = {"pushed": 0, "committed": 1, "open": 2, "ignored": 3, "outside": 4}


def place_of(rel, path):
    """Where in the settings a secret sits, as a person would say it."""
    if rel.endswith(".mcp.json"):
        return "an MCP server's settings"
    if "/.codex/rules/" in "/" + rel:
        return "Codex's command rules"
    if rel.endswith(".codex/config.toml"):
        return "Codex's settings"
    first = path[0] if path else None
    if first == "permissions":
        return "an agent's allow list" if len(path) > 1 and path[1] == "allow" else "an agent's permission rules"
    if first == "env":
        return "Claude Code's environment settings"
    if first == "hooks":
        return "a hook's command"
    if first == "mcpServers":
        return "an MCP server's settings"
    if first in ("apiKeyHelper", "awsAuthRefresh", "awsCredentialExport", "otelHeadersHelper"):
        return "Claude Code's sign-in settings"
    return "Claude Code's settings"


def said(what, place, file, state, remote=None):
    """The finding in one plain sentence: what, where, and how far git has taken it."""
    where = "{} is saved in {} in {}".format(what, place, file)
    if state == "pushed":
        there = " to GitHub" if remote == "GitHub" else ""
        history = "the history on GitHub" if remote == "GitHub" else "the history you pushed"
        return "{}, in a commit already pushed{}. Change that secret now: taking it out here doesn't take it out of {}.".format(where, there, history)
    if state == "committed":
        return "{}, in a commit not pushed yet. Take it out before you push: out of the file, and out of that commit too.".format(where)
    if state == "open":
        return "{}, and git would commit that file.".format(where)
    if state == "ignored":
        return "{}. Git ignores that file, so it stays on this computer, but any program that reads it can see it.".format(where)
    return "{}. The folder isn't in git, so it stays on this computer, but any program that reads it can see it.".format(where)


# ---------- where Arnheim keeps what it found ----------

def store(data):
    """data/.secrets: a hidden folder, so serve.py never serves it, readable by you alone."""
    folder = os.path.join(data, ".secrets")
    for each in (folder, os.path.join(folder, "undo")):
        if not os.path.isdir(each):
            os.makedirs(each, exist_ok=True)
            os.chmod(each, 0o700)  # makedirs alone leaves the mode to the umask
    return folder


def _key(data):
    """A random key of this copy's own, so a finding's id can't be used to guess the secret."""
    path = os.path.join(store(data), "key")
    try:
        with open(path, "rb") as handle:
            key = handle.read()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = os.urandom(32)
    _write(path, key, 0o600)
    return key


def _write(path, raw, mode=0o600):
    """A file written whole, as a new file renamed over the old one, with the given mode."""
    handle, part = tempfile.mkstemp(prefix=".arnheim-", dir=os.path.dirname(path) or ".")
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(raw)
        os.chmod(part, mode)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


class _Locked:
    """One check or change at a time, across serve.py and the minute job."""

    def __init__(self, data):
        self.handle = open(os.path.join(store(data), "lock"), "a")

    def __enter__(self):
        try:
            import fcntl
            fcntl.flock(self.handle, fcntl.LOCK_EX)
        except ImportError:
            pass
        return self

    def __exit__(self, *_):
        self.handle.close()


# ---------- checking ----------

def floors(data):
    """(floor id, project, folder) for every floor that names a folder, as connect/projects.py reads them."""
    try:
        with open(os.path.join(data, "company.json"), encoding="utf-8-sig") as handle:
            company = json.load(handle)
    except (OSError, ValueError):
        return []
    out = []
    for floor in company.get("floors") or [] if isinstance(company, dict) else []:
        if not isinstance(floor, dict):
            continue
        folders = floor.get("folders") or ([floor["folder"]] if floor.get("folder") else [])
        for folder in folders if isinstance(folders, list) else []:
            out.append((str(floor.get("id")), str(floor.get("project") or floor.get("label") or ""), os.path.expanduser(str(folder))))
    return out


def files_of(folder):
    """The settings files to read for one floor's folder: its own, and those at its repository's top, where Claude Code
    keeps the local file when it starts in a folder inside it (never a top that is the home folder or a whole disk)."""
    bases = [os.path.realpath(folder)]
    top = repo_top(folder)
    if top and top not in bases and top != os.path.realpath(os.path.expanduser("~")) and os.path.dirname(top) != top:
        bases.append(top)
    out = []
    for base in bases:
        for rel, kind in FILES:
            out.append((base, rel, kind))
        try:
            rules = sorted(n for n in os.listdir(os.path.join(base, *RULES.split("/"))) if n.endswith(".rules"))[:20]
        except OSError:
            rules = []
        out.extend((base, RULES + "/" + n, "rules") for n in rules)
    return out


def read_text(path):
    """A small settings file's text, or None: missing, too big, or not text."""
    try:
        if not os.path.isfile(path) or os.path.getsize(path) > MOST_BYTES:
            return None
        with open(path, "rb") as handle:
            return handle.read().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def shown_file(path, folder):
    """The file as the page names it: inside the floor's folder, from there; at the repository's top, from that folder's name."""
    folder = os.path.realpath(folder)
    real = os.path.realpath(path)
    if real.startswith(folder + os.sep):
        return os.path.relpath(real, folder).replace(os.sep, "/")
    top = repo_top(os.path.dirname(path)) or os.path.dirname(real)
    return os.path.basename(top) + "/" + os.path.relpath(real, top).replace(os.sep, "/")


def finding_id(key, path, value):
    return hmac.new(key, "{}\0{}".format(os.path.realpath(path), value).encode("utf-8", "surrogatepass"), hashlib.sha256).hexdigest()[:20]


def scan_file(path, kind, rel, key):
    """{id: (hit, line, path, count)} for one file's secrets, each value once, at its first place."""
    text = read_text(path)
    if text is None:
        return {}, None
    try:
        hits = file_hits(text.lstrip("\ufeff"), kind)
    except (ValueError, RecursionError):
        return {}, text  # not valid JSON: Claude Code says so itself, and nothing here can be taken out
    found = {}
    for hit, line, where in hits:
        fid = finding_id(key, path, hit.value)
        if fid in found:
            found[fid][3] += 1
        else:
            found[fid] = [hit, line, where, 1]
    return found, text


def scan(data=None):
    """Every secret in every floor's agent settings, as the page shows it: never the secret, only its kind, where,
    a hint, how far git has taken it, and which fixes would work."""
    data = data or DATA
    key = _key(data)
    findings, seen, heads = [], set(), {}
    for floor_id, project, folder in floors(data):
        if not os.path.isdir(folder):
            continue
        for base, rel, kind in files_of(folder):
            path = os.path.join(base, *rel.split("/"))
            real = os.path.realpath(path)
            if real in seen:
                continue
            found, text = scan_file(path, kind, rel, key)
            if not found:
                continue
            seen.add(real)
            # the file, or a folder on the way to it such as .claude, is a link: Take it out would write where it points
            linked = real != os.path.normpath(os.path.join(os.path.realpath(base), *rel.split("/")))
            info = FileGit(path, heads)
            file = shown_file(path, folder)
            for fid, (hit, line, where, count) in found.items():
                state, remote = info.state(hit.value)
                try:
                    without(text.lstrip("\ufeff"), kind, rel, hit.value)
                    out_ok = not linked
                except (Refused, ValueError):
                    out_ok = False
                what, place = hit.words, place_of(rel, where)
                findings.append({
                    "id": fid, "project": project, "floor": floor_id, "path": real, "rel": rel, "type": kind,
                    "file": file, "line": line, "count": count, "kind": hit.kind, "what": what, "hint": hint(hit),
                    "place": place, "state": state, "remote": remote, "tracked": info.tracked,
                    "fix": {"out": out_ok, "exclude": bool(info.top) and not info.tracked and not info.ignored},
                    "says": said(what, place, file, state, remote),
                })
    findings.sort(key=lambda f: (ORDER.get(f["state"], 9), f["project"], f["file"], f["line"]))
    return {"at": int(time.time()), "findings": findings}


def check(data=None):
    """A check now, kept in data/.secrets/found.json for the page. Gives what it found."""
    data = data or DATA
    with _Locked(data):
        return _check(data)


def _check(data):
    found = scan(data)
    _write(os.path.join(store(data), "found.json"), json.dumps(found, ensure_ascii=False, indent=1).encode("utf-8"))
    return found


def read_found(data):
    try:
        with open(os.path.join(store(data), "found.json"), encoding="utf-8") as handle:
            found = json.load(handle)
        return found if isinstance(found, dict) and isinstance(found.get("findings"), list) else {"findings": []}
    except (OSError, ValueError):
        return {"findings": []}


# ---------- fixing, and undoing ----------

UNDO = re.compile(r"^[0-9a-f]{16}$")
FINDING = re.compile(r"^[0-9a-f]{20}$")


def _undo_paths(data, uid):
    folder = os.path.join(store(data), "undo")
    return os.path.join(folder, uid + ".kept"), os.path.join(folder, uid + ".json")


def _sha(raw):
    return hashlib.sha256(raw).hexdigest() if raw is not None else None


def _read_bytes(path):
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except OSError:
        return None


def _keep(data, meta, before):
    """Keeps a copy of a file as it was (its bytes, or that there was none) and what was done, for Undo."""
    uid = os.urandom(8).hex()
    copy, about = _undo_paths(data, uid)
    _write(copy, before if before is not None else b"", 0o600)
    _write(about, json.dumps({**meta, "undo": uid, "at": int(time.time()), "existed": before is not None,
                              "before": _sha(before)}, indent=1).encode("utf-8"), 0o600)
    return uid


def _finding(data, fid):
    """The finding with that id, checked again first, so a fix is never made on an old list."""
    if not isinstance(fid, str) or not FINDING.match(fid):
        raise Refused("That isn't one of the secrets found.")
    for f in _check(data)["findings"]:
        if f["id"] == fid:
            return f
    raise Refused("It isn't there any more: the list has been checked again.")


def take_out(fid, data=None):
    """Take it out: removes only the rules or entries that hold the secret from its file, after keeping a copy of the
    file for Undo. Gives (what was done, the undo's id)."""
    data = data or DATA
    with _Locked(data):
        f = _finding(data, fid)
        path = f["path"]
        if not f["fix"]["out"]:  # checked here too, not only by the page hiding the button
            raise Refused("Arnheim can't take it out of {} safely: it is reached through a link, or taking it out would "
                          "leave a hook or a server broken. Open the file and change it by hand.".format(f["file"]))
        before = _read_bytes(path)
        text = before.decode("utf-8") if before is not None else None
        if text is None:
            raise Refused("{} couldn't be read.".format(f["file"]))
        bom = "\ufeff" if text.startswith("\ufeff") else ""
        key = _key(data)
        value = next((h.value for h, _, _ in file_hits(text[len(bom):], f["type"]) if finding_id(key, path, h.value) == fid), None)
        if value is None:
            raise Refused("It isn't in {} any more.".format(f["file"]))
        try:
            new = bom + without(text[len(bom):], f["type"], f["rel"], value)
        except (Refused, ValueError) as why:
            raise Refused("Arnheim can't take it out of {} safely ({}). Open the file and take it out by hand.".format(f["file"], why))
        if any(finding_id(key, path, h.value) == fid for h, _, _ in file_hits(new[len(bom):], f["type"])):
            raise Refused("It couldn't be taken out of {} cleanly, so nothing was changed.".format(f["file"]))
        after = new.encode("utf-8")
        uid = _keep(data, {"kind": "out", "path": path, "file": f["file"], "project": f["project"], "floor": f["floor"],
                           "what": f["what"], "state": f["state"], "remote": f["remote"], "after": _sha(after),
                           "mode": os.stat(path).st_mode & 0o7777}, before)
        try:
            _write(path, after, os.stat(path).st_mode & 0o7777)
        except OSError:
            _forget(*_undo_paths(data, uid))  # nothing changed, so nothing to undo
            raise
        _check(data)
        words = "Taken out of {}, and a copy kept for a week, so Undo can put it back.".format(f["file"])
        if f["state"] == "pushed":
            words += " Change that secret now: it is still in the history{}.".format(" on GitHub" if f["remote"] == "GitHub" else " you pushed")
        elif f["state"] == "committed":
            words += " It is still in a commit you haven't pushed: take it out of that commit before you push."
        return words, uid


def _exclude_line(rel):
    """The repository's path as an exclude line that matches only that file."""
    return "/" + re.sub(r"([*?\[\\!#])", r"\\\1", rel)


EXCLUDE_NOTE = "# Kept out of git by Arnheim's secrets check"


def keep_git_out(fid, data=None):
    """Keep git out of it: adds the file to the repository's .git/info/exclude, which changes no tracked file and is
    this copy's alone. Only for a file git doesn't track yet. Gives (what was done, the undo's id)."""
    data = data or DATA
    with _Locked(data):
        f = _finding(data, fid)
        if not f["fix"]["exclude"]:
            raise Refused("git already tracks {}, so an exclude line wouldn't keep it out: take the secret out instead.".format(f["file"])
                          if f["tracked"] else "git already leaves {} out.".format(f["file"]))
        top = repo_top(os.path.dirname(f["path"]))
        code, out = git(["rev-parse", "--git-path", "info/exclude"], top)
        if not top or code != 0:
            raise Refused("git couldn't say where this repository keeps its exclude list.")
        exclude = os.path.join(top, out.decode("utf-8", "replace").strip())
        rel = os.path.relpath(f["path"], top).replace(os.sep, "/")
        before = _read_bytes(exclude)
        text = before.decode("utf-8", "surrogateescape") if before is not None else ""
        added = ("" if not text or text.endswith("\n") else "\n") + "{}\n{}\n".format(EXCLUDE_NOTE, _exclude_line(rel))
        after = (text + added).encode("utf-8", "surrogateescape")
        os.makedirs(os.path.dirname(exclude), exist_ok=True)
        mode = os.stat(exclude).st_mode & 0o7777 if before is not None else 0o644
        _write(exclude, after, mode)
        if git(["check-ignore", "-q", "--", rel], top)[0] != 0:
            _put_back(exclude, before, mode)
            raise Refused("git still didn't leave {} out, so the exclude list was put back as it was.".format(f["file"]))
        uid = _keep(data, {"kind": "exclude", "path": exclude, "file": f["file"], "project": f["project"], "floor": f["floor"],
                           "what": f["what"], "state": f["state"], "added": added, "after": _sha(after), "mode": mode}, before)
        _check(data)
        return ("git now leaves {} out, in this copy of the repository only (.git/info/exclude). No tracked file "
                "changed.".format(f["file"])), uid


def _put_back(path, before, mode):
    if before is None:
        try:
            os.remove(path)
        except OSError:
            pass
    else:
        _write(path, before, mode)


def undo(uid, data=None):
    """Puts a file back as it was before Take it out or Keep git out of it, byte for byte, if it hasn't changed since.
    Gives what was done."""
    data = data or DATA
    with _Locked(data):
        meta, copy, about = _meta(data, uid)
        before = _read_bytes(copy) if meta.get("existed") else None
        if meta.get("existed") and _sha(before) != meta.get("before"):
            raise Refused("The copy kept for Undo isn't whole any more, so nothing was changed.")
        now = _read_bytes(meta["path"])
        if _sha(now) != meta.get("after"):
            if meta["kind"] == "exclude" and now is not None and meta.get("added", "") in now.decode("utf-8", "surrogateescape"):
                text = now.decode("utf-8", "surrogateescape").replace(meta["added"], "", 1)
                _write(meta["path"], text.encode("utf-8", "surrogateescape"), os.stat(meta["path"]).st_mode & 0o7777)
                _forget(copy, about)
                _check(data)
                return "The exclude line Arnheim added is out again. The rest of the list changed since, and was kept."
            raise Refused("{} has changed since, so putting the old one back would undo those changes too. Nothing was "
                          "changed.".format(meta["file"]))
        _put_back(meta["path"], before, int(meta.get("mode") or 0o600))
        _forget(copy, about)
        _check(data)
        return ("Put back: {} is as it was.".format(meta["file"]) if meta["kind"] == "out"
                else "Put back: git no longer leaves {} out.".format(meta["file"]))


def forget(uid, data=None):
    """Deletes a copy kept for Undo now, rather than after a week."""
    data = data or DATA
    with _Locked(data):
        _, copy, about = _meta(data, uid)
        _forget(copy, about)
        return "The copy is deleted, so that can't be undone now."


def _meta(data, uid):
    if not isinstance(uid, str) or not UNDO.match(uid):
        raise Refused("There is nothing like that to undo.")
    copy, about = _undo_paths(data, uid)
    try:
        with open(about, encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        raise Refused("There is nothing like that to undo: it may be more than a week old.")
    return meta, copy, about


def _forget(copy, about):
    for path in (copy, about):
        try:
            os.remove(path)
        except OSError:
            pass


def taken(data=None, now=None):
    """What was fixed lately and can still be undone, newest first; copies older than a week are deleted here."""
    data = data or DATA
    now = time.time() if now is None else now
    folder = os.path.join(store(data), "undo")
    out = []
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json") or not UNDO.match(name[:-5]):
            continue
        copy, about = _undo_paths(data, name[:-5])
        try:
            with open(about, encoding="utf-8") as handle:
                meta = json.load(handle)
        except (OSError, ValueError):
            continue
        if now - float(meta.get("at") or 0) > KEEP_DAYS * 86400:
            _forget(copy, about)
            continue
        out_kind = meta.get("kind") == "out"
        remind = None
        if out_kind and meta.get("state") == "pushed":
            remind = "Change that secret now: it is still in the history{}.".format(" on GitHub" if meta.get("remote") == "GitHub" else " you pushed")
        elif out_kind and meta.get("state") == "committed":
            remind = "It is still in a commit you haven't pushed: take it out of that commit before you push."
        out.append({"undo": meta.get("undo"), "kind": meta.get("kind"), "project": meta.get("project"), "file": meta.get("file"),
                    "at": meta.get("at"), "remind": remind,
                    "says": ("{} was taken out of {}.".format(meta.get("what"), meta.get("file")) if out_kind
                             else "git leaves {} out now.".format(meta.get("file")))})
    return sorted(out, key=lambda t: -float(t.get("at") or 0))


# ---------- serve.py's /secrets/ ----------

def public(f):
    """A finding as the page gets it: without the file's whole path."""
    return {k: v for k, v in f.items() if k not in ("path", "rel", "type")}


def listing(data, on=True):
    found = read_found(data) if on else {"findings": []}
    return {"on": on, "at": found.get("at"), "findings": [public(f) for f in found["findings"] if isinstance(f, dict)],
            "taken": taken(data)}


def handle(name, body, data=None, on=True):
    """/secrets/ for serve.py, which has already made sure it is this computer's own page and, on a POST, that it
    sent the page's token from the page's own Origin. GET gives what was found; POST check, out (Take it out),
    exclude (Keep git out of it), undo and forget change things. Gives (status, answer)."""
    data = data or DATA
    if body is None:
        return (200, listing(data, on)) if name == "" else (404, {"error": "No such request."})
    try:
        given = json.loads(body.decode("utf-8") or "{}")
    except (UnicodeDecodeError, ValueError):
        given = None
    if not isinstance(given, dict):
        return 400, {"error": "That wasn't a JSON object."}
    try:
        if name == "check":
            if not on:
                raise Refused("The secrets check is switched off. Switch it on in Settings, under Switches.")
            found = check(data)["findings"]
            words = ("Checked: nothing secret in your agents' settings." if not found else
                     "Checked: {} secret{} in your agents' settings.".format(len(found), "" if len(found) == 1 else "s"))
            return 200, {**listing(data, on), "said": words}
        if name in ("out", "exclude"):
            words, uid = (take_out if name == "out" else keep_git_out)(given.get("id"), data)
            return 200, {**listing(data, on), "said": words, "undo": uid}
        if name == "undo":
            return 200, {**listing(data, on), "said": undo(given.get("undo"), data)}
        if name == "forget":
            return 200, {**listing(data, on), "said": forget(given.get("undo"), data)}
    except Refused as why:
        return 409, {**listing(data, on), "error": str(why)}
    except OSError as error:
        return 409, {**listing(data, on), "error": "That couldn't be done: {}.".format(error.strerror or error)}
    return 404, {"error": "No such request."}


def main():
    parser = argparse.ArgumentParser(description="Finds passwords and tokens saved in your agents' settings, in each floor's folder.")
    parser.add_argument("--show", action="store_true", help="say what it found here too (never the secrets themselves)")
    args = parser.parse_args()
    found = check()["findings"]
    taken()  # each minute's run also deletes copies older than a week, whether or not the page asks
    if args.show:
        for f in found:
            print("{}: {} (line {}, {})".format(f["project"], f["says"], f["line"], f["hint"]))
        print("Nothing secret in your agents' settings." if not found else "{} found.".format(len(found)))


if __name__ == "__main__":
    sys.exit(main())
