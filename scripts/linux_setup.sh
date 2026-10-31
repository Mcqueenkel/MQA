#!/usr/bin/env bash
# MQA Linux setup for Ubuntu 24.04 / Debian 12. Idempotent: re-run it after every `git pull`.
#   bash ~/mqa/scripts/linux_setup.sh
# Installs the apt packages, builds ~/mqa/.venv with requirements.txt, installs steam-user (npm ci)
# and creates ~/.mqa and ~/.config/mqa (0700). It does not install the systemd units or copy the
# identity: see LINUX.md.
set -euo pipefail

REPO=$(cd "$(dirname "$0")/.." && pwd)
die() { echo "linux_setup: $*" >&2; exit 1; }
node_major() { node -p 'process.versions.node.split(".")[0]' 2>/dev/null || echo 0; }

[ "$(id -u)" -ne 0 ] || die "run this as your normal user, not root (it calls sudo only for apt)"
[ -f "$REPO/main.py" ] || die "$REPO is not an MQA checkout"
grep -q 'def carrying_identity' "$REPO/uma_api/client.py" \
    || die "this MQA checkout has no carried-identity support (UMA_CARRY_IDENTITY); update it first"
[ "$REPO" = "$HOME/mqa" ] \
    || echo "linux_setup: note: the systemd units expect $HOME/mqa; this checkout is $REPO, so edit WorkingDirectory/ExecStart in them" >&2

# shellcheck disable=SC1091
. /etc/os-release

# steam-user (the only way to log in on Linux) needs Node >= 14. Keep a node that is already good
# enough (e.g. NodeSource); Ubuntu 22.04's apt node is 12, so do not install it there.
NODESOURCE="Install Node 20 from NodeSource, then re-run this script:
  curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
  sudo apt-get install -y nodejs"
pkgs="git ca-certificates python3 python3-venv"
if command -v node >/dev/null && command -v npm >/dev/null && [ "$(node_major)" -ge 14 ]; then
    :
elif [ "${ID:-}" = ubuntu ] && [ "${VERSION_ID%%.*}" -lt 24 ]; then
    die "Ubuntu ${VERSION_ID} ships Node 12; steam-user needs >= 14. $NODESOURCE"
else
    pkgs="$pkgs nodejs npm"
fi

missing=""
for p in $pkgs; do
    # shellcheck disable=SC2016
    dpkg-query -W -f='${Status}' "$p" 2>/dev/null | grep -q 'install ok installed' || missing="$missing $p"
done
if [ -n "$missing" ]; then
    echo "linux_setup: apt install:$missing"
    sudo apt-get update
    # shellcheck disable=SC2086
    sudo apt-get install -y $missing
fi
[ "$(node_major)" -ge 14 ] || die "node $(node -v 2>/dev/null || echo missing) is too old for steam-user. $NODESOURCE"

# Python deps in a venv (frida is skipped off Windows by its marker in requirements.txt).
python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))' \
    || die "$(python3 --version 2>&1) is too old: MQA needs Python 3.10 or newer (tested on 3.10 to 3.14)"
[ -x "$REPO/.venv/bin/python" ] || python3 -m venv "$REPO/.venv"
"$REPO/.venv/bin/python" -m pip install --disable-pip-version-check -q -r "$REPO/requirements.txt"

# steam-user, exactly as locked in package-lock.json.
(cd "$REPO" && npm ci --no-audit --no-fund)

# Identity folder (auth_config.json goes here) and the service env folder: owner-only.
mkdir -p "$HOME/.mqa" "$HOME/.config/mqa"
chmod 700 "$HOME/.mqa" "$HOME/.config/mqa"
[ ! -f "$HOME/.mqa/auth_config.json" ] || chmod 600 "$HOME/.mqa/auth_config.json"

echo "linux_setup: done ($(python3 --version 2>&1), node $(node -v)). Next: LINUX.md, 'Install the services'."
