import base64
import json
import os
import re
import time
import uuid
from curl_cffi import requests
import hashlib
import random
import secrets
import struct
import msgpack
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import subprocess
import platform
import socket
import shutil
import tempfile
import collections
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from career_bot.core.delay import dna_sleep, dna_uniform, dna_gauss, dna_randint, backoff_sleep, jittered_sleep, server_sleep

# --- Auto-backoff circuit breaker -------------------------------------------
# If the game server rejects this many API calls within the rolling window
# (seconds), the client trips its breaker. The runner polls `circuit_tripped`
# and stops cleanly instead of hammering a server that is clearly unhappy
# (e.g. throttling / temporary restriction). Tunable via env vars.
CIRCUIT_ERROR_THRESHOLD = int(os.environ.get('SWEEPY_CIRCUIT_THRESHOLD') or 6)
CIRCUIT_ERROR_WINDOW_SEC = float(os.environ.get('SWEEPY_CIRCUIT_WINDOW_SEC') or 90.0)
# Once the breaker trips, pause before allowing the next request. The pause is deliberately
# server_sleep-based, so the NO CD UI switch cannot turn the safety cooldown into a hot retry loop.
# Text of the exception call() raises when should_abort() ends a cooldown (the runner matches it).
CIRCUIT_COOLDOWN_STOP = "Stopped during circuit-breaker cooldown"
CIRCUIT_COOLDOWN_SEC = float(os.environ.get('SWEEPY_CIRCUIT_COOLDOWN_SEC') or 300.0)

class StateRecoveryError(Exception):
    pass


# Every server rejection call() raises reads 'API error <rc> on <ep>: <json>'. The JSON embeds
# data_headers (servertime, viewer_id), so a bare `'205' in str(e)` also matches those digits by
# chance (~2% of errors, or EVERY error for a viewer_id that contains the code). Match the prefix only.
_API_RC_RE = re.compile(r"\bAPI error (\d+) on ")


def api_error_code(exc):
    """The server result code carried by an UmaClient error (outermost one if chained), else None."""
    m = _API_RC_RE.search(str(exc))
    return int(m.group(1)) if m else None


def is_api_error(exc, *codes):
    """True when `exc` is an 'API error <rc> on ...' for one of `codes` (ints)."""
    return api_error_code(exc) in codes

BASE_URL = 'https://api.games.umamusume.com/umamusume/'
DIR = str(Path(__file__).resolve().parent.parent)
LAST_TICKET_GEN_RESULT = None
LAST_SAVED_CONFIG = None


def runtime_output_root():
    override = os.environ.get("UMA_RUNTIME_DIR")
    if override:
        return Path(override).expanduser().resolve()

    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".git").exists():
            return candidate / "uma_runtime"
    # No .git (a ZIP download): the app root, as career_bot/runner.py does -- not the folder above it.
    return here.parent.parent / "uma_runtime"


TRACE_DIR = runtime_output_root() / "trace_logs"

TICKET_GEN_JS = """const SteamUser = require("steam-user");

const args = process.argv.slice(2);
// MQA passes the login in the env, never argv (argv is world-readable); the flags are for manual use.
let username = process.env.MQA_STEAM_USERNAME || "";
let password = process.env.MQA_STEAM_PASSWORD || "";
let appid = 3224770;
let code = process.env.MQA_STEAM_CODE || "";

for (let i = 0; i < args.length; i++) {
  if (args[i] === "--username") username = args[++i];
  else if (args[i] === "--password") password = args[++i];
  else if (args[i] === "--appid") appid = parseInt(args[++i]);
  else if (args[i] === "--code") code = args[++i];
}

if (!username || !password) {
  process.stderr.write(
    "Usage: node ticket_gen.js --username X --password Y [--code Z]\\n"
  );
  process.exit(1);
}

const client = new SteamUser();

const loginOpts = {
  accountName: username,
  password: password,
};

if (code) {
  loginOpts.twoFactorCode = code;
}

client.logOn(loginOpts);

client.on("steamGuard", (domain, callback) => {
  process.stderr.write(
    "NEED_GUARD:" + (domain || "2fa") + "\\n"
  );
  process.exit(2);
});

client.on("error", (err) => {
  process.stderr.write("ERROR:" + err.message + "\\n");
  process.exit(1);
});

client.on("loggedOn", () => {
  process.stderr.write(
    "Logged in as " + client.steamID.getSteamID64() + "\\n"
  );
  client.createAuthSessionTicket(appid, (err, sessionTicket) => {
    if (err) {
      process.stderr.write("Ticket error: " + err.message + "\\n");
      process.exit(1);
    }
    const buf = Buffer.isBuffer(sessionTicket) ? sessionTicket : sessionTicket.sessionTicket || sessionTicket;
    const result = {
      steam_id: client.steamID.getSteamID64(),
      session_ticket: Buffer.from(buf).toString("hex").toUpperCase(),
    };
    process.stdout.write(JSON.stringify(result) + "\\n");
    process.stderr.write(
      "Ticket generated (" + Buffer.from(buf).length + " bytes)\\n"
    );
    setTimeout(() => process.exit(0), 500);
  });
});
"""

SALT = b'co!=Y;(UQCGxJ_n82'
HEAD = bytes.fromhex('6b20e2ab6c311330f761d737ce3f3025750850665eea58b6372f8d2f57501eb344bdb7270a9067f5b63cd61f152cfb986cbfbf7a')
SENSITIVE_ERROR_KEYS = {"auth_key", "steam_session_ticket", "sid", "udid", "device_id"}
SENSITIVE_LOG_KEYS = SENSITIVE_ERROR_KEYS | {
    "password", "session_ticket", "steam_ticket", "refresh_token", "access_token",
    "shared_secret", "identity_secret",
    # sent with every request (common header) or by Data Transfer; the api_library kept them in clear
    "steam_id", "ip_address", "input_viewer_id", "email",
}
# Any wire key containing these is a credential. Checked against every field name in the game client's
# metadata: they hit only password / one_time_password / *_token, never gameplay data.
SENSITIVE_LOG_PARTS = ("password", "token", "secret")


def redact_for_log(value, key=""):
    """Remove credentials from persistent traces while preserving diagnostic payload shape."""
    k = str(key).lower()
    if k in SENSITIVE_LOG_KEYS or any(p in k for p in SENSITIVE_LOG_PARTS):
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_for_log(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_log(item, key) for item in value]
    if isinstance(value, tuple):
        return [redact_for_log(item, key) for item in value]
    return value


def redact_for_console(value, key=""):
    if key in SENSITIVE_ERROR_KEYS:
        return "<redacted>"
    if isinstance(value, dict):
        return {k: redact_for_console(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_console(item, key) for item in value[:20]]
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "...<truncated>"
    return value


def format_api_error(ep, rc, res):
    details = {
        "endpoint": ep,
        "response_code": res.get("response_code"),
        "result_code": rc,
        "data_headers": redact_for_console(res.get("data_headers") or {}),
    }
    data = res.get("data")
    if isinstance(data, dict):
        interesting = {}
        for key in (
            "error_code",
            "error_message",
            "message",
            "result_code",
            "viewer_id",
            "current_turn",
            "chara_info",
            "single_mode_chara_light",
        ):
            if key in data:
                interesting[key] = data[key]
        if interesting:
            details["data"] = redact_for_console(interesting)
    elif data is not None:
        details["data"] = redact_for_console(data)
    return json.dumps(details, ensure_ascii=False, default=str)


def is_deterministic_205(ep):
    """Endpoints whose 205 means 'not valid for the current game state' -- DETERMINISTIC, so retrying is
    futile: fail fast (no retry storm, no circuit-breaker note; the caller handles it -- items.py
    blacklists the item, the race clock loop just breaks). Covers the shop multi_item_* calls AND
    `continue` (the clock/race-retry: live URA 205s a continue on a lost non-goal race). Suffix-matched
    because `ep` is namespace-routed per scenario (single_mode/continue for URA, single_mode_free/continue
    for MANT, single_mode_team/* for Unity).

    master_square (Grand Live) belongs here too: live_data_set.next_square_info_array is a PERSISTENT
    preview of the pending board choice, not a per-turn claimable offer -- it stays identical for turns
    on end (verified: turns 1-12 of capture 20260723_070635 all show the same three squares, and the
    client claimed exactly once, at turn 12). Claiming when the board hasn't advanced is a deterministic
    'not now', so retrying just storms 205s."""
    return str(ep).rsplit("/", 1)[-1] in ("continue", "multi_item_exchange", "multi_item_use",
                                          "master_square", "gain_skills")

def sm5(data):
    h = hashlib.md5()
    h.update(data)
    h.update(SALT)
    return h.digest()

def make_sid(vid, udid):
    return sm5((str(vid) + udid).encode())

def next_sid(sid):
    return sm5(sid.encode())

def gen_key():
    out = b''
    while len(out) < 32:
        out += format(random.randint(0, 65535), 'x').encode()
    return out[:32]

def get_iv(udid):
    return udid.replace('-', '').lower()[:16].encode()

def get_raw_udid(udid):
    return bytes.fromhex(udid.replace('-', '').lower())

def pack(sid, udid_raw, auth, payload, udid):
    key = gen_key()
    p = msgpack.packb(payload, use_bin_type=True)
    body = AES.new(key, AES.MODE_CBC, get_iv(udid)).encrypt(pad(struct.pack('<I', len(p)) + p, 16)) + key
    h = HEAD + sid + udid_raw + os.urandom(32)
    if auth: h += auth
    return base64.b64encode(struct.pack('<I', len(h)) + h + body)

def unpack(text, udid):
    raw = base64.b64decode(text)
    key, cipher = raw[-32:], raw[:-32]
    p = unpad(AES.new(key, AES.MODE_CBC, get_iv(udid)).decrypt(cipher), 16)
    return msgpack.unpackb(p[4:4+struct.unpack('<I', p[:4])[0]], raw=False, strict_map_key=False)


# --- Carried identity (opt-in): log in once on Windows, run headless elsewhere --------------------
# UMA_AUTH_CONFIG=<file> on the Windows PC writes the identity after a login that worked;
# UMA_CARRY_IDENTITY=1 on the headless host starts from that file instead of capturing. With neither
# set nothing here reads or writes anything. Off Windows the device fields are never derived from the
# host (its model/GPU/kernel/IP are a different machine to the server): the file must carry them all.
CARRIED_FIELDS = ("device_id", "device_name", "graphics_device_name", "ip_address",
                  "platform_os_version", "app_ver", "res_ver", "screen_h")


def carrying_identity():
    """UMA_CARRY_IDENTITY=1 (exactly; "true"/"yes"/"0"/unset are all off): start from the identity
    file instead of a capture."""
    return (os.environ.get("UMA_CARRY_IDENTITY") or "").strip() == "1"


def windows_screen_h():
    """The screen height race_out's synthetic click is scaled to: this PC's, read the way the game
    sees it (864 when it can't be read)."""
    import ctypes
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDPIAware()
        return user32.GetSystemMetrics(1)
    except Exception:
        return 864


def _same_or_under(path, root):
    """path is root or inside it: by file identity (junctions, symlinks, 8.3 / trailing-space names),
    else by resolved name (a root that does not exist)."""
    for p in (path, *path.parents):
        try:
            if os.path.samefile(p, root):
                return True
        except OSError:
            pass
    return path == root or root in path.parents


def auth_config_path():
    """The identity file: UMA_AUTH_CONFIG, else ~/.mqa/auth_config.json when carrying, else None.

    Also None (refused) inside the app tree or a OneDrive folder: the file holds auth_key, and this
    repo lives in OneDrive, which would sync it off the machine."""
    explicit = (os.environ.get("UMA_AUTH_CONFIG") or "").strip()
    if not explicit and not carrying_identity():
        return None
    path = Path(explicit or Path.home() / ".mqa" / "auth_config.json").expanduser()
    # \\?\ and \\host\C$ forms dodge the comparison below (resolve() even turns a trailing-space
    # folder name into \\?\...), and a network share is no place for auth_key either: refuse every
    # path that starts with two backslashes -- a UNC one before resolve() could reach its host.
    if not str(path).startswith("\\\\"):
        path = path.resolve()
    if str(path).startswith("\\\\"):
        print(f"[identity] REFUSING {path}: \\\\?\\ and network (UNC) paths are not allowed. "
              f"Point UMA_AUTH_CONFIG at a plain local path.", flush=True)
        return None
    for root in filter(None, (DIR, os.environ.get("OneDrive"), os.environ.get("OneDriveConsumer"),
                              os.environ.get("OneDriveCommercial"))):
        root = Path(root).resolve()
        if _same_or_under(path, root):
            print(f"[identity] REFUSING {path}: it is inside {root} (checked in / cloud-synced). "
                  f"Point UMA_AUTH_CONFIG outside it.", flush=True)
            return None
    return path


def missing_carried_fields(cfg):
    return [k for k in CARRIED_FIELDS if not str(cfg.get(k) or "").strip()]


def load_auth_config():
    """The carried identity as a UmaClient cfg ({} when not opted in, absent or unreadable). A Steam
    ticket is never carried (single-use, and the Windows game owns it): login mints a fresh one."""
    path = auth_config_path()
    if not path:
        return {}
    try:
        if platform.system() != "Windows" and path.stat().st_mode & 0o077:
            os.chmod(path, 0o600)   # copied over from Windows (scp / USB) with a loose mode
            print(f"[identity] {path} was readable by other users: set it to 0600", flush=True)
        cfg = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(cfg, dict) or not all(isinstance(v, (str, int)) for v in cfg.values()):
            raise ValueError("not a JSON object of strings and numbers")
        int(cfg.get("auth_key_len") or 0), int(cfg.get("screen_h") or 0)   # the values parsed as ints
    except (OSError, ValueError) as e:
        print(f"[identity] no usable identity at {path} ({e})", flush=True)
        return {}
    for key in ("steam_id", "steam_session_ticket", "steam_password_seed"):
        cfg.pop(key, None)
    return cfg


def _write_private(path, text):
    """Atomic, and 0600 from creation: a fresh, exclusive temp name (mkstemp: O_EXCL, 0600) that no
    other writer or planted link can share, removed again if anything fails."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_auth_config(cfg, path=None):
    """Write the identity file (None when not opted in / refused): atomic, and 0600 from creation."""
    path = path or auth_config_path()
    if not path:
        return None
    _write_private(path, json.dumps(cfg, indent=1))
    return path


def device_seed():
    """This install's own random seed for device_id: <runtime>/device_seed (uma_runtime/ is gitignored),
    made on the first run and again whenever it is blank. Never the Steam password."""
    # ponytail: two first-ever starts at the same instant each mint one and the later write wins; the
    # earlier process's device_id then changes once at its next restart. Lock the file if that matters.
    # (On Windows the losing os.replace can raise instead: then use the seed the winner just wrote.)
    path = runtime_output_root() / "device_seed"
    try:
        seed = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        seed = ""
    if not seed:
        seed = secrets.token_hex(32)
        try:
            _write_private(path, seed)
        except OSError:
            seed = path.read_text(encoding="utf-8").strip()
            if not seed:
                raise
    return seed


def get_gpu():
    if platform.system() != "Windows":
        raise RuntimeError(f"Unsupported OS: {platform.system()}. Only Windows is supported for PC info consistency.")

    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Video") as video_key:
            for i in range(winreg.QueryInfoKey(video_key)[0]):
                adapter_guid = winreg.EnumKey(video_key, i)
                adapter_path = rf"SYSTEM\CurrentControlSet\Control\Video\{adapter_guid}\0000"
                try:
                    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, adapter_path) as adapter_key:
                        value, _ = winreg.QueryValueEx(adapter_key, "HardwareInformation.AdapterString")
                        if isinstance(value, bytes):
                            value = value.decode("utf-16-le", errors="ignore")
                        gpu_name = str(value).replace("\x00", "").strip()
                        if gpu_name:
                            return gpu_name
                except OSError:
                    continue
    except Exception as e:
        raise RuntimeError(f"Failed to fetch GPU info: {e}") from e

    raise RuntimeError("Failed to fetch GPU info: display adapter registry value empty")

def get_os():
    return f"Windows 11  ({platform.version()}) 64bit"

def get_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    return ip

def get_hwid():
    guid = str(uuid.uuid4()).lower()
    
    if platform.system() != "Windows":
        # Off Windows every device field comes from the carried identity (UmaClient refuses without
        # them) -- never this host's own model/GPU/kernel/IP. Only the udid fallback is minted here.
        return {'udid': guid}
    
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"HARDWARE\DESCRIPTION\System\BIOS") as bios_key:
            device_name, _ = winreg.QueryValueEx(bios_key, "SystemProductName")
            device_name = str(device_name).strip()
            try:
                board_mfg, _ = winreg.QueryValueEx(bios_key, "BaseBoardManufacturer")
                if board_mfg:
                    device_name = f"{device_name} ({str(board_mfg).strip()})"
            except OSError:
                pass
        if not device_name:
            raise RuntimeError("System product name returned empty. Refusing to start.")
            
        machine_guid = ""
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as crypto_key:
                machine_guid, _ = winreg.QueryValueEx(crypto_key, "MachineGuid")
        except OSError:
            pass
            
    except Exception as e:
        raise RuntimeError(f"Failed to fetch system product name: {e}. Refusing to start.")

    hardware_string = f"{device_name}_{machine_guid}_{device_seed()}"
    device_id = hashlib.sha1(hardware_string.encode()).hexdigest()

    return {
        'device_name': device_name,
        'graphics_device_name': get_gpu(),
        'platform_os_version': get_os(),
        'ip_address': get_ip(),
        'udid': guid,
        'device_id': device_id
    }

def check_deps():
    if not shutil.which('node'):
        raise Exception("Node.js not found. Node is ONLY needed for the manual Steam-login path -- the "
                        "normal in-game auth capture (python main.py --reauth) needs no Node/npm. Install "
                        "from https://nodejs.org and reopen the terminal, or just use the --reauth capture.")
    if not os.path.exists(os.path.join(DIR, 'node_modules')):
        # On Windows npm is npm.cmd/npm.ps1 (there's no npm.exe), so a bare shell=False exec raises
        # FileNotFoundError [WinError 2] even when Node is correctly installed -- run it via the shell there.
        subprocess.run(['npm', 'install', '--silent'], check=True, cwd=DIR, shell=(os.name == 'nt'))

def get_ticket(u, p, c=''):
    global LAST_TICKET_GEN_RESULT
    check_deps()
    cmd = ['node', '-e', TICKET_GEN_JS]
    # The login rides in the child's environment, never argv: argv is world-readable
    # (/proc/<pid>/cmdline), and a TimeoutExpired message would print it.
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60, cwd=DIR,
                              env=dict(os.environ, MQA_STEAM_USERNAME=u, MQA_STEAM_PASSWORD=p,
                                       MQA_STEAM_CODE=c or ''))
    except subprocess.TimeoutExpired:
        raise Exception('Steam login timed out after 60s') from None
    LAST_TICKET_GEN_RESULT = {
        'stdout': proc.stdout,
        'stderr': proc.stderr,
        'returncode': proc.returncode,
    }
    if proc.returncode == 2:
        raise Exception('STEAM_GUARD_REQUIRED')
        
    out = proc.stdout.strip()
    if not out or proc.returncode != 0:
        error_msg = proc.stderr.strip() or 'fail'
        raise Exception(error_msg)
        
    line = out.split('\n')[-1]
    try:
        d = json.loads(line)
        return d['steam_id'], d['session_ticket']
    except:
        raise Exception('bad json')

class UmaClient:

    def __init__(self, cfg, trace_enabled=True):
        missing = missing_carried_fields(cfg) if platform.system() != "Windows" else []
        if missing:
            raise RuntimeError(f"Off Windows MQA only sends the identity carried from the Windows PC, and it "
                               f"lacks {', '.join(missing)}. Re-export it there (UMA_AUTH_CONFIG=<file>, "
                               f"then log in) and copy the file over again.")
        profile = get_hwid()

        self.viewer_id = cfg.get('viewer_id', 0)
        self.udid_str = cfg.get('udid') or profile['udid']
        self.auth_key_hex = cfg.get('auth_key', '')
        self.steam_id = str(cfg.get('steam_id', ''))
        self.steam_ticket = cfg.get('steam_session_ticket', '')
        # Steam creds, present only when a form login was used. They let login() re-mint a
        # fresh Steam ticket mid-run on error 394 (stale/single-use ticket) instead of
        # re-presenting the dead one forever. Empty for captured-ticket logins -> re-mint
        # no-ops and login falls back to the plain retry. steam_password_seed is now ONLY that
        # in-memory password (old name): device_id comes from device_seed(), not from it.
        self.steam_username = cfg.get('steam_username', '') or ''
        self.steam_password_seed = cfg.get('steam_password_seed', '') or ''
        
        self.device_id = cfg.get('device_id') or profile['device_id']
        self.device_name = cfg.get('device_name') or profile['device_name']
        self.graphics_device = cfg.get('graphics_device_name') or profile['graphics_device_name']
        self.ip_address = cfg.get('ip_address') or profile['ip_address']
        self.platform_os = cfg.get('platform_os_version') or profile['platform_os_version']
        self.locale = cfg.get('locale', 'JPN')
        # The Windows PC's screen height, carried so race_out's click stays that PC's (0: read it live).
        self.screen_h = int(cfg.get('screen_h') or 0)
        
        # Version mismatch (server 214/217 on load/index) is the #1 post-update breakage: the
        # RES-VER/APP-VER captured off the game no longer match what the server requires. Allow a
        # manual override via env (UMA_APP_VER / UMA_RES_VER / UMA_UNITY_VER) for when the capture is
        # stale, and print what we're about to send so a stale value is immediately visible.
        self.unity_ver = os.environ.get('UMA_UNITY_VER') or cfg.get('unity_ver', '2022.3.62f2')
        self.app_ver = os.environ.get('UMA_APP_VER') or cfg.get('app_ver', '')
        self.res_ver = os.environ.get('UMA_RES_VER') or cfg.get('res_ver', '')
        print(f"[client] sending APP-VER={self.app_ver or '?'} RES-VER={self.res_ver or '?'} "
              f"UNITY={self.unity_ver}", flush=True)

        self.sid = bytes(16)
        self.cached_load_data = {}
        self.tp_info = {}
        self.coin_info = {}
        self.item_map = {}
        self.current_scenario_id = None
        # Auto-backoff: rolling window of recent server-error timestamps. When it
        # fills past CIRCUIT_ERROR_THRESHOLD, `circuit_tripped` flips True and the
        # runner stops to avoid hammering a throttled/unhappy server.
        self.circuit_tripped = False
        # Sticky copy of a trip: the cooldown inside the NEXT call() clears circuit_tripped before the
        # runner ever polls it, so the runner/loop stop on this instead. Only reset_circuit() clears it.
        self.circuit_trip_seen = False
        # Optional zero-arg callable; True aborts a breaker cooldown (the runner wires its Stop flag).
        self.should_abort = None
        self._err_window = collections.deque()
        self._circuit_tripped_at = 0.0
        # probing_102() nesting depth: >0 means 102s are EXPECTED state-probes right now
        # (start-102 succession sweep / is-a-career-active diagnostics) and must not feed the breaker.
        self._probe_102_depth = 0
        self.session = requests.Session()
        self.update_headers()
        self.api_jitter = dna_uniform(-0.02, 0.02)

        self.on_api_log = None
        self.trace_file = None
        if trace_enabled:
            self._init_trace_log()

    def _init_trace_log(self):
        try:
            log_dir = TRACE_DIR / "api_payloads"
            log_dir.mkdir(parents=True, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            suffix = uuid.uuid4().hex[:6]
            self.trace_file = log_dir / f"{ts}_{suffix}_payloads.jsonl"
        except Exception as e:
            print(f"Error initializing trace log: {e}")
            self.trace_file = None

    def api_log(self, direction, ep, data, req_id=None):
        safe_data = redact_for_log(data)
        log_entry = {
            "ts": time.time(),
            "direction": direction,
            "endpoint": ep,
            "data": safe_data
        }
        if req_id:
            log_entry["req_id"] = req_id
            
        if callable(self.on_api_log):
            try:
                self.on_api_log(direction, ep, safe_data, req_id)
            except Exception:
                pass
        
        if self.trace_file:
            try:
                def _json_default(obj):
                    if isinstance(obj, bytes):
                        return obj.hex()
                    return str(obj)

                with open(self.trace_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps(log_entry, ensure_ascii=False, default=_json_default) + "\n")
            except Exception as e:
                print(f"Error writing to log: {e}")

        # Per-endpoint API library: records every call under uma_runtime/api_library/<dir>/<ep>.jsonl
        try:
            from uma_api import api_library
            api_library.record(log_entry)
        except Exception:
            pass

    def api_payload_summary(self, ep, payload):
        payload = payload or {}
        summary = {"current_turn": payload.get("current_turn")}
        if ep == "single_mode_free/gain_skills":
            summary["gain_skill_info_array"] = payload.get("gain_skill_info_array") or []
        elif ep == "single_mode_free/multi_item_exchange":
            summary["exchange_item_info_array"] = payload.get("exchange_item_info_array") or []
        elif ep == "single_mode_free/multi_item_use":
            summary["use_item_info_array"] = payload.get("use_item_info_array") or []
        return summary

    def safe_payload(self, payload):
        return redact_for_log(dict(payload or {}))

    def response_summary(self, res):
        data = res.get("data") or {}
        headers = res.get("data_headers") or {}
        chara = data.get("chara_info") or data.get("single_mode_chara_light") or {}
        home = data.get("home_info") or {}
        events = data.get("unchecked_event_array") or []
        race = data.get("race_start_info") or {}
        summary = {
            "result_code": headers.get("result_code"),
            "keys": list(data.keys()),
        }
        if chara:
            summary["chara"] = {
                "turn": chara.get("turn"),
                "vital": chara.get("vital"),
                "max_vital": chara.get("max_vital"),
                "skill_point": chara.get("skill_point"),
                "fans": chara.get("fans"),
                "playing_state": chara.get("playing_state"),
            }
        if home:
            summary["commands"] = [
                {
                    "type": item.get("command_type"),
                    "id": item.get("command_id"),
                    "group": item.get("command_group_id"),
                    "enable": item.get("is_enable"),
                    "fail": item.get("failure_rate"),
                }
                for item in home.get("command_info_array") or []
            ]
        if events:
            summary["events"] = [
                {
                    "event_id": item.get("event_id"),
                    "chara_id": item.get("chara_id"),
                    "choices": len(((item.get("event_contents_info") or {}).get("choice_array") or [])),
                }
                for item in events
            ]
        if race:
            summary["race_start_info"] = {
                "program_id": race.get("program_id"),
                "race_instance_id": race.get("race_instance_id"),
                "is_short": race.get("is_short"),
            }
        return summary

    def auth_bytes(self):
        if not self.auth_key_hex or self.auth_key_hex == 'YOUR_AUTH_KEY_HERE':
            return b''
        return bytes.fromhex(self.auth_key_hex)

    def has_captured_auth(self):
        try:
            int(self.viewer_id)
            bytes.fromhex(str(self.auth_key_hex))
        except (TypeError, ValueError):
            return False
        return bool(
            self.viewer_id
            and self.udid_str
            and self.auth_key_hex
            and self.auth_key_hex != 'YOUR_AUTH_KEY_HERE'
            and self.steam_id
            and self.steam_ticket
        )

    def refresh_cached_account_state(self, data):
        if not data:
            return
        self.cached_load_data.update(data)
        if data.get('tp_info'):
            self.tp_info = data['tp_info']
        if data.get('coin_info'):
            self.coin_info = data['coin_info']

        item_list = data.get('user_item') or data.get('user_item_array') or data.get('item_list')
        if isinstance(item_list, list):
            for item in item_list:
                iid = item.get('item_id')
                num = item.get('number')
                if iid is not None and num is not None:
                    self.item_map[int(iid)] = int(num)

    def regen_sid(self):
        self.sid = make_sid(self.viewer_id, self.udid_str)

    def common(self):
        return {
            'viewer_id': self.viewer_id, 'device': 4, 'device_id': self.device_id,
            'device_name': self.device_name, 'graphics_device_name': self.graphics_device,
            'ip_address': self.ip_address, 'platform_os_version': self.platform_os,
            'carrier': '', 'keychain': 0, 'locale': self.locale,
            'button_info': '', 'dmm_viewer_id': None, 'dmm_onetime_token': None,
            'steam_id': self.steam_id,
            'steam_session_ticket': self.steam_ticket
        }

    def update_headers(self):
        self.session.headers.update({
            'User-Agent': f'UnityPlayer/{self.unity_ver} (UnityWebRequest/1.0, libcurl/8.10.1-DEV)',
            'Accept': '*/*', 'Accept-Encoding': 'deflate, gzip',
            'Content-Type': 'application/x-msgpack', 'X-Unity-Version': self.unity_ver
        })

    def reset_circuit(self):
        """Clear auto-backoff state for a fresh, deliberate run. If the server is
        still throttling, the breaker simply re-trips within the next window."""
        self.circuit_trip_seen = False
        self._clear_circuit()

    def _clear_circuit(self):
        self.circuit_tripped = False
        self._err_window.clear()
        self._circuit_tripped_at = 0.0

    def _wait_for_circuit_cooldown(self):
        """Wait out a tripped-breaker cooldown before allowing another API call.

        The breaker is cleared lazily on the next call instead of from a background timer. That keeps
        the reset serialized with network activity and never starts traffic on its own while the
        server may still be throttling. `circuit_trip_seen` survives the clear so the runner still
        stops. The wait is sliced so a Stop (should_abort) ends it without sending the request.
        """
        if not self.circuit_tripped:
            return
        tripped_at = float(getattr(self, "_circuit_tripped_at", 0.0) or 0.0)
        end = tripped_at + CIRCUIT_COOLDOWN_SEC
        if end > time.time():
            print(f"CIRCUIT BREAKER: cooling down {end - time.time():.1f}s before the next API call", flush=True)
        while (left := end - time.time()) > 0:
            abort = getattr(self, "should_abort", None)
            if callable(abort) and abort():
                raise Exception(f"{CIRCUIT_COOLDOWN_STOP} (request not sent)")
            server_sleep(min(2.0, left), min(2.0, left))
        self._clear_circuit()

    @contextmanager
    def probing_102(self):
        """Scope in which 102 results are EXPECTED state-probes -- the start-102 succession sweep,
        the is-a-career-active diagnostics, the force-delete no-op. Inside this scope a 102 still
        RAISES to the caller (the probe loop needs the failure), but it doesn't feed the circuit
        breaker or dump the full error JSON: the bot's own calibration probes must never trip its
        own auto-backoff (live log 20260706_171909: the sweep's expected 102s tripped the breaker,
        which then killed the very career the sweep had just successfully started). Every OTHER
        result code (205/208/5xx -- the real throttle signals) keeps full accounting."""
        self._probe_102_depth += 1
        try:
            yield
        finally:
            self._probe_102_depth -= 1

    def _should_note_error(self, ep, rc):
        """False only for EXPECTED 102s: the documented already-done race endpoints, or any 102
        inside a probing_102() scope. Everything else counts toward the breaker."""
        if rc != 102:
            return True
        # `call()` routes the canonical free endpoint before checking the response, so the same
        # already-completed cleanup can surface under every scenario namespace. Match the exact
        # leaf to cover those routes without silencing Unity's distinct `team_race_out` endpoint.
        if str(ep).rsplit('/', 1)[-1] in {"race_end", "race_out"}:
            return False
        return getattr(self, "_probe_102_depth", 0) <= 0

    def _note_api_error(self, ep, rc):
        """Record a surfaced server error and trip the circuit breaker if too
        many happen within the rolling window. Sets `self.circuit_tripped` so the
        runner can stop; does NOT raise (the normal API error still propagates)."""
        now = time.time()
        win = self._err_window
        win.append(now)
        cutoff = now - CIRCUIT_ERROR_WINDOW_SEC
        while win and win[0] < cutoff:
            win.popleft()
        if len(win) >= CIRCUIT_ERROR_THRESHOLD and not self.circuit_tripped:
            self.circuit_tripped = True
            self.circuit_trip_seen = True
            self._circuit_tripped_at = now
            print(
                f"CIRCUIT BREAKER TRIPPED: {len(win)} server errors within "
                f"{int(CIRCUIT_ERROR_WINDOW_SEC)}s (last: {rc} on {ep}). "
                f"Auto-backoff -- the server is likely throttling. Stopping soon.",
                flush=True,
            )

    # scenario_id -> the namespaced career `load` used to probe/resume an in-progress career.
    # MUST list every playable scenario: a missing id makes load_career's `pinned in EP` check fail, so
    # the probe silently skips that namespace and an already-running career of that type can never be
    # resumed (this is exactly what happened to Grand Live / 3 = single_mode_live).
    CAREER_LOAD_EP = {4: 'single_mode_free/load', 2: 'single_mode_team/load',
                      1: 'single_mode/load', 3: 'single_mode_live/load'}

    @staticmethod
    def _route_ep(ep, scenario_id):
        # Every career endpoint is written internally as single_mode_free/* (MANT's namespace) and
        # remapped here by the LIVE scenario -- payloads are byte-identical across namespaces, only
        # the URL prefix differs:
        #   scenario 2 (Team/Unity) -> single_mode_team/*  (verified: team start rc=1, capture
        #       20260703_233031; whole career incl. START runs on the team prefix)
        #   scenario 1 (URA Finale) -> single_mode/*       (the PLAIN prefix -- sourced from a
        #       working URA fork ("new api bot": set_scenario(1) -> api_prefix "single_mode",
        #       single_mode/start in its live 205-handling); URA is the original scenario, so it
        #       keeps the original unsuffixed namespace)
        #   scenario 4 (MANT)       -> single_mode_free/*  (unchanged)
        # Non-single_mode endpoints pass through untouched.
        if ep.startswith('single_mode_free/'):
            leaf = ep[len('single_mode_free/'):]
            if scenario_id == 2:
                return 'single_mode_team/' + leaf
            if scenario_id == 1:
                return 'single_mode/' + leaf
            #   scenario 3 (Grand Live / "Our Grand Concert") -> single_mode_live/*  (CONFIRMED from a
            #       full 78-turn capture: start/load/check_event/exec_command/get_choice_reward/
            #       race_entry|start|end|out/gain_skills/factor_select/finish all carry byte-identical
            #       payloads to the other namespaces, plus the two Grand-Live-only calls
            #       master_square{square_id} and live_start{} -- see scenarios/grand_live.py)
            if scenario_id == 3:
                return 'single_mode_live/' + leaf
        return ep

    def call(self, ep, args=None, retry_208=6, retry_205=3, timeout=30, retry_net=7, retry_res=2,
             retry_394=1):
        # Succession-point calibration deliberately tries several candidate start payloads. A 208 on
        # one candidate should be handled by that outer sweep, not retried repeatedly inside the same
        # candidate and multiplied across the whole calibration loop.
        self._wait_for_circuit_cooldown()
        if (getattr(self, "_sweep_start_no_retry_208", False)
                and str(ep).rsplit("/", 1)[-1] == "start"):
            retry_208 = 0
        if not hasattr(self, '_last_raw_call_ts'):
            self._last_raw_call_ts = 0

        el = time.time() - self._last_raw_call_ts
        if el < 0.14:
            dna_sleep(0.14 - el, 0.14 - el)

        self._last_raw_call_ts = time.time()

        req_id = str(uuid.uuid4())[:8]
        payload = args or {}
        payload.update(self.common())

        ep = self._route_ep(ep, self.current_scenario_id)

        # Synthetic "tap to continue" click coordinate on race_out (anti-detection). Match by SUFFIX
        # because `ep` is already scenario-routed above: URA -> single_mode/race_out, MANT ->
        # single_mode_free/race_out, Unity -> single_mode_team/race_out. The old prefix tuple listed
        # only the free/team paths, so URA's routed race_out silently shipped no click coord. Excludes
        # Unity's team_race_out (leaf 'team_race_out' != 'race_out'), which never carried button_info.
        if str(ep).rsplit('/', 1)[-1] == 'race_out':
            screen_h = getattr(self, 'screen_h', 0) or windows_screen_h()

            window_w = int(screen_h * 9 / 16)
            scale_factor = 1080 / window_w
            
            ref_x = max(844, min(1150, int(dna_gauss(991, 62))))
            ref_y = max(55, min(255, int(dna_gauss(144, 33))))
            
            physical_x = int(ref_x / scale_factor)
            physical_y = int(ref_y / scale_factor)
            
            click_x = int(physical_x * scale_factor * 10000)
            click_y = int(physical_y * scale_factor * 10000)
            
            click_ts = int(time.time() - dna_uniform(3.0, 4.5))
            btn = {
                "ViewerId": self.viewer_id,
                "DeviceId": 4,
                "ScenarioId": self.current_scenario_id,
                "ClickPosX": click_x,
                "ClickPosY": click_y,
                "ClickServerTime": click_ts
            }
            payload['button_info'] = json.dumps(btn, separators=(',', ':'))

        self.api_log("REQ", ep, {
            "payload": payload,
        }, req_id)

        max_retries = max(1, int(retry_net))
        for attempt in range(max_retries):
            # Re-pack body + headers on EVERY attempt so each retry uses the CURRENT self.sid, which
            # now rotates on error responses too (see below). Building the body once with a stale sid
            # is what turned a single failure into a 217 cascade after the 1.32.8 update.
            body = pack(self.sid, get_raw_udid(self.udid_str), self.auth_bytes(), payload, self.udid_str)
            headers = {
                'SID': self.sid.hex(), 'Device': '4', 'ViewerID': str(self.viewer_id),
                'APP-VER': self.app_ver, 'RES-VER': self.res_ver,
            }
            try:
                resp = self.session.post(BASE_URL + ep, data=body, headers=headers, timeout=timeout)
            except Exception as e:
                if attempt < max_retries - 1:
                    backoff_sleep(attempt, base=1.0, cap=15.0)
                    continue
                self.api_log("ERR", ep, {"error": str(e)}, req_id)
                raise Exception(f'Network error on {ep}: {e}')
            # Transient server-side errors (HTTP 5xx, e.g. a 500 on race_end) are
            # retried with backoff instead of crashing the whole career/loop.
            if 500 <= resp.status_code < 600 and attempt < max_retries - 1:
                print(f"HTTP {resp.status_code} on {ep}, retrying... (attempt {attempt + 1})", flush=True)
                backoff_sleep(attempt, base=1.0, cap=15.0)
                continue
            break

        if resp.status_code != 200:
            body_preview = resp.text[:500] if resp.text else ""
            self.api_log("ERR", ep, {"http_status": resp.status_code, "body": body_preview}, req_id)
            print(f"HTTP error on {ep}: status={resp.status_code} body={body_preview}")
            raise Exception(f'HTTP {resp.status_code} on {ep}: {body_preview}')
            
        res = unpack(resp.text.strip(), self.udid_str)
        dh = res.get('data_headers', {})
        rc = dh.get('result_code', 0)
        # Latest game server time (Unix UTC) -- the authoritative clock for the daily reset,
        # so the fan tally rolls over with the GAME's new day, not the local machine clock.
        st = dh.get('servertime')
        if st:
            try:
                self.last_servertime = int(st)
            except (TypeError, ValueError):
                pass

        self.api_log("RES", ep, res, req_id)
        
        data = res.get('data', {})
        if isinstance(data, dict):
            if data.get('tp_info'):
                self.tp_info = data['tp_info']
            if data.get('coin_info'):
                self.coin_info = data['coin_info']
            if data.get('chara_info') and data['chara_info'].get('scenario_id'):
                self.current_scenario_id = data['chara_info']['scenario_id']
            # Fix 2A (Global 2026-07): adopt the server-advertised resource version PROACTIVELY.
            # start_session/load success responses carry the current version in data.res_version;
            # taking it here means we stop sending a stale RES-VER before the server has to reject us
            # with a 214 (the reactive 214 handler below still covers the endpoints that enforce it).
            srv_res_ver = data.get('res_version')
            if srv_res_ver and str(srv_res_ver) != str(self.res_ver):
                print(f"[RES-VER] adopted from server on {ep}: {self.res_ver} -> {srv_res_ver}", flush=True)
                self.res_ver = str(srv_res_ver)
            item_list = data.get('user_item') or data.get('user_item_array')
            if isinstance(item_list, list):
                for item in item_list:
                    iid = item.get('item_id')
                    num = item.get('number')
                    if iid is not None and num is not None:
                        self.item_map[int(iid)] = int(num)

        # Rotate the sid on EVERY response -- success AND error. The server issues a fresh sid in
        # data_headers on every reply; only advancing it on success (the old behaviour, at the bottom
        # of the method) left a STALE sid after any error, so the next call failed with 217 ("invalid
        # session sequence"). Once 1.32.8 made read_info start returning 102, that poisoned the sid
        # and cascaded 217 across every subsequent call. Rotate here, before the 709/error handling.
        if dh.get('sid') and isinstance(dh['sid'], str) and dh['sid'].strip():
            self.sid = next_sid(dh['sid'])

        if rc == 709:
            # 709 = viewer_id/auth mismatch. The server echoes a viewer_id in data_headers, but on a
            # non-success reply that is often an ERROR SENTINEL, not a real account to adopt (corpus
            # check across 661 run logs: the client never once legitimately SENT the sentinel id --
            # e.g. 6553960516532 appears only in error responses). Adopting it would silently run the
            # rest of the loop as the wrong account and 102 forever. So report the mismatch and fail
            # clean -- do NOT self.viewer_id = new_vid. The freshly Frida-captured id is authoritative.
            srv_vid = dh.get('viewer_id') or res.get('data', {}).get('viewer_id')
            if srv_vid and srv_vid != self.viewer_id:
                print(f"709 on {ep}: server returned viewer_id {srv_vid} != captured {self.viewer_id} "
                      f"(NOT adopting -- likely a server error sentinel, not a real account)")
            raise Exception(f'709 on {ep}')
        # 214 on load/index = resource-version mismatch after a game res patch. The server helpfully
        # returns the CORRECT res_ver in data_headers.resource_version -- adopt it and retry (like the
        # 709 viewer-id auto-adopt above), so small res bumps (e.g. 10006800 -> 10006810) self-heal
        # without a re-capture or manual UMA_RES_VER override. The value-changed guard + retry_res cap
        # prevent an infinite loop if the server keeps rejecting the same version.
        if rc == 214 and retry_res > 0:
            server_res = str(dh.get('resource_version') or (res.get('data') or {}).get('resource_version') or '')
            if server_res and server_res != str(self.res_ver):
                print(f"[RES-VER auto-update] {self.res_ver} -> {server_res} after 214 on {ep}; retrying", flush=True)
                self.res_ver = server_res
                return self.call(ep, args, retry_208=retry_208, retry_205=retry_205,
                                 timeout=timeout, retry_net=retry_net, retry_res=retry_res - 1,
                                 retry_394=retry_394)
        # 394 = stale Steam ticket; it rides in common() on EVERY request, so it can surface mid-career.
        # Carried-identity hosts re-mint ONCE from the stored Steam login and retry (Windows default
        # unchanged: it stops). Never on 391 -- that is the Windows game taking the one Steam session.
        # A re-mint whose retry still got 394 is not repeated (one Steam login per API call) until a call
        # succeeds again, and a Stop never starts one.
        if rc == 1:
            self._remint_failed = False
        if (rc == 394 and retry_394 > 0 and carrying_identity() and not getattr(self, "_remint_failed", False)
                and not (callable(getattr(self, "should_abort", None)) and self.should_abort())):
            try:
                reminted = self.refresh_steam_ticket()
            except Exception as exc:
                print(f"[steam] could not re-mint after 394 on {ep}: {exc}", flush=True)
                reminted = False
            if reminted:
                print(f"[steam] re-minted the session ticket after 394 on {ep}; retrying", flush=True)
                try:
                    return self.call(ep, args, retry_208=retry_208, retry_205=retry_205, timeout=timeout,
                                     retry_net=retry_net, retry_res=retry_res, retry_394=retry_394 - 1)
                except Exception as exc:
                    if is_api_error(exc, 394):
                        self._remint_failed = True
                    raise
        if rc != 1:
            # 205 on multi_item_exchange/use (shop action invalid for the current state) OR on `continue`
            # (the game won't accept a clock/race-retry now -- seen live in URA on a lost non-goal race)
            # is DETERMINISTIC: retrying is futile, and instant re-hits look bot-like. Surface it on the
            # FIRST hit and DON'T trip the circuit breaker -- the caller handles it (items.py blacklists
            # the item; the race clock loop breaks cleanly instead of a ~28-call 205/208 storm).
            if rc == 205 and is_deterministic_205(ep):
                err_detail = format_api_error(ep, rc, res)
                raise Exception(f'API error {rc} on {ep}: {err_detail}')

            if rc == 205 and retry_205 > 0:
                print(f"205 on {ep}, retrying... ({retry_205} left)")
                # server_sleep: must wait even with the delay kill-switch on.
                server_sleep(0.3, 0.7)
                return self.call(ep, args, retry_208=retry_208, retry_205=retry_205 - 1,
                                 timeout=timeout, retry_net=retry_net, retry_res=retry_res,
                                 retry_394=retry_394)

            if rc == 208 and retry_208 > 0:
                # gain_skills / multi_item_* return 208 as a benign "busy" -- the action still lands, so
                # accept it instead of retry-storming. Match by SUFFIX (not the single_mode_free/* string)
                # because `ep` is already namespace-routed: a Unity career's end-of-career skill buy hits
                # single_mode_team/gain_skills, which the old free-only set missed -> it hammered the 208
                # backoff and failed. Now team + free both short-circuit cleanly.
                if str(ep).rsplit("/", 1)[-1] in {"gain_skills", "multi_item_exchange", "multi_item_use"}:
                    return res

                # 208 = the server explicitly saying "slow down". Back off
                # EXPONENTIALLY (1s -> 2s -> 4s -> 8s -> 15s, jittered) and never
                # skip the wait -- instant re-hits are what get accounts flagged.
                # (The first retry used to skip this: `retry_208 < 6` is False at the default 6.)
                attempt = max(0, 6 - retry_208)
                print(f"API error 208 (SERVER BUSY) on {ep}, backing off and retrying... (attempts left: {retry_208-1})")
                backoff_sleep(attempt, base=1.0, cap=15.0)
                # Thread retry_205 through: without it a 208 reset the 205 budget to its default every
                # time, so a mixed 205/208 sequence ping-ponged into ~28 hits instead of stopping.
                return self.call(ep, args, retry_208=retry_208 - 1, retry_205=retry_205,
                                 timeout=timeout, retry_net=retry_net, retry_res=retry_res,
                                 retry_394=retry_394)
            # 102 on read_info/index = "already read / nothing new to acknowledge": a benign no-op.
            # start_session + load/index already succeeded, and read_info's result is only a
            # side-effect home-data load (discarded by login/hard_reset, try/except'd in main.py).
            # The live game began returning this after an update; treat it as success so it never
            # kills login. Returns the response as-is; does NOT touch the circuit breaker.
            if rc == 102 and ep == 'read_info/index':
                return res
            err_detail = format_api_error(ep, rc, res)
            err_msg = f'API error {rc} on {ep}: {err_detail}'
            # Expected 102s (already-done race endpoints, or any probing_102() scope) are not real
            # server rejections -- they must not count toward the breaker or spam the log.
            if self._should_note_error(ep, rc):
                self._note_api_error(ep, rc)
                print(err_msg)
            raise Exception(err_msg)
        # (sid already rotated above, for both success and error responses)
        return res

    def hard_reset(self):
        self.sid = bytes(16)
        self.regen_sid()
        self.session.close()
        self.session = requests.Session()
        self.update_headers()
        try:
            self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
            res = self.call('load/index', {
                'adid': ''
            })
            data = res.get('data', {})
            self.refresh_cached_account_state(data)
            # read_info/index is deprecated after 1.32.8 (always 102); load/index above already
            # populated tp_info/coin_info/item_map via refresh_cached_account_state.

            try:
                sm_res = self.call('single_mode_free/load', {})
                chara = sm_res.get('data', {}).get('chara_info')
                if not chara:
                    raise StateRecoveryError("No chara_info returned in single_mode_free/load after hard reset.")
            except Exception as e:
                if isinstance(e, StateRecoveryError):
                    raise
                if "API error 201" in str(e) or "API error 102" in str(e):
                    raise StateRecoveryError(f"Cannot recover training state: {e}")
                print(f"single_mode_free/load during hard_reset failed: {e}")
                # A home/load response is not a usable career state. Let the real recovery error
                # propagate instead of returning an account payload to the runner as if it were a
                # successfully reloaded turn.
                raise

            return sm_res
        except StateRecoveryError:
            raise
        except Exception as e:
            print(f"Hard Reset Failure: {e}")
            raise

    def resync_session(self):
        """Fix 5 (Global 2026-07): re-establish a clean SID chain WITHOUT requiring an in-progress
        career. hard_reset() does single_mode_free/load and raises StateRecoveryError when there's no
        career, so it can't recover a start-time 217. This reseeds the SID and re-handshakes only
        (start_session + load/index). Used by the start path after a residual 217 session desync."""
        self.sid = bytes(16)
        self.regen_sid()
        self.session.close()
        self.session = requests.Session()
        self.update_headers()
        self.call('tool/start_session', {'attestation_type': 0, 'device_token': None})
        res = self.call('load/index', {'adid': ''})
        self.refresh_cached_account_state(res.get('data', {}) or {})
        return res

    def signup(self):
        self.regen_sid()
        self.call('tool/pre_signup')
        jittered_sleep(0.83)
        self.regen_sid()
        res = self.call('tool/signup', {
            'error_code': 0, 'error_message': '', 'attestation_type': 0, 
            'optin_user_birth': 199801, 'dma_state': 0, 'country': 'Canada', 'credential': ''
        })
        d = res.get('data', {})
        if d.get('viewer_id'): 
            self.viewer_id = d['viewer_id']
        if d.get('auth_key'): self.auth_key_hex = base64.b64decode(d['auth_key']).hex()
        self.save_config()
        return res

    def refresh_steam_ticket(self, code=''):
        """Mint a fresh Steam session ticket mid-run after error 394 (stale/single-use
        ticket). Re-presenting the dead ticket can never succeed, so a fresh one is minted
        from stored Steam creds and any subsequent signup re-derives auth from it.

        Returns True on success, False when no Steam creds are stored (captured-ticket
        logins -> caller falls back to the plain retry). Re-raises STEAM_GUARD_REQUIRED so a
        genuine 2FA prompt can fall back to manual auth; other mint failures return False."""
        if not (self.steam_username and self.steam_password_seed):
            return False
        if carrying_identity():
            # One Steam login per stale-ticket spell: a mint that fails (Guard code needed, changed
            # password, Steam down) is not retried by every later 394 or runner re-login -- the run
            # stops instead. The next call that succeeds clears it (see call()).
            if getattr(self, "_remint_failed", False):
                return False
            self._remint_failed = True
        try:
            sid, tkt = get_ticket(self.steam_username, self.steam_password_seed, code)
        except Exception as exc:
            if 'STEAM_GUARD_REQUIRED' in str(exc):
                raise
            return False
        if not (sid and tkt):
            return False
        self.steam_id = str(sid)
        self.steam_ticket = tkt
        return True

    def login(self, max_retries=3):
        using_existing_auth = self.has_captured_auth()
        if not using_existing_auth:
            self.signup()
            using_existing_auth = self.has_captured_auth()

        old_h = dict(self.session.headers)
        self.session.close()
        self.session = requests.Session()
        self.session.headers.update(old_h)

        ticket_refreshed = False
        for attempt in range(max_retries + 1):
            try:
                self.regen_sid()
                # retry_394=0: login's own 394 branch below is its single re-mint authority.
                self.call('tool/start_session', {'attestation_type': 0, 'device_token': None}, retry_394=0)
                res = self.call('load/index', {'adid': ''}, retry_394=0)
                data = res.get('data', {})
                self.refresh_cached_account_state(data)
                # read_info/index is deprecated after 1.32.8 (always 102) -- the official login flow
                # is now just start_session -> load/index. load/index already populated the caches.
                return res
            except Exception as e:
                err = str(e)
                if 'API error 709 on' in err or 'API error 501 on' in err:
                    # 709 = the captured viewer_id/auth_key pair this Steam client is logged into does
                    # not match a live account; 501 = that account is dead/invalid. Both are
                    # ENVIRONMENTAL (the Steam session is bound to the wrong or dead in-game account),
                    # NOT a capture bug -- the Frida hook reads viewer_id + auth from the SAME request
                    # (verified identical to upstream). The former signup-wipe "recovery" here could
                    # silently mint or adopt a phantom account, so it was removed. The only real fix is
                    # an in-game Data Transfer of your real account onto this Steam client. Fail clean.
                    raise
                if is_api_error(err, 394) and attempt < max_retries:
                    # 394 = stale/expired single-use Steam ticket, NOT transient server-busy.
                    # Mint a fresh ticket ONCE from stored creds and retry instead of looping
                    # forever on the dead one. No-op (-> plain wait) for captured-ticket logins.
                    if not ticket_refreshed and self.refresh_steam_ticket():
                        ticket_refreshed = True
                        if not self.has_captured_auth():
                            try:
                                self.signup()  # re-derive auth_key from the fresh ticket
                            except Exception:
                                pass
                        continue
                    # server_sleep: a server-error retry must wait even with NO CD on.
                    server_sleep(2.0, 3.0)
                    continue
                if is_api_error(err, 202) and attempt < max_retries:
                    server_sleep(3.5, 4.8)
                    continue
                raise

    TP_POTION_ITEM_ID = 32  # "Toughness 30" -- restores 30 TP per use

    def tp_potion_count(self, item_id=None):
        item_id = int(item_id or self.TP_POTION_ITEM_ID)
        return int(self.item_map.get(item_id, 0) or 0)

    def recovery_tp(self, count=1):
        """Recover TP by spending Carats/Jewels via user/recovery_trainer_point.
        Each `count` recovers 30 TP. For item-backed recovery use use_recovery_item()."""
        total_jewels = self.coin_info.get("fcoin", 0) + self.coin_info.get("coin", 0)
        # Spending premium currency is irreversible. If the response is lost, retrying this request
        # could charge the account twice even though the first request reached the server.
        result = self.call_once("user/recovery_trainer_point", {
            "count": count,
            "client_own_num": total_jewels,
        })
        data = result.get("data", {})
        tp = data.get("tp_info", {})
        if tp:
            self.tp_info = tp
        coin = data.get("coin_info", {})
        if coin:
            self.coin_info = coin
        return tp

    def use_recovery_item(self, item_num=1, item_id=None):
        """Recover TP by USING a TP-recovery item (default Toughness 30 = id 32) via
        item/use_recovery_item -- the known-good payload {item_id, client_own_num,
        item_num} (verified against the live game + the SweepyMod fork). This is a
        DIFFERENT endpoint from recovery_trainer_point, which only spends Carats.
        Each item restores 30 TP; client_own_num is the owned POTION count."""
        item_id = int(item_id or self.TP_POTION_ITEM_ID)
        item_num = max(1, int(item_num or 1))
        own = self.tp_potion_count(item_id)
        # Potion use has the same ambiguous-response hazard as jewel recovery: dispatch it once and
        # let the next account refresh reconcile whether the server accepted it.
        result = self.call_once("item/use_recovery_item", {
            "item_id": item_id,
            "client_own_num": own,
            "item_num": item_num,
        })
        data = result.get("data", {}) if isinstance(result, dict) else {}
        tp = data.get("tp_info", {})
        if tp:
            self.tp_info = tp
        coin = data.get("coin_info", {})
        if coin:
            self.coin_info = coin
        # Decrement local count; the next account-state refresh corrects it exactly.
        self.item_map[item_id] = max(0, own - item_num)
        return tp

    def read_info(self):
        # 1.32.8 rejects the old add_*_data_array payload and returns 102; deprecated endpoint, kept
        # only for the career-start path (wrapped in try/except). Empty payload.
        return self.call('read_info/index', {})

    def finish_career(self, current_turn, is_force_delete=False, factor_lottery_id=1,
                      target_trained_chara_id=None):
        # UNITY / team (scenario 2), current game version: finish IS the slot-release step and takes
        # {target_viewer_id, target_trained_chara_id} (returns succession_history_array) -- NOT the old
        # 1.32.8 {current_turn, factor_lottery_id} shape. The old shape 102s and never releases the slot,
        # so a LOOP's next single_mode_team/start 102s ("in-progress career blocks a fresh start"). The
        # grade still comes back from factor_select, so single careers look fine; only the loop wedges.
        # Verified against live capture dumps/20260713_192951 (finish req = target_viewer_id +
        # target_trained_chara_id). MANT (4) / URA (1) keep the 1.32.8 shape until captured on this version.
        # Grand Live (3) behaves like Unity here: the plain {current_turn, factor_lottery_id} finish
        # returns rc=1 and the grade comes back -- so a SINGLE career looks fine -- but it does NOT
        # release the slot, so a LOOP's next single_mode_live/start 102s and wedges (live:
        # career_log_20260724_005918 -> finish rc=1, nickname rc=1, then start 102 forever). The
        # id-based {target_viewer_id, target_trained_chara_id} shape is the actual slot-release. The
        # scenario-3 single-career capture shows the plain shape precisely because a single career never
        # exposes the wedge -- same trap the Unity note describes.
        if self.current_scenario_id in (2, 3) and target_trained_chara_id:
            payload = {'target_viewer_id': self.viewer_id,
                       'target_trained_chara_id': int(target_trained_chara_id)}
            if is_force_delete:
                payload['is_force_delete'] = True
            return self.call('single_mode_free/finish', payload)
        # 1.32.8 (MANT/URA, + Unity fallback when the trained_chara_id is unknown): finish takes
        # factor_lottery_id (the lottery_id chosen in factor_select), NOT is_skip_story. Must run AFTER
        # factor_select or it returns 102 and never releases the career slot.
        return self.call('single_mode_free/finish', {
            'is_force_delete': is_force_delete,
            'current_turn': current_turn,
            'factor_lottery_id': factor_lottery_id,
        })

    def factor_select(self, current_turn=None, skill_id_array=None):
        """1.32.8 end-of-career inheritance-factor selection. Empty call rolls/returns the options
        (single_mode_factor_select_common.factor_select_info_array, each with a lottery_id); the
        turn'd call confirms and returns single_mode_finish_common (final grade + sparks)."""
        if current_turn is None:
            return self.call('single_mode_free/factor_select', {})
        return self.call('single_mode_free/factor_select',
                         {'current_turn': current_turn, 'skill_id_array': skill_id_array})

    def call_once(self, ep, args=None, timeout=30):
        """Dispatch a MUTATING call EXACTLY once -- no network, state-error, or version replay.

        Use this for irreversible currency/item consumption: after an ambiguous network failure the
        caller must refresh account state instead of risking a duplicate spend.
        """
        return self.call(ep, args, retry_208=0, retry_205=0, timeout=timeout, retry_net=1, retry_res=0,
                         retry_394=0)

    def current_tp_snapshot(self, tp_info=None):
        """The TP tuple the server validates a reroll against, recomputed at the latest server clock.
        TP regenerates 1 per 10 minutes, so sending a stale current_tp gets the call rejected."""
        src = tp_info if isinstance(tp_info, dict) else (self.tp_info or {})

        def _i(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        max_tp = max(1, _i(src.get('max_tp'), 1))
        max_recovery_time = _i(src.get('max_recovery_time'), 0)
        server_time = _i(getattr(self, 'last_servertime', 0), 0)
        if max_recovery_time <= server_time:
            current = max_tp
        else:
            missing = (max_recovery_time - server_time + 599) // 600   # 1 TP per 10 min, round up
            current = max(0, max_tp - missing)
        return {'current_tp': current, 'max_tp': max_tp, 'max_recovery_time': max_recovery_time}

    def factor_lottery(self, lottery_count=1, tp_info=None, use_tp=30):
        """Spend TP for ONE inheritance-spark reroll. Routed by scenario like every career endpoint
        (MANT single_mode_free / Unity single_mode_team / URA single_mode). Uses call_once so a
        network retry can never double-charge the TP."""
        return self.call_once('single_mode_free/factor_lottery', {
            'lottery_count': max(1, int(lottery_count or 1)),
            'tp_info': self.current_tp_snapshot(tp_info),
            'use_tp': max(1, int(use_tp or 30)),
        })

    # Scenario-completion nickname sent by the close-out's change_nickname (nickname.scenario_id in
    # master.mdb). Team/Unity=154 + MANT=180 both live-verified. URA has NO scenario-1 rows in the
    # nickname table, so it uses the GENERIC 92 (scenario_id 0, rank 1, receivable by any career --
    # verified worn by an actual URA-trained uma in the user's own roster capture).
    # scenario_id -> the completion nickname_id change_nickname must send. Wrong id -> 500, and for
    # Grand Live that 500 leaves the career slot UNRELEASED, so the next start 102s and a loop wedges
    # (live: career_log_20260724_004649 sent MANT's 180 on a Grand Live finish -> 500 -> can't loop).
    # 3 = Grand Live, confirmed from capture 20260723_070635 (change_nickname{nickname_id: 235}).
    SCENARIO_COMPLETION_NICKNAME = {2: 154, 4: 180, 1: 92, 3: 235}

    def change_nickname(self, trained_chara_id, nickname_id=None):
        """1.32.8 close-out final step: name the just-finished trainee. The live client calls this after
        finish, right before a new start succeeds -- it appears to finalise the career slot.

        nickname_id is SCENARIO-specific (see SCENARIO_COMPLETION_NICKNAME): sending a MANT title (180)
        on a Unity/team career 500s. The 500 is cosmetic -- the slot releases regardless -- but matching
        the scenario avoids the error AND actually names the uma."""
        if nickname_id is None:
            nickname_id = self.SCENARIO_COMPLETION_NICKNAME.get(self.current_scenario_id, 180)
        return self.call('trained_chara/change_nickname', {
            'trained_chara_id': int(trained_chara_id),
            'nickname_id': int(nickname_id),
        })

    def remove_trained_chara(self, trained_chara_ids):
        """RELEASE (permanently delete) finished trainees from the roster. Batch call, verified from a
        live umacap capture: trained_chara/remove{trained_chara_id_array:[...]} -- one call removed ~98
        ids at once and returned reward_summary_info (the release refund) + the updated
        trained_chara_array. viewer_id + device fields ride in via common(), exactly like change_nickname.

        Irreversible (the uma's inheritance sparks are gone), so dispatch ONCE with no 205/208 replay --
        a transparent retry could re-issue a delete that already succeeded (mirrors factor_lottery's
        call_once). Empty/zero-only input is a no-op (returns None) so the caller never fires a blank
        delete."""
        ids = [int(x) for x in (trained_chara_ids or []) if int(x or 0) > 0]
        if not ids:
            return None
        return self.call_once('trained_chara/remove', {'trained_chara_id_array': ids})

    def close_career(self, current_turn, trained_chara_id=None, factor_chooser=None):
        """Full career close-out: load -> factor_select{current_turn} -> finish -> change_nickname. This is
        what RELEASES the career slot; finish alone just 102s and the slot stays 'active' (looping
        then resumes the finished career forever). Returns the state carrying single_mode_finish_common
        (grade + inheritance sparks). Tolerant of an already-finished career (steps 102 harmlessly)."""
        def _tcid(state):
            # The new-uma id lives in trained_chara_info OR single_mode_finish_common depending on
            # which close-out call returned it (1.32.8 returns single_mode_finish_common.trained_chara_id
            # on the bot's own finish -- verified career_log_20260702_131913). Reading only
            # trained_chara_info left _tcid None -> change_nickname (the slot-RELEASE step) skipped ->
            # career finished-but-unreleased -> both load and start 102 forever.
            d = ((state or {}).get('data') or {})
            for c in (d.get('trained_chara_info'), d.get('single_mode_finish_common'), d.get('chara_info')):
                if isinstance(c, dict) and c.get('trained_chara_id'):
                    return int(c['trained_chara_id'])
            return None

        def _pick_lottery(response, opts, default):
            # Injected spark chooser (scores the options by the preset's per-colour priorities and may
            # spend TP to reroll). ANY failure falls back to the default first-option roll -- the
            # finish/slot-release mechanics below are untouched, only WHICH lottery_id is chosen.
            if factor_chooser is not None:
                try:
                    cid = factor_chooser(response)
                    if cid:
                        return int(cid)
                except Exception as e:
                    print(f"spark chooser fell back to default roll: {e}", flush=True)
            if opts and opts[0].get('lottery_id'):
                return int(opts[0]['lottery_id'])
            return default

        loaded_state = None
        try:
            loaded_state = self.load_career()  # loads the finished career; also our trained_chara_id fallback
        except Exception:
            pass
        lottery_id = 1
        confirm_state = None
        # factor_select OPENS the inheritance-factor lottery and returns factor_select_info_array[0].
        # lottery_id, which finish then consumes as factor_lottery_id. This is REQUIRED for team too:
        # authoritative full close-out capture 20260706_101235 (single_mode_team/*, turn 78, every call
        # rc=1) is factor_select{current_turn, skill_id_array:null} -> finish{factor_lottery_id:1} ->
        # change_nickname{nickname_id:154}. The earlier "team skips factor_select" note came from the
        # INCOMPLETE 042752/053931 captures; skipping it is what left the team finish/slot wedged (finish
        # then references a lottery that was never opened).
        # EVERY scenario uses the SINGLE current_turn call: it opens the lottery AND returns the options
        # (factor_select_info_array), and each scenario routes it to its own namespace. MANT used to send
        # an open{} first (a 1.32.8 capture), but on the current client that open answered 102 in 1,650
        # of 1,650 MANT careers and the confirm then 208'd once or twice: 208 only ever follows that 102
        # (URA/Unity/Grand Live: 193/193 first-try successes). It also meant MANT never reached
        # _pick_lottery, so the preset's spark priorities / reroll were silently ignored -- the confirm
        # reply carries the same single_mode_factor_select_common as URA's.
        try:
            confirm_state = self.factor_select(current_turn=current_turn)
            opts = ((((confirm_state or {}).get('data') or {}).get('single_mode_factor_select_common') or {})
                    .get('factor_select_info_array') or [])
            lottery_id = _pick_lottery(confirm_state, opts, lottery_id)
        except Exception as e:
            print(f"factor_select failed: {e}", flush=True)
        # Unity (scenario 2) finish is the slot-RELEASE step and needs target_trained_chara_id, so
        # resolve it BEFORE the finish call (from the factor_select confirm / loaded-career state, or
        # the caller-supplied id). Without it, finish falls back to the 1.32.8 shape and the slot never
        # releases -> the loop's next start 102s.
        pre_tcid = (_tcid(confirm_state) or _tcid(loaded_state)
                    or (int(trained_chara_id) if trained_chara_id else None))
        fin_state = None
        try:
            fin_state = self.finish_career(current_turn=current_turn, is_force_delete=False,
                                           factor_lottery_id=lottery_id,
                                           target_trained_chara_id=pre_tcid)
        except Exception as e:
            if not (is_api_error(e, 102, 201) or isinstance(e, StateRecoveryError)):
                raise
            print(f"finish reconciled (already done): {e}", flush=True)
        # Name the new trainee -- this is the step that RELEASES the slot (finish alone leaves it
        # 'active', so the loop resumes the finished career forever). Required for ALL scenarios,
        # INCLUDING Team/Unity: captures 20260706_042752 + _053931 both call change_nickname
        # {trained_chara_id} right after the team finish. (An earlier note wrongly said team skipped it;
        # that left the Unity slot stuck at 'state 3'.) When finish 102s -- the finals already finished
        # the career, so it returns no id -- fall back to the loaded finished-career state for the id.
        # trained_chara_id lives at data.trained_chara_info.trained_chara_id / single_mode_finish_common
        # (verified in capture 20260706_053931). The caller passes it captured from the finish-decision
        # state BEFORE the skill buy drops it -- the most reliable source, since the team finish 102s and
        # returns nothing, and a plain load doesn't carry trained_chara_info.
        tcid = (_tcid(fin_state) or _tcid(confirm_state) or _tcid(loaded_state)
                or (int(trained_chara_id) if trained_chara_id else None))
        if not tcid:
            # The team finish 102s (career already finished), so no id from its response -- but the
            # finished uma IS saved to the roster (verified: roster count grows each career). The newest
            # (highest) trained_chara_id is the just-finished one. Read it from load/index so
            # change_nickname (the slot-RELEASE step) can still run. This is what unwedges the loop.
            try:
                li = (self.call("load/index", {"adid": ""}) or {}).get("data") or {}
                ids = [int(c.get("trained_chara_id") or 0) for c in (li.get("trained_chara") or [])
                       if isinstance(c, dict) and c.get("trained_chara_id")]
                if ids:
                    tcid = max(ids)
                    print(f"close_career: trained_chara_id {tcid} from roster (newest of {len(ids)} trainees)", flush=True)
            except Exception as e:
                print(f"close_career: roster id lookup failed: {e}", flush=True)
        if tcid:
            try:
                self.change_nickname(tcid)
            except Exception as e:
                print(f"change_nickname failed (non-fatal): {e}", flush=True)
        else:
            # No id anywhere -> the slot-RELEASE (change_nickname) can't run, so the finished career stays
            # wedged. Dump where any trained_chara_id lives in the loaded state so the NEXT run pins the
            # exact source (the bot's own traffic isn't captured by UmaDumpy, so this is our data channel).
            def _tcid_paths(o, p=""):
                out = []
                if isinstance(o, dict):
                    for k, v in o.items():
                        if k == "trained_chara_id" and isinstance(v, int) and v:
                            out.append(p + "." + k + "=" + str(v))
                        out += _tcid_paths(v, p + "." + k)
                elif isinstance(o, list):
                    for i, v in enumerate(o[:30]):
                        out += _tcid_paths(v, p + "[" + str(i) + "]")
                return out
            paths = _tcid_paths((loaded_state or {}).get("data") or {})
            print("close_career: NO trained_chara_id -> change_nickname skipped, slot will NOT release. "
                  "loaded-state paths: " + str(paths[:8] or "NONE"), flush=True)
        # Live client's next step after change_nickname (capture msg 0006): look up the friend
        # whose support card was borrowed this career. Best-effort -- purely mirrors the client.
        if getattr(self, 'last_friend_viewer_id', 0):
            try:
                self.friend_search(self.last_friend_viewer_id)
            except Exception as e:
                print(f"friend_search failed (non-fatal): {e}", flush=True)
        # Prefer whichever response carries the finish payload (grade + sparks). It rides on the
        # factor_select CONFIRM response at res['data']['single_mode_finish_common'] (per live capture).
        for s in (confirm_state, fin_state):
            if s and ((s.get('data') or {}).get('single_mode_finish_common')):
                return s
        return confirm_state or fin_state

    def load_career(self):
        # The active career may be FREE (URA/MANT) or TEAM (Unity, scenario 2). At login/dashboard we
        # don't yet know which, and loading a team career via single_mode_free/load (or vice versa)
        # returns 205. So try the scenario's namespace, and on a namespace mismatch flip to the OTHER
        # ONCE (fast -- retry_205=1 -- because a wrong-namespace 205 is deterministic, not transient).
        # A successful load's chara_info.scenario_id then pins the namespace for every later call.
        # THREE career namespaces exist: MANT=single_mode_free/*, Team/Unity=single_mode_team/*,
        # URA=single_mode/* (plain). Probe the pinned/likely one first, then the OTHERS -- each probe
        # fast (retry_205=1: a wrong-namespace 205 is deterministic, not transient). Missing the plain
        # namespace here is exactly what 205-stormed a dashboard login while a URA career was live
        # (log 20260707: free -> 205s, team -> 205s, hard_reset, never tried single_mode/load).
        # current_scenario_id is set per probe so _route_ep stays consistent; a successful load's
        # chara_info.scenario_id then pins the REAL scenario for every later call.
        # Class-qualified, not self.*: load_career is also invoked UNBOUND with a stand-in `self`
        # (tests/test_unity_scenario.py), which has no class attributes.
        EP = UmaClient.CAREER_LOAD_EP
        try:
            pinned = int(self.current_scenario_id or 0)
        except (TypeError, ValueError):
            pinned = 0
        # FOUR namespaces now -- Grand Live (3) = single_mode_live/*. Leaving 3 out of EP made
        # `pinned in EP` False for a Grand Live session, so the probe fell back to [4, 2, 1] and never
        # tried single_mode_live/load: every probe 205'd and an ALREADY-RUNNING Grand Live career could
        # not be resumed at all.
        ALL = (4, 2, 1, 3)
        order = [pinned] + [s for s in ALL if s != pinned] if pinned in EP else list(ALL)
        original = self.current_scenario_id
        last_err = None
        for sid in order:
            try:
                self.current_scenario_id = sid
                res = self.call(EP[sid], {}, timeout=20, retry_net=2, retry_205=1)
                self._pin_scenario_from(res)
                if sid != order[0]:
                    print(f"load_career: {EP[order[0]]} failed -> loaded via {EP[sid]}", flush=True)
                return res
            except Exception as e:
                self.current_scenario_id = original
                es = str(e)
                # 205 (wrong namespace / stale) or 102/201 (no career here) -> try the next namespace.
                if not any(x in es for x in ("API error 205", "API error 102", "API error 201")):
                    raise
                last_err = e
        # All namespaces failed. Persistent 205 = the session/sid is out of sync (fresh capture, or
        # the game advanced). hard_reset regenerates the sid + re-handshakes, then retry the primary.
        if "API error 205" in str(last_err or ""):
            print(f"load_career: persistent 205 -> hard_reset + retry ({last_err})", flush=True)
            self.hard_reset()
            self.current_scenario_id = order[0] if order[0] in EP else None
            res = self.call(EP.get(order[0], 'single_mode_free/load'), {}, timeout=20, retry_net=2, retry_205=1)
            self._pin_scenario_from(res)
            return res
        raise last_err

    def _pin_scenario_from(self, res):
        # Once a load succeeds, lock the namespace to the career's real scenario so every subsequent
        # call routes correctly (load/index doesn't carry it, so current_scenario_id can be wrong).
        sid = (((res or {}).get('data') or {}).get('chara_info') or {}).get('scenario_id')
        if sid:
            self.current_scenario_id = int(sid)

    def minigame_end(self, current_turn, result_state=1, result_value=0, result_detail_array=None):
        return self.call('single_mode_free/minigame_end', {
            'result': {
                'result_state': result_state,
                'result_value': result_value,
                'result_detail_array': result_detail_array,
            },
            'current_turn': current_turn,
        })
    
    def save_config(self, cfg_path=None):
        global LAST_SAVED_CONFIG
        LAST_SAVED_CONFIG = {
            "viewer_id": self.viewer_id,
            "udid": self.udid_str,
            "auth_key": self.auth_key_hex,
            "steam_id": self.steam_id,
            "steam_session_ticket": self.steam_ticket,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "graphics_device_name": self.graphics_device,
            "ip_address": self.ip_address,
            "platform_os_version": self.platform_os,
        }

    def export_identity(self):
        """Write this just-verified identity to the carried file -- exactly what this client sends,
        minus any Steam ticket/password. None (nothing written, nothing probed) unless
        UMA_AUTH_CONFIG / UMA_CARRY_IDENTITY opt in."""
        path = auth_config_path()
        if not path:
            return None
        return write_auth_config({
            "viewer_id": self.viewer_id, "udid": self.udid_str, "auth_key": self.auth_key_hex,
            "auth_key_len": len(self.auth_key_hex) // 2, "app_ver": self.app_ver, "res_ver": self.res_ver,
            "device_id": self.device_id, "device_name": self.device_name,
            "graphics_device_name": self.graphics_device, "ip_address": self.ip_address,
            "platform_os_version": self.platform_os, "locale": self.locale,
            "screen_h": self.screen_h or windows_screen_h()}, path)

    def pre_single_mode(self, exclude_viewer_ids=None):
        payload = {}
        if exclude_viewer_ids:
            payload['exclude_viewer_id_array'] = exclude_viewer_ids
        return self.call('pre_single_mode/index', payload, timeout=15, retry_net=1)

    def friend_support_card_reload(self, exclude_viewer_ids):
        # Reroll the offered friend-support batch (server returns 10 at a time);
        # exclude_viewer_id_array = friends already offered/seen this session.
        return self.call('pre_single_mode/friend_support_card_reload',
                         {'exclude_viewer_id_array': list(exclude_viewer_ids or [])})

    def change_party(self, support_card_deck_array):
        # The live client calls this right AFTER a successful single_mode_free/start (capture
        # 20260702_005444 msg 0011): it saves the (possibly edited) support-card deck lineups
        # server-side. Payload is the full 10-deck array, same shape pre_single_mode/index returns.
        return self.call('support_card_deck/change_party',
                         {'support_card_deck_array': support_card_deck_array})

    def friend_search(self, friend_viewer_id):
        # The live client calls this right after change_nickname at career end (capture
        # 20260702_005444 msg 0006): looks up the borrowed friend's profile/request history.
        return self.call('friend/search', {'friend_viewer_id': int(friend_viewer_id),
                                           'deleted_response_type': 0})

    def start_career(self, card_id, support_card_ids, friend_viewer_id, friend_card_id,
                     parent_id_1, parent_id_2, scenario_id, deck_id=1, use_tp=30,
                     tp_info=None, current_money=0, succession_rank_point=0,
                     rental_viewer_id=0, rental_trained_chara_id=0,
                     difficulty_id=0, difficulty=0, is_boost=0,
                     boost_story_event_id=0):
        if not tp_info:
            tp_info = {'current_tp': 100, 'max_tp': 100, 'max_recovery_time': 0}
        start_payload = {
            'start_chara': {
                'card_id': card_id,
                'support_card_ids': support_card_ids,
                'friend_support_card_info': {
                    'viewer_id': friend_viewer_id,
                    'support_card_id': friend_card_id
                },
                'succession_trained_chara_id_1': parent_id_1,
                'succession_trained_chara_id_2': parent_id_2,
                'rental_succession_trained_chara': {
                    'viewer_id': rental_viewer_id,
                    'trained_chara_id': rental_trained_chara_id,
                    'is_circle_member': False,
                    'is_event_rental': False
                },
                'scenario_id': scenario_id,
                'selected_difficulty_info': {
                    'difficulty_id': difficulty_id,
                    'difficulty': difficulty,
                    'is_boost': is_boost
                },
                'select_deck_id': deck_id,
                'boost_story_event_id': boost_story_event_id,
                'boost_factor_research_event_id': 0,
                'is_play_training_challenge': False,
                'training_challenge_mode': 0
            },
            'tp_info': tp_info,
            'current_money': current_money,
            'use_tp': use_tp,
            'current_succession_rank_point': succession_rank_point
        }
        # Remembered for close_career's post-nickname friend/search (live-client step, msg 0006).
        self.last_friend_viewer_id = int(friend_viewer_id or 0)
        # Dump the EXACT payload we send so a failing start can be diffed byte-for-byte against a
        # live in-game start capture (the only way to see a field the summary diag misses).
        try:
            import pathlib, json as _json
            pathlib.Path('uma_runtime').mkdir(exist_ok=True)
            pathlib.Path('uma_runtime/last_start_payload.json').write_text(
                _json.dumps(start_payload, ensure_ascii=False, indent=1), encoding='utf-8')
        except Exception:
            pass
        return self._promote_start_common(
            self.call('single_mode_free/start', start_payload, timeout=20, retry_net=2))

    @staticmethod
    def _promote_start_common(res):
        """Flatten the career-start response to the shape the bot reads. A mid-July 2026 game
        update stopped duplicating the career state flat at data.* -- chara_info / home_info /
        unchecked_event_array now live ONLY inside data.single_mode_start_common (older servers
        sent both). Every reader (runner, brain, apply_career_result) expects the flat shape, so
        promote the nested block; without this a fresh start looks like an empty turn-0 state and
        the runner idles out instantly (the zero-second "error / ended@turn0" stub careers)."""
        data = res.get('data') if isinstance(res, dict) else None
        common = data.get('single_mode_start_common') if isinstance(data, dict) else None
        if isinstance(common, dict) and not isinstance(data.get('chara_info'), dict):
            for k, v in common.items():
                data.setdefault(k, v)
        return res

    def exec_command(self, command_type, command_id, current_turn, current_vital, command_group_id=0, select_id=0):
        return self.call('single_mode_free/exec_command', {
            'command_type': command_type,
            'command_id': command_id,
            'command_group_id': command_group_id,
            'select_id': select_id,
            'current_turn': current_turn,
            'current_vital': current_vital
        })

    def check_event(self, event_id, current_turn, chara_id=0, choice_number=0):
        payload = {
            'event_id': event_id,
            'chara_id': chara_id or 0,
            'choice_number': choice_number if choice_number is not None else 0,
            'current_turn': current_turn
        }
        return self.call('single_mode_free/check_event', payload)

    def get_choice_reward(self, event_id, current_turn=None, chara_id=0, choice_number=None):
        # Reward-CLAIM step for choice events. The game fires this (event_id ONLY) IMMEDIATELY BEFORE
        # the event's check_event whenever a real option is picked (choice_number >= 1). Verified
        # against a full URA capture (20260709_142251): every choice>=1 event is preceded by
        # get_choice_reward{event_id}, and choice==0 events never are -- perfect correlation, 0
        # exceptions. Uses the routable single_mode_free prefix so _route_ep sends it to the live
        # scenario's namespace (URA -> single_mode/, Team -> single_mode_team/). current_turn/chara_id/
        # choice_number are kept for caller symmetry but NOT sent -- the live request is event_id alone.
        return self.call('single_mode_free/get_choice_reward', {'event_id': event_id})

    def use_items(self, use_item_info_array, current_turn):
        return self.call('single_mode_free/multi_item_use', {
            'use_item_info_array': use_item_info_array,
            'current_turn': current_turn
        })

    def exchange_items(self, exchange_item_info_array, current_turn):
        return self.call('single_mode_free/multi_item_exchange', {
            'exchange_item_info_array': exchange_item_info_array,
            'current_turn': current_turn
        })

    def gain_skills(self, gain_skill_info_array, current_turn, retry_205=3):
        """retry_205=0 for a MID-RUN buy: a 205 there means "the game won't sell that right now", which
        does not change within the turn, so the 3 replays are 3 extra circuit-breaker errors for
        nothing. The career-END dump keeps the retries -- there a 205 is usually a stale SID that a
        reload does fix (see runner._buy_skills)."""
        gain_skill_info_array = [
            {
                "skill_id": item.get("skill_id"),
                "level": item.get("level", item.get("skill_level", 1)),
            }
            for item in gain_skill_info_array
        ]
        return self.call('single_mode_free/gain_skills', {
            'gain_skill_info_array': gain_skill_info_array,
            'current_turn': current_turn
        }, retry_205=retry_205)

    def race_entry(self, program_id, current_turn, running_style=None, retry_208=6, retry_205=3):
        if running_style is not None:
            payload = {
                'program_id': program_id,
                'running_style': running_style,
                'current_turn': current_turn
            }
            return self.call('single_mode_free/change_running_style', payload, retry_208=retry_208, retry_205=retry_205)
        else:
            payload = {
                'program_id': program_id,
                'current_turn': current_turn
            }
            return self.call('single_mode_free/race_entry', payload, retry_208=retry_208, retry_205=retry_205)

    def race_start(self, is_short, current_turn):
        return self.call('single_mode_free/race_start', {
            'is_short': is_short,
            'current_turn': current_turn
        })

    def race_end(self, current_turn):
        return self.call('single_mode_free/race_end', {
            'current_turn': current_turn
        })

    def race_out(self, current_turn):
        return self.call('single_mode_free/race_out', {
            'current_turn': current_turn
        })

    def race_continue(self, current_turn, continue_type):
        return self.call('single_mode_free/continue', {
            'current_turn': current_turn,
            'continue_type': continue_type
        })

    def reserve_race(self, current_turn, add_race_array=None, cancel_race_array=None):
        return self.call('single_mode_free/reserve_race', {
            'current_turn': current_turn,
            'add_race_array': add_race_array or [],
            'cancel_race_array': cancel_race_array or []
        })
