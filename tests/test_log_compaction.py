"""Career-log compaction: drop the device/auth envelope + the giant response blob, keep what's worth
analysing (functional request fields, result_code, a tiny chara summary), preserve turn assignment."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from career_bot.core.report import compact_api_data, add_api_call, new_report


def test_compaction():
    # REQUEST: envelope stripped, functional fields kept, long array -> length, short array kept
    req = {"payload": {"event_id": 102001, "choice_number": 5, "current_turn": 34,
                       "use_item_info_array": [1, 2, 3, 4, 5, 6, 7, 8],
                       "skill_id_array": [101, 102],
                       "viewer_id": 123, "steam_session_ticket": "SECRET" * 50, "device_id": "abc"}}
    c = compact_api_data("REQ", req)
    assert c == {"event_id": 102001, "choice_number": 5, "current_turn": 34,
                 "use_item_info_array": 8, "skill_id_array": [101, 102]}, c
    assert "steam_session_ticket" not in c and "viewer_id" not in c

    # RESPONSE: result_code + chara summary; the multi-KB blob is dropped
    resp = {"response_code": 1, "data_headers": {"result_code": 1, "sid": "x"},
            "data": {"chara_info": {"turn": 34, "vital": 80, "speed": 500, "fans": 9000, "junk": [0] * 1000},
                     "home_info": {"huge": "x" * 5000}}}
    c = compact_api_data("RES", resp)
    assert c["result_code"] == 1
    assert c["chara"] == {"turn": 34, "vital": 80, "speed": 500, "fans": 9000}, c
    assert "data" not in c and "home_info" not in str(c)

    # add_api_call assigns the turn from the RAW payload, THEN trims
    rep = new_report()
    add_api_call(rep, {"direction": "REQ", "endpoint": "single_mode/check_event",
                       "data": {"payload": {"event_id": 5, "current_turn": 40, "viewer_id": 9}}, "turn": 40})
    t = rep["turns"][0]
    assert t["turn"] == 40, t
    assert t["api_calls"][0]["data"] == {"event_id": 5, "current_turn": 40}
    print("log compaction OK (envelope + response blob dropped, functional fields + turn preserved)")


if __name__ == "__main__":
    test_compaction()
