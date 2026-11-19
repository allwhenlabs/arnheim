# Arnheim for Mac

Arnheim's Mac app runs Arnheim for you, with no terminal. Open it, and it starts Arnheim and opens the
building in your browser. Then it stays in the menu bar at the top of your screen, as a small tower.

It needs macOS 13 (Ventura) or newer, on Apple silicon or Intel, and a browser with WebGL 2 (any current
Chrome, Edge, Firefox or Safari). Arnheim runs on Python 3.7 or newer, which Apple's free command line tools
bring: if this Mac has no Python, the app offers to install them.

## Get it and open it

1. Get `Arnheim.zip`: from a release on GitHub that has it, or build it yourself (below).
2. Double-click `Arnheim.zip` to unpack it, then drag Arnheim into your Applications folder.
3. Open Arnheim. The first time, macOS stops it, because the app isn't signed with an Apple developer
   account (the last section says why):
   - **On macOS 15 (Sequoia) and later:** macOS says it can't check Arnheim. Click **Done**. Open
     **System Settings**, choose **Privacy & Security**, and scroll down to **Security**, where it says
     Arnheim was blocked. Click **Open Anyway**, give your password, then click **Open Anyway** once more
     when macOS asks.
   - **On macOS 13 and 14:** in your Applications folder, Control-click Arnheim (or right-click it),
     choose **Open**, then **Open** again.

   You do this once. After that, Arnheim opens like any other app.
4. A small window says Arnheim is starting. The first time, it downloads the pictures for the photo-real
   look (52 MB) once, and shows how far it has got. Then your browser opens the building.

If this Mac has no Python, a window says so. Choose **Install** and follow Apple's window, which takes a
few minutes. Arnheim starts by itself once the tools are in.

## The menu

Click the tower in the menu bar:

- **Open Arnheim** opens the building in your browser. Opening the app again does the same.
- **Connect my agents** opens Settings, where the page shows how to connect Claude Code and Codex.
- **Start at login** starts Arnheim each time you log in, quietly, without opening your browser. A tick
  shows it is on. macOS may ask you to allow it first, in System Settings, General, Login Items.
- **Show the log** shows what Arnheim has said, in Console.
- **Quit Arnheim** stops Arnheim, then the app.

The menu's first line says how Arnheim is: starting, running, or stopped and why. If Arnheim stops by
itself, the app starts it again, up to four times, waiting a little longer each time. If it still won't
run, the first line says so with the last line of the log, and Open Arnheim tries again.

If Arnheim already runs on this Mac (started with `python3 serve.py --always`, say, or in a terminal), the
app doesn't start a second one. It opens that one, and leaves it running when you quit.

## Where its files are

- **Arnheim itself:** `~/Library/Application Support/Arnheim/app`. Your own company goes in its `data`
  folder ([README](../README.md), "Make it yours"), the pictures are in `baked`, and the voice, if you set
  it up, in `.voice`.
- **The log:** `~/Library/Logs/Arnheim/serve.log`. Past 5 MB it starts again, and the old one is kept as
  `serve.old.log`.

A newer version of the app replaces Arnheim's own files there, and keeps `data`, `baked` and `.voice`.
If the new version needs new pictures, it downloads them the next time it starts.

Arnheim's other commands run in that folder. Open Terminal and go there first:

```bash
cd ~/Library/Application\ Support/Arnheim/app
python3 connect/setup.py
python3 serve.py --set-up-voice
```

When `connect/setup.py` offers to start Arnheim each time you log in, say no: the app is already running
it, and its own Start at login does that.

## Remove it

1. If you connected your agents, take Arnheim's hooks out of Claude Code and Codex first, because they run
   files in Arnheim's folder. In Terminal:

   ```bash
   cd ~/Library/Application\ Support/Arnheim/app
   python3 connect/setup.py --undo
   ```

2. If Start at login is on, click it in the menu to switch it off.
3. Quit Arnheim from its menu.
4. Drag Arnheim from your Applications folder to the Bin.
5. To remove your company's files, the pictures and the voice as well, delete the folder
   `~/Library/Application Support/Arnheim`. The log is in `~/Library/Logs/Arnheim`.

## Build it yourself

On a Mac with Xcode or Apple's command line tools, in a clone of Arnheim:

```bash
mac/build.sh
```

It makes `mac/build/Arnheim.app`, for Apple silicon and Intel, and `mac/build/Arnheim.zip` to hand out.
The app carries the files git tracks in your clone, as they are now, except `tests`, `studio`, `mac` and
the README's pictures: a change you made shows in the app you build. It never carries `data`, `baked` or
`.voice`. It is signed ad hoc, with no Apple account. A copy you build opens on your own Mac without the
warning, since it wasn't downloaded; on another Mac it needs the steps above.

For tests, the app takes these from its environment:

- `ARNHEIM_APP_HOME`: a folder to use instead of `~/Library/Application Support/Arnheim`, with the log
  in its `logs` folder. While it is set, Start at login is left alone.
- `ARNHEIM_APP_PORT`: the port, instead of 8740.
- `ARNHEIM_APP_NO_OPEN=1`: no browser and no windows. It writes what it would have opened to the log.
- `ARNHEIM_APP_PYTHON`: this Python, and no other.

```bash
ARNHEIM_APP_HOME=/tmp/arnheim-test ARNHEIM_APP_PORT=8751 ARNHEIM_APP_NO_OPEN=1 \
  mac/build/Arnheim.app/Contents/MacOS/Arnheim
```

Ctrl-C stops it and the Arnheim it started. `Arnheim --find-python` prints the Python it would use, and
`Arnheim --version` the version of Arnheim it carries.

## Opening without the warning

An app that opens without macOS's warning has to be signed with a Developer ID and notarized by Apple,
which needs the maker's paid Apple Developer Program membership. That isn't done yet, so the app is signed
ad hoc, and the first open takes the steps above.
