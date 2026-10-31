# MQA

MQA is a Windows automation bot for the career modes in **Umamusume: Pretty Derby**. It serves a local
FastAPI web UI, captures the active game's authentication with Frida, calls the live game API, and
drives career decisions through scenario-specific strategies. Windows is its home; an optional Linux
mode (an always-on home Linux machine, no screen needed) is described in [LINUX.md](LINUX.md).

Supported scenarios, as numbered in MQA's startup menu (the `--scenario` name is in brackets):

1. MANT/Trackblazer (`mant`)
2. Unity/Aoharu (`unity`)
3. URA Finale (`ura`)
4. Grand Live/Grand Concert (`grand`)

## Setup on Windows (normal)

**You need** the Steam version of Umamusume (installed and fully updated), plus:

- **Python 3.10 to 3.14.** On [python.org](https://www.python.org/downloads/windows/) pick a
  **3.13.x "Windows installer (64-bit)"** (not a newer version than 3.14), and tick
  **"Add python.exe to PATH"** in the installer.
- **Node.js and Git.** Open **PowerShell** (Start menu, type PowerShell) and run:

  ```powershell
  winget install -e --id OpenJS.NodeJS
  winget install -e --id Git.Git
  ```

When everything is installed, **close PowerShell and open a new one** (so it sees the new programs).

**1. Get MQA and install it** (git asks you to sign in to GitHub the first time):

```powershell
git clone https://github.com/Mcqueenkel/lmao-repo.git MQA
cd MQA
python -m pip install -r requirements.txt
npm.cmd install
```

(`npm.cmd` instead of `npm` avoids PowerShell's "running scripts is disabled" error.)

**2. Start it:**

```powershell
python main.py
```

1. Type the scenario number from the menu (or skip the menu with `python main.py --scenario mant`).
2. MQA opens Umamusume through Steam. Reach the in-game **home menu within 3 minutes**; MQA captures
   your login there and closes the game. (If it times out, close the game and run it again.)
3. Open **http://127.0.0.1:1616**, log in with your **Steam username and password** (and the Steam
   Guard code if asked), pick the trainee, deck, friend and parents, and start.

Leave the PowerShell window open while MQA runs; press **Ctrl+C** in it to stop. Next time: open
PowerShell, `cd MQA`, `python main.py`.

**Handy options:**

```powershell
python main.py 8080        # another port (then open http://127.0.0.1:8080)
```

Optional command-line driver, in a 2nd PowerShell window while MQA runs (no browser needed):

```powershell
cd MQA
python mqa_cli.py status                          # what MQA is doing (also: account, log, history, presets)
python mqa_cli.py start --preset fan --runs 3     # uses the team you last picked in the web UI
python mqa_cli.py stop
```

Run `python mqa_cli.py --help` for all commands (`pause`, `resume`, `watch`, `login` with MQA's saved
Steam login, `--json` output).

Optional Discord remote, in a 2nd PowerShell window (setup steps are at the top of the file):

```powershell
cd MQA
python discord_remote.py
```

Run one MQA per Steam account at a time.

**Updating:**

```powershell
cd MQA
# MQA rewrites these game-data files on every run; this resets them (your presets are kept)
git checkout -- ':(glob)data/*.json' public/assets/data/uma_race_data.json
git pull
python -m pip install -r requirements.txt
npm.cmd install
```

## Setup on Linux (optional)

Only for when the laptop can't stay on. **Stay on Windows if you can.** The full guide, with
troubleshooting, is [LINUX.md](LINUX.md). The rules:

- A Linux machine on your **home network**: never a rented cloud server (VPS) or a VPN.
- **Never** run the game (on any device with this Steam account) or Windows MQA while Linux MQA runs.
- One in-game account at a time, and never expose port 1616 or ssh to the internet.

Below, `you@mqa-box` means your Linux username @ the machine's IP address (run `hostname -I` on it,
e.g. `you@192.168.1.50`).

**1. Prepare the Linux machine** (in a terminal on the machine itself; Ubuntu 24.04 or Debian 12, a
normal user with sudo):

```bash
sudo apt-get update && sudo apt-get install -y git openssh-server
git clone https://github.com/Mcqueenkel/lmao-repo.git ~/mqa
bash ~/mqa/scripts/linux_setup.sh
sudo loginctl enable-linger "$USER"
mkdir -p ~/.config/systemd/user
cp ~/mqa/deploy/mqa.service ~/mqa/deploy/mqa-discord.service ~/.config/systemd/user/
[ -f ~/.config/mqa/mqa.env ] || cp ~/mqa/deploy/mqa.env.example ~/.config/mqa/mqa.env
nano ~/.config/systemd/user/mqa.service
systemctl --user daemon-reload
```

The repository is private: when `git clone` asks for a password, paste a GitHub **personal access
token** (GitHub → Settings → Developer settings → Personal access tokens; read access to this repo's
contents is enough), not your GitHub password.

In `nano`, the `ExecStart=` line ends in `--scenario mant`: change `mant` to `unity`, `ura` or `grand`
if needed (save: Ctrl+O, Enter; quit: Ctrl+X). The copied `~/.config/mqa/mqa.env` already has
`UMA_CARRY_IDENTITY=1`; leave it exactly `1`. **Don't start MQA yet.**

**2. Export your login on Windows, once** (with the in-game account you want on Linux active):

```powershell
cd MQA
$env:UMA_AUTH_CONFIG = "$HOME\.mqa\auth_config.json"
python main.py
```

Log in at http://127.0.0.1:1616 as usual. When the console prints `[identity] saved to ...`, press
Ctrl+C, check the game is closed, and close this PowerShell window. (Never set `UMA_AUTH_CONFIG`
permanently, e.g. with `setx`.)

**3. Copy two files to Linux.** On the PC (new PowerShell window). The first time, ssh asks you to
type `yes` and then your Linux password:

```powershell
cd MQA
ssh you@mqa-box "mkdir -m 700 mqa-in"
scp "$HOME\.mqa\auth_config.json" career_bot\.timing_dna you@mqa-box:mqa-in/
```

Then on the Linux machine:

```bash
install -m 600 ~/mqa-in/auth_config.json -t ~/.mqa/
install -m 600 ~/mqa-in/.timing_dna -t ~/mqa/career_bot/
rm -r ~/mqa-in
```

Back on the PC, delete the Windows copy: `Remove-Item "$HOME\.mqa\auth_config.json"`. The identity
file can sign game requests as your account: treat it like a password.

**4. Start it.** On the Linux machine:

```bash
systemctl --user enable --now mqa
journalctl --user -u mqa -f        # watch the log; Ctrl+C only stops watching
```

On the PC (PowerShell), open a tunnel to the web UI. It prints nothing; that's normal, keep it open:

```powershell
ssh -N -L 1616:127.0.0.1:1616 you@mqa-box
```

Browse to **http://127.0.0.1:1616**, log in with your Steam username and password (and Steam Guard
code if asked), pick the team and start. You can then close the tunnel and the laptop.

- **Stop:** `systemctl --user stop mqa`.
- **After a restart or reboot** MQA comes up logged out: open the tunnel and log in again (Discord
  can't). A career in progress resumes; a new one needs the team picked again.
- **After a game update or an in-game account switch:** `systemctl --user stop mqa` on Linux. After a
  game update, open the game on Windows to the title screen, let it finish downloading, and close it.
  Redo steps 2-3, then `systemctl --user start mqa` and log in again.
- **Updating MQA on Linux:**

  ```bash
  systemctl --user stop mqa
  git -C ~/mqa pull --ff-only
  bash ~/mqa/scripts/linux_setup.sh
  systemctl --user daemon-reload && systemctl --user start mqa
  ```

  If `deploy/mqa.service` changed, see [LINUX.md](LINUX.md) section 6.

## Good to know

- The web UI only listens on this computer (`127.0.0.1`).
- On Windows, starting `main.py` really launches the game and logs in, and it force-closes any program
  already using the chosen port. Don't start it just to check that it works.
- Don't delete `uma_runtime/device_seed` (created on the first run): it keeps MQA looking like the same
  device to the game server. It is random per install and never committed. (When you first update to
  the version that added it, the game server sees a new device once.)

## Tests

Tests are offline and can be run directly without the game or network:

```powershell
python tests/test_event_scorer.py
python tests/test_stabilization_guards.py
```

For the whole suite, install the test-only extras (pytest, and httpx for the API tests) once:

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests
```

## Project map

- `main.py` — startup, auth capture, FastAPI state, and career-control endpoints
- `discord_remote.py` — optional Discord slash-command remote that calls MQA's local web API
- `uma_api/client.py` — encrypted live-game API boundary, retries, and circuit breaker
- `career_bot/runner.py` — career turn loop and action dispatch
- `career_bot/core/` — reusable decision, race, event, skill, learning, and reporting logic
- `career_bot/scenarios/` — URA, Unity, Grand Live, and MANT-specific behavior
- `public/` — browser UI
- `data/*.json` — generated reference data
- `data/presets/` — personal run presets; preserve these unless intentionally editing a preset
- `uma_runtime/` — gitignored logs and local runtime configuration
- `deploy/`, `scripts/linux_setup.sh` — optional Linux host (see `LINUX.md`)

See `CLAUDE.md`, `STRUCTURE.md`, `DEPENDENCIES.md`, and `LINUX.md` for deeper implementation and setup notes.
