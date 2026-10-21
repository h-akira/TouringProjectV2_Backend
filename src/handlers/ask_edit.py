"""PUT /asks/{askId}/memo and DELETE /asks/{askId}: the app's changes to an ask it keeps (slice 3 spec §6.2)."""
from __future__ import annotations

from handlers.common import deleted, iso, log, no_content, response, utc_now
from lib import rides, store
from lib.request import UUID_RE, BadRequest, user_name


def handler(event, context):
    try:
        user = user_name(event)
        ask_id = _ask_id(event)
        if event.get("httpMethod") == "DELETE":
            store.delete_ask(user, ask_id, iso(utc_now()))
            log({"event": "ask_deleted", "askId": ask_id})
            return no_content()
        return _memo(event, user, ask_id)
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})
    except store.Deleted:
        return deleted()


def _ask_id(event: dict) -> str:
    value = (event.get("pathParameters") or {}).get("askId") or ""
    if not UUID_RE.match(value):
        raise BadRequest("askId must be a lowercase UUID")
    return value


def _memo(event: dict, user: str, ask_id: str) -> dict:
    memo, updated_at = rides.parse_ask_memo(event)
    applied = store.put_ask_memo(user, ask_id, memo, updated_at)
    if not applied and store.get_ask(user, ask_id) is None:
        return response(404, {"error": "not_found"})
    log({"event": "ask_memo_saved", "askId": ask_id, "applied": applied, "hasMemo": memo is not None})
    return response(200, {"askId": ask_id, "applied": applied})
