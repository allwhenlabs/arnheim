# Your phone, from anywhere

Talk to the building from your own phone: ask the receptionist what needs you, ask a floor's lead
where the project stands, pass instructions on and answer requests, out loud or typed, at home or
away. Arnheim keeps listening only on your computer. A private way in that you run yourself gives
your phone a real https address for it, which the phone's microphone needs. Only your own devices
can reach that address.

This page uses Tailscale, whose personal plan is free. Its command-line part is open source; the Mac
and iPhone apps are not. Another private way in works too if it is an https proxy that forwards your
name to `http://127.0.0.1:8740` and says so in an `X-Forwarded-For` header, as Tailscale Serve does.
Never a plain port forward (`tailscale serve --tcp`, `ssh -R`, `socat` and the like): what comes
through one looks to Arnheim as if it came from this computer itself, with everything that allows.

## Set it up (about five minutes)

1. **Install Tailscale** on this computer and on your phone, from tailscale.com or your app store,
   and sign in to the same account on both.
2. **Turn on HTTPS.** In Tailscale's admin page, under DNS, keep MagicDNS on and turn on HTTPS
   certificates. The computer's name goes into public certificate logs, so keep anything private
   out of it.
3. **Open the way in**, on this computer:

   ```bash
   tailscale serve --bg 8740
   ```

   It prints your computer's https address, such as `https://my-mac.your-tailnet.ts.net`. Only
   devices signed in to your Tailscale account can open it.
4. **Start Arnheim with that name**, adding `--control` and `--brain` as you usually do:

   ```bash
   python3 serve.py --remote my-mac.your-tailnet.ts.net --control --brain
   ```

5. **Pair your phone.** On this computer, open the Company page, find Switches (Talking, with the made-up company), and press **Pair a
   phone**. On your phone, open the https address and type the code it shows. The code works once,
   for five minutes.
6. **Talk.** On the phone, tap **Talk**, then **Voice**. Phones put sound to sleep when the screen
   locks; if the panel says "Tap anywhere to wake the voice", tap once.

## What a paired phone can do

- Everything the page shows, the walk included, and talk to everyone in the building, out loud or
  typed. The voice is your computer's (README, "Voice").
- **Answer and instruct agents only while you let it.** On this computer, under Switches on the Company page, each phone
  has **Control for 15 minutes**. Until you press it, the phone can ask and listen but can't allow,
  deny, stop or tell an agent anything, and the leads say so. **Stop control** ends it early.
- Anything that may touch something private (a key, a login, a hidden file) is never answered by
  voice, from any device: it opens on the screen to answer there.

## How it keeps you safe

- Arnheim still listens only on this computer. Without `--remote`, anything that reaches it through
  an https proxy (one that says so, as Tailscale Serve does) is refused outright, so a way in like
  this left open by mistake gets nowhere. A plain port forward can't be told apart from this computer
  itself, which is why it is never to be used.
- With `--remote`, what comes through it is never taken for this computer. It must be for the name
  you gave, and every change it asks for must come from that https page.
- A phone gets in only with the one-time code from this computer's own page. Five wrong codes in a
  minute stop pairing until you make a new code. The phone then holds a key of its own in a cookie its
  pages can't read; only the key's fingerprint is kept here, in `data/remote/`, which is never served
  to anyone.
  A phone not seen for 30 days is let go, and every phone after 90 days.
- With Tailscale, a phone paired from your login stops working if the same key arrives from another
  login.
- Every request a phone makes with control is written to `data/remote/log.jsonl`, with the phone and
  the time, never what was said. That counts an instruction your assistant or a lead passes on for
  it, too. A phone can make 20 a minute at most.

**Never use `tailscale funnel` for Arnheim.** Funnel puts an address on the open internet. Arnheim
refuses requests that aren't for the name you gave it, but a way in should be private in the first
place.

## Stop it

- **One phone:** Remove, under Switches on this computer's Company page, or Unpair this phone on the phone itself.
- **Every phone:** start Arnheim without `--remote`. Phones you paired stay listed in `data/remote/`
  until you remove them or delete that folder.
- **The way in:** `tailscale serve reset` on this computer.

## Not yet tried

The pairing, the keys, control and refusals are tested on this computer with a stand-in for the
phone. A real iPhone and Android phone over Tailscale, the microphone there, and sound waking after
the screen locks are expected to work as on any https page, but haven't been tried yet. If your phone
does something else, the page's console and `http://127.0.0.1:8740/voice/status` say what went wrong.
