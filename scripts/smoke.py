"""End-to-end check of the deployed API. Positions are public landmarks only.

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

    accepted, result, elapsed = ask_and_wait(api, key, {"text": "富士山の高さは？", "location": TOKYO_STATION, "headingSample": sample(10)})
    ok = result.get("status") == "completed" and bool(result.get("answer")) and len(result.get("audio", [])) == 1
    results.append(check("text question", ok, f"{elapsed:.1f}s answer={result.get('answer')} error={result.get('error')}"))
    if ok:
        with urllib.request.urlopen(result["audio"][0]["url"], timeout=30) as res:
            audio_ok = res.status == 200 and res.headers.get("Content-Type") == "audio/mpeg" and len(res.read()) > 1000
        results.append(check("answer audio download", audio_ok))
    print("      timings:", json.dumps(result.get("timings"), ensure_ascii=False))
    conversation_id = accepted.get("conversationId")
    expires = accepted.get("conversationExpiresAt")
    results.append(check("conversation expiry returned", bool(expires), str(expires)))

    audio_b64 = base64.b64encode(FIXTURE.read_bytes()).decode()
    accepted2, result2, elapsed2 = ask_and_wait(api, key, {"audio": audio_b64, "location": TOKYO_STATION, "headingSample": sample(10), "conversationId": conversation_id})
    ok = result2.get("status") == "completed" and "山" in (result2.get("transcript") or "")
    results.append(check("audio question", ok, f"{elapsed2:.1f}s transcript={result2.get('transcript')} answer={result2.get('answer')}"))
    print("      timings:", json.dumps(result2.get("timings"), ensure_ascii=False))
    results.append(check("same conversation", accepted2.get("conversationId") == conversation_id))

    _, result3, elapsed3 = ask_and_wait(api, key, {"text": "最初に聞いた山の名前をもう一度言って", "location": TOKYO_STATION, "conversationId": conversation_id})
    results.append(check("follow-up answered", result3.get("status") == "completed", f"{elapsed3:.1f}s answer={result3.get('answer')}"))

    status, body = request("GET", f"{api}/asks/{uuid.uuid4()}", key, USER)
    results.append(check("unknown ask is 404", status == 404 and body == {"error": "not_found"}))
    status, _ = request("GET", f"{api}/asks/{accepted.get('askId')}", key, "someoneelse")
    results.append(check("other user's ask is 404", status == 404))

    print(f"{sum(results)}/{len(results)} passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
