---
name: open
description: Opens Arnheim's page, http://127.0.0.1:8740, in the person's browser. Use when the person asks to open, show or go to Arnheim or its building.
---

# Open Arnheim

1. Check that Arnheim answers. This changes nothing, so run it without asking:

   ```bash
   python3 -c "import urllib.request as u; print(u.urlopen('http://127.0.0.1:8740/look', timeout=3).read().decode())"
   ```

   It prints `{"look": ...}` when Arnheim runs there.

2. If it answers, open the page:

   ```bash
   python3 -m webbrowser http://127.0.0.1:8740
   ```

   With no browser here (over SSH, say), give the person the address instead.

3. If it doesn't answer, say so and start nothing yourself. Offer the choices: start it in its
   folder with `python3 serve.py`, once the person says yes, or set it up with the setup skill
   (`/arnheim:setup` in Claude Code, `$arnheim:setup` in Codex).

On Windows, type `py` where a command says `python3`. If the person started Arnheim on another port,
use that port.
