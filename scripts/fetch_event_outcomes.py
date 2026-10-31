"""Build data/support_event_outcomes.json: per-choice OUTCOMES for every support-card event.

Source: GameTora's training-event data (the de-facto community DB; master.mdb has NO outcomes --
they live in story-timeline assets). GameTora keys events by support_card_id AND carries the same
story_id the live game API sends, so the join to data/support_events.json is exact, no name fuzz.

Pipeline (repeatable -- run again after a banner adds new cards):
  manifest (/data/manifests/umamusume.json)  -> content-hash per data file
  training_events/{ssr,sr,friend,group}      -> [[card_id, [event...]], ...] where
        event = [title_loc_id, [[choice_loc_id, [effect_id...]], ...], story_id, variants?]
  dict/evrew                                  -> effect_id -> [type, value, ref?]  (index-addressed)

Output (data/support_event_outcomes.json):
  { "<story_id>": {"support_card_id": N, "title": str,
                   "choices": [{"n": 1, "effects": [[type, value, ref?]...], "summary": str}]} }
Choice order is GameTora's top->bottom, which matches the API's choice_number 1..N.

Run: python scripts/fetch_event_outcomes.py
"""
import json
import os
import subprocess
import sys
import tempfile

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GT = "https://gametora.com"
# ssr/sr/friend/group are keyed by support_card_id; shared (cross-card events, keyed by chara_id)
# and scenario (keyed by scenario id) use the same [owner_id, [events]] shape and carry the story_ids
# our catalog needs for events like "Taking a Break" / summer-camp shared events.
FILES = ["training_events/ssr", "training_events/sr", "training_events/friend", "training_events/group",
         "training_events/shared", "training_events/scenario"]

# effect type -> readable label (the scoring-relevant core; unknown codes pass through raw)
LABEL = {"sp": "Speed", "st": "Stamina", "po": "Power", "gu": "Guts", "in": "Wit", "5s": "All stats",
         "en": "Energy", "mo": "Mood", "pt": "Skill points", "bo": "Bond", "sk": "Skill hint",
         "he": "Heal", "se": "Status", "fa": "Fans", "me": "Medic", "ct": "Chain", "sc": "Coins",
         "brp": "Random branch", "brf": "Random branch", "rs": "Random stats"}


def fetch(url, dest):
    subprocess.run(["curl", "-sL", url, "-o", dest], check=True)
    with open(dest, encoding="utf-8") as f:
        return json.load(f)


def summarize(effects):
    parts = []
    for e in effects:
        if not isinstance(e, list) or not e:
            continue
        t, val = e[0], (e[1] if len(e) > 1 else "")
        ref = e[2] if len(e) > 2 else None
        label = LABEL.get(t, str(t))
        parts.append(f"{label} {val} [{ref}]" if ref is not None else f"{label} {val}".strip())
    return ", ".join(parts)


def main():
    tmp = tempfile.mkdtemp(prefix="gt_events_")
    man = fetch(f"{GT}/data/manifests/umamusume.json", os.path.join(tmp, "manifest.json"))
    evrew = fetch(f"{GT}/data/umamusume/dict/evrew.{man['dict/evrew']}.json",
                  os.path.join(tmp, "evrew.json"))

    def decode(effect_ids):
        out = []
        for i in effect_ids:
            if isinstance(i, int) and 0 <= i < len(evrew) and isinstance(evrew[i], list):
                out.append(evrew[i])
            else:
                out.append(["raw", i])   # nested/unknown shapes preserved, never dropped
        return out

    outcomes = {}
    for key in FILES:
        data = fetch(f"{GT}/data/umamusume/{key}.{man[key]}.json",
                     os.path.join(tmp, key.replace("/", "_") + ".json"))
        for card in data:
            if not (isinstance(card, list) and len(card) >= 2):
                continue
            card_id = card[0]
            # a card entry can hold SEVERAL event-list sections (group cards split theirs into
            # intro / outing / per-chara blocks) -- walk every list section, not just card[1]
            for section in card[1:]:
                if not isinstance(section, list):
                    continue
                for ev in section:
                    # event = [title_loc_id, [choices], story_id, optional variant/condition tail]
                    if not (isinstance(ev, list) and len(ev) >= 3 and isinstance(ev[2], int)):
                        continue
                    story_id = str(ev[2])
                    choices = []
                    for n, ch in enumerate(ev[1] or [], start=1):
                        ids = ch[1] if isinstance(ch, list) and len(ch) > 1 else []
                        effects = decode(ids if isinstance(ids, list) else [])
                        choices.append({"n": n, "effects": effects, "summary": summarize(effects)})
                    outcomes[story_id] = {"support_card_id": card_id, "choices": choices}

    # attach our master.mdb titles (data/support_events.json) so entries are human-checkable
    try:
        with open(os.path.join(BASE, "data", "support_events.json"), encoding="utf-8") as f:
            ours = json.load(f)
        titles = {ev["story_id"]: ev["title"] for entry in ours.values() for ev in entry["events"]}
        for sid, o in outcomes.items():
            if sid in titles:
                o["title"] = titles[sid]
        covered = sum(1 for sid in titles if sid in outcomes)
        print(f"coverage: {covered}/{len(titles)} of master.mdb support-card events have outcomes")
    except FileNotFoundError:
        print("note: data/support_events.json missing (run the bot once to generate it)")

    dest = os.path.join(BASE, "data", "support_event_outcomes.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(outcomes, f, ensure_ascii=False, indent=1)
    print(f"wrote {dest} -- {len(outcomes)} events, "
          f"{sum(len(o['choices']) for o in outcomes.values())} choices")


if __name__ == "__main__":
    main()
