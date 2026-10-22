"""GET /records: a user's records, one page at a time, for taking over on another device (slice 4 spec §6.2,
adr/0010)."""
from __future__ import annotations

from typing import Optional

from handlers.common import log, response
from lib import records, store
from lib.request import BadRequest, user_name

# One DynamoDB query (at most 1 MB) per page; tests set a small limit to read many pages.
PAGE_LIMIT: Optional[int] = None


def handler(event, context):
    try:
        user = user_name(event)
        after = records.decode_cursor((event.get("queryStringParameters") or {}).get("cursor"))
    except BadRequest as error:
        return response(400, {"error": "bad_request", "message": str(error)})
    items, last = store.query_records(user, after, PAGE_LIMIT)
    views = [view for view in map(records.view, items) if view is not None]
    log({"event": "records_read", "items": len(views), "more": last is not None})
    return response(200, {"items": views, "cursor": records.encode_cursor(last) if last is not None else None})
