"""End-to-end check of the deployed API. Positions are public landmarks only.
Every ask is sent with the smoke ride, and the ride is deleted at the end, so a run leaves only deletion marks.

Usage: AWS_PROFILE=touring env/bin/python scripts/smoke.py
"""
from __future__ import annotations

import base64
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import boto3

REGION = "ap-northeast-1"
STACK = "stack-trv2-dev-backend"
USER = "smoketest"
TOKYO_STATION = {"latitude": 35.6812, "longitude": 139.7671}
SOUTH_60M = {"latitude": 35.68066, "longitude": 139.7671}
FIXTURE = Path(__file__).resolve().parent.parent / "tests" / "fixtures" / "question_16k.pcm"


def stack_outputs() -> dict:
    stack = boto3.client("cloudformation", region_name=REGION).describe_stacks(StackName=STACK)["Stacks"][0]
    return {o["OutputKey"]: o["OutputValue"] for o in stack["Outputs"]}


def request(method: str, url: str, key: str | None, user: str | None, body: dict | None = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["x-api-key"] = key
    if user:
        headers["x-user-name"] = user
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            return error.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return error.code, {"raw": raw.decode(errors="replace")}


def wait(api: str, key: str, ask_id: str) -> tuple[dict, float]:
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        status, body = request("GET", f"{api}/asks/{ask_id}", key, USER)
        if status == 200 and body["status"] != "processing":
            return body, elapsed
        if elapsed > 120:
            return body, elapsed
        time.sleep(1 if elapsed < 10 else 2)


def check(name: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'OK' if ok else 'NG'}] {name} {detail}")
    return ok


def sample(seconds_ago: int) -> dict:
    at = datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)
    return {**SOUTH_60M, "at": at.strftime("%Y-%m-%dT%H:%M:%SZ")}


def minutes_ago(minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def smoke_ride() -> dict:
    return {"name": "smoke", "status": "paused", "segments": [{"startedAt": minutes_ago(30), "endedAt": minutes_ago(10)}],
            "autoEnded": False, "updatedAt": minutes_ago(10), "memo": "smoke の走行のメモ"}


def ride_checks(api: str, key: str, ride_id: str) -> list[bool]:
    results = []
    ride = smoke_ride()
    status, body = request("PUT", f"{api}/rides/{ride_id}", key, USER, ride)
    results.append(check("ride saved", status == 200 and body == {"rideId": ride_id, "applied": True}, str(status)))
    status, body = request("PUT", f"{api}/rides/{ride_id}", key, USER, {**ride, "name": "older", "updatedAt": minutes_ago(20)})
    results.append(check("older ride ignored", status == 200 and body.get("applied") is False, str(status)))
    status, body = request("PUT", f"{api}/rides/{ride_id}", key, USER, {**ride, "name": " "})
    results.append(check("bad ride is 400", status == 400 and body.get("error") == "bad_request", str(status)))
    points = [{"t": minutes_ago(30 - i), "lat": TOKYO_STATION["latitude"] + i * 0.0005, "lon": TOKYO_STATION["longitude"],
               "accuracy": 5.0, "segment": 0} for i in range(5)]
    status, body = request("PUT", f"{api}/rides/{ride_id}/route/0", key, USER, {"points": points})
    results.append(check("route chunk saved", status == 200 and body == {"rideId": ride_id, "seq": 0}, str(status)))
    status, _ = request("PUT", f"{api}/rides/{ride_id}/route/0", None, USER, {"points": points})
    results.append(check("ride without key is 403", status == 403, str(status)))
    return results


def note_checks(api: str, key: str, ride_id: str, note_id: str) -> list[bool]:
    results = []
    note = {"at": minutes_ago(15), "location": TOKYO_STATION, "headingSample": {**SOUTH_60M, "at": minutes_ago(15)},
            "text": "smoke の地点メモ", "updatedAt": minutes_ago(15)}
    url = f"{api}/rides/{ride_id}/notes/{note_id}"
    status, body = request("PUT", url, key, USER, note)
    results.append(check("note saved with its place", status == 200 and body.get("applied") is True and bool(body.get("address")),
                         f"{status} address={body.get('address')} heading={body.get('headingDegrees')}"))
    status, body = request("PUT", url, key, USER, {**note, "text": "older", "updatedAt": minutes_ago(20)})
    results.append(check("older note ignored", status == 200 and body.get("applied") is False and bool(body.get("address")), str(status)))
    status, body = request("PUT", url, key, USER, {**note, "text": " "})
    results.append(check("bad note is 400", status == 400 and body.get("error") == "bad_request", str(status)))
    return results


def memo_checks(api: str, key: str, ask_id: str) -> list[bool]:
    url = f"{api}/asks/{ask_id}/memo"
    status, body = request("PUT", url, key, USER, {"memo": "smoke の会話のメモ", "updatedAt": minutes_ago(1)})
    results = [check("ask memo saved", status == 200 and body == {"askId": ask_id, "applied": True}, str(status))]
    status, body = request("PUT", url, key, USER, {"memo": "older", "updatedAt": minutes_ago(2)})
    results.append(check("older ask memo ignored", status == 200 and body.get("applied") is False, str(status)))
    status, body = request("PUT", f"{api}/asks/{uuid.uuid4()}/memo", key, USER, {"memo": "x", "updatedAt": minutes_ago(1)})
    results.append(check("memo for an unknown ask is 404", status == 404, str(status)))
    return results


def transcription_check(api: str, key: str, audio_b64: str) -> bool:
    status, accepted = request("POST", f"{api}/transcriptions", key, USER, {"audio": audio_b64})
    if status != 202:
        return check("point memo voice transcribed", False, str(status))
    start = time.monotonic()
    while True:
        elapsed = time.monotonic() - start
        status, body = request("GET", f"{api}/transcriptions/{accepted['transcriptionId']}", key, USER)
        if (status == 200 and body["status"] != "processing") or elapsed > 120:
            break
        time.sleep(1 if elapsed < 10 else 2)
    ok = body.get("status") == "done" and "山" in (body.get("text") or "")
    return check("point memo voice transcribed", ok, f"{elapsed:.1f}s text={body.get('text')} failure={body.get('failure')}")


def delete_checks(api: str, key: str, ride_id: str, note_id: str, ask_id: str) -> list[bool]:
    status, _ = request("DELETE", f"{api}/rides/{ride_id}", key, USER)
    results = [check("ride deleted", status == 204, str(status))]
    later = minutes_ago(-1)
    status, body = request("PUT", f"{api}/rides/{ride_id}", key, USER, {**smoke_ride(), "updatedAt": later})
    results.append(check("deleted ride does not come back", status == 410 and body == {"error": "deleted"}, str(status)))
    note = {"at": minutes_ago(15), "location": TOKYO_STATION, "text": "late", "updatedAt": later}
    status, _ = request("PUT", f"{api}/rides/{ride_id}/notes/{note_id}", key, USER, note)
    results.append(check("deleted note does not come back", status == 410, str(status)))
    status, _ = request("PUT", f"{api}/asks/{ask_id}/memo", key, USER, {"memo": "late", "updatedAt": later})
    results.append(check("memo of a deleted ask is 410", status == 410, str(status)))
    status, _ = request("GET", f"{api}/asks/{ask_id}", key, USER)
    results.append(check("ask of a deleted ride is gone", status == 404, str(status)))
    status, _ = request("DELETE", f"{api}/rides/{ride_id}", key, USER)
    results.append(check("deleting again is 204", status == 204, str(status)))
    return results


def ask_and_wait(api: str, key: str, body: dict) -> tuple[dict, dict, float]:
    status, accepted = request("POST", f"{api}/asks", key, USER, body)
    if status != 202:
        return accepted, {"status": "post_failed", "http": status}, 0.0
    result, elapsed = wait(api, key, accepted["askId"])
    return accepted, result, elapsed


def main() -> int:
    outputs = stack_outputs()
    api = outputs["ApiUrl"]
    key = boto3.client("apigateway", region_name=REGION).get_api_key(apiKey=outputs["ApiKeyId"], includeValue=True)["value"]
    results = []

    status, body = request("GET", f"{api}/health", None, None)
    results.append(check("health without key", status == 200 and body == {"status": "ok"}))
    status, _ = request("POST", f"{api}/asks", None, USER, {"text": "Q"})
    results.append(check("no key is 403", status == 403, str(status)))
    status, body = request("POST", f"{api}/asks", key, "BAD", {"text": "Q"})
    results.append(check("bad user is 400", status == 400 and body.get("error") == "bad_request", str(status)))

    ride_id, note_id = str(uuid.uuid4()), str(uuid.uuid4())
    results.extend(ride_checks(api, key, ride_id))
    results.extend(note_checks(api, key, ride_id, note_id))

    accepted, result, elapsed = ask_and_wait(
        api, key, {"text": "富士山の高さは？", "location": TOKYO_STATION, "headingSample": sample(10), "rideId": ride_id}
    )
    ok = result.get("status") == "completed" and bool(result.get("answer")) and len(result.get("audio", [])) == 1
    results.append(check("text question", ok, f"{elapsed:.1f}s answer={result.get('answer')} error={result.get('error')}"))
    if ok:
        with urllib.request.urlopen(result["audio"][0]["url"], timeout=30) as res:
            audio_ok = res.status == 200 and res.headers.get("Content-Type") == "audio/mpeg" and len(res.read()) > 1000
        results.append(check("answer audio download", audio_ok))
    print("      timings:", json.dumps(result.get("timings"), ensure_ascii=False))
    ok = bool(result.get("askedAt")) and bool(result.get("address")) and result.get("headingDegrees") is not None
    results.append(check("ask has when, where and heading", ok,
                         f"askedAt={result.get('askedAt')} address={result.get('address')} heading={result.get('headingDegrees')}"))
    conversation_id = accepted.get("conversationId")
    expires = accepted.get("conversationExpiresAt")
    results.append(check("conversation expiry returned", bool(expires), str(expires)))

    audio_b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
    accepted2, result2, elapsed2 = ask_and_wait(api, key, {"audio": audio_b64, "location": TOKYO_STATION, "headingSample": sample(10),
                                                           "conversationId": conversation_id, "rideId": ride_id})
    ok = result2.get("status") == "completed" and "山" in (result2.get("transcript") or "")
    results.append(check("audio question", ok, f"{elapsed2:.1f}s transcript={result2.get('transcript')} answer={result2.get('answer')}"))
    print("      timings:", json.dumps(result2.get("timings"), ensure_ascii=False))
    results.append(check("same conversation", accepted2.get("conversationId") == conversation_id))

    _, result3, elapsed3 = ask_and_wait(api, key, {"text": "最初に聞いた山の名前をもう一度言って", "location": TOKYO_STATION,
                                                   "conversationId": conversation_id, "rideId": ride_id})
    results.append(check("follow-up answered", result3.get("status") == "completed", f"{elapsed3:.1f}s answer={result3.get('answer')}"))

    status, body = request("GET", f"{api}/asks/{uuid.uuid4()}", key, USER)
    results.append(check("unknown ask is 404", status == 404 and body == {"error": "not_found"}))
    status, _ = request("GET", f"{api}/asks/{accepted.get('askId')}", key, "someoneelse")
    results.append(check("other user's ask is 404", status == 404))

    results.extend(memo_checks(api, key, accepted.get("askId")))
    results.append(transcription_check(api, key, audio_b64))
    results.extend(delete_checks(api, key, ride_id, note_id, accepted.get("askId")))

    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
