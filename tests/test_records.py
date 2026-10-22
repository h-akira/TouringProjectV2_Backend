"""Tests for GET /records: a user's records read back page by page (moto)."""
import base64
import json

import pytest

from handlers import records
from lib import store

USER = "rider01"
RIDE = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"
NOTE = "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a"
ASK = "11111111-1111-4111-8111-111111111111"
OFFLINE = "22222222-2222-4222-8222-222222222222"
GONE = "33333333-3333-4333-8333-333333333333"
CID = "44444444-4444-4444-8444-444444444444"
HERE = {"latitude": 35.6812, "longitude": 139.7671}
T0, T1, T2 = "2026-10-22T00:00:00.000Z", "2026-10-22T01:00:00.000Z", "2026-10-22T01:00:05.000Z"


def read(cursor=None, user=USER):
    event = {"httpMethod": "GET", "headers": {"x-user-name": user},
             "queryStringParameters": None if cursor is None else {"cursor": cursor}}
    return records.handler(event, None)


def page(cursor=None, user=USER):
    result = read(cursor, user)
    assert result["statusCode"] == 200
    return json.loads(result["body"])


def read_all(user=USER):
    items, cursor = [], None
    while True:
        body = page(cursor, user)
        items += body["items"]
        cursor = body["cursor"]
        if cursor is None:
            return items


def put(item):
    store.create_ask(item)  # a plain put of any record


def everything(user=USER):
    pk = f"USER#{user}"
    put({"pk": pk, "sk": f"RIDE#{RIDE}", "rideId": RIDE, "name": "箱根", "status": "ended",
         "segments": [{"startedAt": T0, "endedAt": T1}], "autoEnded": False, "updatedAt": T1, "memo": "また行く",
         "savedAt": T1})
    for seq in (0, 1):
        put({"pk": pk, "sk": f"RIDE#{RIDE}#ROUTE#{seq:05d}", "rideId": RIDE, "seq": seq, "savedAt": T1,
             "points": [{"t": T0, "lat": 35.0 + seq, "lon": 139.0, "accuracy": 5.0, "segment": 0}]})
    put({"pk": pk, "sk": f"RIDE#{RIDE}#NOTE#{NOTE}", "noteId": NOTE, "rideId": RIDE, "at": T0, "location": HERE,
         "text": "ここ", "updatedAt": T0, "address": "東京都千代田区丸の内", "headingDegrees": 0.0, "savedAt": T0})
    put({"pk": pk, "sk": f"ASK#{ASK}", "askId": ASK, "userName": user, "conversationId": CID,
         "conversationStartedAt": T1, "status": "completed", "receivedAt": T1, "inputType": "audio",
         "location": HERE, "headingSample": {**HERE, "at": T0}, "volumeDb": 6, "rideId": RIDE, "transcript": "右手の山は？",
         "answer": "愛鷹山です。", "address": "静岡県沼津市", "headingDegrees": 90.0, "answerAudioKey": f"answers/{ASK}.mp3",
         "usage": {"inputTokens": 5}, "timings": {"receivedAt": T1, "agentDoneAt": T2, "synthesizedAt": T2},
         "memo": "晴れていた", "memoUpdatedAt": T2})
    put({"pk": pk, "sk": f"ASK#{OFFLINE}", "askId": OFFLINE, "userName": user, "status": "offline", "receivedAt": T0,
         "location": HERE, "rideId": RIDE, "updatedAt": T0, "address": "東京都千代田区丸の内", "headingDegrees": None,
         "savedAt": T0})
    store.mark_deleted(user, "ask", GONE, T2, ride_id=RIDE)
    put({"pk": pk, "sk": f"CONV#{CID}", "startedAt": T1, "expiresAt": 1})
    put({"pk": pk, "sk": f"TRANSCRIPTION#{GONE}", "status": "done", "text": "声", "expiresAt": 1})


def test_a_user_without_records_reads_one_empty_page(aws):
    assert page() == {"items": [], "cursor": None}


def test_every_kind_of_record_reads_back_in_the_shape_it_was_sent(aws):
    everything()
    assert read_all() == [
        {"kind": "ask", "askId": ASK, "status": "completed", "askedAt": T1, "question": None, "transcript": "右手の山は？",
         "answer": "愛鷹山です。", "error": None, "answeredAt": T2, "location": HERE, "address": "静岡県沼津市",
         "headingDegrees": 90.0, "inputType": "audio", "conversationId": CID, "newConversation": True, "rideId": RIDE,
         "memo": "晴れていた", "memoUpdatedAt": T2, "updatedAt": None},
        {"kind": "ask", "askId": OFFLINE, "status": "offline", "askedAt": T0, "question": None, "transcript": None,
         "answer": None, "error": None, "answeredAt": None, "location": HERE, "address": "東京都千代田区丸の内",
         "headingDegrees": None, "inputType": None, "conversationId": None, "newConversation": False, "rideId": RIDE,
         "memo": None, "memoUpdatedAt": None, "updatedAt": T0},
        {"kind": "deleted", "target": "ask", "id": GONE, "rideId": RIDE, "deletedAt": T2},
        {"kind": "ride", "rideId": RIDE, "name": "箱根", "status": "ended", "segments": [{"startedAt": T0, "endedAt": T1}],
         "autoEnded": False, "updatedAt": T1, "memo": "また行く"},
        {"kind": "note", "rideId": RIDE, "noteId": NOTE, "at": T0, "location": HERE, "text": "ここ", "updatedAt": T0,
         "address": "東京都千代田区丸の内", "headingDegrees": 0.0},
        {"kind": "route", "rideId": RIDE, "seq": 0, "points": [{"t": T0, "lat": 35.0, "lon": 139.0, "accuracy": 5.0, "segment": 0}]},
        {"kind": "route", "rideId": RIDE, "seq": 1, "points": [{"t": T0, "lat": 36.0, "lon": 139.0, "accuracy": 5.0, "segment": 0}]},
    ]


@pytest.mark.parametrize("stored, status, answered_at", [
    ({"status": "pending"}, "processing", None),
    ({"status": "processing"}, "processing", None),
    ({"status": "failed", "error": "agent_failed"}, "failed", None),
    ({"status": "failed", "error": "tts_failed", "answer": "文だけ"}, "failed", T2),
])
def test_an_ask_reads_back_with_the_status_the_app_polls_for(aws, stored, status, answered_at):
    put({"pk": f"USER#{USER}", "sk": f"ASK#{ASK}", "askId": ASK, "conversationId": CID, "conversationStartedAt": T0,
         "receivedAt": T1, "rideId": RIDE, "timings": {"receivedAt": T1, "agentDoneAt": T2}, **stored})
    (item,) = read_all()
    assert item["status"] == status and item["answeredAt"] == answered_at and item["newConversation"] is False


def test_small_pages_read_back_everything_once_in_order(aws, monkeypatch):
    everything()
    whole = read_all()
    monkeypatch.setattr(records, "PAGE_LIMIT", 2)
    pages = []
    cursor = None
    while True:
        body = page(cursor)
        pages.append(body["items"])
        cursor = body["cursor"]
        if cursor is None:
            break
    assert len(pages) > 3 and [item for items in pages for item in items] == whole


def test_records_are_kept_apart_by_user(aws):
    everything(user="someone")
    assert read_all() == []


def test_a_cursor_never_reads_another_users_records(aws):
    # The partition always comes from x-user-name; a cursor that names another user's is not followed there.
    everything(user="someone")
    forged = base64.urlsafe_b64encode(json.dumps({"pk": "USER#someone", "sk": "A"}).encode()).decode().rstrip("=")
    assert page(forged) == {"items": [], "cursor": None}


@pytest.mark.parametrize("cursor", ["", "!!!", base64.urlsafe_b64encode(b"[1]").decode(),
                                    base64.urlsafe_b64encode(b'{"sk": ""}').decode()])
def test_a_bad_cursor_is_400(aws, cursor):
    result = read(cursor)
    assert result["statusCode"] == 400 and json.loads(result["body"])["error"] == "bad_request"


def test_a_bad_user_is_400(aws):
    assert read(user="BAD")["statusCode"] == 400


def test_records_are_read_consistently(aws, monkeypatch):
    # A record sent just before taking over must be read back; moto is always consistent, so check the request.
    from lib import clients
    table = clients.table()
    queries = []
    query = table.query

    def spy(**params):
        queries.append(params)
        return query(**params)

    monkeypatch.setattr(table, "query", spy)
    everything()
    read_all()
    assert queries and all(q.get("ConsistentRead") is True for q in queries)
