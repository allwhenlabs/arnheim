"""Setting Arnheim up from inside an agent: the Claude Code plugin marketplace (.claude-plugin/marketplace.json), the
Codex one (.agents/plugins/marketplace.json), the one plugin both list (plugins/arnheim), and docs/agent-setup.md,
which any agent can follow. Every file parses and has the fields the agents' own docs ask for, every path and command
it names is there, and the plugin holds instructions only: no hooks, servers or scripts.

The field rules follow code.claude.com/docs (plugin marketplaces, the marketplace and manifest references, skills)
and developers.openai.com/plugins/build/plugins (Codex). Standard library only. The one test that runs anything
starts serve.py's own server on a free port, as test_serve does, to try the status check the steps give.

Run from the repository's folder: python3 -m unittest discover tests
"""
import importlib.util
import json
import os
import re
import shlex
import socket
import subprocess
import sys
import threading
import unittest
from urllib.parse import urlparse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "connect"))

import always  # noqa: E402  connect/always.py: where the login item lives
import serve  # noqa: E402

PLUGIN = os.path.join(ROOT, "plugins", "arnheim")
CLAUDE_MARKET = os.path.join(ROOT, ".claude-plugin", "marketplace.json")
CODEX_MARKET = os.path.join(ROOT, ".agents", "plugins", "marketplace.json")
CLAUDE_MANIFEST = os.path.join(PLUGIN, ".claude-plugin", "plugin.json")
CODEX_MANIFEST = os.path.join(PLUGIN, ".codex-plugin", "plugin.json")
AGENT_DOC = os.path.join(ROOT, "docs", "agent-setup.md")
README = os.path.join(ROOT, "README.md")
REPO = "https://github.com/allwhenlabs/arnheim"
SKILLS = ("open", "setup", "status")
PASTE = "Set up Arnheim for me: follow github.com/allwhenlabs/arnheim/blob/main/docs/agent-setup.md"
SHARED = "## Rules for you, the agent"  # where the setup skill and docs/agent-setup.md start to say the same

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")  # each part of plugin@marketplace
KEBAB = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
# Claude Code refuses these marketplace names (marketplace reference, "Reserved names")
RESERVED_MARKETS = {
    "claude-code-marketplace", "claude-code-plugins", "claude-plugins-official", "anthropic-marketplace",
    "anthropic-plugins", "agent-skills", "anthropic-agent-skills", "life-sciences", "knowledge-work-plugins",
    "claude-for-legal", "claude-for-financial-services", "financial-services-plugins", "first-party-plugins",
    "claude-tag-plugins", "claude-community", "claude-plugins-community", "healthcare", "anthropic-plugin-directory",
    "claude-plugin-directory", "inline", "builtin", "skills-dir", "synced", "claude-plugin-test", "constructor",
    "hasOwnProperty", "isPrototypeOf", "propertyIsEnumerable", "toLocaleString", "toString", "valueOf",
    "allwhenlabs-arnheim",  # the folder Claude Code downloads this GitHub repository through
}
MARKET_FIELDS = {"$schema", "name", "owner", "plugins", "description", "version", "metadata",
                 "forceRemoveDeletedPlugins", "allowCrossMarketplaceDependenciesOn", "renames"}
MANIFEST_FIELDS = {"$schema", "name", "displayName", "version", "description", "author", "homepage", "repository",
                   "license", "keywords", "metadata", "defaultEnabled", "engines", "dependencies", "userConfig",
                   "channels", "skills", "commands", "agents", "hooks", "mcpServers", "lspServers", "outputStyles",
                   "workflows", "experimental", "types", "icon", "documentationUrl", "supportUrl", "privacyPolicyUrl",
                   "termsOfServiceUrl"}
ENTRY_FIELDS = (MANIFEST_FIELDS - {"icon", "documentationUrl", "supportUrl", "privacyPolicyUrl", "termsOfServiceUrl"}) \
    | {"source", "category", "tags", "strict", "relevance", "headers", "headersHelper"}
CODEX_INSTALL = {"AVAILABLE", "INSTALLED_BY_DEFAULT", "NOT_AVAILABLE"}


def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def skill_file(name):
    return os.path.join(PLUGIN, "skills", name, "SKILL.md")


def front(text):
    """(the frontmatter of a SKILL.md as a dict, the rest)."""
    lines = text.split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        return None, text
    end = lines.index("---", 1)
    fields = {}
    for line in lines[1:end]:
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields, "\n".join(lines[end + 1:])


def relative_inside(base, path):
    """A relative path as the agents' docs allow it: starts with ./, no .., forward slashes, inside `base`, there."""
    if not isinstance(path, str) or not path.startswith("./") or ".." in path.split("/") or "\\" in path:
        return None
    full = os.path.realpath(os.path.join(base, path))
    return full if (full == os.path.realpath(base) or full.startswith(os.path.realpath(base) + os.sep)) \
        and os.path.exists(full) else None


def is_url(value):
    parts = urlparse(value or "")
    return parts.scheme == "https" and bool(parts.netloc)


def steps():
    """The texts that tell an agent what to run: docs/agent-setup.md and each skill."""
    return {"docs/agent-setup.md": read(AGENT_DOC), **{f"skills/{n}/SKILL.md": read(skill_file(n)) for n in SKILLS}}


def code_in(text):
    """Every command in a text: each line of its fenced blocks, and each `inline` span outside them."""
    found, fence = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if fence:
            found.append(line.strip())
        else:
            found.extend(re.findall(r"`([^`]+)`", line))
    return [c for c in found if c]


def prose(text):
    """The lines of a Markdown text outside its fenced blocks, without inline code."""
    out, fence = [], False
    for line in text.split("\n"):
        if line.strip().startswith("```"):
            fence = not fence
            continue
        if not fence:
            out.append(re.sub(r"`[^`]*`", "", line))
    return out


def readme_block():
    text = read(README)
    start = text.index("**From inside Claude Code")
    return text[start:text.index("\n\n", text.index("agent-setup.md", start))]


def flags_of(script):
    """The options a script's --help lists, by running it with --help (which does nothing else)."""
    said = subprocess.run([sys.executable, os.path.join(ROOT, script), "--help"], capture_output=True, text=True,
                          timeout=60, cwd=ROOT)
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", said.stdout))


class ClaudeMarketplace(unittest.TestCase):
    def test_it_parses_and_has_what_claude_code_requires(self):
        market = load(CLAUDE_MARKET)
        self.assertLessEqual(set(market), MARKET_FIELDS, "a field Claude Code doesn't read")
        self.assertTrue(ID.match(market["name"]) and ".." not in market["name"])
        self.assertTrue(KEBAB.match(market["name"]))
        self.assertNotIn(market["name"], RESERVED_MARKETS)
        self.assertFalse(market["name"].startswith("claudeai-"))
        self.assertTrue(market["owner"]["name"].strip())
        self.assertTrue(market["description"].strip())  # claude plugin validate warns without one
        self.assertIsInstance(market["plugins"], list)
        self.assertEqual(len(market["plugins"]), 1)
        names = [p["name"] for p in market["plugins"]]
        self.assertEqual(len(names), len(set(names)))

    def test_its_plugin_is_in_this_repository_and_named_as_its_manifest(self):
        market = load(CLAUDE_MARKET)
        for entry in market["plugins"]:
            self.assertLessEqual(set(entry), ENTRY_FIELDS, "a field Claude Code doesn't read in an entry")
            self.assertTrue(ID.match(entry["name"]) and KEBAB.match(entry["name"]))
            self.assertTrue(entry["description"].strip())
            folder = relative_inside(ROOT, entry["source"])  # from the marketplace root, the folder above .claude-plugin
            self.assertIsNotNone(folder, f"{entry['source']} isn't a folder inside the repository")
            self.assertEqual(folder, os.path.realpath(PLUGIN))
            self.assertEqual(load(CLAUDE_MANIFEST)["name"], entry["name"])  # else installing by name fails
            self.assertNotIn("version", entry)  # plugin.json's version wins, and validate warns about both

    def test_the_readme_installs_it_by_these_names(self):
        market = load(CLAUDE_MARKET)
        block = readme_block()
        self.assertIn("/plugin marketplace add allwhenlabs/arnheim", block)
        self.assertIn(f"/plugin install {market['plugins'][0]['name']}@{market['name']}", block)
        self.assertTrue(REPO.endswith("/allwhenlabs/arnheim"))


class ClaudePlugin(unittest.TestCase):
    def test_the_manifest_has_what_claude_code_requires(self):
        manifest = load(CLAUDE_MANIFEST)
        self.assertLessEqual(set(manifest), MANIFEST_FIELDS, "a field Claude Code strips")
        name = manifest["name"]
        self.assertTrue(KEBAB.match(name))
        self.assertFalse(re.match(r"^(claude|anthropic|anthropics|cc-plugin)-", name))
        self.assertNotIn(name, {"claude", "anthropic", "anthropics", "claude-code", "claude-mods"})
        self.assertIsInstance(manifest["version"], str)
        self.assertTrue(manifest["description"].strip())
        self.assertTrue(manifest["author"]["name"].strip())
        self.assertTrue(is_url(manifest["homepage"]))  # else the plugin fails to load
        self.assertEqual(manifest["homepage"], REPO)
        self.assertEqual(manifest["repository"], REPO)
        self.assertEqual(manifest["license"], "MIT")

    def test_it_holds_instructions_only(self):
        """No hooks, MCP or LSP servers, commands on PATH or scripts: a plugin runs with the person's rights, and
        Arnheim's own setup adds its hooks, with copies and Undo. Only the two manifests and the skills."""
        files = set()
        for top, dirs, names in os.walk(PLUGIN):
            for name in names:
                if name != ".DS_Store":
                    files.add(os.path.relpath(os.path.join(top, name), PLUGIN).replace(os.sep, "/"))
        expected = {".claude-plugin/plugin.json", ".codex-plugin/plugin.json"} | {f"skills/{n}/SKILL.md" for n in SKILLS}
        self.assertEqual(files, expected)
        for manifest in (load(CLAUDE_MANIFEST), load(CODEX_MANIFEST)):
            for key in ("hooks", "mcpServers", "lspServers", "commands", "agents", "userConfig", "channels", "experimental"):
                self.assertNotIn(key, manifest)
        for entry in load(CLAUDE_MARKET)["plugins"] + load(CODEX_MARKET)["plugins"]:
            self.assertNotIn("hooks", entry)

    def test_each_skill_has_a_name_and_a_description_both_agents_read(self):
        found = sorted(d for d in os.listdir(os.path.join(PLUGIN, "skills")) if not d.startswith("."))
        self.assertEqual(found, list(SKILLS))
        for name in SKILLS:
            fields, body = front(read(skill_file(name)))
            self.assertIsNotNone(fields, f"{name}: no frontmatter")
            self.assertEqual(set(fields), {"name", "description"}, f"{name}: only the fields Codex and Claude Code share")
            self.assertEqual(fields["name"], name)
            self.assertTrue(KEBAB.match(name) and len(name) <= 64)
            self.assertTrue(20 < len(fields["description"]) <= 1024, name)  # Claude Code cuts the listing at 1,536
            self.assertTrue(body.strip())


class CodexMarketplace(unittest.TestCase):
    def test_it_parses_and_has_what_codex_asks_for(self):
        market = load(CODEX_MARKET)
        self.assertEqual(market["name"], load(CLAUDE_MARKET)["name"])
        self.assertTrue(market["interface"]["displayName"].strip())
        self.assertEqual(len(market["plugins"]), 1)
        for entry in market["plugins"]:
            self.assertEqual(entry["name"], load(CODEX_MANIFEST)["name"])
            self.assertEqual(entry["source"]["source"], "local")
            # from the marketplace root: the repository, two folders above .agents/plugins/marketplace.json
            self.assertEqual(relative_inside(ROOT, entry["source"]["path"]), os.path.realpath(PLUGIN))
            self.assertIn(entry["policy"]["installation"], CODEX_INSTALL)
            self.assertTrue(entry["policy"]["authentication"].strip())
            self.assertTrue(entry["category"].strip())

    def test_the_codex_manifest_matches_the_claude_one_and_names_the_skills(self):
        codex, claude = load(CODEX_MANIFEST), load(CLAUDE_MANIFEST)
        self.assertTrue(KEBAB.match(codex["name"]))
        self.assertEqual(codex["name"], claude["name"])
        self.assertEqual(codex["version"], claude["version"])  # one plugin, one version: change both together
        self.assertTrue(codex["description"].strip())
        self.assertEqual(relative_inside(PLUGIN, codex["skills"]), os.path.realpath(os.path.join(PLUGIN, "skills")))
        self.assertEqual(codex["homepage"], REPO)

    def test_the_readme_adds_it_in_codex(self):
        self.assertIn("codex plugin marketplace add allwhenlabs/arnheim", readme_block())
        self.assertIn("/plugins", readme_block())


class TheSteps(unittest.TestCase):
    def test_the_setup_skill_and_the_page_for_any_agent_say_the_same(self):
        doc, skill = read(AGENT_DOC), read(skill_file("setup"))
        self.assertIn(SHARED, doc)
        self.assertIn(SHARED, skill)
        self.assertEqual(skill[skill.index(SHARED):], doc[doc.index(SHARED):],
                         "change docs/agent-setup.md and plugins/arnheim/skills/setup/SKILL.md together")

    def test_the_line_to_paste_points_at_this_page(self):
        self.assertIn(PASTE, read(AGENT_DOC))
        self.assertIn(PASTE, " ".join(readme_block().split()))
        self.assertTrue(PASTE.endswith("docs/agent-setup.md") and os.path.isfile(AGENT_DOC))

    def test_every_skill_they_name_is_there(self):
        texts = dict(steps(), README=readme_block())
        for where, text in texts.items():
            for named in re.findall(r"[/$]arnheim:([a-z-]+)", text):
                self.assertIn(named, SKILLS, f"{where} names {named}")

    def test_every_script_and_option_they_run_is_there(self):
        options = {"serve.py": flags_of("serve.py"), "connect/setup.py": flags_of(os.path.join("connect", "setup.py"))}
        self.assertLessEqual({"--always", "--no-browser", "--drawn"}, options["serve.py"])  # --drawn is named alone
        self.assertLessEqual({"--folder", "--name", "--undo", "--yes"}, options["connect/setup.py"])
        ran = 0
        for where, text in dict(steps(), README=readme_block()).items():
            for command in code_in(text):
                match = re.search(r"python3 ((?:connect/)?[\w.]+\.py)(.*)", command)
                if not match:
                    continue
                script, rest = match.groups()
                self.assertIn(script, options, f"{where}: {command}")
                self.assertTrue(os.path.isfile(os.path.join(ROOT, *script.split("/"))))
                for flag in re.findall(r"(?<![\w-])(--[a-z][a-z-]*)", rest):
                    self.assertIn(flag, options[script], f"{where}: {command}")
                    self.assertNotEqual(flag, "--yes", f"{where} passes --yes: the person answers, not the agent")
                ran += 1
        self.assertGreater(ran, 8)

    def test_they_say_never_to_pass_yes(self):
        self.assertIn("Never pass `--yes` to `connect/setup.py`", read(AGENT_DOC))

    def test_the_rest_they_name_is_there(self):
        texts = steps()
        doc = texts["docs/agent-setup.md"]
        self.assertIn(f"git clone {REPO} <folder>", doc)
        self.assertIn("git -C <folder> pull --ff-only", doc)
        self.assertIsNotNone(importlib.util.find_spec("webbrowser"))  # python3 -m webbrowser
        self.assertIn("python3 -m webbrowser http://127.0.0.1:8740", doc)
        self.assertIn('if path == "/look"', read(os.path.join(ROOT, "serve.py")))
        # the login item that python3 serve.py --always adds (connect/always.py), and where it says what happened
        mac = os.path.basename(always.path_of("darwin"))
        linux = os.path.basename(always.path_of("linux"))
        self.assertIn(f"~/Library/LaunchAgents/{mac}", doc)
        self.assertIn(f"~/.config/systemd/user/{linux}", doc)
        status = texts["skills/status/SKILL.md"]
        self.assertIn(f"~/Library/LaunchAgents/{mac}", status)
        self.assertIn(f"systemctl --user is-enabled {linux}", status)
        self.assertTrue(always.log_of("darwin").endswith(os.path.join("Library", "Logs", "arnheim.log")))
        self.assertIn("~/Library/Logs/arnheim.log", status)
        self.assertIn("WorkingDirectory", always.content(["python3", "serve.py"], "/x", "/usr/bin", "darwin").decode())
        # what connect/setup.py says, as the steps quote it
        setup, flat = read(os.path.join(ROOT, "connect", "setup.py")), " ".join(doc.split())
        for said in ("Stopped before changing anything.", "Go ahead? [Y/n]", "Answer your agents from the building too",
                     "This will:"):
            self.assertIn(said, setup)
            self.assertIn(said.split(" [")[0], flat)

    def test_they_are_plain_and_name_no_one(self):
        texts = dict(steps(), README=readme_block())
        for path in (CLAUDE_MARKET, CODEX_MARKET, CLAUDE_MANIFEST, CODEX_MANIFEST):
            texts[os.path.relpath(path, ROOT)] = read(path)
        for where, text in texts.items():
            self.assertNotIn("\u2014", text, f"{where}: an em dash")
            self.assertNotIn("\u2013", text, f"{where}: an en dash")
            for bad in ("/Users/", "/home/", "C:\\Users", "@gmail", "@icloud"):
                self.assertNotIn(bad, text, where)
            for line in prose(text):
                words = re.sub(r"^\s*(-|\d+\.)\s", "", line)  # a list's own marker is fine
                self.assertNotIn(" - ", words, f"{where}: {line}")


class StatusCheck(unittest.TestCase):
    """The check the steps give for whether Arnheim runs, against serve.py's own server."""

    @staticmethod
    def command():
        lines = [c for c in code_in(read(AGENT_DOC)) if "urllib.request" in c]
        return lines[0]

    def run_it(self, port):
        words = shlex.split(self.command().replace("8740", str(port)))
        self.assertEqual(words[0], "python3")
        return subprocess.run([sys.executable] + words[1:], capture_output=True, text=True, timeout=30)

    def test_every_text_gives_the_same_check(self):
        command = self.command()
        for name in SKILLS:
            self.assertIn(command, read(skill_file(name)))

    def test_it_says_look_when_arnheim_runs(self):
        server = serve.Server(("127.0.0.1", 0), serve.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        said = self.run_it(server.server_address[1])
        self.assertEqual(said.returncode, 0, said.stderr)
        self.assertIn(json.loads(said.stdout)["look"], ("photo", "drawn"))

    def test_it_says_refused_when_nothing_runs(self):
        with socket.socket() as spare:
            spare.bind(("127.0.0.1", 0))
            port = spare.getsockname()[1]
        said = self.run_it(port)
        self.assertNotEqual(said.returncode, 0)
        self.assertIn("refused", said.stderr.lower())


if __name__ == "__main__":
    unittest.main()
