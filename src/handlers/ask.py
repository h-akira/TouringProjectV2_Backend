"""POST /asks: accept a question, store it, and queue it for the worker (07 UC-5)."""
from __future__ import annotations

import json
import os
import uuid
from datetime import timedelta

from handlers.common import iso, log, response, utc_now
from lib import clients, conversation, store
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

    item = {
        **store.ask_key(user, ask_id),
        "askId": ask_id,
        "userName": user,
        "conversationId": conversation_id,
        "conversationStartedAt": started_at,
        "status": "pending",
        "receivedAt": iso(now),
        "inputType": "audio" if ask.audio is not None else "text",
        "question": ask.text,
        "location": ask.location,
        "headingSample": ask.heading_sample,
        "volumeDb": ask.volume_db,
        "timings": {"receivedAt": iso(now)},
    }
    if ask.audio is not None:
        item["audioKey"] = f"audio/{ask_id}.pcm"
        clients.s3().put_object(
            Bucket=os.environ["AUDIO_BUCKET"], Key=item["audioKey"], Body=ask.audio, ContentType="application/octet-stream"
        )
    store.create_ask(item)
    clients.sqs().send_message(QueueUrl=os.environ["QUEUE_URL"], MessageBody=json.dumps({"userName": user, "askId": ask_id}))
    log({"event": "ask_accepted", "askId": ask_id, "inputType": item["inputType"],
         "audioBytes": len(ask.audio) if ask.audio is not None else 0})
    return response(202, {"askId": ask_id, "conversationId": conversation_id, "conversationExpiresAt": iso(expires_at)})
