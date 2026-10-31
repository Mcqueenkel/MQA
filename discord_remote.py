"""MQA Discord remote: operate a running MQA from anywhere through Discord slash commands.

Runs NEXT TO MQA on the same laptop (`python discord_remote.py`, in a second terminal). It connects
OUT to Discord -- no port forwarding -- and turns slash commands into calls to MQA's own local web
API (the same endpoints the web UI uses), so MQA itself needs no changes. Only the Discord users in
`owner_ids` may use it: whoever can run these commands can start careers and spend TP on the account.

One-time setup:
  1. https://discord.com/developers/applications -> New Application -> Bot -> Reset Token -> copy it.
  2. OAuth2 -> URL Generator -> scopes `bot` + `applications.commands`, bot permissions View Channels +
     Send Messages + Embed Links -> open the URL and add the bot to your own server.
  3. Run this file once: it writes uma_runtime/discord_remote.json (gitignored). Fill in
       token      -- the bot token from step 1
       owner_ids  -- your Discord user id (Settings -> Advanced -> Developer Mode, then right-click
                     yourself -> Copy User ID); a list, so a second device/account can be added
       guild_id   -- your server id (right-click the server -> Copy Server ID); commands show up
                     instantly there (without it, global commands can take up to an hour)
       mqa_url    -- only if MQA runs on a non-default port (python main.py 8080)
  4. Start MQA (python main.py) and this file. In Discord: /mqa status, /mqa start, /mqa stop ...

A fresh career reuses the trainee/deck/friend/parents last picked in the MQA web UI (MQA keeps that
selection in memory), so pick them once in the UI after each MQA restart. Resuming an active career
needs nothing.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

import aiohttp
import discord
from discord import app_commands

CONFIG_PATH = Path(__file__).resolve().parent / "uma_runtime" / "discord_remote.json"
TEMPLATE = {"token": "", "owner_ids": [], "guild_id": 0, "mqa_url": "http://127.0.0.1:1616"}
WATCH_EVERY_SEC = 20
SCENARIOS = {1: "URA", 2: "Unity", 3: "Grand Live", 4: "MANT"}
# Off Windows the config this writes (the bot token) is owner-only, not umask-022 world-readable.
if os.name != "nt":
    os.umask(0o077)


class MQAError(Exception):
    pass


def load_config(path=CONFIG_PATH):
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(TEMPLATE, indent=2), encoding="utf-8")
    if os.name != "nt" and path.stat().st_mode & 0o077:
        os.chmod(path, 0o600)   # copied over from Windows (scp / USB) with a loose mode
        print(f"[config] {path} was readable by other users (it holds the bot token): set it to 0600", flush=True)
    cfg = {**TEMPLATE, **json.loads(path.read_text(encoding="utf-8"))}
    missing = [k for k in ("token", "owner_ids") if not cfg.get(k)]
    if missing:
        sys.exit(f"Fill in {' and '.join(missing)} in {path} -- see the setup steps at the top of discord_remote.py.")
    cfg["owner_ids"] = {int(x) for x in cfg["owner_ids"]}
    return cfg


def build_run_body(session, preset, runs, burn_clocks=False, finish=False):
    """The /api/career/run body, mirroring startCareer() in public/app.js."""
    body = {"preset_name": preset, "max_steps": 2500, "burn_clocks": burn_clocks,
            "run_count": runs, "finish_career": finish}
    if (((session.get("account") or {}).get("career")) or {}).get("active"):
        return body   # MQA resumes the live career; the scenario is locked server-side
    sel = session.get("selection") or {}
    trainee, deck, friend = sel.get("trainee"), sel.get("deck"), sel.get("friend")
    vets, guest = sel.get("veterans") or [], sel.get("guestParent")
    if not (trainee and deck and friend and len(vets) >= (1 if guest else 2)):
        raise MQAError("MQA has no full selection yet (trainee, deck, friend, 2 parents). Pick them once "
                       "in the MQA web UI on the laptop; they're reused from then on.")
    return {**body,
            "card_id": int(trainee["id"]),
            "support_card_ids": [int(c["id"]) for c in deck.get("cards") or []],
            "friend_viewer_id": int(friend["viewer_id"]),
            "friend_card_id": int(friend["support_card_id"]),
            "parent_id_1": int(vets[0]["instance_id"]),
            # A borrowed guest parent takes the 2nd slot through the rental fields.
            "parent_id_2": 0 if guest else int(vets[1]["instance_id"]),
            "rental_viewer_id": int(guest["viewer_id"]) if guest else 0,
            "rental_trained_chara_id": int(guest["trained_chara_id"]) if guest else 0,
            "deck_id": int(deck["id"]),
            "use_tp": 30}


def runner_state(runner):
    if runner.get("paused"):
        return "paused"
    if runner.get("running"):
        return "running"
    return "between careers" if runner.get("loop_active") else "idle"


def is_active(runner):
    return bool(runner.get("running") or runner.get("loop_active"))


def status_embed(runner):
    state = runner_state(runner)
    color = {"running": 0x2ECC71, "paused": 0xF1C40F, "between careers": 0x3498DB}.get(state, 0x95A5A6)
    if runner.get("last_error"):
        color = 0xE74C3C
    e = discord.Embed(title=f"MQA - {state}", color=color)
    e.add_field(name="Preset", value=runner.get("preset") or "-")
    e.add_field(name="Scenario", value=SCENARIOS.get(int(runner.get("scenario_id") or 0), "-"))
    e.add_field(name="Turn", value=f"{int(runner.get('turn') or 0)}/78" + (" (finished)" if runner.get("finished") else ""))
    e.add_field(name="Last action", value=str(runner.get("last_action") or "-")[:1024])
    e.add_field(name="Skills / items / clocks",
                value=f"{runner.get('skills_bought', 0)} / {runner.get('items_used', 0)} / {runner.get('clocks_used', 0)}")
    if runner.get("circuit_tripped"):
        e.add_field(name="Auto-backoff", value="Server throttling - MQA stopped itself.", inline=False)
    if runner.get("last_error"):
        e.add_field(name="Error", value=str(runner["last_error"])[:1024], inline=False)
    tail = [f"`T{x.get('turn', 0):>2}` {x.get('action', '')}: {x.get('detail', '')}"[:160]
            for x in (runner.get("log") or [])[-6:]]
    if tail:
        e.add_field(name="Recent", value="\n".join(tail)[:1024], inline=False)
    e.set_footer(text=f"updated {time.strftime('%H:%M:%S')}")
    return e


class MQA:
    """Thin async client for MQA's local web API."""

    def __init__(self, url):
        self.url = url.rstrip("/")
        self.http = None

    async def call(self, method, path, body=None, timeout=30):
        if self.http is None:
            self.http = aiohttp.ClientSession()
        try:
            async with self.http.request(method, self.url + path, json=body,
                                         timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                data = await r.json(content_type=None)
                status = r.status
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            raise MQAError(f"MQA isn't reachable at {self.url} ({type(e).__name__}). "
                           f"Is `python main.py` running on the laptop?")
        if status >= 400 or (isinstance(data, dict) and data.get("success") is False):
            raise MQAError(str((data or {}).get("detail") or f"MQA refused ({path}, HTTP {status})"))
        return data

    async def runner(self):
        return (await self.call("GET", "/api/career/runner")).get("runner") or {}


class Remote(discord.Client):
    def __init__(self, cfg):
        super().__init__(intents=discord.Intents.default())
        self.cfg = cfg
        self.mqa = MQA(cfg["mqa_url"])
        self.tree = app_commands.CommandTree(self)
        self.watch_task = None   # ponytail: one live message at a time; a new /mqa watch replaces it

    async def setup_hook(self):
        self.tree.add_command(MQAGroup())
        if self.cfg.get("guild_id"):
            guild = discord.Object(id=int(self.cfg["guild_id"]))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"[MQA remote] online as {self.user} -> {self.mqa.url}", flush=True)

    async def post_live(self, interaction, runner, text):
        """Answer the command, then post the live status as a plain channel message and keep editing
        it. (An interaction reply can only be edited for 15 minutes; a career takes ~30.)"""
        await interaction.followup.send(text)
        try:
            message = await interaction.channel.send(embed=status_embed(runner))
        except (discord.HTTPException, AttributeError):
            return await interaction.followup.send("Can't post the live status here: give the bot View Channel, "
                                                   "Send Messages and Embed Links in this channel.")
        if self.watch_task and not self.watch_task.done():
            self.watch_task.cancel()
        self.watch_task = asyncio.create_task(self._watch(message))

    async def _watch(self, message):
        """Edit `message` with live status until MQA is idle twice in a row, then ping on an error
        that happened during this watch. Pings once and stops if MQA stops answering."""
        idle, last, misses, saw_active = 0, None, 0, False
        owners = " ".join(f"<@{i}>" for i in self.cfg["owner_ids"])
        while idle < 2:
            await asyncio.sleep(WATCH_EVERY_SEC)
            try:
                runner = await self.mqa.runner()
                misses = 0
            except MQAError as e:
                misses += 1   # one hiccup is fine; ~1 minute of silence means MQA (or its laptop) is down
                if misses < 3:
                    continue
                try:
                    await message.edit(embed=discord.Embed(title="MQA - unreachable", description=str(e), color=0xE74C3C))
                    await message.channel.send(f"{owners} MQA stopped answering. {e}")
                except discord.HTTPException:
                    pass
                return
            saw_active = saw_active or is_active(runner)
            idle = 0 if is_active(runner) else idle + 1
            key = json.dumps({k: v for k, v in runner.items() if k != "log"}, sort_keys=True, default=str) \
                + str(len(runner.get("log") or []))
            if key != last:
                last = key
                try:
                    await message.edit(embed=status_embed(runner))
                except discord.HTTPException:
                    return   # message deleted / no access: stop watching
        if saw_active and runner.get("last_error"):   # not an old error from a run before this watch
            await message.channel.send(f"{owners} MQA stopped with an error: {str(runner['last_error'])[:1500]}")


class MQAGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="mqa", description="Operate MQA on the laptop")

    async def interaction_check(self, interaction):
        if interaction.user.id in interaction.client.cfg["owner_ids"]:
            return True
        await interaction.response.send_message("Not allowed.", ephemeral=True)
        return False

    async def _reply(self, interaction, coro, ok):
        """Defer (MQA calls can outlast Discord's 3s window), run, and report MQAError text."""
        await interaction.response.defer(thinking=True)
        try:
            result = await coro
        except MQAError as e:
            return await interaction.followup.send(f"⚠️ {e}")
        return await ok(result)

    @app_commands.command(description="What MQA is doing right now")
    async def status(self, interaction: discord.Interaction):
        mqa = interaction.client.mqa
        await self._reply(interaction, mqa.runner(),
                          lambda r: interaction.followup.send(embed=status_embed(r)))

    @app_commands.command(description="Post a live status message here that keeps updating")
    async def watch(self, interaction: discord.Interaction):
        client = interaction.client
        await self._reply(interaction, client.mqa.runner(),
                          lambda r: client.post_live(interaction, r, "📡 Live status below (updates every ~20s)."))

    @app_commands.command(description="Start (or resume) careers")
    @app_commands.describe(preset="MQA preset to run", runs="How many careers; 0 = keep going until /mqa stop",
                           burn_clocks="Spend clocks on lost races", finish="Finish the career at the end (UI FINISH toggle)")
    async def start(self, interaction: discord.Interaction, preset: str, runs: app_commands.Range[int, 0, 999] = 1,
                    burn_clocks: bool = False, finish: bool = False):
        client = interaction.client

        async def go():
            try:
                session = await client.mqa.call("GET", "/api/session")
            except MQAError as e:
                if "isn't reachable" in str(e):
                    raise
                raise MQAError("MQA is running but not logged in yet (auth not captured from the game).")
            body = build_run_body(session, preset, runs, burn_clocks, finish)
            await client.mqa.call("POST", "/api/career/run", body, timeout=600)
            return await client.mqa.runner()

        what = "until /mqa stop" if runs == 0 else f"{runs} career(s)"
        await self._reply(interaction, go(),
                          lambda r: client.post_live(interaction, r, f"▶️ Started **{preset}**, {what}."))

    @start.autocomplete("preset")
    async def _preset_names(self, interaction: discord.Interaction, current: str):
        if interaction.user.id not in interaction.client.cfg["owner_ids"]:
            return []
        try:
            presets = (await interaction.client.mqa.call("GET", "/api/presets")).get("presets") or []
        except MQAError:
            return []
        names = [p.get("name", "") for p in presets if current.lower() in p.get("name", "").lower()]
        return [app_commands.Choice(name=n[:100], value=n[:100]) for n in names[:25]]

    @app_commands.command(description="Stop the current career and the run loop")
    async def stop(self, interaction: discord.Interaction):
        mqa = interaction.client.mqa
        await self._reply(interaction, mqa.call("POST", "/api/career/runner/stop"),
                          lambda r: interaction.followup.send("⏹️ Stop sent. MQA finishes its current API call, then stops."))

    @app_commands.command(description="Hold MQA's moves without ending the career")
    async def pause(self, interaction: discord.Interaction):
        mqa = interaction.client.mqa
        await self._reply(interaction, mqa.call("POST", "/api/career/runner/pause"),
                          lambda r: interaction.followup.send("⏸️ Paused. /mqa resume to continue."))

    @app_commands.command(description="Continue after /mqa pause")
    async def resume(self, interaction: discord.Interaction):
        mqa = interaction.client.mqa
        await self._reply(interaction, mqa.call("POST", "/api/career/runner/resume"),
                          lambda r: interaction.followup.send("▶️ Resumed."))

    @app_commands.command(description="Last finished careers")
    async def history(self, interaction: discord.Interaction):
        async def ok(data):
            rows = [f"`{h.get('when', '')[:16]}` **{h.get('uma_name')}** {h.get('rank_letter') or ''} "
                    f"({h.get('rank_score', 0)}) - {h.get('fans', 0):,} fans" for h in (data.get("history") or [])[:10]]
            await interaction.followup.send("\n".join(rows) or "No finished careers yet.")
        await self._reply(interaction, interaction.client.mqa.call("GET", "/api/career/history"), ok)


if __name__ == "__main__":
    cfg = load_config()
    Remote(cfg).run(cfg["token"])
