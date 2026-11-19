# Connect it to your work

Arnheim can follow your real work as it happens. Connect it to Claude Code, and each conversation
you have with Claude in one of your projects shows on that project's floor. Switch on control, and
you can talk to those agents for real, answer their permission requests, and start and stop them
from the building. Connect it to git and GitHub, and each project's unsaved changes and open pull
requests show in its Code room. Anything else that can write a small file can join in too.

Everything stays on your computer. The connectors write into `data/feeds/`, inside the `data/`
folder that git ignores, and the page reads them from there every few seconds, so the building
follows along without a reload.

## What you will see

- **A seat for each Claude Code conversation**, in the project's Conversations room, named after
  the conversation, or after the first line of your first message.
- **Someone in the seat while Claude works**, and the room lit blue. They stay seated while it
  waits for you.
- **An amber desk when Claude needs you**: when it asks for your permission or asks you something,
  a desk in the Work room says what it is waiting for, the floor says "Needs you", and the receptionist lists it
  when you ask what needs you. It goes as soon as you answer.
- **A mark in the list when Claude has finished** and it is your turn, until you reply: an empty ring, or a
  tick once its work is proven (step 5). The room goes back to plain light, so only amber, blue and red stand out.
- **Claude's task list as desks**: one for each task, someone at it while it is being done. Finished
  tasks leave. Newer Claude models keep no written task list unless you ask for one: start Claude
  Code with `CLAUDE_CODE_ENABLE_TODO_TOOLS=1 claude` to have it keep one.
- **The conversation talks**: on a walk, stand at its ring and ask how it's going, and it answers
  with the first sentences of the last thing Claude said. Unless control is on (step 4), what you
  say there doesn't reach Claude: the page only shows.
- **From git**: a crate in the Code room when a project has changes not yet committed, with how
  many. **From GitHub**: a book for each open pull request.

## The quick way

In Arnheim's folder:

```bash
python3 connect/setup.py
```

It does steps 1 and 2 for you, and adds step 4's hook too, so control works as soon as you switch it
on. It finds the projects you have worked on with Claude Code or Codex: it reads only the first lines
of each recent conversation's file in `~/.claude/projects` (and `~/.codex/sessions`), which name the
folder it ran in, never what was said. A folder inside a git repository counts as that repository,
and so does a git worktree; the home folder, hidden and temporary folders, and a folder that only
holds other projects are left out. It lists at most twelve, the most recent first, and asks which
to use and what to call the building. Before it changes anything it says what it will do and asks.

- **Your building.** With no `data/company.json`, it writes one: a floor for each project with the
  Work, Conversations and Code rooms, the connectors' `feeds`, and a front desk with a receptionist.
  With one already there, it only adds floors for projects that have none, and any of the connectors'
  `feeds` it lacks, after keeping a copy in `data/backups/`.
- **Claude Code's settings.** It adds Arnheim's hooks to `~/.claude/settings.json` (or the
  `settings.json` in `CLAUDE_CONFIG_DIR`, if you set that), beside any hooks already there, after
  keeping a copy beside it. The hooks run the Python that ran the setup, by a name that survives an
  upgrade where there is one. A settings file that isn't valid JSON is left alone, with where the
  mistake is. If another copy of Arnheim already has hooks there, it says so and changes nothing. If
  you connected a project by hand in its own `.claude/settings.json` (step 2), it says so: take those
  out, or Claude Code tells the building everything twice in that project.
- **Codex's hooks.** If Codex is on this computer, it adds Arnheim's hooks to `~/.codex/hooks.json` (or
  the one in `CODEX_HOME`) the same way, beside any already there, after keeping a copy beside it
  (step 9). Codex runs new hooks only once you trust them: start Codex, type `/hooks`, and trust
  Arnheim's, once. It says if your `config.toml` switches hooks off, or if your Codex is too old to
  have them.
- **Claude Code's status line.** For the usage forecast (step 18), it sets Claude Code's status line
  to `connect/usage.py`, which notes your plan's limits each time Claude Code redraws it. A status
  line of your own stays: it is kept, and shows exactly as before.

Running it again changes nothing that is already done. `--yes` takes every suggestion without
asking, `--folder PATH` names a project yourself (give it again for more), `--name` names a new
building, and `--no-hooks` leaves Claude Code's settings alone. Nothing is half done: if one file
can't be written, neither is. `python3 connect/setup.py --undo`
takes every one of Arnheim's hooks out of Claude Code's settings and leaves every other setting and
hook there as it was, and puts your own status line back; your building stays, and deleting the `data`
folder goes back to the made-up company.

It asks one more thing: whether you want to answer your agents from the building (step 4). Your
answer is kept in `data/serve.json`, so `serve.py` starts with control on, or off, without being
told; the Switches in Settings change it (step 20), and `python3 serve.py --no-control` leaves it off once. Last, on a Mac or Linux, it offers to start
Arnheim now and each time you log in, so it keeps running when you close the window: that is
`python3 serve.py --always`, and `python3 serve.py --always off` takes it out again.

Before that, it offers to set your agents up well (step 23): it shows what it would do in each project and
asks once. `--well` says yes without asking, `--no-well` doesn't ask, and `--yes` alone leaves it.

**From the page.** On the made-up company's welcome card, or in Settings, on the computer that runs `serve.py` (never a
phone, `--lan` or `--share`), **Connect my agents** does the same without a terminal. It lists the
projects setup finds, each ticked, takes one more folder you type (it must be there, and not your home
folder or a whole disk), says whether Claude Code and Codex are here, and asks the one question about
answering agents from the building, yes unless you say no. Connect runs setup in `serve.py` for those
folders, with the same copies and words, and switches control on at once if you chose it. It never
offers to start Arnheim at login: that stays in the terminal. The page then shows your own company,
what was done, and **Undo**, which takes the hooks and status line out as `--undo` does and moves
`data/company.json` into `data/backups/`, so the page shows the made-up company again. Until your
first conversation arrives, Needs you lists the folders to open Claude Code (or Codex) in.

`serve.py` does step 3 itself. The steps below do the same by hand, and say what each piece does.

## 1. Tell Arnheim where each project lives

Start with your own company in `data/` (README, "Make it yours"). Then, in `data/company.json`,
give each floor the folder its project is in, give it the rooms these things show in
(Conversations, Work and Code), and add the connectors' two files as `feeds`:

```json
{
  "company": "Example Studio",
  "feeds": ["feeds/claude-code.json", "feeds/projects.json"],
  "rooms": [
    { "id": "work", "label": "Work", "about": "Tasks, and what Claude is waiting on you for." },
    { "id": "conversations", "label": "Conversations", "about": "Claude Code conversations." },
    { "id": "code", "label": "Code", "about": "Unsaved changes and open pull requests." }
  ],
  "floors": [
    { "id": "lantern", "label": "Lantern", "folder": "~/code/lantern" },
    { "id": "tidepool", "label": "Tidepool", "folders": ["~/code/tidepool-app", "~/code/tidepool-kit"] }
  ]
}
```

A conversation belongs to a floor when it runs in that floor's folder or in any folder inside it.
`~` is your home folder. Work in folders that no floor names is left out, so nothing else shows.
Reload the page after changing `company.json`.

## 2. Connect Claude Code

Claude Code can run a command at set moments in a conversation: when it starts, when you send a
message, after Claude uses a tool, when it needs you, when it finishes, when a task is made or done,
and when it ends. These are its hooks. Add Arnheim's to Claude Code's settings: in
`~/.claude/settings.json` for every project on this computer, or in a project's own
`.claude/settings.json` for that project alone. Put the path to your copy of Arnheim where it says
`/path/to/arnheim`:

```json
{
  "hooks": {
    "SessionStart": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "UserPromptSubmit": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "PreToolUse": [{ "matcher": "Edit|MultiEdit|Write|NotebookEdit|Bash", "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "PostToolUse": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "Notification": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "Stop": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "TaskCreated": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "TaskCompleted": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
    "SessionEnd": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }]
  }
}
```

If your settings file already has `"hooks"`, add these beside the ones there; if it has other
settings, keep them. Put the path in quotes inside the command if it has spaces, and on Windows
write `python` instead of `python3`. In Claude Code, `/hooks` shows what is set up.

The next conversation you start in one of the floors' folders appears in the building. The
connector prints nothing and always lets Claude carry on; each time it runs takes a few hundredths
of a second, the time Python takes to start.

To try it without Claude, hand it a moment yourself, with a folder one of your floors names:

```bash
echo '{"hook_event_name": "UserPromptSubmit", "session_id": "try", "cwd": "/path/to/a/project", "prompt": "Hello"}' | python3 connect/claude_code.py
```

A seat called "Hello" appears, with someone in it. This takes it away again:

```bash
echo '{"hook_event_name": "SessionEnd", "session_id": "try", "cwd": "/path/to/a/project"}' | python3 connect/claude_code.py
```

## 3. Connect git and GitHub

`serve.py` does this for you: once a floor names a folder, it looks every minute while it runs
(`python3 serve.py --no-git` leaves it off). To run it yourself instead, in a terminal beside
`serve.py`, in Arnheim's folder:

```bash
python3 connect/projects.py --every 60
```

Every minute it counts each floor folder's changes that are not yet committed and, if GitHub's
`gh` command is installed and signed in, lists the folder's open pull requests. It only reads, and
never changes a repository. `--no-github` leaves out pull requests, and without `--every` it looks
once.

## 4. Control your agents from the building

Optional, and off unless you switch it on. Then the person at this computer can:

- **Talk to an agent.** What you type or say in its ring on a walk, or send from its page in the
  panel, reaches its Claude Code conversation at its next step, and its answer comes back to you.
  An agent waiting for you in Claude Code sees it the next time you send it something there.
- **Answer its permission requests.** When it asks to run a command or change a file, the request
  shows on its card in the walk and on its page in the panel, with Allow and Deny. In its ring you
  can also say "allow" or "deny". An answer is for that one request only. A request waits in the
  building only while you are using it (walking, or you touched it in the last two minutes), and for
  two minutes at most. Otherwise Claude Code asks as it always does.
- **Always allow what you always allow.** Once you have allowed the same command on a floor twice in
  two weeks, here or in the agent's own window, its next request offers **Always allow here**. From
  then on Arnheim allows that exact command on that floor for every agent, Claude Code's and Codex's,
  without asking you, and its card says so. Only a command from a short list can be allowed for good:
  the project's tests, checks and builds (`npm test`, `npm run lint`, `pytest`, `cargo test`,
  `go test`, `make test` and the like) and commands that only look (`ls`, `git status`, `git diff`,
  `git log` and the like). It must match word for word, one plain command: nothing chained, piped or
  redirected, no quotes or variables, nothing run outside the agent's sandbox or in the background,
  and nothing that names anything private or outside the project. A test or build runs the project's own code, as it does
  each time you allow it once. Reads, searches, file changes and web requests always ask. Settings
  lists each one, with **Stop allowing**.
- **See everything waiting on you in one list.** The Needs you tab puts together every
  agent's permission requests (the one whose wait runs out first at the top), the questions agents
  stopped to ask, your own tasks marked as needing you, and agents that finished in the last two
  hours and wait for your next step. Each has its answer beside it: Allow and Deny, or a box to reply.
  When two or more requests only read a file, "Allow all" answers them together. Ask the
  receptionist "what's waiting on me?" to hear it, and say "allow all the reads" to let those go
  ahead. Commands, changes, searches and reads of anything that looks like a key, a password, a token
  or a credentials file are never allowed together: each needs its own answer.
- **Stop it.** Stop on its card, or say "stop": it stops at its next step.
- **Start one.** In a floor's Conversations room, or by asking the receptionist ("start an agent on
  Lantern to fix the login page", then "start it"). It runs in the floor's folder with your own
  Claude Code settings, as if you had started it there, and stays in the building to talk to.
- **Pass something on through your assistant.** With the brain on too ([brain.md](brain.md)), ask
  your assistant to tell an agent at work something, and it reaches that agent as a message from the
  building does.
- **Or through the floor's lead.** Each floor's lead passes on what you tell them ("tell them to test
  it on the spare laptop") to the agent at work on that floor, brain or not, and asks which one when
  several are. Anything final, such as merging, deploying or deleting, is read back first. Ask them
  "what's new?" later to hear what that agent did since. Leads can be switched off in the Talk panel.
- **Answer by voice.** Say "allow" in the Talk panel, or to the receptionist, a lead or the agent
  itself, and the next request is read back first; say "allow" again within a minute to answer it,
  once, or "deny". A request that may touch something private is never answered by voice: it opens on
  the screen. Allow and Deny on a card still answer at once.

To switch it on, connect Claude Code (step 2) and add one more hook beside those, for permission
requests (`connect/setup.py` adds it for you). It waits for your answer, so it gets a longer time limit:

```json
"PermissionRequest": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py", "timeout": 150 }] }]
```

Then start Arnheim with `--control`:

```bash
python3 serve.py --control
```

While control is on, a light in the top bar says **Answering here** while the page counts as in use
(walking, or touched in the last two minutes), so a request waits there for you, and **Agents ask in
their windows** when it doesn't. Press it to read why; touching the page makes it answer again. With
**Desktop alerts when an agent needs you** on (on Needs you, or under Switches, for each browser
apart), a permission request or a question that comes while the page is in the background brings one
desktop alert, named after its floor; clicking it opens what is asked. Nothing that was already
waiting when the page opened alerts, nor anything in the made-up company.

Control answers only the page on the computer that runs `serve.py`, with the token that page is
given, and never works with `--lan`. Starting agents needs Claude Code's `claude` command
(`ARNHEIM_CLAUDE` names another). `ARNHEIM_CONTROL_WAIT` sets how long a permission request waits
for an answer in the building, in seconds: keep the hook's `timeout` above it.

## 5. Done means proven

An agent saying it has finished isn't proof that its work holds up. Give a floor a check, the
command that shows its work is sound (its tests, say), and Arnheim runs it for you each time an agent
on that floor finishes a turn in which it changed files:

```json
{ "id": "lantern", "label": "Lantern", "folder": "~/code/lantern",
  "check": { "run": ["npm", "test"], "label": "The tests", "timeout": 600 } }
```

`run` is the command and its arguments, one to a string. It runs in the floor's folder (or in
`folder`, if the check names one), with no shell, as you, and is stopped after `timeout` seconds (ten
minutes if left out). `label` is what the building calls it. `"check": ["npm", "test"]` is enough.

Then each conversation that changed files says, in the list, its room's light and its page in the
panel, which of these is true:

- **Proven**: the check passed after its last change. The list gives it a green tick, and its seat and room stay
  plain: nothing more to look at there.
- **Not proven**: the check failed, ran too long, or couldn't start. A red lamp lights at its seat and the room turns red,
  and its page shows the check's last lines.
- **Claimed**: it changed files and nothing has checked them since, perhaps because the floor has no
  check, or it changed more while the check ran.

The check runs in the background, so Claude Code never waits for it, and one runs per floor at a
time: turns that end meanwhile get one more run when it ends. Arnheim only notices changes made with
Claude Code's own tools for editing files. With control on, "Check it again" on a conversation's page
runs it once more. It needs only step 2's hooks.

## 6. Company memory

Every agent should know what you have already decided, without being told again in each
conversation. Tell the receptionist, by typing or out loud:

> Remember that we never push on a Friday.

("Remember: ...", "from now on, ..." and "going forward, ..." work too.) Or type it under "What every
agent is told" in Settings, where Forget takes one out again. Saving needs control on (step 4).
The decisions are kept in `data/memory.json`, which you can also edit by hand:

```json
{ "memory": [{ "id": "m-1", "text": "We never push on a Friday." }] }
```

Then, through the hooks of step 2:

- **Every conversation in the company's folders is told them as it starts**, and again if its
  context is compacted. Conversations in other folders are told nothing.
- **One already at work is told decisions made since**, with the next message you send it.
- **When an agent asks you something you've decided before**, the list of what waits on you shows
  your decision under its question, with "Send it that". Arnheim matches the words of the question
  with your decisions, so it only suggests: nothing is sent until you press it.

Ask the receptionist "what have we decided?" to hear the memory. With the brain on, they know it too.

## 7. A budget per floor, and pausing everyone

Arnheim counts what each conversation spends each day, from Claude Code's own record of it: the new
tokens of each reply, that is what Claude read fresh, wrote to its cache, and wrote back. Re-reading
its cache is left out, since that is the same context again, and so is the work of its sub-agents.
Activity shows each floor's total for today under "Spent today", and each floor's page says it too.

Give a floor a budget for a day, in new tokens, or give the company one for every floor:

```json
{ "company": "Example Studio", "budget": 3000000,
  "floors": [{ "id": "lantern", "label": "Lantern", "folder": "~/code/lantern", "budget": 1000000 }] }
```

When a floor's agents pass it, the one at work stops at its next step, and the list of what waits on
you asks whether they may go on. **Let them go on** (with control on) gives them as much again, for
today; or leave them, and the budget starts afresh tomorrow. Each conversation is stopped once for each
limit it passes, so if you carry on with it in Claude Code yourself, it lets you.

With control on, **Pause all** at the top of the page (on a phone, in the ... menu), or **Pause everyone** in the lobby, stops every agent in the
company's folders at its next step, and a message you send one in Claude Code is turned away with a
note saying so: send it again after you **Resume all**. Nothing is ever stopped in the middle of a step, and a message you send from the
building is always handed over first.

## 8. Replay the day, ask its history, and the week

When something went wrong, or you were away, drag the slider under "Replay the day" in Activity
back through today. The building shows who was at work at that moment, who was waiting on you and who
had finished, with a banner saying which time you are looking at, and the list beside it shows the
last moments before then: when each conversation started work, which files it changed, what it asked
you and what it said when it finished. Tap a moment to read that conversation, or press Back to now.

It needs only step 2's hooks. A file changed inside a floor's folder is named by its path there; one
outside it, by its name alone.

The building keeps a week of these days, and you can ask about them. Ask the receptionist **"What
happened yesterday?"**, **"What did the agents do on Tuesday?"**, **"What happened on Lantern this
week?"** or **"Who changed reader/bookmark.js?"**, and they answer from the moments.

**This week**, in Activity, is the weekly report: each floor's conversations, the instructions you
gave, the files they changed, how many finished or stopped, how long they waited on you, and what they
spent. **Copy the report** copies it as plain text, for a message or a document. Ask **"How was the
week?"** to hear it summed up.

**How long things wait on you**: each line under "Waiting on you" says how long it has waited, and a
meter fills as the longest an agent has been held up grows, amber past five minutes and red past
fifteen. Under it, how long agents waited on you today in all. A wait starts when an agent asks you
for a permission or an answer, and ends when it goes on. Ask **"How long have the agents waited on
me?"** for the same in words.

## 9. Codex, and any other agent

Other agents can sit in the building too, in the same rooms, the same list of what waits on you and
the same replay. Add their feed to `data/company.json`'s `feeds`, beside Claude Code's:

```json
"feeds": ["feeds/claude-code.json", "feeds/agents.json", "feeds/projects.json", "feeds/restore.json"]
```

**OpenAI's Codex CLI** is a full member, like Claude Code. Since version 0.124 it has hooks with the
same names, and `python3 connect/setup.py` adds Arnheim's to `~/.codex/hooks.json` for you. By hand,
the same file:

```json
{"hooks": {
  "SessionStart": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
  "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
  "PreToolUse": [{"matcher": "apply_patch|Edit|Write|Bash", "hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
  "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
  "PermissionRequest": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py", "timeout": 150}]}],
  "Stop": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
  "SessionEnd": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py", "timeout": 3}]}],
  "Interrupt": [{"hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py", "timeout": 3}]}]
}}
```

Codex runs new hooks only once you trust them: type `/hooks` in Codex and trust Arnheim's. Then each
Codex conversation in a floor's folder sits on that floor just as a Claude Code one does, named as
Codex's: someone at work while it works, its plan as tasks, the files it changes (for collision
warnings and its floor's check), amber while it waits for your permission, what it said last, and
what it spends against the floor's budget. With control on, you answer its permissions, send it
messages and stop it from the building, as for Claude Code. Two things differ: Codex can't be
interrupted while it asks, so "stop" there denies the request and it stops at its next step; and
starting a new agent from the building starts Claude Code, unless it carries a Claude Code conversation on at
a limit (step 21).

An older Codex, without hooks, can still show when a turn ends, through its `notify` setting, in
`~/.codex/config.toml`:

```toml
notify = ["python3", "/path/to/arnheim/connect/codex.py"]
```

That shows each conversation finished and waiting for your next step, nothing while it works. Once
Codex has run Arnheim's hooks, notify stays quiet, so nothing is told twice; `connect/setup.py` adds
hooks only for a Codex that has them.

**Any other agent, script or tool** can say where it is with one command, from its own hooks or
wrapper, each time something changes:

```bash
python3 connect/agents.py --agent Gemini --session 42 --cwd ~/code/lantern --state working --says "Fixing the login"
```

`--state` is `working`, `asking` (it shows in the list of what waits on you), `finished` or `ended`.
`--session` is the conversation's own id, the same each time. The building names the agent on each
conversation. Answering and stopping from the building (step 4) is for Claude Code and Codex, whose
hooks let another program hand them words; starting new work there starts Claude Code.

## 10. Collision warnings

Two agents changing the same file can undo each other's work. When a conversation changes a file that
another conversation on the same floor changed in the last two hours, Arnheim tells it at once, with the
other's name, so it looks at their work before going on. Needs you lists the pair under "Two agents
on the same files", and the floor says "Two agents, one file". With control on, "Make ... wait" tells either one to wait
until the other has finished. It needs only step 2's hooks, and sees changes made with Claude Code's
own tools for editing files.

## 11. Hand out work by talking

With control on (step 4), tell the receptionist what you want done, in everyday words: "get someone to
fix the login bug on Lantern", "have an agent on Tidepool tidy the tests", "ask Claude to write the
release notes". If you don't name a floor, they ask which. They tell you what they will start, and it
starts when you say "start it" (or tap Start). It works the same on a walk and in the panel's chat.

The new agent is a Claude Code conversation in the floor's folder, with your own settings. It is
given a brief: the job, that it was started from the building by the person it works for, the
company's memory (step 6), and, on a floor with a check (step 5), that the check must pass for the
work to count as done. From the panel, the building turns to the Conversations room where it sits
down.

## 12. A review line

A floor can say that every change gets checked before it reaches you:

```json
{ "id": "lantern", "label": "Lantern", "folder": "~/code/lantern", "review": true,
  "check": { "run": ["npm", "test"], "label": "The tests" } }
```

Then, when a Claude Code or Codex conversation there finishes a turn in which it changed files,
Arnheim holds the turn while the work goes through the line:

1. the floor's check (step 5), if it has one, and, if that passes,
2. a reader: a second agent, which can only read files, is shown what changed (from git) and what
   you asked for, and says whether the work is ready for you.

Work that passes reaches you as usual, and its page says it passed, who reviewed it and what they
thought, such as "Codex reviewed Claude Code's work: ...". Work that doesn't goes back to the agent
with the reason, and it carries on fixing it; meanwhile it isn't listed as waiting on you. After two
sends back it reaches you anyway, marked as having failed, so nothing goes round for ever.

**Who reviews.** Out of the box the other agent does: Codex reads Claude Code's work, and Claude Code
reads Codex's, since a reviewer from another maker catches what the writer's own kind misses. When
the other one isn't installed, the same agent reads it, and the result says so. To pick one for a
floor, whoever wrote the work, add `"reviewer"`:

```json
"review": { "reviewer": "codex" }
```

`"other"` is the usual, `"claude"` is always Claude Code, and `"codex"` is always Codex. The floor's
page and Settings say who reviews on each floor, and every result names who reviewed it.

`"review": { "read": false }` leaves the reader out, so only the check decides. `"times"` sets how
often work can be sent back (0 to 5, two if left out), and `"timeout"` the reader's time limit in
seconds (five minutes if left out). Claude Code reads with its `claude` command (`ARNHEIM_CLAUDE`
names another), in the floor's folder, with only the tools that read and search files, no MCP
servers, and nothing saved to your Claude Code history. Codex reads with `codex exec`
(`ARNHEIM_CODEX` names another), in the floor's folder, in a read-only sandbox, never asking for
approval, without your `config.toml` (so none of your MCP servers), your rules or hooks, and nothing
saved to your Codex history. It still uses your Codex sign-in. Either way, what it spends counts
towards the floor's budget (step 7): a few thousand new tokens for a small change.

The line runs while the agent waits for the turn to end, so give its Stop hook a time limit longer
than the check's and the reader's together: step 2's for Claude Code, and step 9's `hooks.json` for
Codex, which waits ten minutes if it isn't told:

```json
"Stop": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py", "timeout": 1200 }] }]
```

If the limit runs out first, the turn ends as usual and the building says the work wasn't reviewed.
A conversation you stop from the building isn't reviewed. Other agents (step 9), and a Codex that
shows only through `notify`, aren't held, since the building only hears from them once they have
finished.

## 13. Routines

Jobs that run on a schedule, such as a weekly look for outdated packages, a nightly security scan or
a check that a release is ready. List them on their floor:

```json
{ "id": "lantern", "label": "Lantern", "folder": "~/code/lantern",
  "routines": [
    { "id": "outdated", "label": "Outdated packages", "every": "monday", "at": "09:00", "run": ["npm", "outdated"] },
    { "id": "scan", "label": "Security scan", "every": "weekday", "at": "07:30",
      "ask": "Look for secrets or unsafe code added since yesterday, and fix what you safely can." }
  ] }
```

- `id`: a short name of its own on the floor (letters, numbers, `-` and `_`).
- `every`: `hour`, `day`, `weekday` (Monday to Friday), a day's name such as `monday`, or `week` with
  `"on": "saturday"`. `at` is the time of day on this computer's clock, 24-hour: 09:00 if left out.
- `run`: a command, which runs as a floor's check does (step 5): in the floor's folder, with no shell,
  and stopped after `timeout` seconds (ten minutes if left out). It is all clear if it succeeds.
- `ask`: instead of a command, a job for a new Claude Code agent on the floor, which gets a brief as
  in step 11 and is asked to end with "All clear" when nothing needs you. It can do what your Claude
  Code settings let it do without asking, and is stopped after `timeout` seconds (an hour if left
  out). Its conversation shows in the building as any other does.

To run them, start Arnheim with `--routines`, which checks every minute while it runs:

```bash
python3 serve.py --routines
```

Or have your computer's own scheduler run `python3 /path/to/arnheim/connect/routines.py` every few
minutes (cron or launchd), which starts the routines that are due and gives back at once. Add
`"feeds/routines.json"` to `feeds` in `company.json` too.

Activity lists each routine, when it runs and what its last run came to. You only hear about one
when it needs you: a command that fails or runs too long, or an agent that doesn't end all clear, puts
a task in "Waiting on you", which goes when a later run is all clear. With control on, "Run it now"
and "Run it again" run one at once. A new routine waits for its first time after Arnheim first sees
it, and one missed while the computer slept runs once when it is next checked, not once for each time
it missed. Ask the receptionist "what routines are there?" to hear them.
`python3 connect/routines.py --list` says each one and when it runs next, and `--run <id>` runs one
now and waits for it.

## 14. Project health

Each floor says at a glance whether it is well, from what the building already knows. A floor needs
looking at while:

- an agent's work there failed its check (step 5), and the agent isn't back at work on it,
- work failed the review line (step 12),
- a routine needs you (step 13),
- an agent's settings hold a secret that git has shared, or would (step 22).

It has a warning while:

- a pull request that isn't a draft has waited a week or more since it was last updated (step 3),
- an agent at work has said nothing for twenty minutes: it may be stuck in a command, or waiting on
  something it never asked about. With control on, **Stop it** stops it at its next step.
- an agent's conversation has been shortened to fit twice, when agents start to forget what they
  were doing. With control on, **Start fresh with a hand-over** starts a new agent on the floor,
  handed what the old one was asked, the files it changed and its last words; stop the old one once
  the new one has it.
- an agent's settings hold a secret that stays on this computer: git ignores the file, or the folder
  isn't in git (step 22).

The floor's label says "Something to fix" (or how many), its page
lists each thing in words, and the "Project health" card in Activity puts
every floor together. With control on, each thing has "Send an agent", which starts one on the floor
with a brief that says what is wrong and asks it to fix it, or, for a pull request, to say what it
needs without merging or closing it. Ask the receptionist "is anything broken?" or "how are the
projects doing?" to hear it.

## 15. A morning brief, and pings on your phone

The receptionist tells you what happened since you were last here: how many agents were at work,
which finished and whether their work was proven, which were stopped, which routines ran, and what
waits on you now. On a walk they greet you with it the first time you come to the desk, out loud
with Voice on. Ask "brief me", "what did I miss?" or "what happened overnight?" to hear it again.
Needs you shows it too, as "Since you were last here". Your last visit is kept in that browser,
and the brief never reaches back more than a day.

To have it on your phone, add "pings" to company.json, and Arnheim sends the brief at the first time
of the day. At each later time it sends only when a decision has come up since the last ping: a
permission an agent asks for, a question it stopped to ask, or a task marked as needing you. A quiet
night sends nothing.

```json
"pings": { "ntfy": "https://ntfy.sh/a-long-topic-name-nobody-could-guess", "at": ["08:00", "13:00", "17:30"] }
```

[ntfy](https://ntfy.sh) is free and open source: install its app on your phone and subscribe to the
same topic. The words go to that server, which hands them to the app. They are the counts in the
brief, the titles of your agents' work and the floors they are on, the questions agents stop to ask
you in their own words, the titles of your tasks that need you, and for a permission only its kind
("wants your permission to run a command"), never the command or the file. Anyone who knows the
topic can read them, so pick a name nobody could guess, or run your own ntfy server. The address
must be https, or plain http to a server on this computer, and the page is never shown the topic:
serve.py leaves "pings" out of the company.json it gives the page. Or send them your own way:
`"run": ["/path/to/your/notifier"]` gets each ping on its standard input, its first line the title.

```bash
python3 serve.py --pings
python3 connect/ping.py --test
```

`--pings` checks every minute while Arnheim runs (or have your computer's scheduler run `python3
connect/ping.py` every few minutes). `--test` sends a hello now, to check it reaches you, `--show`
prints what the brief would say without sending it, and `--now` sends the brief now. A new setting
waits for its first time, and a time missed while the computer slept sends once.

## 16. Restore points

Before an agent changes a project's files, Claude Code or Codex, Arnheim keeps how they were, so you can
go back. `python3 connect/setup.py` (or Connect my agents on the page) sets this up for both: the
`PreToolUse` hooks in step 2 and step 9, which run only for tools that change files and for shell
commands, and `"feeds/restore.json"` in `feeds` in `company.json`. Then, before the first file an agent changes
after each message you send it, and before any command that deletes or overwrites files in bulk (`rm
-r`, `git reset --hard`, `git clean -f`, `git checkout -- ...`, `git stash` and the like), the hook
saves the floor's files as a restore point: every file in the floor's own folder that git doesn't
ignore, and nothing outside it, even when that folder sits inside a bigger repository. Files that look
like secrets (`.env` files, keys, certificates, credentials and the like) are never saved, even ones
git tracks. It knows them by their names only, so keep anything private in `.gitignore` as well: that
is what really keeps it out. It uses git, beside the project's own history: your branch, what you have
staged and your files are left as they are, and `git log` shows nothing new unless you ask it for
`--all`. A folder that isn't in git gets none. The hook keeps a list of its own for each floor inside
the repository's `.git` folder, so after the first restore point the next ones are quick. A floor's
folder so big that saving takes too long (20 seconds for one step, or 40 in all) gets no restore points
for six hours, so its agents aren't held up.

Each conversation's page and each floor's page list its restore points. With control on (step 4), **Go
back to here** puts the floor's files as they were then: those changed since are put back and those
deleted since come back. Files that weren't there then, made or committed since, are left where they
are, and listed. Secret-looking files are left as they are. It keeps how things are first, as a restore
point of its own, so going back can be undone too, and if it can't keep that, it doesn't go back. It
won't while an agent working in the same folder is at work or waiting on you: let it finish, or stop
it, first. The last 40 restore points are kept; git tidies older ones away in its own time.

## 17. A shelf of how-tos

Write down how your company does things, a short Markdown file each, and list them in `company.json`'s
`howtos` (docs/data.md, "How-tos"). Each agent in a floor's folder is told that floor's how-tos, and
those every floor shares, as it starts, with where to read each one, and is asked to follow the one
that covers what it is about to do. In the building they stand on the Library's shelf.

## 18. Your plan's limits, and when you'd reach them

Claude Code and Codex each stop your agents when your plan's limit for the next five hours, or for
the week, is used up, and the usual complaint is reaching it without warning. Each says how much is
used and when it starts again, and Arnheim keeps a few hours of those readings. Activity's "Your
plan" card shows each limit, how much is used, and when you would reach it at this pace if that comes
before it starts again: "At this pace you reach it around 15:40, before it starts again at 17:00." A
five-hour limit goes by the last hour's pace, a weekly one by its average since the week began. When
one would run out first, the card names the floor whose agents spent most today, so you know where to
slow down, and with control on it has **Pause everyone** (step 7). Ask the receptionist "how much of
my limit is left?" to hear it.

Claude Code says it to its status line, so `connect/setup.py` sets the status line to
`connect/usage.py`. By hand, in `~/.claude/settings.json`:

```json
"statusLine": { "type": "command", "command": "python3 /path/to/arnheim/connect/usage.py" }
```

It shows a short line of its own ("Arnheim · 5h 42%"). To keep your own status line instead, give
its command after `--then`: `python3 /path/to/arnheim/connect/usage.py --then 'your command'`.
Codex says it in each conversation's own record, which Arnheim reads as Codex's hooks run (step 9),
so there is nothing to add for it.

## 19. Hand-overs: the next agent hears what the last one finished

A new conversation knows nothing of the others, so agents redo work that is already done, or undo
it. When an agent on a floor finishes a turn in which it changed files, Arnheim keeps a few lines of
it: what it was asked, what it said last, and the files it changed. The next conversation to start on
that floor, Claude Code or Codex, is handed the last five, three days back at most, as it starts,
with whether the floor's check (step 5) passed after each, and asked to look before it begins. What
the others said is quoted as information, never as instructions, and a conversation is never handed
its own work back.

## 20. Switches: every feature on or off

The **Switches** in Settings turn each feature on or off, at once and for every start. They are
only on the page on the computer that runs `serve.py`, never on a phone or another computer, and a
change needs that page's own token.

- **Your agents:** answering them from the building (step 4), hand-overs (step 19), the company's
  memory (step 6), how-tos (step 17), Always allow (step 4), proving the work (step 5), the review line
  (step 12), the budget brake (step 7), restore points (step 16), and the warning when two agents
  change one file (step 10). The hooks read them at each event, so a new setting holds from the agent's
  next step. Off keeps what was there: the memory, the standing allows and the budgets wait until
  their switch is on again.
- **While Arnheim runs:** the receptionist and your assistant thinking with Claude (`--brain`),
  routines (`--routines`, step 13), pings (`--pings`, step 15), looking in project folders
  (`--no-git` turns it off, step 3), and looking for a newer Arnheim (below).
- **On this page:** the Your plan card (step 18), carrying on at a limit (step 21), and, on this device,
  desktop alerts (step 4) and the talking switches, which are each browser's own.

**Look for a newer Arnheim** is on unless you switch it off. When Arnheim's folder is a git checkout
of github.com/allwhenlabs/arnheim, `serve.py` asks GitHub as it starts and once a day whether `main`
has changes this copy hasn't, sending only this copy's commit. If it has, this computer's Needs you tab says
"A newer Arnheim is out", with how many changes, and **Update now**: `serve.py` runs `git pull
--ff-only` in its own folder and starts itself again with the same words, and the page reloads. It says
why when it can't, such as changes of your own in the folder. By hand: `git pull` in Arnheim's folder,
then start it again. A copy with commits GitHub doesn't know, or no network, simply gets no notice.

They are kept in `data/serve.json`, beside setup's answer about control, as `true` or `false`, such as
`{ "control": true, "handovers": false }`; a switch not there is at its usual setting. A word given to
`serve.py` as it starts (`--control`, `--no-control`, `--brain`, `--routines`, `--pings`, `--no-git`)
holds its switch for that start, and the page shows it as set by that word. With `--lan` or `--share`,
control and the brain stay off. Phones (`--remote`), the network (`--lan`, `--share`) and starting at
login (`--always`) are only ever in the terminal.

## 21. Carry on at a limit

Reaching your plan's limit in the middle of the work is the loudest complaint about every coding agent,
and the usual way round it is to keep both Claude Code and Codex and switch to the other. Arnheim does the
switching with you. When a conversation's agent will reach its 5-hour or weekly limit within about half
an hour at this pace (step 18), or has reached it, and the other agent is on this computer with room
left, Needs you shows one item for that conversation:

> Claude Code's 5-hour limit runs out in about 20 minutes, before it starts again at 16:10. Carry on in Codex?

It works both ways, Codex to Claude Code too. It is offered for each conversation at work in the agent that
is running out, and for one that stopped on its limit in the last two hours, once for each.

- **Carry on in Codex** (with control on, step 4) starts the other agent on the same floor, in the floor's
  folder, with a hand-over: what the conversation was for (its first request), the latest request, its
  task list, the files it changed, its last words, and that the first agent reached its limit, so it
  carries on from there and doesn't redo finished work. As in step 11, it is also told it was started from
  the building, and the floor's check. If the first one is still at work, it stops at its next step, so
  the two never change the same files. **What Codex is told** shows the hand-over before you press.
- **With control off**, the item shows the hand-over instead, with **Copy**: start the other agent in the
  floor's folder and paste it in.
- **Not now** hides it for that conversation, in this browser, until that limit starts again.

Codex starts without a window, as `codex exec --json --sandbox workspace-write -`, with the hand-over on
its standard input: it may change files in the floor's folder, and nothing outside it, without the network
unless your Codex settings allow it. Codex works only in a folder kept in git: on a floor that isn't, the
button says so, and **Copy**, under What Codex is told, gives you the hand-over. Codex's hooks (step 9) show it on its floor like any Codex conversation, and you
talk to it and stop it from the building as you would a Claude Code one started there. `ARNHEIM_CODEX`
names another `codex` command, as `ARNHEIM_CLAUDE` does Claude Code's.

To know when a Claude Code conversation stopped on its limit, `connect/setup.py` adds one more hook,
`StopFailure`, which Claude Code runs instead of Stop when a turn ends on an error from its service. By
hand, beside step 2's:

```json
"StopFailure": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }]
```

For the hand-over, the feed also keeps the first words of each conversation's first message. It is a
switch in Settings (step 20), **Carry on at a limit**, on unless you switch it off.

## 22. Secrets in your agents' settings

When you choose "Yes, and don't ask again", Claude Code saves the command as a rule in
`.claude/settings.local.json`, word for word, so a command that named a token or a password keeps it
there. Copies of that file with passwords and tokens in them have been found in public repositories on
GitHub. Codex's rules, and the MCP servers your agents use, can hold keys too.

When it starts, and every minute while it runs, `serve.py` reads the files where agents keep their
settings, in each floor's folder and at the top of its repository, where newer Claude Code keeps the
local file:

- `.claude/settings.json` and `.claude/settings.local.json`: Claude Code's allow rules, environment
  and hooks,
- `.mcp.json`: the project's MCP servers,
- `.codex/config.toml` and `.codex/rules/*.rules`: Codex's settings and command rules.

It looks for keys in the shapes Anthropic, OpenAI, GitHub, GitLab, Slack, AWS, Google, Stripe, Hugging
Face, npm and others give them, private key blocks, a bearer token, a password in an address
(`user:password@`), a password or token given to a flag (`--password ...`) or to a name
(`DB_PASSWORD=...`), and long random strings. A reference to a secret kept elsewhere, such as `$TOKEN`
or `${TOKEN}`, isn't one.

Then it asks git how far each has gone, and Needs you lists them, worst first. Each floor's health
counts its own (step 14):

- **Pushed**: the secret is in a commit already pushed. Change it now: taking it out here doesn't take
  it out of the history on GitHub, or wherever you pushed it.
- **Committed**: it is in a commit not pushed yet. Take it out before you push, out of that commit too.
- **Git would commit it**: the file isn't committed yet, and git doesn't ignore it.
- **Ignored**: git keeps the file out, so it stays on this computer, but any program that reads it can
  see it.

Each says what it is, the file and line, and a hint (`ghp_…1a2b`, or for a password only how long it
is), and never the secret itself. Only the page on the computer that runs `serve.py` gets them: never a
phone, `--lan` or `--share`.

**Take it out** takes only the rules or entries that hold it out of the file, and leaves every other
byte as it was, after keeping a copy of the file in `data/.secrets/undo/`, readable by you alone.
**Undo** puts the file back exactly, byte for byte, unless it has changed since. The copy holds the
secret, so it is deleted after a week, or at once with **Delete the copy now**. An agent that needs the
key can be given it from an environment variable instead: `${NAME}` in `.mcp.json`, or
`bearer_token_env_var` in Codex's settings.

**Keep git out of it**, for a file git doesn't track yet, adds it to the repository's
`.git/info/exclude`, which belongs to this copy of the repository alone and changes no tracked file.
Undo takes the line out again. For a file git already tracks, an exclude line does nothing: take the
secret out instead.

**Check again** looks at once. No agent is ever sent to fix one, since it would read the secret. Switch
the check off under Switches (step 20). `python3 connect/secret_scan.py --show` checks and says in the
terminal what it found, never the secrets.

## 23. Set your agents up well, both at once

Claude Code and Codex each want setting up, in different files. Connect my agents offers to do it for both,
in each project you connect, and `python3 connect/setup.py` asks once. Each step is ticked and said in
plain words first, and **Show the exact changes** lists every file and line. Untick anything you don't
want. In Settings, **Your agents' setup** shows what each floor has in place, and **Set up what is
missing** does the rest the same way.

It looks at a few of the project's own files to see what it is: package.json and its lock file,
pyproject.toml, go.mod, Cargo.toml, Package.swift, a Makefile's targets, Gradle and Maven files and the
like. It never opens .env files, keys or anything private, and it never guesses: what the files don't say
plainly is left out.

- **One instructions file both agents read.** Codex reads AGENTS.md. Claude Code reads CLAUDE.md, where a
  line `@AGENTS.md` brings AGENTS.md in. With neither file, it writes a short AGENTS.md from what it found
  (the language, the package manager, how to run the tests and build, the main folders, and to run the
  tests before saying a change is done) and a CLAUDE.md that is only `@AGENTS.md`. With AGENTS.md alone,
  it adds that CLAUDE.md. With CLAUDE.md alone, nothing in your project changes: Codex is told to read
  CLAUDE.md where a folder has no AGENTS.md, with one line at the top of `~/.codex/config.toml`,
  `project_doc_fallback_filenames = ["CLAUDE.md"]`. Codex reads it as it is, so files it brings in with
  `@` stay Claude Code's. With both, and neither bringing in the other, it offers one line, `@AGENTS.md`,
  at the end of CLAUDE.md.
- **Its check.** The project's own test command becomes its floor's check (step 5), only when it is sure
  of it: package.json's `test` script (never npm's placeholder), pytest or unittest, `go test ./...`,
  `cargo test`, `swift test`, a Makefile's `test` target, Gradle, Maven, `dotnet test` or rspec. Change
  it before you connect, or type one where none was found.
- **Secrets kept from Claude Code.** Deny rules in your own `~/.claude/settings.json`, once for every
  project, beside whatever is there: `Read(**/.env)` and `Read(**/.env.*)`, keys (`*.pem`, `*.key`,
  `id_rsa` and the like), and the folders that hold your logins (`~/.ssh`, `~/.aws`, `~/.gnupg`,
  `~/.config/gcloud`, `~/.kube`, `~/.netrc`, `~/.npmrc` and a few more). A Read rule stops Claude's own
  file tools and the file commands it knows, such as cat; a program it runs, such as your tests, can still
  read them. `.env.example` is kept from it too: take `Read(**/.env.*)` out if your agents need it.
  Codex has no safe setting for this yet. Its permission profiles can deny files, but they are in beta,
  replace its whole sandbox for every conversation, and would stop your tests reading .env, so that stays
  yours to choose.
- **Its check without asking.** One exact rule, such as `Bash(npm test)`, in the project's own
  `.claude/settings.local.json`, so Claude Code runs that command there, and only that, without asking.
  A line in the repository's `.git/info/exclude`, which is never committed, keeps the file out of git.
  Only a plain test, check or build command qualifies, from the same short list as Always allow (step 4):
  never one that deletes, pushes, installs or reaches the network, so `uv run pytest` keeps asking.
  Codex runs the check in its sandbox without asking already; its rules would run a command outside that
  sandbox, so its settings stay as they are.
- **The same MCP servers in both.** It lists the servers each agent has for every project, Claude Code's
  in `~/.claude.json` and Codex's in `~/.codex/config.toml`, and adds one that only one of them has to the
  other, with that agent's own command: `codex mcp add NAME -- COMMAND ARGS` (or `--url URL`), or
  `claude mcp add-json --scope user NAME JSON`. A project's own `.mcp.json` servers stay with that project:
  Claude Code waits for your OK there, and Codex would start them in every folder. A server with keys,
  headers, a sign-in or a folder of its own, or a key the secrets check (step 22) sees in its command, words
  or address, is only named, for you to add. A key in a shape that check doesn't know could still be copied,
  so keep keys in each agent's env settings.

Everything it changes is written down in `data/.secrets/agent-setup.json`, with each file as it was: a
hidden folder `serve.py` never serves, readable by you alone, since those files can hold tokens. Undo on the
page, or `python3 connect/setup.py --undo`, puts each file back byte for byte. A file you changed since
loses only what this added (a rule, a line, a check), and one you rewrote is left as yours. MCP servers
come out with each agent's own command, or Codex's config.toml put back. Running it again changes nothing.

## What is kept, and where

`connect/setup.py` keeps a copy of each file before it changes it: `data/backups/company.before-arnheim-<when>.json`
for your building, and `settings.before-arnheim-<when>.json` beside Claude Code's settings. The page's
Undo moves your building to `data/backups/company.undone-<when>.json`. Setting your agents up well keeps
`data/.secrets/agent-setup.json`, what it changed and each file as it was, until Undo (step 23).

The connectors write `data/feeds/claude-code.json` and `data/feeds/projects.json`. From Claude Code
they keep, for each conversation: its title, or the first line of your first message; the first
words of your latest message; the first sentences of the last thing Claude said; what it asks you
for; and its task titles. Nothing else from the conversation is kept, and nothing leaves this
computer, unless you serve Arnheim with `--lan`, when anyone on your network can open it, or with
`--share`, when those you give its view-only link can (README, "A view-only link").

A floor's check keeps the last lines it printed beside each conversation it checked, and a lock and
a note for its next run in `data/feeds/proof/`. The company's memory is `data/memory.json`, and the
feed notes when each conversation was last told it. For the budget, the feed keeps each conversation's
new tokens for today and how far its transcript has been read; `data/control/` keeps a pause, and how
far each floor was let go past its budget today. On a floor with a review line, the feed also
keeps what the line made of each conversation's work. Routines keep `data/feeds/routines.json`: each
routine, when Arnheim first saw it, and its last run, with a command's last lines or an agent's last
words. Pings keep `data/feeds/pings.json`: when the last was sent, what each of the last fourteen said, and whether it arrived. The replay's moments are kept a file a day in
`data/feeds/history/`, for a week, with what each floor's agents spent that day. Restore points are
listed in `data/feeds/restore.json`, and their files kept by git in each project's own repository,
under `refs/arnheim/restore/`.

The usage forecast keeps `data/feeds/usage.json`: the limits' readings, twelve hours back. Hand-overs
keep `data/control/handover.json`: a few pieces of finished work for each floor, three days back.
Carrying on at a limit keeps `data/control/carry-on.json`, which conversations were carried on, six hours back.
The secrets check keeps what it found in `data/.secrets/found.json` (each secret's kind, file, line and
hint, never the secret), and each copy for Undo in `data/.secrets/undo/`, for a week. `serve.py` never
serves that folder.
Always allow keeps `data/control/allowed.json`, what you allowed two weeks back, and
`data/control/always.json`, the commands you allow for good. `data/serve.json` keeps the switches (step 20),
setup's answer about control among them.

With control on, your messages wait in `data/control/` until Claude takes them, a permission
request and its answer are deleted once it is answered, and each agent started from the building
keeps its last words there.

A conversation leaves the building when it ends, or after twelve hours with no word from it. One
started from the building stays until then, to talk to.
Delete the files to start afresh. If the Claude Code connector meets any trouble, it writes it to
`data/feeds/claude-code.log` and lets Claude carry on.

## Anything else

Any tool can add to the building. Have it write a JSON file with any of `work.json`'s lists in it
([docs/data.md](data.md)) into `data/feeds/`, and add the file's path to `feeds` in
`company.json`. The page adds its lists to `work.json`'s, and reads it again every few seconds.
Write the whole file at once, as a new file renamed over the old one, so the page never reads half
of it.

A nightly build that shows on a machine in the basement (a basement room whose `id` is `build`),
in Python:

```python
import json, os

feed = {"jobs": [{"id": "nightly", "name": "Nightly build", "machine": "build", "state": "running"}]}
with open("data/feeds/builds.json.part", "w") as out:
    json.dump(feed, out)
os.replace("data/feeds/builds.json.part", "data/feeds/builds.json")
```

Other ideas: an issue tracker's open issues as tasks, a deploy pipeline's runs as jobs, your
websites' up-checks as `presence`. Give each item an `id` of its own, and a `project` that names a
floor.

## If nothing shows

- Feeds are read only for your own company in `data/`, not the sample, and only those named in
  `feeds`. Reload the page after changing `company.json`.
- A conversation shows only when it runs in a floor's folder, and only on a floor with a
  Conversations room. Check the folder in `company.json`.
- Try the connector by hand (above), and look in `data/feeds/claude-code.json`.
- `data/feeds/claude-code.log` says what went wrong, if anything did.
- `python3 connect/projects.py` without `--every` says what it found, and why a folder was left out.
