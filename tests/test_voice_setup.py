"""Setting up the voice (voice/install.py, python3 serve.py --set-up-voice): it finds a Python from 3.10 to
3.12, says the disk it takes and asks, then makes .voice, installs Kokoro and Whisper and fetches the models,
in that order, and carries on after a stop. Nothing real is installed or downloaded: the Pythons here are
stand-ins that write down what they were asked and answer as the real ones do. Each test works in a
temporary folder.

Run from the repository's folder: python3 -m unittest discover tests
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from voice import install  # noqa: E402

# A stand-in Python: writes down each command, and answers the version question, venv, pip and the worker.
STAND_IN = r'''
import json, os, shutil, sys
log = os.environ["FAKE_LOG"]
me = os.path.abspath(sys.argv[1])  # the stand-in's own name, as its wrapper gives it
args = sys.argv[2:]
with open(log, "a") as out:
    out.write(json.dumps([os.path.basename(os.path.dirname(me)) + "/" + os.path.basename(me)] + args) + "\n")
version = json.load(open(me + ".version")) if os.path.exists(me + ".version") else [3, 12]
if args[:1] == ["-c"]:
    print(json.dumps({"version": version, "executable": me, "venv": not os.path.exists(me + ".novenv")}))
elif args[:2] == ["-I", "-c"]:
    sys.exit(0 if os.path.exists(os.path.join(os.path.dirname(me), "installed")) else 1)
elif args[:2] == ["-m", "venv"]:
    if os.environ.get("FAKE_NO_VENV"):
        sys.exit(1)  # as Debian's Python does without python3-venv
    bin_ = os.path.join(args[2], "bin")
    os.makedirs(bin_, exist_ok=True)
    for name in ("python", "python.py"):
        shutil.copy(os.path.join(os.path.dirname(me), name if name.endswith(".py") else os.path.basename(me)), os.path.join(bin_, name))
elif args[:3] == ["-m", "pip", "install"]:
    if os.environ.get("FAKE_PIP_FAILS"):
        sys.exit(1)
    open(os.path.join(os.path.dirname(me), "installed"), "w").close()
elif args[:1] == ["-I"] and args[1].endswith("worker.py"):
    assert os.environ.get("ARNHEIM_VOICE_FETCH") == "1"
    print(json.dumps({"ok": True, "ready": True, "voices": ["af_heart", "bm_george"], "hear": True, "rate": 24000}))
'''


@unittest.skipIf(os.name == "nt", "the stand-in Pythons are shell scripts")
class VoiceSetupTest(unittest.TestCase):
    def setUp(self):
        self.base = os.path.realpath(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.base, True)
        self.bin = os.path.join(self.base, "bin")
        os.makedirs(self.bin)
        self.folder = os.path.join(self.base, "arnheim", ".voice")
        os.makedirs(os.path.dirname(self.folder))
        self.log = os.path.join(self.base, "log.jsonl")
        os.environ["FAKE_LOG"] = self.log
        self.addCleanup(os.environ.pop, "FAKE_LOG", None)
        with open(os.path.join(self.bin, "python.py"), "w") as handle:
            handle.write(STAND_IN)
        self.free = 50e9
        real = install.free_bytes
        install.free_bytes = lambda folder: self.free
        self.addCleanup(setattr, install, "free_bytes", real)

    def wrapper(self, path):
        with open(path, "w") as handle:
            handle.write(f'#!/bin/sh\nexec "{sys.executable}" "$(dirname "$0")/python.py" "$0" "$@"\n')
        os.chmod(path, 0o755)

    def python(self, name, version=(3, 12)):
        path = os.path.join(self.bin, name)
        self.wrapper(path)
        with open(path + ".version", "w") as handle:
            json.dump(list(version), handle)
        return path

    def run_it(self, *argv, system="Darwin", answer=True):
        asked = []
        out = io.StringIO()
        with redirect_stdout(out):
            code = install.main(list(argv), folder=self.folder, path=self.bin, system=system,
                                ask=lambda q: asked.append(q) or answer)
        return code, out.getvalue(), asked

    def commands(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as handle:
            return [json.loads(line) for line in handle]

    def test_set_up_in_order(self):
        self.python("python3.13", (3, 13))  # too new: passed over
        self.python("python3.11", (3, 11))
        code, said, asked = self.run_it()
        self.assertEqual(code, 0, said)
        self.assertEqual(len(asked), 1)
        self.assertIn("about 1.5 GB of disk", said)
        self.assertIn("50 GB free", said)
        self.assertIn("Python 3.11", said)
        did = [c for c in self.commands() if c[1:2] != ["-c"]]  # leave out the version questions
        self.assertEqual(did[0], ["bin/python3.11", "-m", "venv", self.folder])
        self.assertEqual(did[1], ["bin/python", "-m", "pip", "install", "kokoro", "openai-whisper"])
        self.assertEqual(did[2][:2], ["bin/python", "-I"])
        self.assertTrue(did[2][2].endswith(os.path.join("voice", "worker.py")))
        self.assertEqual(len(did), 3)
        self.assertIn("Step 3 of 3", said)
        self.assertIn("The voice is ready: 2 voices, and listening", said)
        self.assertTrue(os.access(install.venv_python(self.folder), os.X_OK))  # where voice/bridge.py looks

        # Run again: it is there, so only the models are checked.
        os.remove(self.log)
        code, said, asked = self.run_it()
        self.assertEqual((code, asked), (0, []))
        self.assertIn("installed already", said)
        self.assertEqual([c[1:3] for c in self.commands() if c[1:2] != ["-c"]], [["-I", "-c"], ["-I", install.WORKER]])

    def test_linux_gets_pytorch_without_graphics_libraries_and_speak_only(self):
        self.python("python3.12")
        code, said, _ = self.run_it("--speak-only", system="Linux")
        self.assertEqual(code, 0, said)
        pips = [c[1:] for c in self.commands() if c[1:3] == ["-m", "pip"]]
        self.assertEqual(pips, [["-m", "pip", "install", "torch", "--index-url", install.TORCH_CPU], ["-m", "pip", "install", "kokoro"]])

    def test_asks_first_and_no_changes_nothing(self):
        self.python("python3.12")
        code, said, asked = self.run_it(answer=False)
        self.assertEqual(code, 1)
        self.assertIn("Nothing was changed", said)
        self.assertFalse(os.path.exists(self.folder))
        self.assertTrue(all(c[1:2] == ["-c"] for c in self.commands()))  # it only asked versions

    def test_too_little_disk_stops_before_anything(self):
        self.python("python3.12")
        self.free = 1.5e9
        code, said, asked = self.run_it("--yes")
        self.assertEqual((code, asked), (1, []))
        self.assertIn("1.5 GB free", said)
        self.assertIn("so it stops here", said)
        self.assertFalse(os.path.exists(self.folder))

    def test_no_suitable_python_says_how_to_get_one(self):
        self.python("python3.13", (3, 13))
        code, said, _ = self.run_it("--yes")
        self.assertEqual(code, 1)
        self.assertIn("Python 3.10, 3.11 or 3.12", said)
        self.assertIn("brew install python@3.12", said)
        self.assertFalse(os.path.exists(self.folder))

    def test_uv_fetches_one_when_there_is_none(self):
        self.wrapper(os.path.join(self.bin, "stand-in"))  # not a name it looks for: only uv can make .voice
        uv = os.path.join(self.bin, "uv")
        with open(uv, "w") as handle:
            handle.write('#!/bin/sh\necho "[\\"uv\\", \\"$1\\", \\"$2\\", \\"$3\\", \\"$4\\"]" >> "$FAKE_LOG"\n'
                         'exec "$(dirname "$0")/stand-in" -m venv "$5"\n')
        os.chmod(uv, 0o755)
        code, said, _ = self.run_it("--yes")
        self.assertEqual(code, 0, said)
        self.assertIn("through uv", said)
        self.assertEqual(self.commands()[0], ["uv", "venv", "--seed", "--python", "3.12"])

    def test_a_failed_step_says_which_and_carries_on_next_time(self):
        self.python("python3.12")
        os.environ["FAKE_PIP_FAILS"] = "1"
        try:
            code, said, _ = self.run_it("--yes", system="Linux")
        finally:
            os.environ.pop("FAKE_PIP_FAILS")
        self.assertEqual(code, 1)
        self.assertIn("Step 2 of 4 didn't work", said)
        self.assertIn("Run it again to carry on", said)
        os.remove(self.log)
        code, said, _ = self.run_it("--yes", system="Linux")  # .voice is there: it isn't made again
        self.assertEqual(code, 0, said)
        self.assertNotIn(["-m", "venv"], [c[1:3] for c in self.commands()])
        self.assertIn("Step 3 of 3", said)

    def test_a_python_without_venv_on_linux_says_what_to_install(self):
        self.python("python3.12")
        os.environ["FAKE_NO_VENV"] = "1"
        try:
            code, said, _ = self.run_it("--yes", system="Linux")
        finally:
            os.environ.pop("FAKE_NO_VENV")
        self.assertEqual(code, 1)
        self.assertIn("sudo apt install python3-venv", said)

    def test_a_python_without_its_venv_part_goes_through_uv_or_says_what_to_install(self):
        open(self.python("python3.12") + ".novenv", "w").close()  # Ubuntu's, before python3.12-venv
        code, said, _ = self.run_it("--yes", system="Linux")
        self.assertEqual(code, 1)
        self.assertIn("sudo apt install python3.12-venv", said)
        self.assertFalse(os.path.exists(self.folder))
        self.wrapper(os.path.join(self.bin, "stand-in"))
        with open(os.path.join(self.bin, "uv"), "w") as handle:
            handle.write('#!/bin/sh\nexec "$(dirname "$0")/stand-in" -m venv "$5"\n')
        os.chmod(os.path.join(self.bin, "uv"), 0o755)
        code, said, _ = self.run_it("--yes", system="Linux")
        self.assertEqual(code, 0, said)
        self.assertIn("through uv", said)

    def test_an_old_voice_folder_is_left_alone(self):
        os.makedirs(os.path.join(self.folder, "bin"))
        old = self.python("python3.9", (3, 9))
        shutil.copy(old, os.path.join(self.folder, "bin", "python"))
        shutil.copy(old + ".version", os.path.join(self.folder, "bin", "python.version"))
        shutil.copy(os.path.join(self.bin, "python.py"), os.path.join(self.folder, "bin", "python.py"))
        code, said, _ = self.run_it("--yes")
        self.assertEqual(code, 1)
        self.assertIn("doesn't work with the voice (Python 3.9)", said)
        self.assertTrue(os.path.exists(os.path.join(self.folder, "bin", "python")))  # never deleted for you


if __name__ == "__main__":
    unittest.main()
