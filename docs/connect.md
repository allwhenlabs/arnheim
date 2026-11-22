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
    "PreToolUse": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }],
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
  "PreToolUse": [{"matcher": "apply_patch|Edit|Write|Bash|mcp__.*", "hooks": [{"type": "command", "command": "python3 /path/to/arnheim/connect/codex.py"}]}],
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
`PreToolUse` hooks in step 2 and step 9 (Claude Code's runs before every step, and takes a restore point
only before one that changes files or runs a shell command), and `"feeds/restore.json"` in `feeds` in `company.json`. Then, before the first file an agent changes
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
  (step 12), the budget brake (step 7), restore points (step 16), the warning when two agents
  change one file (step 10), and the five parts of working beside them (step 24): looking over their
  shoulder, replies straight away, questions coming to you, reviewing together, and hold on and carry
  on; and the leads answering what you've decided (step 26) and office hours (step 27), with their
  own group. The hooks read them at each event, so a new setting holds from the agent's
  next step. Off keeps what was there: the memory, the standing allows and the budgets wait until
  their switch is on again.
- **While Arnheim runs:** the receptionist and your assistant thinking with Claude (`--brain`),
  routines (`--routines`, step 13), pings (`--pings`, step 15), looking in project folders
  (`--no-git` turns it off, step 3), looking for a newer Arnheim (below), the daily cycle (step 29),
  with its two times under its switch, and the night shift (step 30), with its quiet hours and share
  under its switch.
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

## 24. Work beside your agents

Working with an agent should feel like working beside a colleague: you can see what they are doing, ask
how it's going, steer them as they go, look over the work together, and they come to you when something
isn't clear. Each part below is a switch (step 20), on unless you switch it off. The first needs only
step 2's hooks; the rest need control on (step 4).

- **Look over their shoulder.** Each agent's page, and its desk monitor on a walk, shows what it is doing
  right now in plain words ("Running npm test", "Editing src/login.js") and for how long, its to-do list
  ticking off, and the lines it has changed so far, in red and green, as it works. Claude Code's edits
  come with their line numbers. A file it writes whole is compared with the file as it was, kept a moment
  before it was written; when that couldn't be read, the whole new file shows, marked so. Codex's patches
  show the same way. **Changes so far** puts the agent's changes file by file, and beside them everything
  not yet committed in the floor's folder, when that folder is kept in git. That second part is everyone's
  changes there, yours and other agents' included, and says so.
- **A reply straight away.** Say something to an agent at work and it answers at once, in its own words,
  from what the building can see: "Got it. I'm running npm test right now, 40 seconds in. I'll pick this
  up as soon as that's done." It says plainly when it will read your message: at its next step, once a
  permission it waits on is answered, straight away while you hold it, or the next time it works if it
  has finished. Each message shows as queued, then taken (with when), then answered, and its real reply
  follows as before. No model is asked for the first reply: it comes from the agent's screen.
- **Questions come to you.** When Claude asks you something with its question tool, or ends a turn with a
  question, the question shows in the building, with its choices, and on Needs you. While you are using
  the building, the agent waits a while for your answer there (as long as a permission request does, two
  minutes unless `ARNHEIM_CONTROL_WAIT` says otherwise) and carries on with it. Your answer reaches
  Claude Code as the question tool's own answers, the way Claude Code's hooks are made to give them. With
  no answer in time, or nobody there, the agent asks in its own window as it always did, and the question
  stays as a card: answering it later reaches the agent as a message, at once for an agent started from
  the building, or at its next step for any other. A message you send while it waits on a question counts
  as the answer. Agents started from the building are told to ask rather than guess on anything that
  matters.
- **Review together.** **Walk me through it** asks the agent to explain its changes file by file, in a
  sentence or two each, and its answer comes back as any reply does, to show and read out beside the
  changes. Tap a changed line, or say "the second change", then say what you want: it reaches the agent as
  one message tied to that file, that line and what the line says. **Looks good** runs the floor's check on
  the work again (step 5, "Check it again"); on a floor with a review line, the line read the work when
  the turn ended (step 12).
- **Hold on, and carry on.** **Hold on**, or saying "hold on", holds the agent at its next step without
  ending its turn. What you say while it is held reaches it straight away; it answers, and is held again
  at its next step, so you can talk it through. A step it was about to take when you spoke is turned down,
  so it reads you first, and takes it again only if it still fits. **Carry on** lets it go on in the new
  direction, keeping what it has done. A hold ends when you say carry on, after ten minutes, or two minutes
  after nobody is using the building, and the agent is told which. **Stop** still stops it.

**Codex** gets all of it but the question tool, which it doesn't have: its commands and patches on its
screen, a turn that ends with a question, and holding before its next command or patch, since its hooks can
turn a step down or add words to it. Stop there turns the step down and stops it at the one after, as for a
permission. Tried with a real Codex (0.169): its commands showed on its screen, a message sent mid-task was
followed, Hold on, words while held and Carry on worked, and a turn that ended with a question went on with
the answer given in the building. Codex runs a project's own hooks only in a folder it trusts.

`python3 connect/setup.py` adds what this needs. Claude Code's PreToolUse hook now runs before every step,
with no matcher: your messages and a hold's words reach Claude there, as words added before the step, and
its question tool and a helper's long run come through it too. Handed over after a step, your words would
sit inside that step's output, and Claude Code rightly won't take instructions from a tool's output.

```json
"PreToolUse": [{ "hooks": [{ "type": "command", "command": "python3 /path/to/arnheim/connect/claude_code.py" }] }]
```

Running it again over an older install puts this one in place of the old matcher, beside any hooks of your
own, and `--undo` takes it out with the rest. A hook never waits longer than nine and a half minutes in one
go, under Claude Code's and Codex's own limit of ten; a hold that lasts longer goes on at the next step.
`ARNHEIM_HOLD_MOST` and `ARNHEIM_HOLD_NOBODY` change a hold's ten and two minutes, in seconds.

**Where it is kept.** Each agent's screen is a file in `data/live/`, with an index of them all: the last 200
steps, the last 200 changes, each cut to 80 lines of 400 characters, the to-do list and the last 40
messages, 600 KB at most for one conversation, for twelve hours after it was last heard from. Anything
that looks like a password, a token or a key is hidden before it is kept: what the secrets check finds
(step 22), and a value given to a name such as `password` or `client_secret`, quoted or not, as code,
settings files and commands write them. It can't promise to find every secret, so treat the screen as you
would the agent's own window. It holds lines of your code and the commands your agents run, so `serve.py` gives it to this computer
only: never with `--lan`, never through a view-only link, and a paired phone sees it only through control,
while this computer lets that phone control agents ([phone.md](phone.md)). Questions and holds wait in
`data/control/` with the rest of control's mail.

## 25. One front door

With control on (step 4), anything you say or type that is work becomes a **ready task** for a floor. Say it
to the receptionist, a floor's lead or anyone in Talk, type it in the **What needs doing?** box on Needs you
or in a floor's Work room, or do either from a paired phone: "the login feels slow on Tidepool", "fix the
footer links", "we need a dark theme on Lantern", "get someone to tidy the tests".

**Which floor.** The one your words name. Else the floor you are on: a lead's own, or the floor page you are
looking at. Else one your words begin to name ("on tide"). Else the only floor there is. With several and
none of those, the lead asks which, in one line, and you say its name or tap it.

**What a ready task says.** A short title, from your words. **Done when**: one sentence. **Proven by**: the
floor's check (step 5), or the test command the project's own files name, as setup finds it (step 23), or
"You look at it". Its agent: Claude Code, unless the floor says `"agent": "Codex"` in `data/company.json`. And
an **estimate**, only once three or more pieces of work have finished on that floor: the median time from the
day's moments (step 8) and the median spend from the feed. With less, there is no estimate, never a guess.

With the brain on ([brain.md](brain.md)), the floor's lead writes the title and Done when from your words. What it writes is
checked: one line, not too long, nothing that looks like a password or token, and nothing the building
refuses or can't take back that you didn't say yourself. If either fails, the rule's words are used.

**Start.** The lead reads it back in a sentence or two and asks "Start it?". Say "yes" or "start it", or tap
**Start** on its card; "no" leaves it ready. Starting hands a new agent your words, Done when and Proven by,
and asks it to prove the work that way before it says it is done. Each card also has **Change** (the title and
Done when) and **Drop**.

**One at a time on a floor.** While an agent started from the building is at work on a floor, the next one
waits there, **queued**, and starts when the last finishes. The card says what it waits for, and Needs you
says what is next on each floor ("Next on Tidepool: ..."). Nothing starts while every agent is paused or while
the floor is over today's budget (step 7): it waits, queued, and starts once you resume them or let them go on.

**Start ready tasks by themselves** (a switch in Settings, off unless you switch it on) starts each new ready
task without the tap, one at a time on each floor. It never starts one by itself that mentions a password or a
key, or does something that can't be taken back (merge, publish, deploy, push, delete and the like): those
wait for your Start.

**What it won't take.** Words with a password, token or key in them are refused and never written down: say
it again without it. Work the building never hands out is refused too: signing in, sending messages or
posts, buying or paying for you.

**Where it is kept.** Each ready task is a file in `data/control/intake/`, written whole. `serve.py` never serves
that folder, to anyone, this computer included: the page and a phone read the tasks only through control.
Ready and queued tasks are kept for 7 days, started, finished and dropped ones for 30. **One front door** is a
switch in Settings too, on unless you turn it off; with it off, the receptionist hands out work as in step 11.
## 26. A chain of command

In a well-run company, a question that has been settled before doesn't climb to the top again. When an
agent asks you something, with Claude's question tool or a turn that ends with a question, its floor's
lead looks first at what you have already decided. If that clearly answers it, the lead answers for you,
and says from which decision: "Answered from your decision on 18 Nov: use pnpm". The switch is **Leads
answer what you've decided** (step 20), on unless you switch it off. It needs control on (step 4) and
Questions come to you (step 24).

**Clearly** means one of these, and nothing looser:

- **The same question, asked before on the same floor, that you answered with Remember my answer
  ticked.** The tick sits beside every question's answers, on Needs you and in the sitting (step 27). For
  a question with options, your answer must still be one of them, or the options must be the same as
  before. It never keeps a question or an answer with a password, token or key in it, or one about what is
  never answered for you (below): it says so, before anything is sent.
- **A decision in the company's memory (step 6) that names exactly one of the question's options**, and not
  after "never" or "not", and shares at least two words that carry meaning with the question and its
  options: the same test as "You decided before" on Needs you. "Use pnpm, never npm or yarn" answers
  "Which package manager?" with pnpm.
- **With the brain on** (`--brain`, docs/brain.md), the floor's lead may also judge whether one of your
  decisions really answers it, and must quote it word for word. A quote that isn't one of your decisions,
  or an answer that isn't one of the options, answers nothing. Without the brain, a turn that ends with an
  open question is answered only when it is the same question you answered before.

**Never answered for you:** anything about secrets, passwords or keys, money, deleting, pushing or merging,
publishing or releasing, or sending a message or an email, whatever was decided; a question no decision
answers; and a kind of question you marked **Always ask me this** (the other tick). Permissions are never
answered from a decision: only Always allow's exact commands go without you (step 4), as before.

An answer goes back the way your own would: as the question tool's own answers (Claude Code's hooks give
PreToolUse "allow" with the answers for this), with words beside it saying it came from your decision, or
for a turn that ended with a question, as the words it carries on with. Each one is listed on Needs you
under **Answered for you**, and in the sitting, with **Undo**. Undo tells the agent "The person changed
this", with what you write or "don't take that earlier decision as the answer", before its next step (after
it for Codex, which takes messages there), and that decision is never used for that kind of question again.
Settings lists **What the leads answer from**: your remembered answers and the questions you always answer
yourself, each with **Remove**.

## 27. Office hours

Agents shouldn't interrupt you all day. Switch on **Office hours** (step 20, off unless you switch it on)
and choose up to four times a day in Settings: 13:00 and 18:00 unless you choose others. Each is open for
half an hour, and **Open a sitting now** opens one whenever you like.

Outside office hours, while nobody is using the building:

- **Claude's question tool is answered at once** with: "The person is away until 13:00 (office hours). If one
  option is clearly safe and easy to change later, take it and say which you took; otherwise put this aside,
  carry on with work that doesn't depend on it, and if there is none, finish your turn saying what you
  need." The question waits for the sitting. Answering it there reaches the agent as a message.
- **A turn that ends with a question** waits as a card, as it always did.
- **A permission request** asks in the agent's own window, as it always did, and is listed for the sitting,
  with whether it was answered there.

**Urgent things still reach you at once**, with a desktop alert (step 4): a permission that reaches
something that may be private, or that would delete in bulk, push, publish or deploy; an agent close to
its plan's limit (step 18), or about to stop at it (step 21); an agent asking the same thing a second
time; and a question about secrets, money, deleting, pushing, publishing or sending (its question, header or
any option), which is never told you are away: it waits for you as a card. While you are using the
building, or in an office hour, nothing waits: everything is as it always was.

At each office hour the page sends a desktop alert, "Office hours: 7 things, about 4 minutes", and Needs
you says what waits. **The sitting** takes you through it one thing at a time, full screen on a computer
or a phone, "3 of 7": each question, with its options as buttons and a box for your own words; each
permission waiting now, with Allow, Deny and Later (the A, D and L keys) and how careful to be; what
waited while you were away; then what the leads answered for you, to glance at, with Undo; and ready
tasks, where the building has them. In Talk you can say "next", "skip", "allow", "deny", "the first
one", or answer in your own words. A spoken "allow" follows the same rule as at the desk: never for
something that may be private, nor with Answering by voice switched off. Typed or tapped, it goes. It
ends with a short summary of what you did.

Codex gets all of it but the question tool, which it doesn't have. The times are kept in
`data/serve.json` as `"office_times"`, beside the switches.
## 28. Show me

Finished work comes with something to look at, so you can review it by seeing it, not by reading code.
Tell Arnheim how to show a floor's work in `data/company.json`, with either or both of these:

```json
{ "id": "lantern", "label": "Lantern", "folder": "~/code/lantern",
  "show_url": "http://localhost:3000/",
  "show": { "run": ["npm", "run", "screenshots"], "timeout": 60 } }
```

- `show_url` is a page of the project to take a picture of: usually its dev server's address, or a page
  inside the floor's folder, such as `site/index.html`.
- `show` is a command that writes pictures or prints what it did. It runs in the floor's folder, with no
  shell and with its time limit (60 seconds unless `timeout` says otherwise). It is handed
  `ARNHEIM_SHOW_OUT`, a folder to write `.png` or `.jpg` pictures into (six at most, 6 MB each),
  `ARNHEIM_SHOW_PHASE` (`before` or `after`) and `ARNHEIM_SHOW_URL`. What it prints is kept too, its last
  30 lines, with anything that looks like a secret hidden.

**What you see.** When an agent's turn finishes work on that floor (it changed files, and it doesn't end
by asking you something), a **Show me** card comes up on Needs you ("3 things to look at") and on the
conversation's page. It shows the page as it is now beside the same page from before the work started,
at a desktop width and a phone width. Tap a picture to see it bigger. Beside them: whether the floor's
check passed (step 5), the lines changed in short, and what the agent said. Then:

- **Looks good** marks the work as looked at and approved. Work started from a ready task (step 25) marks
  that task looked at too.
- **Not quite** opens a box for what to change. It reaches the agent as any message from the building does
  (step 4): an agent started from the building that has finished carries on with it straight away, and any
  other reads it at its next step, or the next time you send it something in its own window. In Talk, say
  "looks good", or "not quite" and what to change.
- On a phone, swipe right for Looks good and left for Not quite, as well as the buttons. Only a clearly
  sideways swipe counts, so scrolling up and down never answers anything.

**How the pictures are taken.** With a browser already on this computer, Chrome, Chromium or Edge, without
a window (`--headless --screenshot`), with a profile of its own that is thrown away afterwards and with
its own syncing, updates and reports switched off. Arnheim looks for it where each system keeps it: the
Applications folders on a Mac, Program Files on Windows, and the usual commands on Linux
(`google-chrome`, `chromium`, `microsoft-edge` and the like). `ARNHEIM_BROWSER` can name another, or
`none`. Each picture has 30 seconds (`ARNHEIM_SHOW_SECONDS`). With no browser, or no `show_url`, the
floor's `show` command runs instead; with neither, the card says why there is no picture. If nothing
answers at the `show_url`, the card says its server may not be running.

The picture from before is taken as the agent starts its first change after your message, so it shows
the work as it was. The agent waits for it at that one step, at most 20 seconds (`ARNHEIM_SHOW_BEFORE`);
a picture usually takes a second or two. The picture from after is taken in the background as the turn
ends, so the agent never waits for it. An agent started from the building whose hooks didn't see it gets
its card as it finishes.

**Where it is kept.** Everything stays in `data/shows/` on this computer: a small file for each card and
its pictures. Nothing is sent anywhere. `serve.py` gives that folder to this computer only, never with
`--lan` or through a view-only link; a paired phone that may control agents gets each picture through
control, as do pages whose server keeps the data elsewhere (`show_image`). The last 20 cards of each
conversation are kept, for 30 days, and 200 in all. When a conversation finishes more work, its newest
card is the one Needs you counts. Show me is a switch (step 20), on by default; it does nothing on a
floor that doesn't say how to show its work, and with it off nothing is taken and no card shows. The
made-up company has three made-up cards, with pictures drawn by the page.

## 29. The daily cycle

A plan in the morning and a close in the evening, for the whole company. It is a switch in Settings
(step 20), **The daily cycle**, off unless you switch it on, and it needs control (step 4) to start
anything. Under the switch are its two times: 09:00 for the plan and 18:00 for the close unless you set
others. They are kept in `data/serve.json` beside the switches, as `"day_plan": "09:00"` and
`"day_close": "18:00"`.

**The plan.** At the plan time, each floor's lead proposes the day for their floor, in this order:
what was approved yesterday and didn't start, or was stopped before it was done; work whose check
failed (step 5); the ready tasks at the front door, when your Arnheim has it; the floor's open tasks;
then a next step toward each of its open goals. Only floors with a folder on this computer are
planned, since only they can start an agent. A floor proposes up to three things, and one when your
plan is tight. The plan is fitted to the allowance left today:

- **Your plan's limits** (step 18), as Claude Code and Codex last reported them. The plan says how much
  of each weekly limit is left, and how much that is a day until it starts again. It is tight when a
  weekly limit is used up, or would be at this pace before it starts again. A 5-hour limit that is
  used up is said, and only delays the work. With no readings at all, the plan says so plainly
  ("No forecast") and isn't fitted to them: it never makes a number up.
- **A floor's budget** (step 7): once what a piece of work costs there is known (below), a floor
  proposes only as many things as what is left of its budget today allows. A floor past it says so.

An item says what it may cost only when the floor has finished at least three pieces of work Arnheim
counted: the middle of what they spent, such as "about 300 thousand tokens". Otherwise it says
nothing about cost.

**Approving it.** The plan shows on Needs you, just after the first thing an agent is waiting on you for.
**Approve the day** approves it all with one tap, **Approve** beside a floor approves that floor, and
the box under it changes it in words:

- "drop the second one on Tidepool", "drop the README one"
- "add: tidy the README on Lantern", or "add to the plan fix the login on Lantern" (never words with a password,
  token or key in them: it says so in the front door's words, and writes nothing down)
- "do the third one first on Kitefield"

With one floor planned, the floor can be left out. **Make it again** makes the plan afresh, keeping
what you approved, added and dropped.

**Starting the work.** Approved items start in order, one at a time on each floor: the next starts
when the last is no longer at work. With the front door, an item goes in as a ready task on its
floor, with the plan's title, and is started there once, so it carries Done when and Proven by and
the plan follows its agent; if the front door queues it, the item says why it waits. With the front
door switched off, it starts as an agent started from the building, told it is one item on today's
approved plan, with the floor's check as for any agent started there. Nothing starts while every agent is paused, or on a floor past its budget today: the
item says why it waits, and starts once that changes. An item that has started can't be dropped: stop
its agent instead.

**The close.** At the close time: what was proven today (a check that passed after the work), what is
stuck and why (a check that failed, a plan item that was stopped or never started, and what it waited
on), what needs you tomorrow (questions agents asked you, tasks marked as needing you, and items you
didn't approve), and what today cost, floor by floor, in new tokens (step 7), with how much of each
weekly limit is used. In the evening it takes the plan's place on Needs you; Activity has both.

**Out loud and on a phone.** Ask the receptionist or your assistant "what's the plan?", "approve the
day" or "how did today go?", and they answer for the whole company. Ask a floor's lead and they answer
for their floor: "what's the plan?", "approve the day" (that floor only), "drop the second one", "add:
tidy the README". "Make the plan" makes it now. A paired phone that may control agents
([phone.md](phone.md)) has the same cards, through control.

**When it runs.** Nothing runs while Arnheim isn't running. `serve.py` looks every half a minute, and
the page's own reads look too, so a plan time missed while this computer slept or Arnheim was stopped
makes the plan when the page next opens. A desktop alert (step 4) comes when the plan is made ("Today's
plan is ready: 6 things on 3 floors") and when the close is, while the page is in the background.
`python3 connect/day.py` makes what is due and gives back at once, for a scheduler of your own;
`--plan` and `--close` make them now, and `--show` says today's plan.

**Control's names.** For a page of your own, or a phone: `day` reads today (`{date, plan_at, close_at,
made, plan: [{floor, label, lead, approved, items: [{title, why, cost?, state}]}], approved, allowance,
close}`; `null` in `state` while it is off), `day_plan` makes or refreshes the plan, `day_approve`
takes `{floors}` or nothing for all, `day_change` takes `{floor, words}`, `day_close` makes the close
now, and `day_times` takes `{plan, close}`. An item's state is proposed, approved, started, done,
stopped or failed.

The made-up company has a made-up plan and close (`sample/day.json`) that say so. Approving or
changing it changes only the page: nothing starts.

## 30. The night shift

Your Claude Code and Codex allowances start again on a timer, and whatever you haven't used by then
is lost. The night shift spots allowance that would go unused and runs work you have already approved
in those gaps, overnight. It is a switch in Settings (step 20), **The night shift**, off unless you
switch it on, and it needs control (step 4) to start anything. Under the switch are its settings, kept
in `data/serve.json` beside the switches: the quiet hours (`"night_from": "23:00"`, `"night_to":
"07:00"` unless you set others; they may run across midnight) and the share (`"night_share": 80`),
how much of what would go unused it may use.

**Which work.** Only what you approved for it:

- a ready task at the front door (step 25) you ticked **Tonight** on its card, or said "do it tonight"
  to when the receptionist asked "Start it?", or said with "tonight" at the end ("fix the footer on
  Tidepool tonight");
- an item of the day's approved plan (step 29) that didn't start. While the night shift is on, the
  daily cycle leaves its approved items to it during the quiet hours.

Never one that names a password or key, is work Arnheim never hands out (signing in, sending, buying),
says something the chain of command never answers for you (secrets, money, deleting, pushing,
publishing, sending: step 26), reaches outside this computer or tidies away what is there (uploading,
syncing, a pull request, a reply or a comment, pruning or cleaning up), or asks you to decide something.
Those stay listed, with why they wait for you, and the Tonight tick refuses them at once. An item of the
day's plan is read in full, whatever it came from, not only its title. The words err on the safe side:
"fix the sync bug" or "add comments to the parser" waits for you too. Never while every agent is
paused, on a floor past its budget (step 7), or on a floor whose folder isn't kept in git, where no
restore point could be kept.

**When.** Only during the quiet hours, and only while the forecast (step 18) says some of an allowance
would go unused before it starts again. For each agent, the weekly limit decides: when it starts again
before you're back, all of what is left of it would be lost; when it starts again later, the forecast
at your own pace this week says how much would be left. A 5-hour window that ends before you're back
is said too, since what it doesn't use is lost when the week has room to spare. The night shift may
use your share of what would go unused, and never comes closer than 10 points to any limit (its
margin). With no forecast (no reading in the last six hours, or not enough to tell your pace), it runs
nothing and says why. The cap is set once a night, from the reading when its first run on that agent
starts, and each start after that waits for a reading taken since the last one began, so it never runs
twice on the same old numbers. Codex reports its limits through its hooks as it works. Claude Code says
them as a run's first request is answered (its `rate_limit_event`), and again only when the week's or
the five hours' use moves by a whole point, so a quiet stretch brings none: while a Claude Code night
run works and the newest reading is more than 10 minutes old, the night shift asks
for a fresh one with a tiny probe of its own (`claude -p "ok"` on Haiku, one turn, no tools, no hooks,
no session kept, in an empty folder under `data/night/`, at most a minute, one at a time), kept as a
run's reading is. Claude Code keeps no conversation of it, only a small folder for that folder among
its projects.

**Each run.** One agent at a time on each floor, Claude Code or Codex as the floor says, started through
the front door (or, with it switched off, as an agent started from the building). Its first message
says it is on the night shift: work only on this, and never push, publish, deploy, merge, upload, open
a pull request, send, reply or delete. What guards that, and how far:

- Where Arnheim's hooks are set up (step 2), they turn down the steps they recognise by their words,
  whatever your own allow rules or permission mode would let through: any command (Bash, Monitor,
  PowerShell, Codex's shell) that pushes, publishes, deploys, sends, uploads, syncs, opens a pull request
  or deletes files in bulk, with options before git's or gh's own word too; one that names a script for
  any of that (`./ship.sh`, `npm run release`, `make publish`: the words push, publish, release, ship,
  deploy or upload anywhere in it); and one that would undo the git settings below. Another server's
  tool is used only when its own name starts with a word that only reads (get, list, read, search,
  fetch, view, find, query, describe, show, status); the rest wait. A command you allowed for good
  (Always allow) still asks. For Codex, its hooks see another server's tools only once Connect has run
  again since this was added (its PreToolUse matcher takes `mcp__.*` now).
- Git's pushes to another computer fail in a night run whatever starts them, the agent or a script of
  the project's: its agent starts with git settings in its environment that send an `https://`,
  `http://`, `ssh://`, `git://` or `git@` address nowhere for a push. A push to a folder on this
  computer still works.
- Publishing some other way from inside a script, under a name the words don't catch, may slip past
  them, and so may a remote whose push address is set apart from its address in its own settings, or one
  written another way (`someone@host:path`). A tool whose name starts with query or fetch is let through
  by its name, and what it is given isn't read. Switching the night shift off while one of its agents
  works stops the hook turning its steps down, though its git pushes still go nowhere until it ends.
  A command over 20,000 characters isn't read: it waits for you.
  Claude Code's and Codex's own permissions stay the last guard. When you carry on a night run's
  conversation yourself, its turns start as yours always do.

The night shift keeps a restore point of the floor's files just before it starts each run (step
16), so there is a way back even where Arnheim's hooks aren't set up; with no restore point, nothing
starts. It counts as proven only when its floor's check passes after its last change (step 5), which
Arnheim knows only where its hooks see the agent's steps: an agent whose steps it never saw is reported
as not proven, never as having changed nothing. When a reading shows the night's cap reached, or the
week started again so what would have gone unused is gone, or nothing says how close the limit is (for
Claude Code, two probes in a row brought no reading; for Codex, none has come for 15 minutes), it is
stopped at its next step (the brake;
an agent started here that hasn't stopped two minutes later is stopped outright), and what is left
waits for another night. Moving the quiet hours during the night moves its end too.

**In the morning.** A **Night shift** report on Needs you, once the quiet hours end: "4 things finished
overnight, 3 proven, 1 not", each with its proof, a link to its Show me card (step 28) when there is
one, and **Undo**, which puts its restore point back (and keeps one of how things were first, so Undo
can be undone too). When later runs changed the same floor, it says what Undo would take back with
it. Undo waits while one of the night's agents is still at work on that floor. **Got it** puts the
report away. A desktop alert says the same when the page next opens, and the
daily cycle's plan carries the line too, when it is on. Activity shows what is approved for tonight,
what waits for you and why, the forecast in words, and the last runs.

**Out loud and on a phone.** Ask the receptionist or your assistant "how did the night go?" or "what's
on tonight?". A paired phone that may control agents ([phone.md](phone.md)) has the same report and
ticks, through control.

**When it runs.** Nothing runs while Arnheim isn't running: `serve.py` looks every half a minute, and
the page's reads look too. `python3 connect/night.py --show` says what the night shift would do now,
and changes nothing.

**Control's names.** For a page of your own, or a phone: `night` reads it (`{on, quiet: {from, to},
share, margin, quiet_now, from, back, window: {known, open, words, agents}, queued: [{kind, id, title,
project, label, agent, why}], ticked, ran, said, report: {id, words, items: [{id, title, label, agent,
state, proof, show, undo, why}]}}`; `null` in `state` while it is off), `night_set` takes `{on, quiet:
{from, to}, share, seen}` (seen: a report's id, to put it away), `night_tick` takes `{id, tonight}` for a
ready task, and `night_undo` takes `{id}` for one of its runs.

The made-up company has a made-up night (`sample/night.json`) that says so. Undo, Show me and the
Tonight ticks there change only the page: nothing runs.

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
The daily cycle keeps each day's plan and close in `data/day/<date>.json`, two weeks back (step 29), for this
computer only: never to another computer, a view-only link or a paired phone, which reads today's plan through
control. Words you add to it that have a password, token or key in them are refused, as the front door refuses them.
The night shift keeps each night in `data/night/<date>.json` (the evening it began), two weeks back:
what it ran, the night's cap for each agent, why anything waited, and the morning's report; and the
ready tasks you ticked Tonight in `data/night/tonight.json` (step 30), and its last probe of Claude Code's
limits in `data/night/probe.json` (the probe runs in the empty folder `data/night/probe/`). They are read
only through control, never served as files.
The secrets check keeps what it found in `data/.secrets/found.json` (each secret's kind, file, line and
hint, never the secret), and each copy for Undo in `data/.secrets/undo/`, for a week. `serve.py` never
serves that folder.
Always allow keeps `data/control/allowed.json`, what you allowed two weeks back, and
`data/control/always.json`, the commands you allow for good. `data/serve.json` keeps the switches (step 20),
setup's answer about control among them.

With control on, your messages wait in `data/control/` until Claude takes them, a permission
request and its answer are deleted once it is answered, and each agent started from the building
keeps its last words there. A question an agent asked is kept there for twelve hours, a hold until
the agent has been told it ended. Each agent's screen is kept in `data/live/` (step 24), for this
computer only. Ready tasks are kept in `data/control/intake/` (step 25), 7 days while they wait and 30 once
started, finished or dropped, and never served as files.

The chain of command (step 26) keeps `data/control/decisions.json`, for this computer only: your remembered
answers, the questions you always answer yourself, and the decisions undone for a kind of question. Yours to
edit. (It was `data/decisions.json` before; it moves itself the first time it is read.) Remember my answer
never keeps an answer whose question or words have a password, token or key in them, or that is about secrets,
money, deleting, pushing, publishing or sending: it says so, and nothing is sent until you untick it. What the leads
answered for you is kept in `data/control/answered/` for two days. Office hours (step 27) keep what waited
for the sitting in `data/control/parked/`, for two days, and a sitting opened from the page in
`data/control/office.json`.

Show me's cards and pictures are kept in `data/shows/` (step 28), the last 20 of each
conversation for 30 days, for this computer only.

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
