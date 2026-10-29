"""lib.store keeps the names the handlers and tests use, and keeps DynamoDB's mechanics apart from the records."""
import importlib

import pytest

from lib import store

NAMES = [
    "Deleted", "ask_key", "claim_ask", "claim_transcription", "conversation_started_at", "create_ask",
    "create_transcription", "delete_ask", "delete_note", "delete_ride", "deleted_key", "discard_ask",
    "finish_transcription", "get_ask", "get_note", "get_transcription", "has_deletion_mark", "mark_deleted",
    "note_key", "put_ask_memo", "put_note", "put_offline_ask", "put_ride", "put_route_chunk", "query_records",
    "ride_key", "route_key", "transcription_key", "update_ask",
]


@pytest.mark.parametrize("name", NAMES)
def test_the_store_keeps_its_names(name):
    assert hasattr(store, name)


@pytest.mark.parametrize("module", ["_dynamo", "ask_items", "ride_items", "conversation_items", "transcription_items",
                                    "listing"])
def test_the_store_is_split_by_kind_of_record(module):
    importlib.import_module(f"lib.store.{module}")


def test_the_retry_waits_live_with_the_dynamodb_mechanics():
    from lib.store import _dynamo

    assert store._MARK_READS == _dynamo._MARK_READS and callable(_dynamo._sleep)


def test_the_set_clause_names_and_numbers_every_field():
    from lib.store._dynamo import _set_clause

    expression, names, values = _set_clause({"status": "done", "text": "こんにちは"})
    assert expression == "SET #k0 = :v0, #k1 = :v1"
    assert names == {"#k0": "status", "#k1": "text"}
    assert values == {":v0": "done", ":v1": "こんにちは"}
