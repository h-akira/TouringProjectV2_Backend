"""The facts block the Backend puts in front of the rider's question (07 UC-8)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from lib.geo import compass

JST = timezone(timedelta(hours=9), "JST")
_WEEKDAYS = "月火水木金土日"


def format_now(now: datetime) -> str:
    local = now.astimezone(JST)
    return f"現在日時: {local.year}年{local.month}月{local.day}日（{_WEEKDAYS[local.weekday()]}）{local.hour}時{local.minute:02d}分（日本時間）"


def _elapsed(seconds: Optional[float]) -> Optional[str]:
    if seconds is None or seconds < 60:
        return None
    return f"この質問は、会話の最初の質問から約{int(seconds // 60)}分後のものです"


def build_prompt(
    question: str,
    now: datetime,
    location: Optional[dict],
    address: Optional[str],
    heading: Optional[float],
    elapsed_seconds: Optional[float],
) -> str:
    lines = [format_now(now)]
    elapsed = _elapsed(elapsed_seconds)
    if elapsed:
        lines.append(elapsed)
    if location is None:
        lines.append("現在地: 不明（位置が取れなかった）")
    else:
        lines.append(f"現在地: 緯度 {location['latitude']:.5f}, 経度 {location['longitude']:.5f}")
        if address:
            lines.append(f"現在地の住所: {address}（確定した事実。座標から推測し直さないこと）")
        else:
            lines.append("現在地の住所: 不明")
    if heading is None:
        lines.append("進行方向: 不明（方角や左右には触れないこと）")
    else:
        lines.append(f"進行方向: {compass(heading)}（真北から{round(heading)}度）")
        lines.append(f"ライダーから見て右手は{compass(heading + 90)}、左手は{compass(heading - 90)}の方角")
    return "\n".join(lines) + f"\n\n質問: {question}"


def agent_location(location: Optional[dict], heading: Optional[float]) -> Optional[dict]:
    """Position and heading as numbers for the agent's place tools (07 UC-8)."""
    if location is None:
        return None
    return {
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "headingDegrees": round(heading, 1) if heading is not None else None,
    }
