"""Tests for DELETE /asks/{askId}, /rides/{rideId} and /rides/{rideId}/notes/{noteId} (moto)."""
import json

from handlers import ask_edit, rides
from lib import store

USER = "rider01"
RIDE = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"
OTHER_RIDE = "6d0b2a1f-3c4e-4f5a-9b7c-8d9e0f1a2b3c"
NOTE = "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a"
ASK = "11111111-1111-4111-8111-111111111111"
ASK2 = "22222222-2222-4222-8222-222222222222"
T = "2026-10-21T01:00:00.000Z"


def call(handler, method, user=USER, body=None, **path):
    event = {"httpMethod": method, "headers": {"x-user-name": user}, "pathParameters": path}
    if body is not None:
        event["body"] = json.dumps(body)
    return handler.handler(event, None)


def sks(aws, prefix=""):
    return sorted(i["sk"] for i in aws.table.scan()["Items"] if i["sk"].startswith(prefix))


def ride_body(updated_at=T):
    return {"name": "箱根", "status": "ended", "segments": [{"startedAt": "2026-10-21T00:00:00.000Z", "endedAt": T}],
            "autoEnded": False, "updatedAt": updated_at}


def note_body(updated_at=T):
    return {"at": T, "location": None, "text": "メモ", "updatedAt": updated_at}


def ask(ask_id, ride_id, user=USER):
    store.create_ask({**store.ask_key(user, ask_id), "askId": ask_id, "status": "completed", "rideId": ride_id})


def a_ride_with_everything(aws, user=USER):
    call(rides, "PUT", user=user, body=ride_body(), rideId=RIDE)
    for seq in ("0", "1"):
        point = {"t": T, "lat": 35.0, "lon": 139.0, "accuracy": 5.0, "segment": 0}
        call(rides, "PUT", user=user, body={"points": [point]}, rideId=RIDE, seq=seq)
    call(rides, "PUT", user=user, body=note_body(), rideId=RIDE, noteId=NOTE)
    ask(ASK, RIDE, user)
    ask(ASK2, OTHER_RIDE, user)


def test_deleting_a_ride_removes_its_route_notes_and_asks_and_marks_them(aws):
    a_ride_with_everything(aws)
    result = call(rides, "DELETE", rideId=RIDE)
    assert result["statusCode"] == 204 and result["body"] == ""
    assert sks(aws) == sorted([f"ASK#{ASK2}", f"DELETED#ASK#{ASK}", f"DELETED#NOTE#{NOTE}", f"DELETED#RIDE#{RIDE}"])
    mark = aws.table.get_item(Key=store.deleted_key(USER, "ask", ASK))["Item"]
    assert mark["kind"] == "ask" and mark["rideId"] == RIDE and mark["deletedAt"].endswith("Z")


def test_a_deleted_ride_does_not_come_back_from_an_old_send(aws):
    a_ride_with_everything(aws)
    call(rides, "DELETE", rideId=RIDE)
    assert call(rides, "PUT", body=ride_body("2026-10-21T09:00:00.000Z"), rideId=RIDE)["statusCode"] == 410
    point = {"t": T, "lat": 35.0, "lon": 139.0, "accuracy": 5.0, "segment": 0}
    assert call(rides, "PUT", body={"points": [point]}, rideId=RIDE, seq="0")["statusCode"] == 410
    assert call(rides, "PUT", body=note_body("2026-10-21T09:00:00.000Z"), rideId=RIDE, noteId=NOTE)["statusCode"] == 410
    memo = {"memo": "戻らない", "updatedAt": "2026-10-21T09:00:00.000Z"}
    assert call(ask_edit, "PUT", body=memo, askId=ASK)["statusCode"] == 410
    assert sks(aws, "RIDE#") == [] and sks(aws, "ASK#") == [f"ASK#{ASK2}"]


def test_deleting_a_ride_leaves_another_users_records(aws):
    a_ride_with_everything(aws, user="someone")
    call(rides, "DELETE", rideId=RIDE)
    assert len([k for k in sks(aws, "RIDE#")]) == 4
    assert call(rides, "PUT", user="someone", body=ride_body("2026-10-21T09:00:00.000Z"), rideId=RIDE)["statusCode"] == 200


def test_deleting_a_ride_with_many_asks_reads_every_page(aws):
    call(rides, "PUT", body=ride_body(), rideId=RIDE)
    asks = [f"{i:08x}-0000-4000-8000-000000000000" for i in range(60)]
    with aws.table.batch_writer() as batch:
        for ask_id in asks:
            batch.put_item(Item={**store.ask_key(USER, ask_id), "askId": ask_id, "rideId": RIDE, "answer": "あ" * 20000})
    call(rides, "DELETE", rideId=RIDE)
    assert sks(aws, "ASK#") == []


def test_deleting_twice_or_deleting_what_never_arrived_is_204(aws):
    assert call(rides, "DELETE", rideId=RIDE)["statusCode"] == 204
    assert call(rides, "DELETE", rideId=RIDE)["statusCode"] == 204
    assert call(rides, "DELETE", rideId=RIDE, noteId=NOTE)["statusCode"] == 204
    assert call(ask_edit, "DELETE", askId=ASK)["statusCode"] == 204
    assert sks(aws) == sorted([f"DELETED#ASK#{ASK}", f"DELETED#NOTE#{NOTE}", f"DELETED#RIDE#{RIDE}"])


def test_deleting_a_note_keeps_the_ride_and_stops_the_note_coming_back(aws):
    call(rides, "PUT", body=ride_body(), rideId=RIDE)
    call(rides, "PUT", body=note_body(), rideId=RIDE, noteId=NOTE)
    assert call(rides, "DELETE", rideId=RIDE, noteId=NOTE)["statusCode"] == 204
    assert sks(aws) == sorted([f"DELETED#NOTE#{NOTE}", f"RIDE#{RIDE}"])
    assert call(rides, "PUT", body=note_body("2026-10-21T09:00:00.000Z"), rideId=RIDE, noteId=NOTE)["statusCode"] == 410
    assert call(rides, "PUT", body=ride_body("2026-10-21T09:00:00.000Z"), rideId=RIDE)["statusCode"] == 200


def test_deleting_an_ask_keeps_its_ride_and_marks_it_with_the_ride(aws):
    call(rides, "PUT", body=ride_body(), rideId=RIDE)
    ask(ASK, RIDE)
    assert call(ask_edit, "DELETE", askId=ASK)["statusCode"] == 204
    assert sks(aws) == sorted([f"DELETED#ASK#{ASK}", f"RIDE#{RIDE}"])
    assert aws.table.get_item(Key=store.deleted_key(USER, "ask", ASK))["Item"]["rideId"] == RIDE


def test_a_bad_id_to_delete_is_400(aws):
    assert call(rides, "DELETE", rideId="ride-1")["statusCode"] == 400
    assert call(rides, "DELETE", rideId=RIDE, noteId="note-1")["statusCode"] == 400
    assert call(ask_edit, "DELETE", askId="ask-1")["statusCode"] == 400
    assert call(ask_edit, "DELETE", user="BAD", askId=ASK)["statusCode"] == 400
    assert sks(aws) == []


def test_deleting_a_ride_reads_its_records_with_consistent_reads(aws, monkeypatch):
    # A note or ask written just before the DELETE must be found; moto is always consistent, so check the request.
    from lib import clients
    table = clients.table()
    queries = []
    query = table.query

    def spy(**params):
        queries.append(params)
        return query(**params)

    monkeypatch.setattr(table, "query", spy)
    a_ride_with_everything(aws)
    call(rides, "DELETE", rideId=RIDE)
    assert len(queries) == 2 and all(q.get("ConsistentRead") is True for q in queries)
