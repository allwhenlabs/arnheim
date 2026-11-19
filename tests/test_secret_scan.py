"""The secrets check (connect/secret_scan.py, src/secret-check.js): passwords and tokens saved in agents' settings in
each floor's folder, how far git has taken each, and the fixes: Take it out (with Undo, byte for byte) and Keep git out
of it. Every secret here is made up as the tests run, from pieces, so nothing shaped like a real one is ever written
in the repository; every project is a fake one in a temporary folder, with a fake home folder and its own git settings.

The page's rules are JavaScript, so those tests run under Node.js and are skipped where Node isn't installed.
Run from the repository's folder: python3 -m unittest discover tests
"""
import argparse
import base64
import http.client
import json
import os
import random
import shutil
import stat
import string
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from connect import secret_scan as scan  # noqa: E402
from connect import switches  # noqa: E402
import serve  # noqa: E402

NODE = shutil.which("node")
R = random.Random(20261119)
ALNUM = string.ascii_letters + string.digits


def made_up(n, alphabet=ALNUM):
    return "".join(R.choice(alphabet) for _ in range(n))


def token(kind):
    """A made-up secret of a known shape, built from pieces as the test runs."""
    return {
        "anthropic": lambda: "sk-" + "ant-" + "api03-" + made_up(90),
        "openai": lambda: "sk-" + "proj-" + made_up(60),
        "github": lambda: "gh" + "p_" + made_up(36),
        "github-fine": lambda: "github" + "_pat_" + made_up(82, ALNUM + "_"),
        "gitlab": lambda: "gl" + "pat-" + made_up(20),
        "slack": lambda: "xo" + "xb-" + made_up(12, string.digits) + "-" + made_up(24),
        "aws": lambda: "AK" + "IA" + made_up(16, string.ascii_uppercase + string.digits),
        "google": lambda: "AI" + "za" + made_up(35),
        "stripe": lambda: "sk" + "_live_" + made_up(24),
        "huggingface": lambda: "hf" + "_" + made_up(34),
        "npm": lambda: "np" + "m_" + made_up(36),
        "jwt": lambda: "ey" + "J" + made_up(20) + ".ey" + "J" + made_up(30) + "." + made_up(30),
    }[kind]()


def kinds(text):
    return [h.kind for h in scan.text_hits(text)]


# ---------- finding them ----------

class DetectTest(unittest.TestCase):
    def test_known_formats(self):
        for kind, words in (("anthropic", "An Anthropic API key"), ("openai", "An OpenAI API key"), ("github", "A GitHub token"),
                            ("github-fine", "A GitHub token"), ("gitlab", "A GitLab token"), ("slack", "A Slack token"),
                            ("aws", "An AWS access key"), ("google", "A Google API key"), ("stripe", "A Stripe key"),
                            ("huggingface", "A Hugging Face token"), ("npm", "An npm token"), ("jwt", "A signed login token (JWT)")):
            secret = token(kind)
            hits = scan.text_hits("Bash(curl -H 'X-Key: {}' https://api.test/v1)".format(secret))
            self.assertEqual([(h.words, h.value) for h in hits], [(words, secret)], kind)

    def test_other_shapes(self):
        password = "Kite" + made_up(8)
        long_value = made_up(40)
        login = base64.b64encode(("user:" + password).encode()).decode()
        cases = [
            ("Bash(curl -u admin:{} https://api.test)".format(password), "A password", password),
            ("Bash(git clone https://me:{}@git.test/kite.git)".format(password), "A password in an address", password),
            ("Bash(kitectl --password {} deploy)".format(password), "A password", password),
            ("Bash(kitectl --api-key={} deploy)".format(long_value), "A token", long_value),
            ("Bash(DB_PASSWORD={} docker compose up)".format(password), "A password", password),
            ("Bash(curl -H 'Authorization: Bearer {}' https://api.test)".format(long_value), "A bearer token", long_value),
            ("Bash(curl -H 'Authorization: Basic {}' https://api.test)".format(login), "A password in a login header", login),
            ("Bash(kitectl sync {})".format(long_value), "Something that looks like a key", long_value),
        ]
        for text, words, value in cases:
            self.assertEqual([(h.words, h.value) for h in scan.text_hits(text)], [(words, value)], text)
        block = "-----BEGIN " + "OPENSSH PRIVATE KEY-----\n" + made_up(64) + "\n-----END " + "OPENSSH PRIVATE KEY-----"
        self.assertEqual(kinds(block), ["private-key"])

    def test_in_each_kind_of_file(self):
        github, password, long_value = token("github"), "Kite" + made_up(8), made_up(40)
        settings = json.dumps({"permissions": {"allow": ["Bash(npm test)", "Bash(GH_TOKEN={} gh pr list)".format(github)]},
                               "env": {"DATABASE_PASSWORD": password, "ANTHROPIC_MODEL": "claude-sonnet-4-5"}}, indent=2)
        found = [(h.words, line, path) for h, line, path in scan.json_hits(settings)]
        self.assertEqual(found, [("A GitHub token", 5, ("permissions", "allow", 1)), ("A password", 9, ("env", "DATABASE_PASSWORD"))])
        mcp = json.dumps({"mcpServers": {"kite": {"command": "kite-mcp", "args": ["--api-key", long_value]},
                                         "web": {"type": "http", "url": "https://mcp.test", "headers": {"X-Api-Key": long_value[::-1]}}}})
        self.assertEqual([h.value for h, _, _ in scan.json_hits(mcp)], [long_value, long_value[::-1]])
        toml = ('model = "gpt-5"\n[mcp_servers.kite.env]\nKITE_TOKEN = "{}"\n[mcp_servers.web]\n'
                'http_headers = {{ "Authorization" = "Bearer {}" }}\n'.format(long_value, long_value[::-1]))
        self.assertEqual([(h.words, line) for h, line, _ in scan.lines_hits(toml)], [("A token", 3), ("A bearer token", 5)])
        rules = 'prefix_rule(\n    pattern = ["kitectl", "--token", "{}"],\n    decision = "allow",\n)\n'.format(long_value)
        self.assertEqual([(h.words, line) for h, line, _ in scan.lines_hits(rules)], [("A token", 2)])

    def test_no_false_alarms(self):
        quiet = [
            "Bash(npm test)", "Bash(git log --oneline -20)", "Bash(git show 3f2a9c1d8e7b6a5f4e3d2c1b0a9f8e7d6c5b4a39)",
            'Bash(curl -H "Authorization: Bearer ${GITHUB_TOKEN}" https://api.github.com)', "Bash(export API_KEY=$API_KEY)",
            "Read(//Users/sample/code/kite/node_modules/some-package/dist/index.js)", "WebFetch(domain:docs.anthropic.com)",
            "mcp__github__create_pull_request", "Bash(psql postgres://kite:${DB_PASSWORD}@localhost/kite)",
            "Bash(gh auth login --with-token:*)", "Bash(npm run build -- --token-file ./token.txt)",
            "Bash(docker run -e POSTGRES_PASSWORD=$POSTGRES_PASSWORD postgres)", "PASSWORD=<your password>",
            "sk-learn-model-classifier-for-the-reading-app", "This basic approach works fine for everyone",
            "ThisIsALongCamelCaseIdentifierWithNoDigitsAtAll2", "feature/add-login-page-with-remember-me-checkbox",
            "Bash(git checkout -b fix-the-bookmark-that-jumps-back-a-page-2024)", "op://Private/GitHub/token",
            "123e4567-e89b-12d3-a456-426614174000", "Bash(npm install @modelcontextprotocol/server-github@2025.4.8)",
            "sha512-Zm9vYmFyYmF6cXV4cXV1eGNvcmdlZ3JhdWx0Z2FycGx5d2FsZG9AbG9uZ2VyMTIz",
            "Bash(python3 -m pytest tests/test_reading_streak_badge_ComputesCorrectly2.py)",
            "Bash(rg -n getUserAccountSettingsFromServerV2Response src/)", "claude-opus-4-1-20250805",
            "Bash(TOKEN_LIMIT=4000 npm test)", "Bash(MAX_TOKENS=8192 python3 run.py)", "Bash(curl -u $USER:$PASS https://api.test)",
            "Bash(kitectl --token $KITE_TOKEN)", "Bash(kitectl --api-key=${KEY})", "Bash(export SECRET_NAME=prod-db-password)",
            "Bash(aws secretsmanager get-secret-value --secret-id prod/db)", "Bash(ssh git@github.com)",
            "Bash(curl -H 'X-Api-Key: your-api-key-here' https://api.test)", "Bash(kitectl --password changeme)",
            "AppDelegateWillFinishLaunchingWithOptions64Bit", "com.kiteapps.reader.BookmarkSyncService2",
        ]
        for text in quiet:
            self.assertEqual(kinds(text), [], text)
        settings = json.dumps({
            "$schema": "https://json.schemastore.org/claude-code-settings.json",
            "permissions": {"allow": quiet[:12], "deny": ["Read(./.env)", "Read(./secrets/**)"]},
            "env": {"ANTHROPIC_MODEL": "claude-sonnet-4-5", "MAX_THINKING_TOKENS": "8000", "GITHUB_TOKEN": "${GITHUB_TOKEN}"},
            "apiKeyHelper": "~/bin/get-key.sh", "statusLine": {"type": "command", "command": "python3 /opt/arnheim/connect/usage.py"},
            "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "python3 /opt/arnheim/connect/claude_code.py", "timeout": 1200}]}]},
            "mcpServers": {"kite": {"command": "npx", "args": ["-y", "@kite/mcp", "--token", "${KITE_TOKEN}"], "env": {"KITE_TOKEN": "${KITE_TOKEN}"}}},
        }, indent=2)
        self.assertEqual(scan.json_hits(settings), [])
        toml = ('model = "gpt-5"\nmodel_reasoning_effort = "high"\n[model_providers.kite]\nenv_key = "KITE_API_KEY"\n'
                '[mcp_servers.web]\nbearer_token_env_var = "WEB_TOKEN"\nenv_http_headers = { "X-Api-Key" = "WEB_API_KEY" }\n'
                '# a comment that doesn\'t say anything secret\n')
        self.assertEqual(scan.lines_hits(toml), [])

    def test_hints_never_give_it_away(self):
        github = token("github")
        hit = scan.text_hits("Bash(GH_TOKEN={} gh pr list)".format(github))[0]
        self.assertEqual(scan.hint(hit), "ghp_…" + github[-4:])
        password = "Kite" + made_up(12)
        hit = scan.text_hits("Bash(kitectl --password {} deploy)".format(password))[0]
        self.assertEqual(scan.hint(hit), "16 characters")  # a password: only how long it is
        for kind in ("anthropic", "openai", "aws", "jwt"):
            secret = token(kind)
            shown = scan.hint(scan.text_hits(secret)[0])
            self.assertLessEqual(len(shown.split("…")[1]), 4, kind)
            self.assertNotIn(secret[len(secret) // 2:len(secret) // 2 + 6], shown, kind)


# ---------- git, with a fake home and fake projects ----------

class Projects(unittest.TestCase):
    """A fake home folder with its own git settings, a data folder, and fake projects as floors."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = os.path.join(self.tmp, "home")
        os.makedirs(self.home)
        with open(os.path.join(self.home, ".gitconfig"), "w") as handle:
            handle.write("[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n[user]\n\tname = Test\n\temail = test@example.com\n")
        env = {"HOME": self.home, "XDG_CONFIG_HOME": os.path.join(self.home, ".config"), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.path.join(self.home, ".gitconfig")}
        patcher = mock.patch.dict(os.environ, env)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.data = os.path.join(self.tmp, "data")
        os.makedirs(self.data)
        self.floors = []

    def git(self, folder, *words):
        done = subprocess.run(["git", *words], cwd=folder, capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def project(self, name, git=True):
        folder = os.path.join(self.tmp, "code", name)
        os.makedirs(folder)
        if git:
            self.git(folder, "init", "-q")
        self.floors.append({"id": name, "label": name.title(), "folder": folder})
        with open(os.path.join(self.data, "company.json"), "w") as handle:
            json.dump({"company": "Made-up Kites", "floors": self.floors}, handle)
        return folder

    def write(self, folder, rel, text):
        path = os.path.join(folder, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", newline="") as handle:
            handle.write(text)
        return path

    def allow(self, folder, secret, rel=".claude/settings.local.json"):
        return self.write(folder, rel, json.dumps({"permissions": {"allow": ["Bash(npm test)", "Bash(GH_TOKEN={} gh pr list)".format(secret)]}}, indent=2) + "\n")

    def found(self):
        return {f["floor"]: f for f in scan.check(self.data)["findings"]}


class GitStateTest(Projects):
    def test_each_state(self):
        secrets = {name: token("github") for name in ("open", "ignored", "tracked", "committed", "pushed", "outside")}
        self.allow(self.project("open"), secrets["open"])
        ignored = self.project("ignored")
        self.write(ignored, ".gitignore", ".claude/settings.local.json\n")
        self.allow(ignored, secrets["ignored"])
        tracked = self.project("tracked")
        self.write(tracked, ".claude/settings.local.json", "{}\n")
        self.git(tracked, "add", "-A")
        self.git(tracked, "commit", "-qm", "Settings")
        self.allow(tracked, secrets["tracked"])  # changed since, not committed
        committed = self.project("committed")
        self.allow(committed, secrets["committed"])
        self.git(committed, "add", "-A")
        self.git(committed, "commit", "-qm", "Settings")
        pushed = self.project("pushed")
        self.allow(pushed, secrets["pushed"])
        self.git(pushed, "add", "-A")
        self.git(pushed, "commit", "-qm", "Settings")
        remote = os.path.join(self.tmp, "remote.git")
        self.git(self.tmp, "init", "-q", "--bare", remote)
        self.git(pushed, "remote", "add", "origin", remote)
        self.git(pushed, "push", "-q", "origin", "main")
        self.allow(self.project("outside", git=False), secrets["outside"])

        got = self.found()
        self.assertEqual({k: (f["state"], f["tracked"], f["fix"]["exclude"]) for k, f in got.items()}, {
            "open": ("open", False, True), "ignored": ("ignored", False, False), "tracked": ("open", True, False),
            "committed": ("committed", True, False), "pushed": ("pushed", True, False), "outside": ("outside", False, False)})
        self.assertEqual(got["open"]["says"], "A GitHub token is saved in an agent's allow list in .claude/settings.local.json, "
                                              "and git would commit that file.")
        self.assertIn("in a commit not pushed yet. Take it out before you push", got["committed"]["says"])
        self.assertIn("Change that secret now", got["pushed"]["says"])
        self.assertIn("Git ignores that file", got["ignored"]["says"])
        self.assertIn("The folder isn't in git", got["outside"]["says"])
        self.assertEqual([f["state"] for f in scan.check(self.data)["findings"]],  # worst first
                         ["pushed", "committed", "open", "open", "ignored", "outside"])
        self.assertTrue(all(f["line"] == 5 and f["file"] == ".claude/settings.local.json" for f in got.values()))

        self.git(pushed, "remote", "set-url", "origin", "https://github.com/made-up/kites.git")
        f = self.found()["pushed"]
        self.assertEqual(f["remote"], "GitHub")
        self.assertIn("pushed to GitHub. Change that secret now: taking it out here doesn't take it out of the history on GitHub.", f["says"])

    def test_claude_code_s_file_at_the_repository_s_top(self):
        top = self.project("kites")
        app = os.path.join(top, "app")
        os.makedirs(app)
        self.floors[-1]["folder"] = app  # the floor is a folder inside the repository
        with open(os.path.join(self.data, "company.json"), "w") as handle:
            json.dump({"company": "Made-up Kites", "floors": self.floors}, handle)
        self.allow(top, token("github"))
        f = self.found()["kites"]
        self.assertEqual(f["file"], "kites/.claude/settings.local.json")

    def test_the_secret_is_never_kept_or_shown(self):
        secrets = [token("github"), token("anthropic"), "Kite" + made_up(10)]
        folder = self.project("kites")
        self.write(folder, ".claude/settings.local.json", json.dumps({"permissions": {"allow": [
            "Bash(GH_TOKEN={} gh pr list)".format(secrets[0]), "Bash(curl -u admin:{} https://api.test)".format(secrets[2])]}}))
        self.write(folder, ".mcp.json", json.dumps({"mcpServers": {"claude": {"command": "x", "env": {"ANTHROPIC_API_KEY": secrets[1]}}}}))
        found = scan.check(self.data)["findings"]
        self.assertEqual(len(found), 3)
        with open(os.path.join(self.data, ".secrets", "found.json"), "rb") as handle:
            kept = handle.read()
        shown = json.dumps(scan.listing(self.data)).encode()
        for secret in secrets:
            self.assertNotIn(secret.encode(), kept)
            self.assertNotIn(secret.encode(), shown)
            self.assertNotIn(secret[-12:-4].encode(), kept)  # nothing of it but the start its kind always has, and its last four
        self.assertNotIn(folder.encode(), shown)  # the page gets the file as the floor names it, not the whole path
        self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.data, ".secrets", "found.json")).st_mode), 0o600)
        for folder in (".secrets", os.path.join(".secrets", "undo")):  # readable by you alone
            self.assertEqual(stat.S_IMODE(os.stat(os.path.join(self.data, folder)).st_mode), 0o700)


# ---------- the fixes ----------

class FixTest(Projects):
    def test_take_it_out_and_undo_byte_for_byte(self):
        folder = self.project("kites")
        secret = token("github")
        original = ('{\r\n\t"permissions" : {\r\n\t\t"allow": [ "Bash(npm test)",\r\n\t\t\t"Bash(GH_TOKEN=' + secret + ' gh pr list)",'
                    '\r\n\t\t\t"Bash(git status)"  ],\r\n\t\t"deny": []\r\n\t},\r\n\t"model":"sonnet"   \r\n}\r\n')
        path = self.write(folder, ".claude/settings.local.json", original)
        os.chmod(path, 0o640)
        f = self.found()["kites"]
        words, uid = scan.take_out(f["id"], self.data)
        self.assertIn("Taken out of .claude/settings.local.json", words)
        with open(path, "rb") as handle:
            now = handle.read().decode()
        self.assertNotIn(secret, now)
        self.assertEqual(json.loads(now), {"permissions": {"allow": ["Bash(npm test)", "Bash(git status)"], "deny": []}, "model": "sonnet"})
        self.assertEqual(now, original.replace('"Bash(GH_TOKEN=' + secret + ' gh pr list)",\r\n\t\t\t', ""))  # every other byte kept
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o640)
        copy = os.path.join(self.data, ".secrets", "undo", uid + ".kept")
        self.assertEqual(stat.S_IMODE(os.stat(copy).st_mode), 0o600)
        self.assertEqual(self.found(), {})
        self.assertEqual([t["says"] for t in scan.taken(self.data)], ["A GitHub token was taken out of .claude/settings.local.json."])
        self.assertEqual(scan.undo(uid, self.data), "Put back: .claude/settings.local.json is as it was.")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), original.encode())
        self.assertFalse(os.path.exists(copy))
        self.assertEqual(scan.taken(self.data), [])
        self.assertIn("kites", self.found())

    def test_undo_never_undoes_a_later_change(self):
        folder = self.project("kites")
        path = self.allow(folder, token("github"))
        _, uid = scan.take_out(self.found()["kites"]["id"], self.data)
        with open(path, "a") as handle:
            handle.write(" ")
        with open(path, "rb") as handle:
            changed = handle.read()
        with self.assertRaises(scan.Refused):
            scan.undo(uid, self.data)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), changed)
        self.assertEqual(scan.forget(uid, self.data), "The copy is deleted, so that can't be undone now.")
        self.assertEqual(os.listdir(os.path.join(self.data, ".secrets", "undo")), [])

    def test_only_the_entries_holding_it(self):
        folder = self.project("kites")
        long_value = made_up(40)
        path = self.write(folder, ".mcp.json", json.dumps({"mcpServers": {
            "kite": {"command": "kite-mcp", "args": ["serve", "--api-key", long_value, "--verbose"], "env": {"KITE_HOME": "/opt/kite", "KITE_SECRET": long_value}},
            "web": {"type": "http", "url": "https://mcp.test"}}}, indent=2))
        found = scan.check(self.data)["findings"]
        self.assertEqual(len(found), 1)  # one secret, in two places
        self.assertEqual(found[0]["count"], 2)
        scan.take_out(found[0]["id"], self.data)
        with open(path) as handle:
            self.assertEqual(json.load(handle), {"mcpServers": {
                "kite": {"command": "kite-mcp", "args": ["serve", "--verbose"], "env": {"KITE_HOME": "/opt/kite"}},
                "web": {"type": "http", "url": "https://mcp.test"}}})

    def test_codex_s_files(self):
        folder = self.project("kites")
        long_value, other = made_up(40), made_up(40)
        toml = self.write(folder, ".codex/config.toml", 'model = "gpt-5"\n\n[mcp_servers.kite.env]\nKITE_TOKEN = "{}"\nKITE_HOME = "/opt/kite"\n'.format(long_value))
        rules = self.write(folder, ".codex/rules/default.rules", 'prefix_rule(pattern = ["npm", "test"])\n\nprefix_rule(\n    pattern = ["kitectl", "--token", "{}"],\n'
                                                                  '    decision = "allow",\n)\nprefix_rule(pattern = ["git", "status"])\n'.format(other))
        found = {f["file"]: f for f in scan.check(self.data)["findings"]}
        self.assertEqual(found[".codex/config.toml"]["place"], "Codex's settings")
        self.assertEqual(found[".codex/rules/default.rules"]["place"], "Codex's command rules")
        for f in found.values():
            scan.take_out(f["id"], self.data)
        with open(toml) as handle:
            self.assertEqual(handle.read(), 'model = "gpt-5"\n\n[mcp_servers.kite.env]\nKITE_HOME = "/opt/kite"\n')
        with open(rules) as handle:
            self.assertEqual(handle.read(), 'prefix_rule(pattern = ["npm", "test"])\n\nprefix_rule(pattern = ["git", "status"])\n')

    def test_never_leaves_a_hook_or_a_server_broken(self):
        folder = self.project("kites")
        gh = token("github")
        self.write(folder, ".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": "curl -H 'Authorization: Bearer {}' https://hooks.example.test".format(gh)}]}]}}, indent=2))
        other = token("github")
        self.write(folder, ".mcp.json", json.dumps({"mcpServers": {"web": {"type": "http", "url": "https://mcp.example.test/sse?token=" + other}}}, indent=2))
        third = made_up(40)
        self.write(folder, ".codex/config.toml", '[mcp_servers.kite]\ncommand = "kite-mcp"\nargs = ["serve", "--api-key", "{}"]\n'.format(third))
        found = scan.check(self.data)["findings"]
        self.assertEqual(len(found), 3)
        def read(path):
            with open(path, "rb") as handle:
                return handle.read()
        for f in found:
            self.assertFalse(f["fix"]["out"], f["file"])  # the button isn't offered
            before = read(f["path"])
            with self.assertRaises(scan.Refused):  # and the server refuses a crafted press
                scan.take_out(f["id"], self.data)
            self.assertEqual(read(f["path"]), before)

    def test_a_linked_folder_is_never_written_through(self):
        folder = self.project("kites")
        elsewhere = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, elsewhere, True)
        self.allow(elsewhere, token("github"))
        os.symlink(os.path.join(elsewhere, ".claude"), os.path.join(folder, ".claude"))
        found = scan.check(self.data)["findings"]
        self.assertEqual(len(found), 1)
        self.assertFalse(found[0]["fix"]["out"])
        with self.assertRaises(scan.Refused):
            scan.take_out(found[0]["id"], self.data)

    def test_keep_git_out_of_it_and_undo(self):
        folder = self.project("kites")
        self.write(folder, "README.md", "Kites\n")
        self.git(folder, "add", "README.md")
        self.git(folder, "commit", "-qm", "First")
        exclude = os.path.join(folder, ".git", "info", "exclude")
        before = None
        if os.path.exists(exclude):
            with open(exclude, "rb") as handle:
                before = handle.read()
        self.allow(folder, token("github"))
        f = self.found()["kites"]
        words, uid = scan.keep_git_out(f["id"], self.data)
        self.assertIn("git now leaves .claude/settings.local.json out", words)
        self.assertEqual(self.git(folder, "status", "--porcelain"), "")  # no tracked file changed, and the file is out of sight
        f = self.found()["kites"]
        self.assertEqual((f["state"], f["fix"]["exclude"]), ("ignored", False))
        self.assertEqual(scan.undo(uid, self.data), "Put back: git no longer leaves .claude/settings.local.json out.")
        if before is None:
            self.assertFalse(os.path.exists(exclude))
        else:
            with open(exclude, "rb") as handle:
                self.assertEqual(handle.read(), before)
        self.assertEqual(self.found()["kites"]["state"], "open")

    def test_keep_git_out_only_where_it_works(self):
        folder = self.project("kites")
        self.allow(folder, token("github"))
        self.git(folder, "add", "-A")
        self.git(folder, "commit", "-qm", "Settings")
        f = self.found()["kites"]
        with self.assertRaises(scan.Refused) as said:
            scan.keep_git_out(f["id"], self.data)
        self.assertIn("git already tracks", str(said.exception))
        with self.assertRaises(scan.Refused):
            scan.take_out("0" * 20, self.data)  # not one of those found
        with self.assertRaises(scan.Refused):
            scan.undo("../../etc/passwd", self.data)

    def test_a_pushed_secret_is_still_to_change(self):
        folder = self.project("kites")
        self.allow(folder, token("github"))
        self.git(folder, "add", "-A")
        self.git(folder, "commit", "-qm", "Settings")
        remote = os.path.join(self.tmp, "remote.git")
        self.git(self.tmp, "init", "-q", "--bare", remote)
        self.git(folder, "remote", "add", "origin", remote)
        self.git(folder, "push", "-q", "origin", "main")
        words, _ = scan.take_out(self.found()["kites"]["id"], self.data)
        self.assertIn("Change that secret now: it is still in the history you pushed.", words)
        self.assertEqual(scan.taken(self.data)[0]["remind"], "Change that secret now: it is still in the history you pushed.")


# ---------- serve.py's /secrets/ ----------

def started(**given):
    words = {"control": False, "no_control": False, "brain": False, "routines": False, "pings": False, "no_git": False}
    return argparse.Namespace(**{**words, **given})


class RouteTest(Projects):
    def setUp(self):
        super().setUp()
        patcher = mock.patch.object(serve, "SAVED", os.path.join(self.data, "serve.json"))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = serve.Server(("127.0.0.1", 0), serve.Handler)
        self.port = self.server.server_address[1]
        self.server.board = serve.Switchboard(started(), None, None)
        self.server.board.server = self.server
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)

    def ask(self, method, path, body=None, headers=None, host=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        try:
            conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
            conn.putheader("Host", host or "127.0.0.1:{}".format(self.port))
            for name, value in (headers or {}).items():
                conn.putheader(name, value)
            raw = json.dumps(body).encode() if body is not None else b""
            if method == "POST":
                conn.putheader("Content-Length", str(len(raw)))
            conn.endheaders(raw if method == "POST" else None)
            reply = conn.getresponse()
            raw = reply.read()
            try:
                return reply.status, json.loads(raw or b"{}"), raw
            except ValueError:
                return reply.status, {}, raw
        finally:
            conn.close()

    def post(self, name, body, token=None, origin=True):
        headers = {"Content-Type": "application/json"}
        if origin:
            headers["Origin"] = "http://127.0.0.1:{}".format(self.port)
        if token:
            headers["X-Arnheim-Switches"] = token
        return self.ask("POST", "/secrets/" + name, body, headers)

    def test_look_fix_and_undo_from_the_page(self):
        folder = self.project("kites")
        secret = token("github")
        path = self.allow(folder, secret)
        with open(path, "rb") as handle:
            original = handle.read()
        scan.check(self.data)
        status, got, raw = self.ask("GET", "/secrets/")
        self.assertEqual(status, 200)
        self.assertTrue(got["on"])
        token_ = got["token"]
        [f] = got["findings"]
        self.assertNotIn("path", f)
        self.assertNotIn(secret.encode(), raw)
        self.assertEqual(self.post("out", {"id": f["id"]})[0], 403)  # no token
        self.assertEqual(self.post("out", {"id": f["id"]}, "guess")[0], 403)
        self.assertEqual(self.post("out", {"id": f["id"]}, token_, origin=False)[0], 403)  # not from its own page
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        status, got, raw = self.post("out", {"id": f["id"]}, token_)
        self.assertEqual(status, 200, got)
        self.assertEqual(got["findings"], [])
        self.assertNotIn(secret.encode(), raw)
        status, got, _ = self.post("undo", {"undo": got["undo"]}, token_)
        self.assertEqual(status, 200, got)
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), original)
        self.assertEqual(self.post("check", {}, token_)[1]["said"], "Checked: 1 secret in your agents' settings.")

    def test_only_this_computer_s_own_page(self):
        self.server.lan = True
        self.assertEqual(self.ask("GET", "/secrets/", host="192.168.1.5:{}".format(self.port))[0], 403)
        self.assertEqual(self.ask("GET", "/secrets/", headers={"X-Forwarded-For": "100.64.0.2"})[0], 403)
        self.assertEqual(self.ask("GET", "/data/.secrets/found.json")[0], 404)  # never served as a file

    def test_switched_off(self):
        self.allow(self.project("kites"), token("github"))
        scan.check(self.data)
        switches.save("secrets", False, self.data)
        status, got, _ = self.ask("GET", "/secrets/")
        self.assertEqual((status, got["on"], got["findings"]), (200, False, []))
        self.assertEqual(self.post("check", {}, got["token"])[0], 409)


# ---------- the switch, the page's rules and the made-up company ----------

class SwitchAndSampleTest(unittest.TestCase):
    def test_the_switch(self):
        self.assertIn("secrets", switches.NAMES)
        self.assertTrue(switches.DEFAULTS["secrets"])
        row = next(s for s in switches.SWITCHES if s[0] == "secrets")
        self.assertNotIn("—", row[2] + row[3])
        self.assertNotIn(" - ", row[2] + row[3])

    def test_the_made_up_company_shows_one(self):
        with open(os.path.join(ROOT, "sample", "work.json"), encoding="utf-8") as handle:
            work = json.load(handle)
        with open(os.path.join(ROOT, "sample", "company.json"), encoding="utf-8") as handle:
            floors = {f.get("project") or f["label"] for f in json.load(handle)["floors"]}
        self.assertEqual(len(work["secrets"]), 1)
        for f in work["secrets"]:
            self.assertIn(f["project"], floors)
            self.assertEqual(f["says"], scan.said(f["what"], f["place"], f["file"], f["state"], f["remote"]))
            self.assertEqual(scan.text_hits(json.dumps(f)), [])  # its hint is no secret

    def test_words_people_read(self):
        with open(os.path.join(ROOT, "src", "secret-check.js"), encoding="utf-8") as handle:
            text = handle.read()
        with open(os.path.join(ROOT, "connect", "secret_scan.py"), encoding="utf-8") as handle:
            text += handle.read()
        self.assertNotIn("—", text)
        for state in scan.ORDER:
            self.assertNotIn(" - ", scan.said("A token", "an agent's allow list", ".mcp.json", state, "GitHub"))


SCRIPT = """
import { pathToFileURL } from 'node:url';
const { healthOf, healthChip, sayHealth } = await import(pathToFileURL(process.argv[1] + '/src/health.js').href);
const { secretsIn } = await import(pathToFileURL(process.argv[1] + '/src/secret-check.js').href);
const secrets = JSON.parse(process.argv[2]);
const floors = ['Kitefield', 'Lantern', 'Studio'].map((p) => ({ project: p, label: p }));
const each = floors.map((f) => { const h = healthOf(f.project, { secrets }); return { state: h.state, chip: healthChip(h), problems: h.problems.map((p) => [p.kind, p.line, p.job]) }; });
console.log(JSON.stringify({ each, said: sayHealth(floors, { secrets }), order: secretsIn(secrets).map((f) => f.state) }));
"""


@unittest.skipUnless(NODE, "Node.js isn't installed")
class PageTest(unittest.TestCase):
    def test_health_counts_them(self):
        secrets = [
            {"id": "b", "project": "Lantern", "state": "ignored", "says": "A token is saved in Codex's settings in .codex/config.toml. Git ignores that file."},
            {"id": "a", "project": "Kitefield", "state": "open", "says": "A GitHub token is saved in an agent's allow list in .claude/settings.local.json, and git would commit that file."},
            {"id": "c", "project": "Studio"},  # not whole: left out
        ]
        done = subprocess.run([NODE, "--input-type=module", "-e", SCRIPT, ROOT, json.dumps(secrets)], capture_output=True, text=True, timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        kite, lantern, studio = out["each"]
        self.assertEqual((kite["state"], kite["chip"]), ("bad", {"text": "One thing to fix", "kind": "failed"}))
        self.assertEqual(kite["problems"], [["secret", secrets[1]["says"], None]])  # no agent is sent: it would read the secret
        self.assertEqual((lantern["state"], lantern["chip"]), ("warn", {"text": "A secret in its settings", "kind": "needs"}))
        self.assertEqual((studio["state"], studio["chip"]), ("good", None))
        self.assertIn("Kitefield: A GitHub token is saved", out["said"])
        self.assertEqual(out["order"], ["open", "ignored"])


if __name__ == "__main__":
    unittest.main()
