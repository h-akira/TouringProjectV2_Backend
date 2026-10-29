"""GET /asks/{askId}: the App polls this for the answer (07 UC-5)."""
from __future__ import annotations

import os

from handlers.common import response
from lib import asks, clients, store
from lib.request import UUID_RE, BadRequest, user_name

PRESIGN_SECONDS = 600


def handler(event, context):
    try:
        user = user_name(event)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})
    ask_id = (event.get("pathParameters") or {}).get("askId") or ""
    item = store.get_ask(user, ask_id) if UUID_RE.match(ask_id) else None
    if item is None:
        return response(404, {"error": "not_found"})

    audio = []
    if item.get("answerAudioKey"):
        url = clients.s3().generate_presigned_url(
            "get_object",
            Params={"Bucket": os.environ["AUDIO_BUCKET"], "Key": item["answerAudioKey"]},
            ExpiresIn=PRESIGN_SECONDS,
        )
        audio = [{"seq": 1, "url": url}]
    return response(200, asks.poll_view(item, ask_id, audio))
