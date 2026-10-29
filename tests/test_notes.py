"""Tests for PUT /rides/{rideId}/notes/{noteId} (moto, the address lookup stubbed)."""
import json

import pytest

from handlers import rides
from lib import address, store

USER = "rider01"
RIDE = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"
NOTE = "9d8c7b6a-5f4e-4d3c-8b2a-1f0e9d8c7b6a"
HERE = {"latitude": 35.6812, "longitude": 139.7671}
# About 60 m south of HERE, 10 s before the note: the rider was heading north.
SOUTH = {"latitude": 35.68066, "longitude": 139.7671, "at": "2026-10-21T00:59:50.000Z"}


@pytest.fixture
def places(monkeypatch):
    calls = []

    def describe(lat, lon):
        calls.append((lat, lon))
        return "東京都千代田区丸の内"

    monkeypatch.setattr(address, "describe_location", describe)
    return calls


def note_body(**changes):
    body = {"at": "2026-10-21T01:00:00.000Z", "location": HERE, "headingSample": SOUTH, "text": "ここ、また来たい",
            "updatedAt": "2026-10-21T01:00:00.000Z"}
    return {**body, **changes}


def put_note(body, note_id=NOTE, ride_id=RIDE, user=USER):
    event = {"httpMethod": "PUT", "headers": {"x-user-name": user}, "pathParameters": {"rideId": ride_id, "noteId": note_id},
             "body": json.dumps(body)}
    return rides.handler(event, None)


def answer(result):
    return json.loads(result["body"])


def test_a_note_is_kept_under_its_ride_with_its_place_and_heading(aws, places):
    result = put_note(note_body())
    assert result["statusCode"] == 200
    assert answer(result) == {"noteId": NOTE, "applied": True, "address": "東京都千代田区丸の内", "headingDegrees": 0.0}
    item = store.get_note(USER, RIDE, NOTE)
    assert item["text"] == "ここ、また来たい" and item["location"] == HERE and item["at"] == "2026-10-21T01:00:00.000Z"
    assert item["rideId"] == RIDE and item["address"] == "東京都千代田区丸の内" and "headingSample" not in item
    assert aws.table.scan()["Items"][0]["sk"] == f"RIDE#{RIDE}#NOTE#{NOTE}"


def test_an_edited_note_keeps_its_place_without_looking_it_up_again(aws, places):
    put_note(note_body())
    result = put_note(note_body(text="直した", updatedAt="2026-10-21T01:10:00.000Z"))
    assert answer(result)["applied"] is True and answer(result)["address"] == "東京都千代田区丸の内"
    assert store.get_note(USER, RIDE, NOTE)["text"] == "直した"
    assert len(places) == 1


def test_a_place_that_could_not_be_found_is_looked_up_on_the_next_put(aws, monkeypatch):
    found = iter([None, "神奈川県足柄下郡箱根町仙石原"])
    monkeypatch.setattr(address, "describe_location", lambda lat, lon: next(found))
    assert answer(put_note(note_body()))["address"] is None
    result = put_note(note_body(updatedAt="2026-10-21T01:10:00.000Z"))
    assert answer(result)["address"] == "神奈川県足柄下郡箱根町仙石原"


def test_an_older_note_is_ignored_and_answers_with_the_stored_place(aws, places):
    put_note(note_body(text="新しい", updatedAt="2026-10-21T01:10:00.000Z"))
    result = put_note(note_body(text="古い"))
    assert result["statusCode"] == 200
    assert answer(result) == {"noteId": NOTE, "applied": False, "address": "東京都千代田区丸の内", "headingDegrees": 0.0}
    assert store.get_note(USER, RIDE, NOTE)["text"] == "新しい"


def test_a_note_without_a_position_has_no_place_or_heading(aws, places):
    result = put_note(note_body(location=None, headingSample=None))
    assert answer(result) == {"noteId": NOTE, "applied": True, "address": None, "headingDegrees": None}
    assert places == [] and "location" not in store.get_note(USER, RIDE, NOTE)


def test_a_note_may_arrive_before_its_ride(aws, places):
    # Notes go after rides in a pass, but a ride refused or still failing must not hold its notes back.
    assert put_note(note_body())["statusCode"] == 200
    assert aws.table.get_item(Key=store.ride_key(USER, RIDE)).get("Item") is None


def test_a_note_of_a_deleted_ride_or_a_deleted_note_is_410(aws, places):
    store.mark_deleted(USER, "ride", RIDE, "2026-10-21T02:00:00.000Z")
    assert put_note(note_body())["statusCode"] == 410
    other = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    store.mark_deleted(USER, "note", other, "2026-10-21T02:00:00.000Z", ride_id="6d0b2a1f-3c4e-4f5a-9b7c-8d9e0f1a2b3c")
    assert put_note(note_body(), note_id=other, ride_id="6d0b2a1f-3c4e-4f5a-9b7c-8d9e0f1a2b3c")["statusCode"] == 410
    assert aws.table.scan(FilterExpression="begins_with(sk, :r)", ExpressionAttributeValues={":r": "RIDE#"})["Items"] == []


def test_notes_are_kept_apart_by_user(aws, places):
    put_note(note_body())
    assert store.get_note("someone", RIDE, NOTE) is None


@pytest.mark.parametrize("changes", [
    {"text": ""}, {"text": "   "}, {"text": "あ" * 2001}, {"text": None},
    {"at": "2026-10-21T01:00:00"}, {"updatedAt": None},
    {"location": {"latitude": 91, "longitude": 0}}, {"location": "here"},
])
def test_a_bad_note_is_400_and_writes_nothing(aws, places, changes):
    result = put_note(note_body(**changes))
    assert result["statusCode"] == 400 and json.loads(result["body"])["error"] == "bad_request"
    assert aws.table.scan()["Items"] == []


def test_a_note_of_2000_characters_is_kept(aws, places):
    assert put_note(note_body(text="あ" * 2000))["statusCode"] == 200


def test_a_broken_heading_sample_only_drops_the_heading(aws, places):
    result = put_note(note_body(headingSample={"latitude": "x"}))
    assert result["statusCode"] == 200 and answer(result)["headingDegrees"] is None


def test_a_bad_note_id_is_400(aws, places):
    assert put_note(note_body(), note_id="note-1")["statusCode"] == 400


def test_sending_the_same_note_again_changes_nothing(aws, places):
    put_note(note_body())
    again = put_note(note_body())
    assert again["statusCode"] == 200 and answer(again)["applied"] is False
    assert len(places) == 1 and len(aws.table.scan()["Items"]) == 1


def test_a_note_of_2000_characters_and_a_trailing_newline_is_kept(aws, places):
    # The length is counted after the surrounding blanks are dropped (Backend #16).
    assert put_note(note_body(text="あ" * 2000 + "\n"))["statusCode"] == 200
    assert store.get_note(USER, RIDE, NOTE)["text"] == "あ" * 2000


def test_a_note_of_a_deleted_ride_or_note_is_refused_without_looking_up_its_place(aws, places):
    # An old send arriving after a deletion costs no ReverseGeocode call (Backend #17).
    store.mark_deleted(USER, "note", NOTE, "2026-10-21T02:00:00.000Z", ride_id=RIDE)
    assert put_note(note_body())["statusCode"] == 410
    other = "0a1b2c3d-4e5f-4a6b-8c7d-9e0f1a2b3c4d"
    ride2 = "6d0b2a1f-3c4e-4f5a-9b7c-8d9e0f1a2b3c"
    store.mark_deleted(USER, "ride", ride2, "2026-10-21T02:00:00.000Z")
    assert put_note(note_body(), note_id=other, ride_id=ride2)["statusCode"] == 410
    assert places == []


def test_an_edited_note_keeps_its_first_heading(aws, places):
    # The heading is settled on the first PUT, like the place (slice 3 spec §6.2, Backend #17).
    put_note(note_body())
    west = {"latitude": 35.6812, "longitude": 139.7664, "at": "2026-10-21T00:59:50.000Z"}
    result = put_note(note_body(text="直した", headingSample=west, updatedAt="2026-10-21T01:10:00.000Z"))
    assert answer(result)["applied"] is True and answer(result)["headingDegrees"] == 0.0
    assert store.get_note(USER, RIDE, NOTE)["headingDegrees"] == 0.0


def test_a_note_first_sent_without_a_heading_gets_one_later(aws, places):
    put_note(note_body(headingSample=None))
    result = put_note(note_body(updatedAt="2026-10-21T01:10:00.000Z"))
    assert answer(result)["headingDegrees"] == 0.0


def test_a_note_keeps_the_apps_heading(aws, places):
    # The sample says north; the app's own heading (adr/0013) is the one kept.
    result = put_note(note_body(headingDegrees=270.0))
    assert answer(result)["headingDegrees"] == 270.0
    assert store.get_note(USER, RIDE, NOTE)["headingDegrees"] == 270.0


def test_an_edited_note_keeps_the_apps_first_heading(aws, places):
    put_note(note_body(headingDegrees=270.0))
    result = put_note(note_body(text="直した", headingDegrees=90.0, updatedAt="2026-10-21T01:10:00.000Z"))
    assert answer(result)["applied"] is True and answer(result)["headingDegrees"] == 270.0
