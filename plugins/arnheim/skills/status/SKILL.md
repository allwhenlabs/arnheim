---
name: status
description: Says whether Arnheim is running on this computer, at which address, and whether it starts by itself at login. Changes nothing. Use when the person asks whether Arnheim is running, up or working.
---

# Is Arnheim running?

Everything here only looks, so run it without asking, and change nothing.

1. Ask Arnheim's page:

   ```bash
   python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8740/look', timeout=3).read().decode())"
   ```

   `{"look": ...}` means Arnheim runs at http://127.0.0.1:8740. "Connection refused" means nothing
   runs there. "timed out" just after a start means it is still downloading its pictures: try again
   in a minute. Anything else means something other than Arnheim has that port.

2. See whether it starts by itself at login (`python3 serve.py --always`).

   On a Mac: `ls ~/Library/LaunchAgents/local.arnheim.serve.plist`. Arnheim's folder is in that
   file, after `WorkingDirectory`, and the last thing it printed is at the end of
   `~/Library/Logs/arnheim.log`.

   On Linux: `systemctl --user is-enabled arnheim.service`, and
   `journalctl --user -u arnheim.service -n 20` for the last thing it printed.

3. Tell the person in a sentence or two: running or not, at which address, and whether it starts at
   login. If it should be running but isn't, show them the last lines of its log. Then offer the
   next step without taking it: open the page (`/arnheim:open` in Claude Code, `$arnheim:open` in
   Codex), start it with `python3 serve.py` in its folder, or set it up (`/arnheim:setup`, or
   `$arnheim:setup` in Codex).

On Windows, type `py` where a command says `python3`. If the person started Arnheim on another port,
use that port.
