"""Tests for the DynamoDB record helpers (moto)."""
from lib import store

USER, ASK = "rider01", "11111111-1111-4111-8111-111111111111"


def new_ask(**extra):
    return {**store.ask_key(USER, ASK), "askId": ASK, "status": "pending", "location": {"latitude": 35.6812, "longitude": 139.7671}, **extra}


def test_create_and_get_round_trips_numbers(aws):
    store.create_ask(new_ask(question="Q", transcript=None))
    item = store.get_ask(USER, ASK)
    assert item["location"] == {"latitude": 35.6812, "longitude": 139.7671}
    assert isinstance(item["location"]["latitude"], float)
    assert "transcript" not in item


def test_get_missing_and_other_user(aws):
    store.create_ask(new_ask())
    assert store.get_ask(USER, "22222222-2222-4222-8222-222222222222") is None
    assert store.get_ask("someoneelse", ASK) is None


def test_claim_only_once(aws):
    store.create_ask(new_ask())
    first = store.claim_ask(USER, ASK)
    assert first["status"] == "processing"
    assert store.claim_ask(USER, ASK) is None


def test_claim_missing_is_none(aws):
    assert store.claim_ask(USER, ASK) is None


def test_update_sets_fields_and_skips_none(aws):
    store.create_ask(new_ask())
    store.update_ask(USER, ASK, {"status": "completed", "answer": "A", "usage": {"inputTokens": 10}, "error": None})
    item = store.get_ask(USER, ASK)
    assert item["status"] == "completed" and item["answer"] == "A" and item["usage"] == {"inputTokens": 10}
    assert "error" not in item


def test_conversation_start_is_kept_from_first_question(aws):
    cid = "33333333-3333-4333-8333-333333333333"
    assert store.conversation_started_at(USER, cid, "2026-10-16T03:00:00.000Z") == "2026-10-16T03:00:00.000Z"
    assert store.conversation_started_at(USER, cid, "2026-10-16T03:10:00.000Z") == "2026-10-16T03:00:00.000Z"


def test_a_deletion_mark_is_one_record_however_often_it_is_written(aws):
    store.mark_deleted("rider01", "note", "n1", "2026-10-21T01:00:00.000Z", ride_id="r1")
    store.mark_deleted("rider01", "note", "n1", "2026-10-21T02:00:00.000Z", ride_id="r1")
    items = aws.table.scan()["Items"]
    assert [i["sk"] for i in items] == ["DELETED#NOTE#n1"]
    assert items[0]["kind"] == "note" and items[0]["id"] == "n1" and items[0]["rideId"] == "r1"


def test_update_ask_does_not_create_a_missing_ask(aws):
    assert store.update_ask("rider01", "a1", {"status": "completed"}) is False
    assert aws.table.scan()["Items"] == []
