"""Discord remote: the run body must match what the web UI sends (public/app.js startCareer), a
missing UI selection must refuse instead of starting a half-filled career, and an MQA that isn't
running must surface as a readable MQAError. No Discord connection is made."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from discord_remote import MQA, MQAError, MQAGroup, build_run_body, is_active, status_embed

SELECTION = {
    "trainee": {"id": 103802},
    "deck": {"id": 3, "cards": [{"id": 30001}, {"id": 30002}, {"id": 30003}]},
    "friend": {"viewer_id": 111, "support_card_id": 30099},
    "veterans": [{"instance_id": 7}, {"instance_id": 8}],
}


def test_fresh_start_uses_the_ui_selection():
    body = build_run_body({"selection": SELECTION}, "fan", 3, finish=True)
    assert body["card_id"] == 103802 and body["deck_id"] == 3
    assert body["support_card_ids"] == [30001, 30002, 30003]
    assert (body["friend_viewer_id"], body["friend_card_id"]) == (111, 30099)
    assert (body["parent_id_1"], body["parent_id_2"]) == (7, 8)
    assert body["run_count"] == 3 and body["preset_name"] == "fan" and body["finish_career"] is True


def test_active_career_resumes_without_selection():
    body = build_run_body({"account": {"career": {"active": True}}, "selection": {}}, "fan", 0)
    assert "card_id" not in body and body["run_count"] == 0


def test_missing_selection_refuses():
    try:
        build_run_body({"selection": {"trainee": {"id": 1}, "veterans": []}}, "fan", 1)
    except MQAError as e:
        assert "selection" in str(e)
    else:
        raise AssertionError("a half-filled selection must not start a career")


def test_unreachable_mqa_is_a_readable_error():
    async def go():
        mqa = MQA("http://127.0.0.1:9")   # discard port: nothing listens
        try:
            await mqa.runner()
        finally:
            await mqa.http.close()
    try:
        asyncio.run(go())
    except MQAError as e:
        assert "isn't reachable" in str(e)
    else:
        raise AssertionError("expected MQAError")


def test_status_and_commands():
    runner = {"running": True, "preset": "fan", "scenario_id": 4, "turn": 40, "last_error": "boom",
              "log": [{"turn": 40, "action": "train", "detail": "speed"}]}
    e = status_embed(runner)
    assert "running" in e.title and any(f.name == "Error" for f in e.fields)
    assert is_active({"loop_active": True}) and not is_active({})
    names = {c.name for c in MQAGroup().commands}
    assert names == {"status", "watch", "start", "stop", "pause", "resume", "history"}


def test_guest_parent_team_uses_the_rental_fields():
    sel = dict(SELECTION, veterans=[{"instance_id": 7}], guestParent={"viewer_id": 555, "trained_chara_id": 42})
    body = build_run_body({"selection": sel}, "fan", 1)
    assert (body["parent_id_1"], body["parent_id_2"]) == (7, 0)
    assert (body["rental_viewer_id"], body["rental_trained_chara_id"]) == (555, 42)


def test_watch_skips_old_errors_and_pings_when_mqa_goes_down():
    import types
    import discord_remote

    class Msg:
        def __init__(self):
            self.sent, self.channel = [], self

        async def edit(self, **_kw):
            pass

        async def send(self, text):
            self.sent.append(text)

    class FakeMQA:
        def __init__(self, seq):
            self.seq = list(seq)

        async def runner(self):
            x = self.seq.pop(0)
            if isinstance(x, Exception):
                raise x
            return x

    saved, discord_remote.WATCH_EVERY_SEC = discord_remote.WATCH_EVERY_SEC, 0
    try:
        old = {"running": False, "last_error": "from yesterday's run"}
        me = types.SimpleNamespace(cfg={"owner_ids": {1}}, mqa=FakeMQA([old, old]))
        msg = Msg()
        asyncio.run(discord_remote.Remote._watch(me, msg))
        assert msg.sent == [], "pinged for an error from before this watch"

        me.mqa = FakeMQA([{"running": True}, MQAError("down"), MQAError("down"), MQAError("down")])
        msg = Msg()
        asyncio.run(discord_remote.Remote._watch(me, msg))
        assert len(msg.sent) == 1 and "stopped answering" in msg.sent[0], msg.sent
    finally:
        discord_remote.WATCH_EVERY_SEC = saved


if __name__ == "__main__":
    test_fresh_start_uses_the_ui_selection()
    test_active_career_resumes_without_selection()
    test_missing_selection_refuses()
    test_unreachable_mqa_is_a_readable_error()
    test_status_and_commands()
    test_guest_parent_team_uses_the_rental_fields()
    test_watch_skips_old_errors_and_pings_when_mqa_goes_down()
    print("test_discord_remote: OK")
