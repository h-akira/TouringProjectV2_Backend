"""POST /transcriptions and GET /transcriptions/{transcriptionId}: turn a point memo's recording into text, without
the agent (07 UC-6, slice 3 spec §6.2). Accepted and polled like an ask; the worker does the work."""
from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta

from handlers.common import iso, log, response, utc_now
from lib import clients, store
from lib.request import UUID_RE, BadRequest, parse_transcription, user_name

KEEP_SECONDS = 24 * 60 * 60  # the record of a transcription is only needed while the app polls (DynamoDB TTL)
_STATUS = {"pending": "processing", "processing": "processing", "done": "done", "failed": "failed"}


def handler(event, context):
    try:
        user = user_name(event)
        if event.get("httpMethod") == "GET":
            return _get(event, user)
        return _accept(event, user)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})


def _accept(event: dict, user: str) -> dict:
    audio = parse_transcription(event)
    now = utc_now()
    transcription_id = str(uuid.uuid4())
    audio_key = f"audio/{transcription_id}.pcm"
    clients.s3().put_object(Bucket=os.environ["AUDIO_BUCKET"], Key=audio_key, Body=audio, ContentType="application/octet-stream")
    store.create_transcription({
        **store.transcription_key(user, transcription_id),
        "transcriptionId": transcription_id,
        "status": "pending",
        "receivedAt": iso(now),
        "audioKey": audio_key,
        "expiresAt": int((now + timedelta(seconds=KEEP_SECONDS)).timestamp()),
    })
    clients.sqs().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps(
        {"kind": "transcription", "userName": user, "transcriptionId": transcription_id}))
    log({"event": "transcription_accepted", "transcriptionId": transcription_id, "audioBytes": len(audio)})
    return response(202, {"transcriptionId": transcription_id})


def _get(event: dict, user: str) -> dict:
    transcription_id = (event.get("pathParameters") or {}).get("transcriptionId") or ""
    item = store.get_transcription(user, transcription_id, consistent=True) if UUID_RE.match(transcription_id) else None
    if item is None:
        return response(404, {"error": "not_found"})
    return response(200, {"transcriptionId": transcription_id, "status": _STATUS.get(item.get("status"), "processing"),
                          "text": item.get("text"), "failure": item.get("failure")})
