"""POST /asks: accept a question, store it, and queue it for the worker (07 UC-5)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta

from handlers.common import discard_audio, iso, log, response, utc_now
from lib import asks, clients, conversation, store
from lib.request import BadRequest, parse_ask, user_name


def handler(event, context):
    try:
        user = user_name(event)
        ask = parse_ask(event)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})

    now = utc_now()
    ask_id = str(uuid.uuid4())
    conversation_id = ask.conversation_id or str(uuid.uuid4())
    expires_at = now + timedelta(minutes=conversation.reset_minutes())
    started_at = store.conversation_started_at(user, conversation_id, iso(now))

    item = asks.new_ask(user, ask_id, ask, conversation_id, started_at, now)
    if ask.audio is not None:
        item["audioKey"] = f"audio/{ask_id}.pcm"
        clients.s3().put_object(
            Bucket=os.environ["AUDIO_BUCKET"], Key=item["audioKey"], Body=ask.audio, ContentType="application/octet-stream"
        )
    store.create_ask(item)
    try:
        clients.sqs().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"userName": user, "askId": ask_id}))
    except Exception as error:  # noqa: BLE001 - reported to the app as 503, which it retries
        # No worker would ever take the ask, so it is not left pending; the app keeps an unreached ask instead (Backend #3).
        log({"event": "ask_queue_failed", "askId": ask_id, "error": type(error).__name__})
        store.discard_ask(user, ask_id)
        if ask.audio is not None:
            discard_audio(item["audioKey"])
        return response(503, {"error": "unavailable"})
    log({"event": "ask_accepted", "askId": ask_id, "inputType": item["inputType"],
         "audioBytes": len(ask.audio) if ask.audio is not None else 0})
    return response(202, {"askId": ask_id, "conversationId": conversation_id, "conversationExpiresAt": iso(expires_at)})
