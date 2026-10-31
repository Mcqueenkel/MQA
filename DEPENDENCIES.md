# Dependencies & Setup

Everything required to run this bot. It is **not** a standalone app — it reads the
real game's data and captures auth from the running game, so the game itself must
be installed.

## System requirements
- **Windows** — the bot uses [Frida](https://frida.re) to attach to the game/Steam process.
- **Umamusume: Pretty Derby** installed via **Steam**. The bot reads the game's
  `master.mdb` and captures your login auth from the running game.
- A **Steam account** that owns the game, plus your own **Uma Musume account**
  (auth is captured per-user; nobody else's auth is shipped with this repo).
- **Linux (optional):** a headless host can run MQA from an identity exported on the
  Windows PC; no game or Frida there. Setup and rules: [LINUX.md](LINUX.md).

## 1. Node.js (do this first)
- Install Node: `winget install -e --id OpenJS.NodeJS`
- Install packages:
  ```bash
  npm install
  ```

| Package | Version | Purpose |
|---|---|---|
| `steam-user` | ^5.0.0 | Fetches a fresh Steam session ticket for login |

## 2. Python
- **Python 3.10 to 3.14** (developed on **3.10.11**; the tests pass on 3.10-3.14)
- Install packages:
  ```bash
  pip install -r requirements.txt
  ```

| Package | Version | Purpose |
|---|---|---|
| `fastapi` | 0.136.1 | Web UI / API server |
| `uvicorn` | 0.18.2 | ASGI server that runs FastAPI |
| `frida` | 17.9.1 | Captures in-game auth (viewer_id / auth_key / app_ver / res_ver). Windows only |
| `curl_cffi` | 0.7.4 | Game API requests with a real-client TLS fingerprint |
| `msgpack` | 1.1.2 | Encode/decode the game API's msgpack payloads (first release with Python 3.14 wheels) |
| `pycryptodome` | 3.14.1 | Request encryption (imported in code as `Crypto`) |
| `pydantic` | 2.13.4 | Request body models |
| `python-multipart` | >=0.0.13 | AI brain upload/export form parsing (imported as `python_multipart`; the old `multipart` name is deprecated) |
| `keyring` | >=24 | Stores the saved Steam login in the OS credential vault |
| `discord.py` | >=2.3 | Optional Discord remote (`discord_remote.py`) |
| `audioop-lts` | Python 3.13+ only | Puts back the `audioop` module discord.py imports (removed from the stdlib in 3.13) |

> Standard-library modules used (no install needed): `gzip`, `uuid`, `json`,
> `threading`, `asyncio`, `pathlib`, `sqlite3`, etc.

Tests only (not needed to run MQA): `pip install -r requirements-dev.txt` installs
`pytest` and `httpx` (FastAPI's TestClient needs it).

## 3. Run
```bash
python main.py
```
- Default port: **1616** → open **http://127.0.0.1:1616**
- Every launch opens the game via Steam and **captures fresh auth** when you reach the
  in-game home menu (Frida). Startup auth is kept in memory for that process. (Exception:
  `UMA_CARRY_IDENTITY=1`, the optional Linux mode, starts from an exported identity file; see
  [LINUX.md](LINUX.md).)
- Keep the game **updated** — a "resource version" mismatch causes **API error 214**;
  update the game fully, then re-capture auth.

## Notes
- Credentials, webhooks and logs live under `uma_runtime/` which is **gitignored** —
  they are never committed/pushed.
- Run `python main.py <port>` to use a different port (multi-account = one process per port).
