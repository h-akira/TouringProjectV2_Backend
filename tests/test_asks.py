"""One ask record, read back two ways: by polling and by taking over (07 UC-5, UC-7)."""
import pytest

from lib import asks

ITEM = {
    "askId": "11111111-1111-4111-8111-111111111111",
    "status": "completed",
    "receivedAt": "2026-10-16T12:00:00.000Z",
    "address": "東京都千代田区",
    "headingDegrees": 90.0,
    "transcript": "ここはどこ",
    "answer": "千代田区です。",
}


@pytest.mark.parametrize("stored", ["pending", "processing", "completed", "failed", "offline", "unknown"])
def test_both_reads_give_the_same_status_for_the_same_record(stored):
    item = {**ITEM, "status": stored}
    assert asks.poll_view(item, ITEM["askId"], [])["status"] == asks.record_view(item)["status"] == asks.status(item)


def test_both_reads_agree_on_what_the_device_keeps():
    poll, record = asks.poll_view(ITEM, ITEM["askId"], []), asks.record_view(ITEM)
    for field in ["askedAt", "address", "headingDegrees", "transcript", "answer", "error"]:
        assert poll[field] == record[field], field


def test_an_unknown_stored_status_reads_as_processing():
    assert asks.status({"status": "unknown"}) == "processing"
    assert asks.status({}) == "processing"
