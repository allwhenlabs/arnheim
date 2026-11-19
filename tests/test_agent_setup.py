"""Set your agents up well (connect/agent_setup.py): what it finds in a project, the one instructions file both
agents read, the floor's check, the secrets kept from Claude Code, the one command allowed without asking, the
same MCP servers in both, the record that lets Undo put every file back byte for byte, running it twice, and where
people meet it: setup's question in the terminal, Connect my agents and Settings on the page (serve.py's /setup/),
and the page's own rules (src/agent-setup.js, under Node). Every test runs in a made-up home folder with made-up
claude and codex commands, so your own settings and agents are never read, run or touched. Standard library only.

Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "connect"))

import serve  # noqa: E402
from connect import agent_setup  # noqa: E402

TOOL = serve.connect_setup  # connect/setup.py, as serve.py and agent_setup see it
SETUP = os.path.join(ROOT, "connect", "setup.py")
NODE = shutil.which("node")
GIT = shutil.which("git")

# Made-up agents: they change only the made-up home's files, the way the real commands are documented to.
FAKE_CODEX = r'''#!PYTHON
import json, os, re, sys
args = sys.argv[1:]
config = os.path.join(os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex"), "config.toml")
with open(os.path.join(os.path.dirname(config), "calls.log"), "a") as log:
    log.write(json.dumps(args) + "\n")
if args[:1] == ["--version"]:
    print("codex-cli 0.150.0")
elif args[:2] == ["mcp", "add"]:
    name, rest = args[2], args[3:]
    text = open(config).read() if os.path.exists(config) else ""
    if rest[:1] == ["--url"]:
        text += '\n[mcp_servers.%s]\nurl = "%s"\n' % (name, rest[1])
    else:
        rest = rest[1:] if rest[:1] == ["--"] else rest
        text += "\n[mcp_servers.%s]\ncommand = %s\nargs = %s\n" % (name, json.dumps(rest[0]), json.dumps(rest[1:]))
    open(config, "w").write(text)
elif args[:2] == ["mcp", "remove"]:
    text = open(config).read()
    open(config, "w").write(re.sub(r"\n\[mcp_servers\." + re.escape(args[2]) + r"\][^\[]*", "", text))
else:
    sys.exit(2)
'''
FAKE_CLAUDE = r'''#!PYTHON
import json, os, sys
args = sys.argv[1:]
home = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~")
with open(os.path.join(home, "claude-calls.log"), "a") as log:
    log.write(json.dumps(args) + "\n")
path = os.path.join(home, ".claude.json")
data = json.load(open(path)) if os.path.exists(path) else {}
words = [a for a in args if a not in ("--scope", "user")]
if words[:2] == ["mcp", "add-json"]:
    data.setdefault("mcpServers", {})[words[2]] = json.loads(words[3])
elif words[:2] == ["mcp", "remove"]:
    data.get("mcpServers", {}).pop(words[2], None)
else:
    sys.exit(2)
json.dump(data, open(path, "w"))
'''


class Home(unittest.TestCase):
    """A made-up home: Claude Code's folder, Codex's if asked, made-up agents on PATH, and a data folder."""

    codex = True

    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.home = os.path.join(self.base, "home")
        self.data = os.path.join(self.base, "data")
        self.claude = os.path.join(self.home, ".claude")
        self.codex_dir = os.path.join(self.home, ".codex")
        self.bin = os.path.join(self.base, "bin")
        for folder in (self.claude, self.data, self.bin):
            os.makedirs(folder)
        if self.codex:
            os.makedirs(self.codex_dir)
            self.script("codex", FAKE_CODEX)
        self.script("claude", FAKE_CLAUDE)
        self.env = {"HOME": self.home, "USERPROFILE": self.home, "PATH": f"{self.bin}{os.pathsep}/usr/bin{os.pathsep}/bin",
                    "ARNHEIM_CLAUDE": os.path.join(self.bin, "claude"), "ARNHEIM_DATA": self.data,
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.path.join(self.home, ".gitconfig")}
        for p in (mock.patch.dict(os.environ, self.env), mock.patch.object(TOOL, "DATA", self.data)):
            p.start()
            self.addCleanup(p.stop)
        for name in ("CLAUDE_CONFIG_DIR", "CODEX_HOME"):  # the patch puts them back afterwards
            os.environ.pop(name, None)

    def script(self, name, text):
        path = os.path.join(self.bin, name)
        with open(path, "w") as handle:
            handle.write(text.replace("PYTHON", sys.executable, 1))
        os.chmod(path, 0o755)

    def project(self, name, files=None, git=True):
        folder = os.path.join(self.home, "code", name)
        os.makedirs(folder)
        for rel, text in (files or {}).items():
            self.put(os.path.join(folder, rel), text)
        if git and GIT:
            subprocess.run([GIT, "init", "-q", folder], check=True, env={**os.environ, **self.env})
        elif git:
            os.makedirs(os.path.join(folder, ".git"))
        return folder

    def put(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(text.encode("utf-8") if isinstance(text, str) else text)

    def read(self, path):
        with open(path, "rb") as handle:
            return handle.read()

    def floor(self, folder, **extra):
        """A building with a floor for the folder, as setup writes it."""
        path = os.path.join(self.data, "company.json")
        company = json.loads(self.read(path)) if os.path.exists(path) else {"company": "Test", "floors": []}
        company["floors"].append({"id": os.path.basename(folder), "label": os.path.basename(folder).title(), "folder": folder, **extra})
        self.put(path, json.dumps(company, indent=2) + "\n")

    def plan(self, *folders, checks=None):
        return agent_setup.plan(list(folders), TOOL, checks)

    def item(self, p, ident, n=0):
        return next(i for i in p["projects"][n]["items"] if i["id"] == ident)

    def everything(self, *folders, checks=None):
        return {"projects": [{"folder": f, "items": list(agent_setup.ITEMS), "check": (checks or {}).get(f)} for f in folders],
                "secrets": True, "mcp": True}

    def snapshot(self, *paths):
        """Every file under these paths (git's own folder left out, but its ignore file in), byte for byte."""
        out = {}
        for top in paths:
            if os.path.isfile(top):
                out[top] = self.read(top)
                continue
            for root, dirs, files in os.walk(top):
                dirs[:] = [d for d in dirs if d != ".git"]
                for f in files:
                    out[os.path.join(root, f)] = self.read(os.path.join(root, f))
                out[root] = None  # folders count too
            exclude = os.path.join(top, ".git", "info", "exclude")
            if os.path.isfile(exclude):
                out[exclude] = self.read(exclude)
        return out


class DetectTest(Home):
    def found(self, files, **kw):
        return agent_setup.detect(self.project("p", files, **kw))

    def test_npm_and_its_placeholder(self):
        f = self.found({"package.json": json.dumps({"scripts": {"test": "jest", "build": "tsc", "lint": "eslint ."}}), "package-lock.json": "{}",
                        "tsconfig.json": "{}", "src/a.ts": ""}, git=False)
        self.assertEqual((f["languages"], f["managers"], f["test"], f["build"], f["lint"]),
                         (["TypeScript"], ["npm"], ["npm", "test"], ["npm", "run", "build"], ["npm", "run", "lint"]))
        self.assertEqual(f["folders"], ["src"])
        placeholder = 'echo "Error: no test specified" && exit 1'
        shutil.rmtree(os.path.join(self.home, "code"))
        self.assertIsNone(self.found({"package.json": json.dumps({"scripts": {"test": placeholder}})}, git=False)["test"])

    def test_package_managers(self):
        for lock, want in (("pnpm-lock.yaml", ["pnpm", "test"]), ("yarn.lock", ["yarn", "test"]), ("bun.lockb", ["bun", "run", "test"])):
            shutil.rmtree(os.path.join(self.home, "code"), ignore_errors=True)
            self.assertEqual(self.found({"package.json": json.dumps({"scripts": {"test": "x"}}), lock: ""}, git=False)["test"], want)

    def test_python(self):
        f = self.found({"pyproject.toml": "[tool.pytest.ini_options]\n", "uv.lock": ""}, git=False)
        self.assertEqual((f["languages"], f["managers"], f["test"]), (["Python"], ["uv"], ["uv", "run", "pytest"]))
        shutil.rmtree(os.path.join(self.home, "code"))
        self.assertEqual(self.found({"requirements.txt": "", "pytest.ini": ""}, git=False)["test"], ["python3", "-m", "pytest"])
        shutil.rmtree(os.path.join(self.home, "code"))
        self.assertEqual(self.found({"setup.py": "", "tests/test_a.py": "import unittest\n"}, git=False)["test"],
                         ["python3", "-m", "unittest", "discover", "-s", "tests"])
        shutil.rmtree(os.path.join(self.home, "code"))
        self.assertIsNone(self.found({"requirements.txt": ""}, git=False)["test"])  # no tests it can be sure of: none

    def test_others(self):
        cases = [({"go.mod": ""}, ["go", "test", "./..."]), ({"Cargo.toml": ""}, ["cargo", "test"]), ({"Package.swift": ""}, ["swift", "test"]),
                 ({"build.gradle.kts": "", "gradlew": ""}, ["./gradlew", "test"]), ({"pom.xml": ""}, ["mvn", "test"]),
                 ({"Makefile": "build:\n\tcc a.c\ntest: build\n\t./t\n", "go.mod": ""}, ["make", "test"]),  # the project's own target first
                 ({"Gemfile": "", ".rspec": ""}, ["bundle", "exec", "rspec"]), ({"app.sln": ""}, ["dotnet", "test"]),
                 ({"CMakeLists.txt": ""}, None), ({}, None)]
        for files, want in cases:
            shutil.rmtree(os.path.join(self.home, "code"), ignore_errors=True)
            self.assertEqual(self.found(files, git=False)["test"], want, files)

    def test_agents_md_says_only_what_it_found(self):
        folder = self.project("p", {"go.mod": "", "cmd/main.go": "", "node_modules/x": "", ".hidden/x": ""}, git=False)
        text = agent_setup.agents_text("P", agent_setup.detect(folder))
        self.assertIn("- Language: Go", text)
        self.assertIn("- Main folders: `cmd/`", text)  # never node_modules or hidden folders
        self.assertIn("- Test: `go test ./...`", text)
        self.assertIn("Run `go test ./...` and say whether it passed", text)
        bare = agent_setup.agents_text("Q", agent_setup.detect(self.project("q", git=False)))
        self.assertNotIn("##", bare)  # nothing found: nothing made up


class InstructionsTest(Home):
    def apply(self, folder, items=("instructions",)):
        return agent_setup.apply({"projects": [{"folder": folder, "items": list(items)}]}, TOOL, say=lambda *_: None)

    def test_neither_file_writes_both(self):
        folder = self.project("a", {"go.mod": ""})
        item = self.item(self.plan(folder), "instructions")
        self.assertEqual([(os.path.basename(c["file"]), c["how"]) for c in item["changes"]], [("AGENTS.md", "new"), ("CLAUDE.md", "new")])
        self.apply(folder)
        self.assertEqual(self.read(os.path.join(folder, "CLAUDE.md")), b"@AGENTS.md\n")
        self.assertIn(b"go test ./...", self.read(os.path.join(folder, "AGENTS.md")))
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "done")

    def test_only_agents_md_adds_a_claude_md_that_brings_it_in(self):
        folder = self.project("a", {"AGENTS.md": "# Mine\n"})
        self.apply(folder)
        self.assertEqual(self.read(os.path.join(folder, "AGENTS.md")), b"# Mine\n")
        self.assertEqual(self.read(os.path.join(folder, "CLAUDE.md")), b"@AGENTS.md\n")

    def test_only_claude_md_changes_nothing_in_the_project(self):
        folder = self.project("a", {"CLAUDE.md": "# Mine\n\nNo emoji.\n"})
        config = os.path.join(self.codex_dir, "config.toml")
        self.put(config, 'model = "x"\n\n[mcp_servers.s]\ncommand = "s"\n')
        before = self.snapshot(folder)
        item = self.item(self.plan(folder), "instructions")
        self.assertEqual(item["changes"][0]["how"], "fallback")
        self.apply(folder)
        self.assertEqual(self.snapshot(folder), before)  # not a byte of the project changed
        text = self.read(config).decode()
        self.assertTrue(text.startswith(agent_setup.FALLBACK_NOTE + '\nproject_doc_fallback_filenames = ["CLAUDE.md"]\n\nmodel = "x"'), text)
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "done")
        if sys.version_info >= (3, 11):
            import tomllib
            self.assertEqual(tomllib.loads(text)["project_doc_fallback_filenames"], ["CLAUDE.md"])  # still TOML, key at the top level

    def test_a_fallback_list_of_your_own_gets_one_more_name(self):
        folder = self.project("a", {"CLAUDE.md": "x\n"})
        config = os.path.join(self.codex_dir, "config.toml")
        self.put(config, 'project_doc_fallback_filenames = ["TEAM.md"]  # mine\n[x]\ny = 1\n')
        self.apply(folder)
        self.assertEqual(self.read(config), b'project_doc_fallback_filenames = ["TEAM.md", "CLAUDE.md"]  # mine\n[x]\ny = 1\n')
        self.put(config, 'project_doc_fallback_filenames = [\n  "TEAM.md",\n]\n')  # over lines: left to you
        item = self.item(self.plan(folder), "instructions")
        self.assertEqual(item["state"], "none")

    def test_both_files_get_only_one_added_line(self):
        folder = self.project("a", {"AGENTS.md": "# Agents\n", "CLAUDE.md": "# Claude\nUse tabs."})
        item = self.item(self.plan(folder), "instructions")
        self.assertEqual(item["changes"][0]["how"], "append")
        self.apply(folder)
        self.assertEqual(self.read(os.path.join(folder, "CLAUDE.md")), b"# Claude\nUse tabs.\n\n@AGENTS.md\n")
        self.assertEqual(self.read(os.path.join(folder, "AGENTS.md")), b"# Agents\n")

    def test_one_that_already_brings_in_the_other_is_left(self):
        folder = self.project("a", {"AGENTS.md": "# A\n", "CLAUDE.md": "@AGENTS.md\n\nMore.\n"})
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "done")
        shutil.rmtree(folder)
        folder = self.project("a", {"AGENTS.md": "# A\n", "CLAUDE.md": "Not this: `@AGENTS.md`\n"})  # in code, no import
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "todo")

    def test_inner_claude_md(self):
        folder = self.project("a", {".claude/CLAUDE.md": "x\n"})
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "none")  # Codex can't read it there
        self.put(os.path.join(folder, "AGENTS.md"), "y\n")
        self.apply(folder)
        self.assertEqual(self.read(os.path.join(folder, ".claude", "CLAUDE.md")), b"x\n\n@../AGENTS.md\n")


class NoCodexTest(Home):
    codex = False

    def test_only_claude_md_without_codex_is_in_place(self):
        folder = self.project("a", {"CLAUDE.md": "x\n"})
        self.assertEqual(self.item(self.plan(folder), "instructions")["state"], "done")
        self.assertEqual(self.plan(folder)["mcp"]["state"], "none")  # nothing to share with


class CheckAllowSecretsTest(Home):
    def test_the_check_goes_on_the_floor(self):
        folder = self.project("a", {"package.json": json.dumps({"scripts": {"test": "vitest"}})})
        self.floor(folder)
        agent_setup.apply({"projects": [{"folder": folder, "items": ["check"]}]}, TOOL, say=lambda *_: None)
        floor = json.loads(self.read(os.path.join(self.data, "company.json")))["floors"][0]
        self.assertEqual(floor["check"], {"run": ["npm", "test"], "label": "The tests"})
        self.assertEqual(self.item(self.plan(folder), "check")["state"], "done")

    def test_a_check_you_type_wins_and_one_of_your_own_stays(self):
        folder = self.project("a", {"go.mod": ""})
        self.floor(folder)
        p = self.plan(folder, checks={folder: ["make", "check"]})
        self.assertEqual(self.item(p, "check")["run"], ["make", "check"])
        self.assertEqual(self.item(p, "allow")["rule"], "Bash(make check)")
        self.assertEqual(self.item(self.plan(folder, checks={folder: []}), "check")["state"], "none")  # typed empty: none
        shutil.rmtree(self.data)
        os.makedirs(self.data)
        self.floor(folder, check={"run": ["./ci.sh"]})
        p = self.plan(folder)
        self.assertEqual((self.item(p, "check")["state"], self.item(p, "check")["run"]), ("done", ["./ci.sh"]))

    def test_secrets_once_beside_your_settings(self):
        mine = {"model": "opus", "permissions": {"deny": ["Bash(rm *)"], "allow": ["Bash(ls)"]}, "hooks": {}}
        path = os.path.join(self.claude, "settings.json")
        self.put(path, json.dumps(mine, indent=4))
        agent_setup.apply({"projects": [], "secrets": True}, TOOL, say=lambda *_: None)
        got = json.loads(self.read(path))
        self.assertEqual(got["permissions"]["deny"], ["Bash(rm *)"] + agent_setup.DENY)
        self.assertEqual({k: got[k] for k in ("model", "hooks")}, {"model": "opus", "hooks": {}})
        self.assertEqual(got["permissions"]["allow"], ["Bash(ls)"])
        self.assertIn(b'\n    "model"', self.read(path))  # its indent kept
        for rule in ("Read(**/.env)", "Read(~/.ssh/**)", "Read(~/.aws/**)", "Read(**/*.pem)"):
            self.assertIn(rule, got["permissions"]["deny"])
        self.assertEqual(self.plan()["secrets"]["state"], "done")
        self.put(path, '{"permissions": "all"}')
        self.assertEqual(self.plan()["secrets"]["state"], "none")  # not as the docs show: left alone
        self.put(path, "{not json")
        self.assertEqual(self.plan()["secrets"]["state"], "none")

    @unittest.skipUnless(GIT, "needs git")
    def test_allow_list_is_one_exact_rule_kept_out_of_git(self):
        folder = self.project("a", {"package.json": json.dumps({"scripts": {"test": "jest"}})})
        self.floor(folder)
        agent_setup.apply({"projects": [{"folder": folder, "items": ["check", "allow"]}]}, TOOL, say=lambda *_: None)
        local = json.loads(self.read(os.path.join(folder, ".claude", "settings.local.json")))
        self.assertEqual(local, {"permissions": {"allow": ["Bash(npm test)"]}})
        ignored = subprocess.run([GIT, "-C", folder, "check-ignore", "-q", ".claude/settings.local.json"], env={**os.environ, **self.env})
        self.assertEqual(ignored.returncode, 0)  # never committed by accident
        self.assertEqual(self.item(self.plan(folder), "allow")["state"], "done")

    def test_only_plain_checks_run_without_asking(self):
        folder = self.project("a", {"pyproject.toml": "[tool.pytest.ini_options]\n", "uv.lock": ""}, git=False)
        self.assertEqual(self.item(self.plan(folder), "allow")["state"], "none")  # uv run can install: it keeps asking
        for words in (["npm", "publish"], ["rm", "-rf", "."], ["git", "push"], ["curl", "x"], ["npm", "install"]):
            self.assertEqual(self.item(self.plan(folder, checks={folder: words}), "allow")["state"], "none", words)
        self.assertEqual(self.item(self.plan(folder, checks={folder: ["pytest"]}), "allow")["state"], "todo")


class McpTest(Home):
    def setUp(self):
        super().setUp()
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"numStartups": 3, "mcpServers": {
            "docs": {"type": "stdio", "command": "npx", "args": ["-y", "docs-mcp"]},
            "keyed": {"type": "stdio", "command": "k", "env": {"API_KEY": "made-up"}},
            "remote": {"type": "http", "url": "https://mcp.example.com/mcp"}}}))
        self.config = os.path.join(self.codex_dir, "config.toml")
        self.put(self.config, '[mcp_servers.search]\ncommand = "uvx"\nargs = ["search-mcp"]\n\n'
                              '[mcp_servers.off]\ncommand = "x"\nenabled = false\n\n'
                              '[mcp_servers.tokened]\nurl = "https://t.example.com"\nbearer_token_env_var = "T"\n')

    def test_each_side_gets_the_other_keyless_servers(self):
        folder = self.project("a", {".mcp.json": json.dumps({"mcpServers": {"shared": {"command": "sh-mcp"}}})}, git=False)
        item = self.plan(folder)["mcp"]
        self.assertEqual(item["state"], "todo")
        self.assertEqual(sorted(r["name"] for r in item["to_codex"]), ["docs", "remote"])  # "shared" is one project's: it stays there
        self.assertEqual([r["name"] for r in item["to_claude"]], ["search"])
        self.assertEqual(sorted(r["name"] for r in item["by_hand"]), ["keyed", "tokened"])  # keys never copied
        lines = []
        agent_setup.apply({"projects": [], "mcp": True}, TOOL, say=lines.append)  # no project given: your user scope's servers
        text = self.read(self.config).decode()
        self.assertIn("[mcp_servers.docs]", text)
        self.assertIn('url = "https://mcp.example.com/mcp"', text)
        self.assertNotIn("keyed", text)
        self.assertNotIn("made-up", text)
        claude = json.loads(self.read(os.path.join(self.home, ".claude.json")))
        self.assertEqual(claude["mcpServers"]["search"], {"type": "stdio", "command": "uvx", "args": ["search-mcp"]})
        self.assertNotIn("tokened", claude["mcpServers"])
        self.assertNotIn("off", claude["mcpServers"])  # switched off in Codex: not shared
        calls = self.read(os.path.join(self.codex_dir, "calls.log")).decode()
        self.assertIn('["mcp", "add", "docs", "--", "npx", "-y", "docs-mcp"]', calls)
        self.assertIn('["mcp", "add", "remote", "--url", "https://mcp.example.com/mcp"]', calls)
        self.assertEqual(self.plan()["mcp"]["state"], "none")  # the keyed two stay yours, so not "the same"
        self.assertEqual(self.plan()["mcp"]["to_codex"] + self.plan()["mcp"]["to_claude"], [])

    def test_undo_takes_the_servers_out_again(self):
        claude_before = self.read(os.path.join(self.home, ".claude.json"))
        config_before = self.read(self.config)
        agent_setup.apply({"projects": [], "mcp": True}, TOOL, say=lambda *_: None)
        self.assertNotEqual(self.read(self.config), config_before)
        TOOL.undo(say=lambda *_: None, page=True)
        self.assertEqual(self.read(self.config), config_before)  # byte for byte
        self.assertEqual(json.loads(self.read(os.path.join(self.home, ".claude.json"))), json.loads(claude_before))
        self.assertFalse(os.path.exists(os.path.join(self.data, agent_setup.RECORD)))

    def test_a_changed_codex_config_loses_only_the_servers(self):
        agent_setup.apply({"projects": [], "mcp": True}, TOOL, say=lambda *_: None)
        with open(self.config, "a") as handle:
            handle.write('\n[projects."/x"]\ntrust_level = "trusted"\n')  # Codex wrote to it since
        agent_setup.undo(TOOL, say=lambda *_: None)
        text = self.read(self.config).decode()
        self.assertNotIn("[mcp_servers.docs]", text)
        self.assertIn('trust_level = "trusted"', text)
        self.assertIn("[mcp_servers.search]", text)


class UndoTest(Home):
    """Everything at once on a project with files of its own, then Undo: every file as it was, byte for byte."""

    def setUp(self):
        super().setUp()
        self.alpha = self.project("alpha", {"package.json": json.dumps({"scripts": {"test": "jest"}}), "src/a.js": ""})
        self.beta = self.project("beta", {"CLAUDE.md": "# Beta\r\nWindows line ends, no last one", "go.mod": ""})
        self.gamma = self.project("gamma", {"AGENTS.md": "# Gamma\n", "CLAUDE.md": "Mine.\n", "Cargo.toml": ""})
        for f in (self.alpha, self.beta, self.gamma):
            self.floor(f)
        self.settings = os.path.join(self.claude, "settings.json")
        self.put(self.settings, '{"model":"opus","permissions":{"deny":["Bash(rm *)"]}}')  # one line, as some keep it
        self.config = os.path.join(self.codex_dir, "config.toml")
        self.put(self.config, '﻿# mine\nmodel = "x"\n')
        self.put(os.path.join(self.home, ".claude.json"), json.dumps({"mcpServers": {"docs": {"command": "d"}}}))
        self.watched = (self.alpha, self.beta, self.gamma, self.settings, self.codex_dir, self.data)

    def test_everything_then_undo_is_byte_for_byte(self):
        before = self.snapshot(*self.watched)
        lines = []
        made = agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lines.append)
        self.assertGreater(made, 8, lines)
        self.assertNotEqual(self.snapshot(*self.watched), before)
        self.assertEqual(self.read(os.path.join(self.gamma, "CLAUDE.md")), b"Mine.\n\n@AGENTS.md\n")
        self.assertEqual(self.read(os.path.join(self.beta, "CLAUDE.md")), b"# Beta\r\nWindows line ends, no last one")  # never touched
        self.assertTrue(self.read(self.config).startswith("﻿# Arnheim".encode("utf-8")))  # the mark that starts it stays first
        lines = []
        agent_setup.undo(TOOL, say=lines.append)
        after = self.snapshot(*self.watched)
        after.pop(os.path.join(self.codex_dir, "calls.log"), None)
        self.assertEqual(after, before, lines)
        self.assertFalse(os.path.exists(os.path.join(self.alpha, ".claude")))  # the folder it made went too

    def test_the_record_is_kept_where_nothing_serves_it_and_only_you_can_read_it(self):
        agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lambda *_: None)
        path = os.path.join(self.data, agent_setup.RECORD)
        self.assertTrue(os.path.isfile(path))
        self.assertEqual(os.path.relpath(path, self.data).split(os.sep)[0], ".secrets")  # a hidden folder: serve.py refuses it
        self.assertFalse(os.path.exists(os.path.join(self.data, "agent-setup.json")))
        if os.name == "posix":
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            self.assertEqual(os.stat(os.path.dirname(path)).st_mode & 0o777, 0o700)

    def test_running_twice_changes_nothing(self):
        agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lambda *_: None)
        once = self.snapshot(*self.watched)
        record = self.read(os.path.join(self.data, agent_setup.RECORD))
        lines = []
        self.assertEqual(agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lines.append), 0, lines)
        again = self.snapshot(*self.watched)
        for snap in (once, again):
            snap.pop(os.path.join(self.codex_dir, "calls.log"), None)
        self.assertEqual(again, once)
        self.assertEqual(self.read(os.path.join(self.data, agent_setup.RECORD)), record)
        self.assertEqual(agent_setup.to_do(self.plan(self.alpha, self.beta, self.gamma)), [])

    def test_what_you_changed_since_stays(self):
        agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lambda *_: None)
        self.put(os.path.join(self.alpha, "AGENTS.md"), "# Alpha, in my words\n")  # yours now
        settings = json.loads(self.read(self.settings))
        settings["permissions"]["deny"].append("Read(./mine)")
        settings["theme"] = "dark"
        self.put(self.settings, json.dumps(settings))
        with open(os.path.join(self.gamma, "CLAUDE.md"), "a") as handle:
            handle.write("And this.\n")
        lines = []
        agent_setup.undo(TOOL, say=lines.append)
        self.assertEqual(self.read(os.path.join(self.alpha, "AGENTS.md")), b"# Alpha, in my words\n")
        self.assertFalse(os.path.exists(os.path.join(self.alpha, "CLAUDE.md")))
        got = json.loads(self.read(self.settings))
        self.assertEqual(got["permissions"]["deny"], ["Bash(rm *)", "Read(./mine)"])  # only the rules this added went
        self.assertEqual(got["theme"], "dark")
        self.assertEqual(self.read(os.path.join(self.gamma, "CLAUDE.md")), b"Mine.\nAnd this.\n")
        self.assertTrue(any("changed since" in line for line in lines), lines)

    def test_a_file_that_cant_be_written_takes_back_this_run(self):
        os.chmod(self.gamma, 0o555)  # gamma's folder can't be written
        self.addCleanup(os.chmod, self.gamma, 0o755)
        if os.access(self.gamma, os.W_OK):
            self.skipTest("running as a user who can write anywhere")
        before = self.snapshot(self.alpha, self.beta, self.settings, self.data)
        with self.assertRaises(TOOL.Refused) as said:
            agent_setup.apply(self.everything(self.alpha, self.beta, self.gamma), TOOL, say=lambda *_: None)
        self.assertIn("Nothing was changed", str(said.exception))
        self.assertEqual(self.snapshot(self.alpha, self.beta, self.settings, self.data), before)


class CommandLineTest(Home):
    def run_setup(self, *args, answers=""):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_CONFIG_DIR", "CODEX_HOME")}
        env.update(self.env)
        done = subprocess.run([sys.executable, SETUP, *args], input=answers, capture_output=True, text=True, env=env, timeout=120)
        return done.returncode, done.stdout + done.stderr

    def setUp(self):
        super().setUp()
        self.alpha = self.project("alpha", {"package.json": json.dumps({"scripts": {"test": "jest"}})})

    def test_yes_alone_never_changes_your_projects(self):
        before = self.snapshot(self.alpha)
        code, out = self.run_setup("--yes", "--folder", self.alpha)
        self.assertEqual(code, 0, out)
        self.assertIn("Set your agents up well too?", out)
        self.assertIn("python3 connect/setup.py --well", out)
        self.assertEqual(self.snapshot(self.alpha), before)

    def test_well_does_it_and_undo_takes_it_back(self):
        before = self.snapshot(self.alpha)
        code, out = self.run_setup("--yes", "--folder", self.alpha, "--well")
        self.assertEqual(code, 0, out)
        self.assertTrue(os.path.isfile(os.path.join(self.alpha, "AGENTS.md")), out)
        floor = json.loads(self.read(os.path.join(self.data, "company.json")))["floors"][0]
        self.assertEqual(floor["check"]["run"], ["npm", "test"])
        self.assertIn("Read(**/.env)", self.read(os.path.join(self.claude, "settings.json")).decode())
        code, again = self.run_setup("--yes", "--folder", self.alpha, "--well")
        self.assertIn("set up well in these projects already", again)
        code, out = self.run_setup("--undo")
        self.assertEqual(code, 0, out)
        self.assertIn("Setting your agents up well, taken back", out)
        self.assertEqual(self.snapshot(self.alpha), before)
        self.assertNotIn("check", json.loads(self.read(os.path.join(self.data, "company.json")))["floors"][0])

    def test_asked_once_and_no_leaves_it(self):
        code, out = self.run_setup("--folder", self.alpha, "--name", "Mine", answers="y\ny\nn\n")
        self.assertEqual(code, 0, out)
        self.assertIn("Set your agents up well too? [Y/n]", out)
        self.assertFalse(os.path.exists(os.path.join(self.alpha, "AGENTS.md")))
        code, out = self.run_setup("--folder", self.alpha, answers="y\n")  # set up already: only this is asked, yes
        self.assertTrue(os.path.exists(os.path.join(self.alpha, "AGENTS.md")), out)

    def test_no_hooks_and_no_well_leave_it(self):
        for flag in ("--no-hooks", "--no-well"):
            code, out = self.run_setup("--yes", "--folder", self.alpha, flag, "--well")
            self.assertEqual(code, 0, out)
            self.assertFalse(os.path.exists(os.path.join(self.alpha, "AGENTS.md")), flag)


class PageTest(Home):
    """serve.py's /setup/ for setting your agents up well: the plan, Connect with ticks, Settings' card and Undo."""

    def setUp(self):
        super().setUp()
        for patcher in (mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json")),
                        mock.patch.object(TOOL, "start_always", side_effect=AssertionError("never from the page"))):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.alpha = self.project("alpha", {"package.json": json.dumps({"scripts": {"test": "jest"}})})
        self.beta = self.project("beta", {"AGENTS.md": "# Beta\n", "go.mod": ""})
        for n, f in enumerate((self.alpha, self.beta)):
            self.put(os.path.join(self.claude, "projects", f"p{n}", "a.jsonl"), json.dumps({"cwd": f}) + "\n")

    def test_plan_then_connect_with_ticks(self):
        plan = serve.setup_plan(self.data)
        well = plan["well"]
        self.assertEqual([p["folder"] for p in well["projects"]], [p["folder"] for p in plan["projects"]])
        self.assertTrue(all(p["folder"].startswith("~/") for p in well["projects"]))  # shown as a person writes it
        alpha = next(p for p in well["projects"] if p["label"] == "Alpha")
        self.assertEqual([i["state"] for i in alpha["items"]], ["todo", "todo", "todo"])
        self.assertNotIn(self.home, json.dumps(well))  # no whole home path on the page
        ticks = {"projects": [{"folder": alpha["folder"], "items": ["instructions", "check"], "check": "npm run test:unit"},
                              {"folder": "~/code/beta", "items": ["instructions"], "check": None}],
                 "secrets": True, "mcp": False}
        code, answer = serve.setup_connect({"folders": [p["folder"] for p in plan["projects"]], "control": False, "well": ticks}, self.data)
        self.assertEqual(code, 200, answer)
        self.assertTrue(os.path.exists(os.path.join(self.alpha, "AGENTS.md")))
        self.assertFalse(os.path.exists(os.path.join(self.alpha, ".claude")))  # the allow list wasn't ticked
        self.assertEqual(self.read(os.path.join(self.beta, "CLAUDE.md")), b"@AGENTS.md\n")
        floors = {f["id"]: f for f in json.loads(self.read(os.path.join(self.data, "company.json")))["floors"]}
        self.assertEqual(floors["alpha"]["check"]["run"], ["npm", "run", "test:unit"])
        self.assertNotIn("check", floors["beta"])  # not ticked
        self.assertTrue(any("Wrote ~/code/alpha/AGENTS.md" in line for line in answer["lines"]), answer["lines"])
        code, undone = serve.setup_undo(self.data)
        self.assertEqual(code, 200)
        self.assertFalse(os.path.exists(os.path.join(self.alpha, "AGENTS.md")))
        self.assertFalse(os.path.exists(os.path.join(self.beta, "CLAUDE.md")))

    def test_bad_ticks_change_nothing(self):
        plan = serve.setup_plan(self.data)
        folders = [p["folder"] for p in plan["projects"]]
        for well in ({"projects": "x"}, {"projects": [{"folder": "~/elsewhere", "items": []}]},
                     {"projects": [{"folder": folders[0], "items": ["rm"]}]}, {"projects": [{"folder": folders[0], "check": "'open"}]},
                     {"projects": [], "secrets": "yes"}):
            code, answer = serve.setup_connect({"folders": folders, "control": False, "well": well}, self.data)
            self.assertEqual(code, 400, (well, answer))
        self.assertFalse(os.path.exists(os.path.join(self.data, "company.json")))

    def test_a_typed_folder_and_a_changed_check_are_planned_first(self):
        code, answer = serve.well_plan({"folders": ["~/code/alpha"], "checks": {"~/code/alpha": "make check"}}, self.data)
        self.assertEqual(code, 200, answer)
        items = {i["id"]: i for i in answer["well"]["projects"][0]["items"]}
        self.assertEqual(items["check"]["run"], "make check")
        self.assertEqual(items["allow"]["rule"], "Bash(make check)")
        self.assertEqual(serve.well_plan({"folders": ["/no/such/folder"]}, self.data)[0], 400)
        self.assertEqual(serve.well_plan({"folders": [self.home]}, self.data)[0], 400)  # the home folder is never a project
        self.assertEqual(serve.well_plan({"folders": "x"}, self.data)[0], 400)
        self.assertFalse(os.path.exists(os.path.join(self.alpha, "AGENTS.md")))  # a plan changes nothing

    def test_settings_card_sets_up_what_is_missing(self):
        serve.setup_connect({"folders": ["~/code/alpha", "~/code/beta"], "control": False}, self.data)  # connected, nothing more
        status = serve.well_status(self.data)["well"]
        self.assertEqual(sorted(p["label"] for p in status["projects"]), ["Alpha", "Beta"])
        code, answer = serve.well_apply({"projects": [{"folder": "~/code/alpha", "items": list(agent_setup.ITEMS)}], "secrets": True}, self.data)
        self.assertEqual(code, 200, answer)
        alpha = next(p for p in answer["well"]["projects"] if p["label"] == "Alpha")
        self.assertEqual({i["id"]: i["state"] for i in alpha["items"]}, {"instructions": "done", "check": "done", "allow": "done"})
        self.assertEqual(answer["well"]["secrets"]["state"], "done")
        code, again = serve.well_apply({"projects": [{"folder": "~/code/alpha", "items": list(agent_setup.ITEMS)}]}, self.data)
        self.assertEqual(again["lines"], ["Everything chosen was in place already: nothing changed."])
        self.assertEqual(serve.well_apply({"projects": [{"folder": "~/code/gamma", "items": []}]}, self.data)[0], 400)  # not a floor

    def test_only_this_computers_page_may_ask(self):
        class Handler:
            own_page = staticmethod(lambda: False)
            json_answer = staticmethod(lambda code, data: (code, data))
        for name, body in (("agents", None), ("well", b"{}"), ("agents", b"{}")):
            self.assertEqual(serve.Handler.setup_route(Handler, f"/setup/{name}", body)[0], 403)


@unittest.skipUnless(NODE, "needs Node")
class PageRulesTest(unittest.TestCase):
    SCRIPT = r"""
import { pathToFileURL } from 'node:url';
const w = await import(pathToFileURL(process.argv[1] + '/src/agent-setup.js').href);
const item = (id, state, extra = {}) => ({ id, state, says: `${id} ${state}`, changes: state === 'todo' ? [{ file: `~/a/${id}`, how: 'new', text: id }] : [], ...extra });
const well = {
  projects: [
    { folder: '~/a', label: 'A', items: [item('instructions', 'todo'), item('check', 'todo', { run: 'npm test' }), item('allow', 'todo')] },
    { folder: '~/b', label: 'B', items: [item('instructions', 'done'), item('check', 'done', { run: 'go test ./...' }), item('allow', 'none')] },
  ],
  secrets: item('secrets', 'todo'), mcp: item('mcp', 'done'),
};
const out = {};
const st = w.wellStart(well);
out.ticked = [...st.ticked].sort();
out.checks = { ...st.checks };
out.flags = [st.secrets, st.mcp];
st.ticked.delete('~/a|allow');
st.checks['~/a'] = ' npm run test:unit ';
out.request = w.wellRequest(well, st, ['~/a', '~/b']);
out.onlyB = w.wellRequest(well, st, ['~/b']);
out.changes = w.wellChanges(well, st, ['~/a']).map((c) => `${c.label} ${c.file} ${c.how}`);
out.ticks = [w.wellTicked(well, st, ['~/b']), w.wellTicked(well, { ...st, secrets: false }, ['~/b'])];
const fresh = { projects: [{ folder: '~/b', label: 'B', items: [item('instructions', 'done'), item('check', 'done'), item('allow', 'todo')] },
  { folder: '~/c', label: 'C', items: [item('instructions', 'todo')] }], mcp: item('mcp', 'todo') };
const merged = w.wellMerge(well, fresh, st);
out.merged = [merged.projects.map((p) => p.folder), merged.mcp.state, st.ticked.has('~/b|allow'), st.ticked.has('~/c|instructions'), st.ticked.has('~/a|allow')];
out.status = w.wellStatus(well).map((f) => [f.label, f.steps.map((s) => `${s.id}:${s.state}`).join(' ')]);
out.lines = w.wellStatus(well).map(w.wellLine);
out.missing = [w.wellMissing(well), w.wellMissing({ projects: [{ folder: '~/b', items: [item('check', 'done')] }], secrets: item('secrets', 'done'), mcp: item('mcp', 'none') })];
out.notes = w.wellNotes(well);
out.steps = w.WELL_STEPS.map((s) => s.label);
console.log(JSON.stringify(out));
"""

    def test_rules(self):
        done = subprocess.run([NODE, "--input-type=module", "-e", self.SCRIPT, ROOT], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertEqual(out["ticked"], ["~/a|allow", "~/a|check", "~/a|instructions"])
        self.assertEqual(out["checks"], {"~/a": "npm test", "~/b": "go test ./..."})
        self.assertEqual(out["flags"], [True, False])
        self.assertEqual(out["request"], {"projects": [{"folder": "~/a", "items": ["instructions", "check"], "check": "npm run test:unit"},
                                                       {"folder": "~/b", "items": [], "check": None}], "secrets": True, "mcp": False})
        self.assertEqual(out["onlyB"]["projects"], [{"folder": "~/b", "items": [], "check": None}])
        self.assertEqual(out["changes"], ["A ~/a/instructions A new file:", "A ~/a/check A new file:", "Every project ~/a/secrets A new file:"])
        self.assertEqual(out["ticks"], [True, False])
        self.assertEqual(out["merged"], [["~/a", "~/b", "~/c"], "done", True, True, False])  # MCP stays the whole plan's
        self.assertEqual(out["status"][1], ["B", "instructions:done check:done secrets:todo allow:none mcp:done"])
        self.assertEqual(out["lines"][1], "In place: Shared instructions, Check, MCP the same. Can be set up: Secrets guarded. Not set up: Allow list.")
        self.assertEqual(out["missing"], [True, False])
        self.assertEqual(out["notes"], [{"who": "B", "says": "allow none"}])
        self.assertEqual(out["steps"], ["Shared instructions", "Check", "Secrets guarded", "Allow list", "MCP the same"])


class PageWiringTest(unittest.TestCase):
    """The page draws the section and the card, and their words follow the page's rules (no em dashes, no " - ")."""

    def test_wiring_and_words(self):
        with open(os.path.join(ROOT, "src", "demo.js"), encoding="utf-8") as handle:
            demo = handle.read()
        for needle in ("from './agent-setup.js'", "wellSection(f)", "wellCard()", "'Set your agents up well'", "'Your agents\\' setup'",
                       "'Show the exact changes'", "'Set up what is missing'", "well: wellRequest("):
            self.assertIn(needle, demo)
        with open(os.path.join(ROOT, "src", "agent-setup.js"), encoding="utf-8") as handle:
            page = [handle.read()]
        start = demo.index("/* ---------- set your agents up well")
        page.append(demo[start:demo.index("// The commands you allowed for good", start)])
        for text in page:
            self.assertNotIn("\u2014", text)
            for line in text.splitlines():
                quoted = [part for n, part in enumerate(line.split("'")) if n % 2] + [part for n, part in enumerate(line.split("`")) if n % 2]
                self.assertFalse(any(" - " in q for q in quoted), line)
        # What the page shows from the server: every step's words, as a plan gives them.
        with open(os.path.join(ROOT, "connect", "agent_setup.py"), encoding="utf-8") as handle:
            server = handle.read()
        self.assertNotIn("\u2014", server)
        for said in __import__("re").findall(r'says=f?"([^"]*)"', server):
            self.assertNotIn(" - ", said)



@unittest.skipUnless(GIT, "needs git")
class SubfolderProjectTest(unittest.TestCase):
    def test_the_ignore_line_matches_a_project_below_the_repository_s_top(self):
        base = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, base, True)
        quiet = os.path.join(base, "gitconfig")  # this computer's own git settings could ignore the file already
        open(quiet, "w").close()
        env = {"HOME": base, "XDG_CONFIG_HOME": base, "GIT_CONFIG_GLOBAL": quiet, "GIT_CONFIG_NOSYSTEM": "1"}
        patch = mock.patch.dict(os.environ, env)
        patch.start()
        self.addCleanup(patch.stop)
        subprocess.run(["git", "init", "-q", base], check=True)
        web = os.path.join(base, "apps", "web")
        os.makedirs(os.path.join(web, ".claude"))
        exclude = agent_setup.exclude_path(web)  # planned for a project in a subfolder, not only at the top
        self.assertEqual(os.path.realpath(exclude), os.path.realpath(os.path.join(base, ".git", "info", "exclude")))
        line = agent_setup.exclude_line(web)
        self.assertEqual(line, "/apps/web/.claude/settings.local.json")
        with open(os.path.join(base, ".git", "info", "exclude"), "a") as handle:
            handle.write(line + "\n")
        done = subprocess.run(["git", "-C", web, "check-ignore", "-q", ".claude/settings.local.json"])
        self.assertEqual(done.returncode, 0)  # git leaves that file out now
        self.assertEqual(agent_setup.exclude_line(base), "/.claude/settings.local.json")
        self.assertIsNone(agent_setup.exclude_path(web))  # ignored now: nothing more to plan


class CodexSettingsWithoutTomllibTest(unittest.TestCase):
    """Python 3.10 and older have no tomllib: Codex's MCP servers are still read, and only plain ones are shared."""

    def test_plain_servers_are_read_and_the_rest_left_with_the_reason(self):
        text = "\n".join([
            'model = "x"', "[mcp_servers.search]", 'command = "uvx"', 'args = ["search-mcp", "--fast"]  # the usual',
            "[mcp_servers.docs]", 'command = "npx"', "args = [", '  "-y",', '  "docs-mcp",', "]",
            "[mcp_servers.github]", 'command = "gh-mcp"', 'env = { GITHUB_TOKEN = "x" }',
            "[mcp_servers.web]", 'url = "https://example.test/mcp"',
            "[mcp_servers.keys]", 'command = "k"', "[mcp_servers.keys.env]", 'API_KEY = "x"',
            "[mcp_servers.odd]", "command = 'literal'", "[other]", 'command = "no"', ""])
        servers = agent_setup.simple_servers(text)
        plain = {name: agent_setup.keyless(spec) for name, spec in servers.items()}
        self.assertEqual(plain, {"search": {"command": "uvx", "args": ["search-mcp", "--fast"]},
                                 "docs": {"command": "npx", "args": ["-y", "docs-mcp"]}, "github": None,
                                 "web": {"url": "https://example.test/mcp"}, "keys": None, "odd": None})
        self.assertIn("never copies", agent_setup.why_by_hand(servers["keys"]))
        self.assertIn("couldn't read", agent_setup.why_by_hand(servers["odd"]))
        self.assertNotIn("other", servers)  # only Codex's MCP tables

    def test_a_key_in_a_servers_words_or_address_is_never_copied(self):
        import secrets as random_words
        import string
        made_up = lambda n: "".join(random_words.choice(string.ascii_letters + string.digits) for _ in range(n))
        for spec in ({"command": "npx", "args": ["-y", "x-mcp", "--api-key", "sk-" + made_up(40)]},
                     {"command": "npx", "args": ["--token=ghp_" + made_up(36)]},
                     {"url": "https://mcp.example.test/sse?token=ghp_" + made_up(36)}):
            self.assertIsNone(agent_setup.keyless(spec), spec)
            self.assertIn("never copies", agent_setup.why_by_hand(spec))
        self.assertEqual(agent_setup.keyless({"command": "npx", "args": ["-y", "docs-mcp"]}), {"command": "npx", "args": ["-y", "docs-mcp"]})

if __name__ == "__main__":
    unittest.main()
