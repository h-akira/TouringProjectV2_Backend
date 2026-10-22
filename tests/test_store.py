"""Tests for the DynamoDB record helpers (moto)."""
import pytest
from botocore.exceptions import ClientError

from lib import clients, store

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


def test_a_conversation_record_expires_a_day_after_it_starts(aws):
    cid = "33333333-3333-4333-8333-333333333333"
    store.conversation_started_at(USER, cid, "2026-10-16T03:00:00.000Z")
    item = aws.table.get_item(Key={"pk": f"USER#{USER}", "sk": f"CONV#{cid}"})["Item"]
    # 2026-10-16T03:00:00Z is 1792119600 in UNIX seconds.
    assert item["expiresAt"] == 1792119600 + 24 * 60 * 60


def test_a_conversation_started_meanwhile_is_read_consistently(aws, monkeypatch):
    # The second of two first questions reads the record the first one just wrote; moto is always consistent.
    from lib import clients
    table = clients.table()
    reads = []
    get_item = table.get_item

    def spy(**params):
        reads.append(params)
        return get_item(**params)

    monkeypatch.setattr(table, "get_item", spy)
    cid = "33333333-3333-4333-8333-333333333333"
    store.conversation_started_at(USER, cid, "2026-10-16T03:00:00.000Z")
    assert store.conversation_started_at(USER, cid, "2026-10-16T03:10:00.000Z") == "2026-10-16T03:00:00.000Z"
    assert len(reads) == 1 and reads[0].get("ConsistentRead") is True


def test_a_deletion_mark_is_one_record_however_often_it_is_written(aws):
    store.mark_deleted("rider01", "note", "n1", "2026-10-21T01:00:00.000Z", ride_id="r1")
    store.mark_deleted("rider01", "note", "n1", "2026-10-21T02:00:00.000Z", ride_id="r1")
    items = aws.table.scan()["Items"]
    assert [i["sk"] for i in items] == ["DELETED#NOTE#n1"]
    assert items[0]["kind"] == "note" and items[0]["id"] == "n1" and items[0]["rideId"] == "r1"


def test_update_ask_does_not_create_a_missing_ask(aws):
    assert store.update_ask("rider01", "a1", {"status": "completed"}) is False
    assert aws.table.scan()["Items"] == []


def _conflict(operation):
    return ClientError({"Error": {"Code": "TransactionConflictException", "Message": "busy"}}, operation)


def _cancelled(*codes):
    reasons = [{"Code": code} for code in codes]
    return ClientError({"Error": {"Code": "TransactionCanceledException", "Message": "cancelled"},
                        "CancellationReasons": reasons}, "TransactWriteItems")


@pytest.fixture
def no_wait(monkeypatch):
    waits = []
    monkeypatch.setattr(store, "_sleep", waits.append)
    return waits


def test_a_mark_written_during_a_transaction_on_it_is_tried_again(aws, monkeypatch, no_wait):
    # A PUT checking the same mark in a transaction makes the plain write fail for a moment (Backend #18).
    table = clients.table()
    put_item = table.put_item
    failures = iter([_conflict("PutItem")])

    def busy_once(**params):
        error = next(failures, None)
        if error:
            raise error
        return put_item(**params)

    monkeypatch.setattr(table, "put_item", busy_once)
    store.mark_deleted(USER, "ride", "r1", "2026-10-21T01:00:00.000Z")
    assert [i["sk"] for i in aws.table.scan()["Items"]] == ["DELETED#RIDE#r1"]
    assert len(no_wait) == 1


def test_a_mark_that_stays_busy_gives_up_after_three_tries(aws, monkeypatch, no_wait):
    table = clients.table()

    def busy(**params):
        raise _conflict("PutItem")

    monkeypatch.setattr(table, "put_item", busy)
    with pytest.raises(ClientError):
        store.mark_deleted(USER, "ride", "r1", "2026-10-21T01:00:00.000Z")
    assert len(no_wait) == 2


def test_a_write_that_meets_a_deletion_in_progress_is_tried_again_and_refused(aws, monkeypatch, no_wait):
    # The deletion's mark lands while the PUT's transaction runs: the retry sees the mark and answers Deleted.
    client = clients.table().meta.client
    transact = client.transact_write_items
    state = {"first": True}

    def conflict_then_mark(**params):
        if state["first"]:
            state["first"] = False
            store.mark_deleted(USER, "ride", "r1", "2026-10-21T01:00:00.000Z")
            raise _cancelled("None", "TransactionConflict")
        return transact(**params)

    monkeypatch.setattr(client, "transact_write_items", conflict_then_mark)
    with pytest.raises(store.Deleted):
        store.put_ride(USER, "r1", {"name": "n", "updatedAt": "2026-10-21T02:00:00.000Z"})
    assert len(no_wait) == 1 and "RIDE#r1" not in [i["sk"] for i in aws.table.scan()["Items"]]


def test_deleting_an_ask_reads_its_ride_consistently(aws, monkeypatch):
    # The ask may have been written a moment ago; its mark must still name its ride (Backend #18).
    table = clients.table()
    reads = []
    get_item = table.get_item

    def spy(**params):
        reads.append(params)
        return get_item(**params)

    store.create_ask(new_ask(rideId="r1"))
    monkeypatch.setattr(table, "get_item", spy)
    store.delete_ask(USER, ASK, "2026-10-21T01:00:00.000Z")
    assert reads and all(r.get("ConsistentRead") is True for r in reads)
    assert aws.table.get_item(Key=store.deleted_key(USER, "ask", ASK))["Item"]["rideId"] == "r1"
