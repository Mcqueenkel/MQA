# MQA on Linux (carried identity)

MQA normally runs on the Windows PC. Every start launches the game, captures fresh auth with Frida,
and closes the game again. Linux mode runs the same bot headless on an always-on Linux box at home.
It starts from an identity captured once on Windows and copied over: the *carried identity*. It is
opt-in through environment variables only. With them unset, none of this is active on Windows.
(Two changes in the same update do reach every Windows install: the Steam login reaches `node`
through its environment instead of its command line, and `device_id` now comes from a random seed;
see "The identity file is a password".)

In the commands below, `you@mqa-box` is your Linux user and host, and `~/mqa` is the MQA checkout on it.

## Should you use it?

**Stay on Windows if you can.** That is the setup MQA is built and tested on, and no auth is stored
on disk there: it is captured fresh at every start.

Use Linux only when both of these are true:

- the laptop can't stay on for a long batch, and
- you have an always-on Linux machine **on your home network** (Ubuntu 24.04 or Debian 12, x86-64),
  using the same internet connection the account normally plays from.

Don't use it:

- just to control MQA remotely while the laptop is on: `discord_remote.py` already does that;
- on a VPS, a cloud server or behind a VPN. The carried identity says "this Windows PC on this home
  network", and requests from a datacenter IP contradict it.

What is different from Windows:

- `auth_key` sits in a file (`~/.mqa/auth_config.json`, mode 0600) instead of only in memory.
  Treat that file like a password: see "The identity file is a password" below.
- Logging in uses your **Steam username and password**: `steam-user` mints a ticket on the Linux box
  instead of reusing the ticket captured from the game. Steam sees a login from a new device and,
  if Steam Guard is on, asks for a code.
- This mode has only been tested in a simulated Linux on Windows (unit tests plus a faked-Linux
  boot), never on a real Linux machine. Watch the first career in the log.

## Hard rules

1. **Never run Windows MQA or the game while Linux MQA runs.** That means the game on the PC or on
   any other device on this Steam account. Stop Linux first (`systemctl --user stop mqa`). An
   error 391 means this rule was broken.
2. **One account at a time.** One Linux MQA, one identity file. All your in-game accounts share
   one Steam account, so never run Linux on one while Windows plays another.
3. **Home network only.** No VPS. Don't expose port 1616 or ssh to the internet. The web UI only
   listens on 127.0.0.1; reach it through `ssh -L`.

## The identity file is a password

- It holds `auth_key`, `udid` and `viewer_id`, which together sign game API requests as your
  in-game account. Nothing in it comes from your Steam password: `device_id` comes from a random
  per-install seed in `uma_runtime\device_seed` on the PC, which MQA creates when it is missing or
  blank and which is never committed. Don't delete that seed: a new one makes the PC a new device
  to the server. Updating MQA to the version with this seed changes the Windows `device_id` once
  (it used to be derived from the Steam password); it stays the same after that.
- On Windows keep it in `%USERPROFILE%\.mqa` (section 2). Windows ignores the 0600 mode: the file is
  only as private as its folder, and your profile folder is private to you. Turn on BitLocker on
  the PC, and full-disk encryption on the Linux box if you can.
- Once it is on Linux, delete the Windows copy and leave `UMA_AUTH_CONFIG` unset (section 3).
- The web UI has no login of its own: any user or program on the Linux box can reach 127.0.0.1:1616
  and drive MQA. Give MQA its own Linux user, better its own box, that nobody else uses.

## 1. Prepare the Linux box (once)

You need: sshd reachable from the PC over the LAN, and a normal user (not root) with sudo.

```bash
sudo apt-get update && sudo apt-get install -y git
git clone <your MQA repo URL> ~/mqa
bash ~/mqa/scripts/linux_setup.sh
sudo loginctl enable-linger "$USER"     # start your user services at boot, without a login
```

Clone with git. A folder copied from Windows has CRLF line endings, which bash and systemd can't
read. If you copied one anyway, fix it with
`sed -i 's/\r$//' ~/mqa/scripts/linux_setup.sh ~/mqa/deploy/*`.

`linux_setup.sh` is safe to re-run: it only apt-installs missing packages and only creates the venv
if it is missing; `pip install -r requirements.txt` and `npm ci` run every time (`npm ci` reinstalls
`node_modules` from `package-lock.json`). It:

- apt-installs `git ca-certificates python3 python3-venv nodejs npm`;
- builds `~/mqa/.venv` with the system `python3` (3.10 to 3.14; Ubuntu 24.04 has 3.12, Debian 12
  has 3.11) and installs `requirements.txt` (frida is skipped off Windows);
- runs `npm ci` to install `steam-user`, which every Linux login needs;
- creates `~/.mqa` and `~/.config/mqa` with mode 0700.

**Ubuntu 22.04:** its apt Node is 12, and steam-user needs 14 or newer. The script stops and prints
these commands. Run them, then run the script again:

```bash
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs
```

### Install the services

```bash
mkdir -p ~/.config/systemd/user
cp ~/mqa/deploy/mqa.service ~/mqa/deploy/mqa-discord.service ~/.config/systemd/user/
[ -f ~/.config/mqa/mqa.env ] || cp ~/mqa/deploy/mqa.env.example ~/.config/mqa/mqa.env
nano ~/.config/systemd/user/mqa.service
systemctl --user daemon-reload
```

In `mqa.service`, set `--scenario` on the `ExecStart=` line (`mant`, `unity`, `ura` or `grand`). To
get log timestamps in the Windows PC's time zone, uncomment `#Environment=TZ=` and set that zone. In
`~/.config/mqa/mqa.env`, `UMA_CARRY_IDENTITY=1` is all you need. It must be exactly `1`: `true` or
`yes` count as off. Don't start anything yet.

## 2. Export the identity on Windows

Do this once per in-game account, and again after game updates or account switches (section 6).
Make the in-game account you want Linux to run the active one. Then, in PowerShell, in the MQA
folder:

```powershell
$env:UMA_AUTH_CONFIG = "$HOME\.mqa\auth_config.json"
python main.py
```

The capture runs as usual. Log in at http://127.0.0.1:1616 as usual. The console then prints
`[identity] saved to C:\Users\<you>\.mqa\auth_config.json`. If you want the AI brain on Linux,
export it now (section 3). Then press Ctrl+C, check that the game is closed, and close this
PowerShell window. The `$env:` variable only lives in that window, so your normal Windows runs are
unaffected. Never set `UMA_AUTH_CONFIG` for good (System Properties or `setx`): every Windows login
would then rewrite the file.

- With only `UMA_AUTH_CONFIG` set, Windows MQA sends exactly the same requests as without it. The
  one difference is that it writes this file (atomically) after each successful login.
- The file holds `viewer_id`, `udid`, `auth_key`, `app_ver`, `res_ver`, `locale`, the device fields
  Windows MQA sent and the PC's screen height (`screen_h`, which MQA's race taps are scaled to). It
  never holds the Steam ticket, your password or anything derived from it. An export made before
  MQA carried `screen_h` is refused on Linux: export again.
- Keep it on a local disk, outside the MQA folder and outside OneDrive. MQA refuses those and network
  (`\\...`) paths, with `[identity] REFUSING <path>: ...`.

## 3. Copy files to Linux

scp creates files that other users on the Linux box can read. So copy into a private folder first,
then put each file in place with `install -m 600`, which makes it owner-only from the start.

From the MQA folder on Windows, in PowerShell:

```powershell
ssh you@mqa-box "mkdir -m 700 mqa-in"
scp "$HOME\.mqa\auth_config.json" career_bot\.timing_dna you@mqa-box:mqa-in/
```

Then on the Linux box:

```bash
install -m 600 ~/mqa-in/auth_config.json -t ~/.mqa/
install -m 600 ~/mqa-in/.timing_dna -t ~/mqa/career_bot/
rm -r ~/mqa-in
```

And back on Windows, delete the copy there:

```powershell
Remove-Item "$HOME\.mqa\auth_config.json"
```

`career_bot/.timing_dna` is the per-install seed for MQA's human-like timing. Copy it **before**
Linux MQA starts for the first time. Otherwise Linux makes a new seed and the account's rhythm
suddenly changes. If Linux MQA already started: stop it, copy the file, start it again.

**Optional extras**, the same way. scp prints an error for any file you don't have and copies the
rest.

```powershell
ssh you@mqa-box "mkdir -m 700 mqa-in"
# finished-career webhook, Discord remote token, event choices and learned outcomes, history
scp uma_runtime\discord.json uma_runtime\discord_remote.json uma_runtime\event_overrides.json uma_runtime\event_choice_outcomes.json uma_runtime\events_seen.json uma_runtime\career_history.json you@mqa-box:mqa-in/
# presets you changed since your last commit (nothing secret in them)
scp -r data\presets you@mqa-box:mqa/data/
```

Then on the Linux box:

```bash
chmod 700 ~/mqa/uma_runtime
install -m 600 ~/mqa-in/* -t ~/mqa/uma_runtime/
rm -r ~/mqa-in
```

**AI brain (optional; without it the brain learns again from scratch).** While Windows MQA is
still running from step 2:

```powershell
curl.exe -fsS -X POST -F "password=<one-off passphrase>" http://127.0.0.1:1616/api/ai/export -o "$HOME\ai-brain.aibrain"
scp "$HOME\ai-brain.aibrain" you@mqa-box:
Remove-Item "$HOME\ai-brain.aibrain"
```

Use `curl.exe`: in Windows PowerShell, plain `curl` is a different command. The passphrase seals
this one file. After Linux MQA is up (section 4), run this on the Linux box:

```bash
curl -fsS -F "file=@$HOME/ai-brain.aibrain" -F "password=<same passphrase>" http://127.0.0.1:1616/api/ai/import
rm ~/ai-brain.aibrain
```

The reply must contain `"imported":true`.

### master.mdb

The Linux box has no game install, so it has no `master.mdb`. Pick one:

- **A. Do nothing (the default).** Linux uses the `data/*.json` in the clone. At startup MQA prints
  `master.mdb requires user action: <path>`, which is harmless. What you lose: the EVENT CHOICES
  panel can't pre-list a deck's events, and reference data only gets newer when you pull new
  `data/*.json`.
- **B. Copy it** to the path MQA checks by default off Windows. MQA then regenerates `data/*.json`
  at every start. Copy it again after each game update.

  ```powershell
  ssh you@mqa-box "mkdir -p ~/AppData/LocalLow/Cygames/Umamusume/master"
  scp "<Steam library>\steamapps\common\UmamusumePrettyDerby\UmamusumePrettyDerby_Data\Persistent\master\master.mdb" you@mqa-box:AppData/LocalLow/Cygames/Umamusume/master/
  ```

  Older installs keep it in `%USERPROFILE%\AppData\LocalLow\Cygames\Umamusume\master\master.mdb`.
  While Windows MQA runs, `curl.exe -s http://127.0.0.1:1616/api/master-data/status` shows which
  one it uses. Use the Global client's file only, never the JP one.

## 4. Start, use, stop

Before you start: Windows MQA is closed and the game is closed.

```bash
systemctl --user enable --now mqa
journalctl --user -u mqa -f
```

A good start looks like this:

```
[scenario] LOCKED to MANT (4) for this session [from --scenario flag / SWEEPY_SCENARIO] ...
[auth] using the carried identity (viewer_id ..., app_ver ..., res_ver ...) -- no capture, no game launch
Access the Web UI at: http://127.0.0.1:1616
```

To open the web UI, run this on the PC or laptop and keep the window open:

```powershell
ssh -N -L 1616:127.0.0.1:1616 you@mqa-box
```

Then:

1. Browse to http://127.0.0.1:1616.
2. Log in with your Steam username and password, plus the STEAM GUARD CODE if it asks.
3. Pick the trainee, deck, friend and parents, and start.

You can close the tunnel and the laptop afterwards; the run carries on. If `ssh -L` says the port is
already in use, Windows MQA is running: stop it (rule 1).

MQA's saved login can't keep the password on a headless box, because there is no OS keyring there.
Type it at each login. MQA keeps it in memory only, so it can re-mint the Steam ticket once on a 394.
After a successful login MQA rewrites `~/.mqa/auth_config.json` with the identity that just worked.

**After any restart** (crash auto-restart, reboot, `restart`), MQA comes up logged out. Log in
again through the tunnel; Discord can't log in for you. A career already in progress resumes as it
is. A fresh career needs the trainee, deck, friend and parents picked again, because MQA keeps that
selection in memory only.

### Discord remote (optional)

If you didn't copy `discord_remote.json`, run `~/mqa/.venv/bin/python ~/mqa/discord_remote.py` once.
It writes `~/mqa/uma_runtime/discord_remote.json` and exits. Fill in `token`, `owner_ids` and
`guild_id`; the steps are at the top of `discord_remote.py`. Stop the Windows `discord_remote.py`
first, because two copies on one token both answer. Then:

```bash
systemctl --user enable mqa-discord     # from now on it starts and stops together with mqa
systemctl --user start mqa-discord
```

### Everyday commands

| Command | What it does |
|---|---|
| `systemctl --user status mqa mqa-discord` | Is it running? |
| `systemctl --user stop mqa` | Stops MQA and mqa-discord. MQA finishes the API call in flight, then exits (within about 30 s). Careers are resumable. |
| `systemctl --user restart mqa` | Restarts MQA; log in again afterwards |
| `journalctl --user -u mqa -f` | Follow the log |
| `journalctl --user -u mqa --since "1 hour ago"` | Recent log |
| `journalctl --user -u mqa-discord -n 50` | Discord remote log |
| `~/mqa/uma_runtime/bot_logs/latest_career_log.json` | Per-turn decisions of the last career |

If MQA crashes, systemd restarts it after 30 s. After 4 starts in 15 minutes it gives up and leaves
the unit failed. Fix the cause, then run `systemctl --user reset-failed mqa` and start it again.

## 5. Switching between Windows and Linux

**Going to Windows:**

```bash
systemctl --user stop mqa
systemctl --user disable mqa      # if you'll be on Windows a while, so a reboot doesn't start it
systemctl --user is-active mqa    # must not print: active
```

Then use Windows MQA as normal.

**Coming back to Linux:**

1. Close Windows MQA and the game.
2. If you switched in-game accounts or the game updated since the last export, export again
   (section 2) and copy `auth_config.json` (section 3).
3. Run `systemctl --user enable --now mqa` and log in.

The optional state you copied (event learning, history) now exists on both hosts and drifts apart:
the host that ran last is newest. Copy it back the same way if that matters to you.

## 6. Maintenance

**Game update** (Steam updated the game on Windows):

1. On Linux: `systemctl --user stop mqa`.
2. On Windows: launch the game to the title screen, let it finish downloading, then close it.
3. Export again (section 2) and copy `auth_config.json` (section 3), plus `master.mdb` if you use
   option B.
4. On Linux: start MQA and log in.

Small resource bumps fix themselves. On a 214, MQA takes the server's `res_ver` and retries
(`[RES-VER auto-update] ...`), and the next good login saves the new value into the identity file.
An app update (204) does not fix itself: export again. As a stopgap, if you know the new version
but can't get to the PC, put `UMA_APP_VER=<version>` (or `UMA_RES_VER=`) in `~/.config/mqa/mqa.env`
and restart. Remove the line after one successful login: the file then holds the new value.

**In-game account switch:** the identity belongs to one in-game account. Switching accounts on
Windows invalidates it, and Linux then gets 1055 or 709. Make the account you want Linux to run
active, export again, and copy the file. To run a different account on Linux, do the same; it is
still one account at a time.

**Updating MQA on Linux:**

```bash
systemctl --user stop mqa
git -C ~/mqa pull --ff-only
bash ~/mqa/scripts/linux_setup.sh
diff ~/mqa/deploy/mqa.service ~/.config/systemd/user/mqa.service   # copy unit changes by hand, keep your scenario/TZ
systemctl --user daemon-reload && systemctl --user start mqa
```

If `git pull` refuses because `data/*.json` or `public/assets/data/uma_race_data.json` changed locally
(option B regenerates those files), run
`git -C ~/mqa checkout -- ':(glob)data/*.json' public/assets/data/uma_race_data.json` and pull again.
The `:(glob)` keeps `data/presets/` out of it. A plain `'data/*.json'` would also throw away your
preset edits.

After a distro upgrade that changes the Python version, run `rm -rf ~/mqa/.venv` and run the setup
script again.

## 7. Troubleshooting

Game API errors show up in the log as `API error <code> on <endpoint>`. The exception is 709, which
shows as `709 on <endpoint>`.

| Code or symptom | Meaning | What to do |
|---|---|---|
| 102 | Already done, or no career here | Nothing. MQA treats it as "no active career". |
| 201 | No career here (handled like 102) | Nothing. Start a new career from the UI. |
| 204 | App version out of date after a game update | Section 6, game update: export again (`UMA_APP_VER` is the stopgap). |
| 205 | Action not valid in the current state | MQA retries up to 3 times or skips the action. If the run stopped, resume it from the UI or with `/mqa start`. |
| 208 | Server busy ("slow down") | MQA backs off 1 s to 15 s, up to 6 times. If it keeps failing, auto-backoff stops the run (Discord shows "Auto-backoff"). Wait at least 5 minutes before resuming, and don't loop restarts. |
| 214 | Resource version (`res_ver`) out of date | MQA adopts the server's value once by itself. If it keeps failing, do the game-update steps in section 6. |
| 217 | Session sequence out of sync | MQA resyncs: it resumes the active career or retries the start once. If it repeats, run `systemctl --user restart mqa`, log in, and resume. |
| 391 | Another login took the Steam session, almost always the game or Windows MQA starting somewhere | Close it there. MQA doesn't fight over the session on a 391, on purpose. Then log in again on Linux. |
| 394 | Steam ticket is stale | MQA mints one new ticket from the login you typed and retries (`[steam] re-minted ...`). If your account uses Steam Guard codes, an unattended mint can't get past Guard (`[steam] could not re-mint ...`) and the run stops. Log in again with a fresh code, then resume. |
| 709 | `viewer_id`/`auth_key` don't match the live account | The identity belongs to an in-game account that isn't the active one (a switch or data transfer on Windows). Export again from the right account. |
| 1055 | `viewer_id` mismatch after an in-game account switch | Same fix as 709. |
| `... missing or incomplete (lacks device_id, ...)`, then exit | The file didn't come from an export, or it is old or partial (`lacks screen_h`: an export from before MQA carried it) | Export again on Windows (section 2) and copy it (section 3). |
| `no usable identity at ...`, or `Auth capture only runs on the Windows PC ...` at start | The file wasn't copied, or `mqa.env` lacks `UMA_CARRY_IDENTITY=1` (exactly `1`) | Copy the file, then check `~/.config/mqa/mqa.env`. |
| `[identity] REFUSING ...` | `UMA_AUTH_CONFIG` points into `~/mqa`, a OneDrive folder or a network path | Unset it to use the default `~/.mqa/auth_config.json`. |
| Unit failed with `start-limit-hit` | It crashed 4 times in 15 minutes | Read `journalctl --user -u mqa -n 100`, fix the cause, then `systemctl --user reset-failed mqa` and start. |
| `Failed to connect to bus` | You ran `systemctl --user` after `su` or `sudo` | Log in over ssh as the user itself. |
| `journalctl --user` shows nothing | The journal isn't persistent | `sudo mkdir -p /var/log/journal && sudo systemctl restart systemd-journald` |
| `Node.js not found` at login | The service can't find node (nvm installs aren't on its PATH) | Install node from apt or NodeSource (`/usr/bin/node`), then re-run the setup script. The message's `--reauth` advice is for Windows only. |
| Login keeps asking for a code | Steam Guard | Type the authenticator code in STEAM GUARD CODE. The form sends it as a mobile-authenticator code; email Steam Guard codes were never tested on this path. |
| `Steam login timed out after 60s` | Steam is slow or unreachable | Try again later. |
| `Could not save credential` | The headless box has no OS keyring | Expected. Type the password at each login. |
| ssh -L: `Address already in use` | Something on the PC already uses 1616, normally Windows MQA | Stop Windows MQA (rule 1). |

## Reference

### Environment (`~/.config/mqa/mqa.env`)

| Variable | Default | Meaning |
|---|---|---|
| `UMA_CARRY_IDENTITY` | unset (off; anything but `1` is off, `true` and `yes` too) | `1`: start from the identity file, with no game and no Frida. Required off Windows. It also allows one mid-run Steam-ticket re-mint on 394 (never on 391); the login's own single re-mint on a 394 is not gated by it and runs on Windows too. A re-login also reads the file. |
| `UMA_AUTH_CONFIG` | `~/.mqa/auth_config.json` when carrying | The identity file. Set it on Windows for the export. Refused inside the MQA folder or OneDrive, and for any path starting with `\\` (UNC or `\\?\`). A relative path resolves against MQA's working directory (`~/mqa` under the service), so it is refused too: use an absolute or `~/` path. |
| `SWEEPY_SCENARIO` | unset | `mant`, `unity`, `ura` or `grand`, or a scenario id: `4` = MANT, `2` = Unity, `1` = URA, `3` = Grand Live. These are not the startup-menu numbers (there `1` = MANT). Used only when there is no `--scenario` (the flag wins). |
| `SWEEPY_PORT` | `1616` | Web UI port. The address is always 127.0.0.1. |
| `SWEEPY_ACCOUNT` | unset | Account label for logs and Discord (same as `--account`). |
| `UMA_APP_VER` / `UMA_RES_VER` | from the file | Stopgap version override after a game update. |
| `UMA_RUNTIME_DIR` | `~/mqa/uma_runtime` | Leave unset: some state always stays in `~/mqa/uma_runtime`, so moving the rest splits it. |
| `MQA_STEAM_USERNAME`, `MQA_STEAM_PASSWORD`, `MQA_STEAM_CODE` | internal | Set by MQA only in the Steam-login child process (`node`), instead of putting the login on its command line. Never set them yourself. |

### Files on the Linux box

| Path | What it is | Comes from |
|---|---|---|
| `~/.mqa/auth_config.json` (0600) | Carried identity | Windows export, rewritten after each Linux login |
| `~/mqa/career_bot/.timing_dna` (0600) | Timing seed | The Windows MQA folder |
| `~/.config/mqa/mqa.env` | Service environment | `deploy/mqa.env.example` |
| `~/.config/systemd/user/mqa.service`, `mqa-discord.service` | The units | `deploy/` |
| `~/mqa/uma_runtime/discord_remote.json` | Discord remote token | Windows, or written on the first run |
| `~/mqa/uma_runtime/bot_logs/` | Career decision logs | MQA |
