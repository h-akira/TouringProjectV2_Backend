"""Tests for the facts block that precedes the rider's question."""
from datetime import datetime, timezone

from lib import prompt

NOW = datetime(2026, 10, 16, 3, 5, tzinfo=timezone.utc)  # 12:05 JST, Friday
HERE = {"latitude": 35.6812, "longitude": 139.7671}


def test_format_now_is_japan_time():
    assert prompt.format_now(NOW) == "現在日時: 2026年10月16日（金）12時05分（日本時間）"


def test_full_prompt():
    text = prompt.build_prompt("右手の建物は？", NOW, HERE, "東京都千代田区丸の内", 0.0, 600)
    assert text.splitlines() == [
        "現在日時: 2026年10月16日（金）12時05分（日本時間）",
        "この質問は、会話の最初の質問から約10分後のものです",
        "現在地: 緯度 35.68120, 経度 139.76710",
        "現在地の住所: 東京都千代田区丸の内（確定した事実。座標から推測し直さないこと）",
        "進行方向: 北（真北から0度）",
        "ライダーから見て右手は東、左手は西の方角",
        "",
        "質問: 右手の建物は？",
    ]


def test_a_heading_just_short_of_north_is_written_as_0_degrees():
    # round() alone would write 360 for 359.5 and above (Backend #29).
    text = prompt.build_prompt("Q", NOW, HERE, None, 359.6, None)
    assert "進行方向: 北（真北から0度）" in text


def test_unknowns_are_stated_not_guessed():
    text = prompt.build_prompt("Q", NOW, HERE, None, None, 30)
    assert "現在地の住所: 不明" in text
    assert "進行方向: 不明（方角や左右には触れないこと）" in text
    assert "会話の最初の質問から" not in text


def test_no_location():
    text = prompt.build_prompt("Q", NOW, None, None, None, None)
    assert "現在地: 不明（位置が取れなかった）" in text
    assert "住所" not in text


def test_agent_location():
    assert prompt.agent_location(HERE, 12.345) == {"latitude": 35.6812, "longitude": 139.7671, "headingDegrees": 12.3}
    assert prompt.agent_location(HERE, None) == {"latitude": 35.6812, "longitude": 139.7671, "headingDegrees": None}
    assert prompt.agent_location(None, 1.0) is None
