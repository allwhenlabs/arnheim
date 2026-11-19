# Set up Arnheim, for an agent

This page is for an AI agent, such as Claude Code or Codex, that a person has asked to set up
Arnheim. A person can paste this line into any agent:

> Set up Arnheim for me: follow github.com/allwhenlabs/arnheim/blob/main/docs/agent-setup.md

In Claude Code, the Arnheim plugin's `/arnheim:setup` follows the same steps (README, "Start").

## Rules for you, the agent

Arnheim shows the person's Claude Code and Codex agents as a building, with one list of what needs
them. It runs on their own computer, at http://127.0.0.1:8740, and sends nothing anywhere. Its own
setup shows each change before it makes it, keeps a copy of each file it changes, and has Undo.
Keep it that way:

- Ask the person before each change, and show them the exact command first. Run it only after they
  say yes. Looking and checking need no yes.
- Never pass `--yes` to `connect/setup.py`. The person answers its questions, not you.
- Never edit Claude Code's or Codex's settings, or the person's projects, yourself. Arnheim's setup
  does that, and can undo it.
- Use only the commands in these steps. None of them needs `sudo`, an account or a key.
- If a command fails, show the person what it said and stop. If your sandbox blocks one, ask the
  person to allow it or to run it themselves.
- On Windows, type `py` where a command says `python3`.

## 1. Look at what is here

These change nothing, so run them without asking:

- `git --version`, and `python3 --version`, which must say 3.7 or newer. If either is missing, tell
  the person how to get it and stop. On a Mac, the first `git` or `python3` offers to install
  Apple's command line tools, which bring both.
- Whether Arnheim already runs:

  ```bash
  python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8740/look', timeout=3).read().decode())"
  ```

  It prints `{"look": ...}` when Arnheim runs there, and "Connection refused" when nothing does.
  If Arnheim runs, it is set up already: go on to step 4.

## 2. Choose its folder

Ask the person where to keep Arnheim, and suggest a folder called `arnheim` in their home folder
(`~/arnheim`). Their own building is kept in its `data` folder, so it should be a folder that
stays put: not a temporary or downloads folder, and not one that syncs to the cloud.

- **Arnheim is there already** (the folder has `serve.py`, and `git -C <folder> remote -v` names
  github.com/allwhenlabs/arnheim): offer to bring it up to date, and ask first:

  ```bash
  git -C <folder> pull --ff-only
  ```

  If git refuses because of changes made in that folder, leave it as it is and say so.
- **Something else is there:** leave it alone, and ask for another folder.
- **Nothing is there:** offer to copy Arnheim from GitHub, and ask first:

  ```bash
  git clone https://github.com/allwhenlabs/arnheim <folder>
  ```

Run each command after this one in that folder. If your shell forgets the folder between commands,
start each with it, such as `cd ~/arnheim && python3 serve.py --always`.

## 3. Start it

Ask the person which they want:

1. **Keep it running, and start it each time they log in** (Mac and Linux). This adds one login
   item, `~/Library/LaunchAgents/local.arnheim.serve.plist` on a Mac or
   `~/.config/systemd/user/arnheim.service` on Linux, and `python3 serve.py --always off` takes it
   out again. Give the command up to three minutes:

   ```bash
   python3 serve.py --always
   ```

2. **Only for now.** Start `python3 serve.py --no-browser` as a background command of your own, so
   you can go on (it stops when your session ends), or have the person run `python3 serve.py` in a
   terminal of their own, where Ctrl-C stops it.

Tell them first that the first start downloads the pictures for the photo-real look (52 MB, once,
from Arnheim's releases on GitHub), and that adding `--drawn` to either command skips that and keeps
the drawn look.

Then run the check from step 1 until it prints `{"look": ...}`. While the pictures download, it
times out: wait a little and try again.

## 4. Open the page

```bash
python3 -m webbrowser http://127.0.0.1:8740
```

With no browser here (over SSH, say), give the person the address instead.

## 5. Connect their agents

Until the person connects their agents, the page shows Fernhollow, a made-up company. Tell them:

> On the page, press **Connect my agents** on the welcome card, or in Settings. It lists the
> projects you have worked on with Claude Code or Codex, each ticked, asks whether you want to
> answer your agents from the building, and connects them when you press Connect. Then it shows
> what it did, with **Undo**.

Don't press anything on the page yourself: wait for them to say it's done. Connect writes
`data/company.json` in Arnheim's folder, with a floor for each project. It adds Arnheim's hooks to
Claude Code's settings (`~/.claude/settings.json`) and, if Codex is here, to `~/.codex/hooks.json`,
keeping a copy of each file beside it. It lets Claude Code's status line tell Arnheim how much of
the person's plan is used, and their own status line still shows. It changes their projects' files
only for the steps they leave ticked under Set your agents up well (an instructions file both agents
read, the project's check, and that check allowed without asking). Left ticked, it also makes three
changes once for every project: rules that keep Claude Code's own tools from opening secret files, in
`~/.claude/settings.json`; a line in `~/.codex/config.toml` so Codex reads CLAUDE.md where there is no
AGENTS.md; and the same MCP servers in both agents. Undo puts every file back.

**In the terminal instead.** With no browser, or if the person would rather, they can run
`python3 connect/setup.py` in a terminal of their own: it shows what it will change, and asks. If
they want you to run it, give it their answers, never your own. It reads them from its input, one
per line, and stops before changing anything when an answer is missing:

1. See what it finds, changing nothing:

   ```bash
   python3 connect/setup.py < /dev/null
   ```

   It lists the projects, then says "Stopped before changing anything." Ask the person which to
   connect, and, if Arnheim's folder has no `data/company.json` yet, what to call their building.

2. See exactly what it will change, still changing nothing:

   ```bash
   python3 connect/setup.py --folder <project> --folder <another> --name "<name>" --no-well < /dev/null
   ```

   Show the person each line under "This will:". If it asked "Answer your agents from the building
   too", ask them that as well: it means Allow, Deny and messages from the page, on this computer
   only. With no answer, this look took it as no.

3. Only once the person says yes, run the same command with their answers, in the order it asked:
   their answer to "Answer your agents from the building too", if it asked that, then `y` for "Go
   ahead?". For yes and yes:

   ```bash
   printf 'y\ny\n' | python3 connect/setup.py --folder <project> --folder <another> --name "<name>" --no-well
   ```

   If an answer lands on the wrong question, it stops before changing anything: look again with 2.
   `--no-well` keeps this route to connecting only. Setting their agents up well changes files in their
   projects, so leave it to the person: Settings, **Your agents' setup**, on the page, shows each step
   first, or they can run `python3 connect/setup.py --well` themselves.

## 6. Afterwards

- New Claude Code and Codex conversations in the connected folders show in the building. One that
  was open already, like this one, may not until it starts again.
- Codex runs new hooks only once they are trusted: start Codex, type `/hooks`, and trust Arnheim's,
  once.
- If they chose "only for now" in step 3, offer to keep Arnheim running and start it at each login,
  with `python3 serve.py --always`. Ask first.

Then tell the person what you changed, and how to undo each part:

- Arnheim's hooks and status line: **Undo** on the page, or `python3 connect/setup.py --undo`.
- Starting at login: `python3 serve.py --always off`.
- Their building: delete the `data` folder in Arnheim's folder, and the page shows the made-up
  company again.
- Arnheim itself: delete its folder, once its hooks and its login item are out.
