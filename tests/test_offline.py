"""Tests for PUT /asks/{askId}/offline: an ask that never reached the Backend (moto, the address lookup stubbed)."""
import json

import pytest

from handlers import ask_edit, rides
from lib import store

USER = "rider01"
ASK = "11111111-1111-4111-8111-111111111111"
RIDE = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"
HERE = {"latitude": 35.6812, "longitude": 139.7671}
# About 60 m south of HERE, 10 s before the ask: the rider was heading north.
SOUTH = {"latitude": 35.68066, "longitude": 139.7671, "at": "2026-10-22T00:59:50.000Z"}
T1, T2 = "2026-10-22T01:00:00.000Z", "2026-10-22T01:10:00.000Z"


@pytest.fixture
def places(monkeypatch):
    calls = []

    def describe(lat, lon):
        calls.append((lat, lon))
        return "神奈川県足柄下郡箱根町仙石原"

    monkeypatch.setattr(ask_edit.address, "describe_location", describe)
    return calls


def offline_body(**changes):
    return {"askedAt": T1, "location": HERE, "headingSample": SOUTH, "rideId": RIDE, "updatedAt": T1, **changes}


def put_offline(body, ask_id=ASK, user=USER):
    event = {"httpMethod": "PUT", "resource": "/asks/{askId}/offline", "headers": {"x-user-name": user},
             "pathParameters": {"askId": ask_id}, "body": json.dumps(body)}
    return ask_edit.handler(event, None)


def answer(result):
    return json.loads(result["body"])


def test_an_unreached_ask_is_kept_with_its_place_and_heading(aws, places):
    result = put_offline(offline_body())
    assert result["statusCode"] == 200
    assert answer(result) == {"askId": ASK, "applied": True, "address": "神奈川県足柄下郡箱根町仙石原", "headingDegrees": 0.0}
    item = store.get_ask(USER, ASK)
    assert item["status"] == "offline" and item["receivedAt"] == T1 and item["rideId"] == RIDE
    assert item["location"] == HERE and item["updatedAt"] == T1 and item["address"] == "神奈川県足柄下郡箱根町仙石原"
    assert "headingSample" not in item and "conversationId" not in item and "question" not in item


def test_sending_the_same_version_again_changes_nothing(aws, places):
    put_offline(offline_body())
    again = put_offline(offline_body())
    assert again["statusCode"] == 200 and answer(again)["applied"] is False
    assert answer(again)["address"] == "神奈川県足柄下郡箱根町仙石原" and len(places) == 1


def test_an_older_version_is_ignored_and_answers_with_the_stored_place(aws, places):
    put_offline(offline_body(updatedAt=T2))
    result = put_offline(offline_body(updatedAt=T1))
    assert answer(result) == {"askId": ASK, "applied": False, "address": "神奈川県足柄下郡箱根町仙石原", "headingDegrees": 0.0}


def test_a_newer_version_keeps_the_memo_place_and_heading(aws, places):
    # The memo is written on its own path; sending the unreached ask again must not drop it.
    put_offline(offline_body())
    memo = {"httpMethod": "PUT", "headers": {"x-user-name": USER}, "pathParameters": {"askId": ASK},
            "body": json.dumps({"memo": "何の山か聞きたかった", "updatedAt": T1})}
    assert ask_edit.handler(memo, None)["statusCode"] == 200
    west = {"latitude": 35.6812, "longitude": 139.7664, "at": "2026-10-22T00:59:50.000Z"}
    result = put_offline(offline_body(headingSample=west, updatedAt=T2))
    assert answer(result)["applied"] is True and answer(result)["headingDegrees"] == 0.0
    item = store.get_ask(USER, ASK)
    assert item["memo"] == "何の山か聞きたかった" and item["updatedAt"] == T2 and len(places) == 1


def test_a_place_that_could_not_be_found_is_looked_up_on_the_next_put(aws, monkeypatch):
    found = iter([None, "東京都千代田区丸の内"])
    monkeypatch.setattr(ask_edit.address, "describe_location", lambda lat, lon: next(found))
    assert answer(put_offline(offline_body()))["address"] is None
    assert answer(put_offline(offline_body(updatedAt=T2)))["address"] == "東京都千代田区丸の内"


def test_an_unreached_ask_without_a_position_has_no_place_or_heading(aws, places):
    result = put_offline(offline_body(location=None, headingSample=None))
    assert answer(result) == {"askId": ASK, "applied": True, "address": None, "headingDegrees": None}
    assert places == [] and "location" not in store.get_ask(USER, ASK)


def test_an_unreached_ask_that_was_deleted_or_whose_ride_was_deleted_is_410(aws, places):
    store.mark_deleted(USER, "ask", ASK, T2, ride_id=RIDE)
    assert put_offline(offline_body())["statusCode"] == 410
    other = "22222222-2222-4222-8222-222222222222"
    ride2 = "6d0b2a1f-3c4e-4f5a-9b7c-8d9e0f1a2b3c"
    store.mark_deleted(USER, "ride", ride2, T2)
    result = put_offline(offline_body(rideId=ride2), ask_id=other)
    assert result["statusCode"] == 410 and answer(result) == {"error": "deleted"}
    assert places == [] and [i["sk"] for i in aws.table.scan()["Items"] if i["sk"].startswith("ASK#")] == []


def test_the_id_of_an_ask_the_backend_took_in_is_409_and_left_alone(aws, places):
    store.create_ask({**store.ask_key(USER, ASK), "askId": ASK, "status": "completed", "answer": "A", "rideId": RIDE})
    result = put_offline(offline_body())
    assert result["statusCode"] == 409 and answer(result) == {"error": "conflict"}
    item = store.get_ask(USER, ASK)
    assert item["status"] == "completed" and item["answer"] == "A" and places == []


def test_unreached_asks_are_kept_apart_by_user(aws, places):
    put_offline(offline_body())
    assert store.get_ask("someone", ASK) is None


def test_deleting_the_ride_removes_its_unreached_ask_and_marks_it(aws, places):
    put_offline(offline_body())
    event = {"httpMethod": "DELETE", "headers": {"x-user-name": USER}, "pathParameters": {"rideId": RIDE}}
    assert rides.handler(event, None)["statusCode"] == 204
    assert store.get_ask(USER, ASK) is None
    assert aws.table.get_item(Key=store.deleted_key(USER, "ask", ASK))["Item"]["rideId"] == RIDE


@pytest.mark.parametrize("changes", [
    {"askedAt": "2026-10-22T01:00:00"}, {"askedAt": None}, {"updatedAt": None},
    {"rideId": None}, {"rideId": "ride-1"}, {"location": {"latitude": 91, "longitude": 0}}, {"location": "here"},
])
def test_a_bad_unreached_ask_is_400_and_writes_nothing(aws, places, changes):
    result = put_offline(offline_body(**changes))
    assert result["statusCode"] == 400 and answer(result)["error"] == "bad_request"
    assert aws.table.scan()["Items"] == []


def test_a_bad_ask_id_is_400(aws, places):
    assert put_offline(offline_body(), ask_id="ask-1")["statusCode"] == 400


def test_a_broken_heading_sample_only_drops_the_heading(aws, places):
    result = put_offline(offline_body(headingSample={"latitude": "x"}))
    assert result["statusCode"] == 200 and answer(result)["headingDegrees"] is None


def test_an_unreached_ask_keeps_the_apps_heading(aws, places):
    # The sample says north; the app's own heading (adr/0013) is the one kept.
    result = put_offline(offline_body(headingDegrees=270.0))
    assert answer(result)["headingDegrees"] == 270.0
    assert store.get_ask(USER, ASK)["headingDegrees"] == 270.0


def test_a_newer_version_keeps_the_apps_first_heading(aws, places):
    put_offline(offline_body(headingDegrees=270.0))
    result = put_offline(offline_body(headingDegrees=90.0, updatedAt=T2))
    assert answer(result)["applied"] is True and answer(result)["headingDegrees"] == 270.0
