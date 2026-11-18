#!/usr/bin/env python3
"""Gives this computer Arnheim's voice (README, "Voice"): python3 serve.py --set-up-voice

The walk's people speak with Kokoro (Apache 2.0) and listen with Whisper (MIT), open models that run on
this computer, not online. They need a Python from 3.10 to 3.12 in a folder of their own, .voice, beside
serve.py, which is where voice/bridge.py looks. This finds such a Python (or has uv fetch one), says how
much disk the voice takes and how much is free, and asks. Then it makes .voice, installs Kokoro and Whisper
into it, and downloads their models once: Kokoro's into Hugging Face's own folder (~/.cache/huggingface),
Whisper's into .voice. A stopped or failed run carries on where it stopped when run again. To take the
voice out, delete .voice.

  python3 serve.py --set-up-voice            asks first, then sets it up
  python3 voice/install.py --yes             the same, without asking
  python3 voice/install.py --speak-only      speaking only, without Whisper

Each command it runs is a list of fixed words, without a shell. Standard library only.
"""
import argparse
import json
import os
import platform
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FOLDER = os.path.join(os.path.dirname(HERE), ".voice")
WORKER = os.path.join(HERE, "worker.py")
GOOD = ((3, 10), (3, 11), (3, 12))  # Kokoro doesn't install on newer Pythons yet
NEED_GB = {"Linux": 3.2}  # the voice on disk, models included, measured: 3.2 GB on Linux (Whisper brings Triton there)
NEED_ELSE_GB = 1.5  # and on a Mac
MODELS_MB = 470  # the models, downloaded once
SPARE_GB = 1.0  # left free after it, so the computer isn't left full
TORCH_CPU = "https://download.pytorch.org/whl/cpu"  # PyTorch without the graphics card libraries, on Linux
PROBE = ("import importlib.util, json, sys, venv; print(json.dumps({'version': list(sys.version_info[:2]), "
         "'executable': sys.executable, 'venv': importlib.util.find_spec('ensurepip') is not None}))")
QUIET = {"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONUTF8": "1"}


def venv_python(folder):
    return os.path.join(folder, "Scripts", "python.exe") if os.name == "nt" else os.path.join(folder, "bin", "python")


def probe(argv, whole=False):
    """The version of the Python that argv starts, and its own path, or (None, None); whole, also whether it
    can make a venv with pip in it (Debian and Ubuntu leave that part out until python3-venv is installed)."""
    try:
        done = subprocess.run(argv + ["-c", PROBE], capture_output=True, text=True, timeout=60)
        got = json.loads(done.stdout.strip().splitlines()[-1])
        version = tuple(got["version"])
    except (OSError, ValueError, IndexError, KeyError, TypeError, subprocess.TimeoutExpired):
        return (None, None, False) if whole else (None, None)
    if done.returncode:
        return (None, None, False) if whole else (None, None)
    return (version, got.get("executable"), got.get("venv", True) is not False) if whole else (version, got.get("executable"))


def candidates(path=None):
    """The ways to start a Python that may suit, best first. path limits the search to that PATH (tests)."""
    found = [] if path is not None else [[sys.executable]]
    for version in ("3.12", "3.11", "3.10"):
        named = shutil.which("python" + version, path=path)
        if named:
            found.append([named])
    launcher = shutil.which("py", path=path) if os.name == "nt" else None  # Windows' launcher
    if launcher:
        found += [[launcher, "-" + version] for version in ("3.12", "3.11", "3.10")]
    return found


def find_uv(path=None):
    """uv, where its own installer puts it too (~/.local/bin, or ~/.cargo/bin before), in case that isn't on
    PATH yet. path limits the search to that PATH (tests)."""
    found = shutil.which("uv", path=path)
    if found or path is not None:
        return found
    home = os.path.expanduser("~")
    for folder in (os.path.join(home, ".local", "bin"), os.path.join(home, ".cargo", "bin")):
        found = shutil.which("uv", path=folder)
        if found:
            return found
    return None


def find_python(path=None):
    """A Python from 3.10 to 3.12 on this computer that can make a venv, by its own path, and its version;
    or (None, None, the version of one that could if its venv part were installed)."""
    lacking = None
    for argv in candidates(path):
        version, executable, venv = probe(argv, whole=True)
        if version in GOOD and executable:
            if venv:
                return executable, version, None
            lacking = lacking or version
    return None, None, lacking


def free_bytes(folder):
    while folder and not os.path.isdir(folder):
        folder = os.path.dirname(folder)
    return shutil.disk_usage(folder or ".").free


def gb(size):
    n = size / 1e9
    return f"{n:.1f}" if n < 10 else f"{n:.0f}"


def ask_yes(question):
    """Enter is yes. The end of the input counts as no."""
    try:
        said = input(question).strip().lower()
    except EOFError:
        print()
        return False
    return not said or said.startswith("y")


def run_step(argv, env=None, worker=False, quiet=False):
    """Runs one step where you can see it, or, quiet, with the libraries' notes kept back unless it fails.
    (worked, the worker's answer or why not)."""
    try:
        if not worker:
            done = subprocess.run(argv, env=dict(os.environ, **QUIET, **(env or {})))
            return done.returncode == 0, f"it ended with code {done.returncode}"
        # The worker answers on stdout with one line: "ready": true once the models are in place.
        done = subprocess.run(argv, env=dict(os.environ, **QUIET, **(env or {})), cwd=HERE, stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE if quiet else None, text=True, errors="replace")
    except OSError as error:
        return False, error.strerror or str(error)
    lines = [line for line in (done.stdout or "").splitlines() if line.strip().startswith("{")]
    try:
        head = json.loads(lines[0]) if lines else {}
    except ValueError:
        head = {}
    if head.get("ready"):
        return True, head
    if quiet and done.stderr:  # what the libraries said, now that it matters
        print("\n".join(done.stderr.strip().splitlines()[-8:]), flush=True)
    return False, head.get("error") or f"it ended with code {done.returncode}"


def plan(folder, maker, system, speak_only, installed=False):
    """The steps, in order: (what it does, the command, its environment, whether it is the worker)."""
    py = venv_python(folder)
    steps = []
    if maker:
        steps.append(("Making .voice, a Python of the voice's own", maker, None, False))
    if not installed:
        if system == "Linux":
            steps.append(("Installing PyTorch without the graphics card libraries, which are several GB",
                          [py, "-m", "pip", "install", "torch", "--index-url", TORCH_CPU], None, False))
        steps.append(("Installing Kokoro" + ("" if speak_only else " and Whisper") + ". This takes a few minutes",
                      [py, "-m", "pip", "install", "kokoro"] + ([] if speak_only else ["openai-whisper"]), None, False))
    steps.append((f"Downloading the models, about {MODELS_MB} MB, once" if not installed else "Checking the models",
                  [py, "-I", WORKER], {"ARNHEIM_VOICE_FETCH": "1"}, True))
    return steps


def main(argv=None, folder=None, path=None, system=None, ask=None):
    parser = argparse.ArgumentParser(prog="python3 serve.py --set-up-voice", description="Gives this computer Arnheim's voice.")
    parser.add_argument("--yes", action="store_true", help="set it up without asking")
    parser.add_argument("--speak-only", action="store_true", help="speaking only, without Whisper's listening")
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)
    folder = folder or FOLDER
    system = system or platform.system()
    ask = ask or ask_yes
    print("Arnheim's voice: the walk's people speak with Kokoro and listen with Whisper, open models that run on "
          "this computer, not online.", flush=True)
    if os.environ.get("ARNHEIM_VOICE_PYTHON"):
        print("ARNHEIM_VOICE_PYTHON is set, so Arnheim speaks with that Python, not this one. This sets up .voice "
              "anyway; it counts once that is unset.", flush=True)

    py = venv_python(folder)
    maker = None
    installed = False
    if os.path.exists(py):
        version, _ = probe([py])
        if version not in GOOD:
            print(f"There is a .voice here already, but it doesn't work with the voice "
                  f"({'Python ' + '.'.join(map(str, version)) if version else 'its Python does not start'}). "
                  f"Delete the folder {folder} and run this again.", flush=True)
            return 1
        needs = "import kokoro" + ("" if args.speak_only else ", whisper")
        try:
            installed = subprocess.run([py, "-I", "-c", needs], capture_output=True, timeout=300).returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            installed = False
        where = f"The .voice already here (Python {'.'.join(map(str, version))})"
    else:
        python, version, lacking = find_python(path)
        uv = None if python else find_uv(path)
        if python:
            maker = [python, "-m", "venv", folder]
            where = f"Python {'.'.join(map(str, version))} ({python})"
        elif uv:
            maker = [uv, "venv", "--seed", "--python", "3.12", folder]
            where = "Python 3.12 through uv, which fetches it if this computer hasn't got it"
        elif lacking:
            named = "python" + ".".join(map(str, lacking))
            print(f"Python {'.'.join(map(str, lacking))} is here, but without the part that makes a Python of the voice's own. "
                  f"Add it with: sudo apt install {named}-venv (or install uv), then run this again.", flush=True)
            return 1
        else:
            print("It needs Python 3.10, 3.11 or 3.12, and this computer has none (newer ones can't run it yet). "
                  "Get Python 3.12 from https://www.python.org/downloads/ "
                  + ("(or: brew install python@3.12) " if system == "Darwin" else
                     "(or: sudo apt install python3.12 python3.12-venv) " if system == "Linux" else "")
                  + "and run this again. Your own Python stays as it is.", flush=True)
            return 1

    if installed:
        print(f"Kokoro{'' if args.speak_only else ' and Whisper'} are installed already. Checking the models...", flush=True)
        ok, got = run_step(plan(folder, None, system, args.speak_only, installed=True)[0][1], {"ARNHEIM_VOICE_FETCH": "1"},
                           worker=True, quiet=True)
        return finish(ok, got, 1, 1)

    free = free_bytes(folder)
    need = NEED_GB.get(system, NEED_ELSE_GB)
    print(f"It takes about {need} GB of disk ({MODELS_MB} MB of it the models), and this computer has {gb(free)} GB free. "
          f"It uses {where}.", flush=True)
    if free < (need + SPARE_GB) * 1e9:
        print(f"That would leave less than {SPARE_GB:.0f} GB free, so it stops here. Make room and run this again.", flush=True)
        return 1
    steps = plan(folder, maker, system, args.speak_only)
    if not args.yes and not ask(f"Set it up now? It takes {len(steps)} steps and a few minutes. [Y/n] "):
        print("Nothing was changed. python3 serve.py --set-up-voice sets it up when you want it.", flush=True)
        return 1
    try:
        for n, (title, command, env, worker) in enumerate(steps, 1):
            print(f"\nStep {n} of {len(steps)}: {title}...", flush=True)
            ok, got = run_step(command, env, worker)
            if not ok:
                if n == 1 and maker and system == "Linux":
                    got = f"{got}. On Debian and Ubuntu, Python needs its venv part first: sudo apt install python3-venv"
                return finish(False, got, n, len(steps))
    except KeyboardInterrupt:
        print("\nStopped. Run it again to carry on: what's done stays done.", flush=True)
        return 130
    return finish(True, got, len(steps), len(steps))


def finish(ok, got, n, total):
    if not ok:
        print(f"\n{'Step ' + str(n) + ' of ' + str(total) if total > 1 else 'It'} didn't work: {got}. Run it again to "
              "carry on where it stopped; README, \"Voice\", has the steps to do by hand.", flush=True)
        return 1
    voices = len(got.get("voices") or []) if isinstance(got, dict) else 0
    hears = isinstance(got, dict) and got.get("hear")
    print(f"\nThe voice is ready: {voices} voices{', and listening' if hears else ', speaking only'}. Turn on Voice on a walk. "
          "If Arnheim is running, it uses it from the next answer; the first takes a few seconds while the voice wakes.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
