"""Tests for PUT /rides/{rideId} and PUT /rides/{rideId}/route/{seq} (moto)."""
import json

from handlers import rides
from lib import store
from lib.store._dynamo import _from_item

USER = "rider01"
RIDE = "5c9a1f0e-2b3d-4e5f-8a6b-7c8d9e0f1a2b"
T0 = "2026-10-18T09:00:00.000Z"


def ride_body(**changes):
    body = {
        "name": "箱根",
        "status": "paused",
        "segments": [{"startedAt": T0, "endedAt": "2026-10-18T10:00:00.000Z"}],
        "autoEnded": False,
        "updatedAt": "2026-10-18T10:00:00.000Z",
    }
    return {**body, **changes}


def put_ride(body, ride_id=RIDE, user=USER):
    return rides.handler({"headers": {"x-user-name": user}, "pathParameters": {"rideId": ride_id}, "body": json.dumps(body)}, None)


def put_route(points, seq="0", ride_id=RIDE, user=USER):
    event = {"headers": {"x-user-name": user}, "pathParameters": {"rideId": ride_id, "seq": seq}, "body": json.dumps({"points": points})}
    return rides.handler(event, None)


def stored(aws, key):
    item = aws.table.get_item(Key=key).get("Item")
    return _from_item(item) if item else None


def point(i, segment=0):
    return {"t": f"2026-10-18T09:00:{i:02d}.000Z", "lat": 35.0 + i * 0.001, "lon": 139.0, "accuracy": 5.0, "segment": segment}


def message(result):
    return json.loads(result["body"])["message"]


def test_a_ride_is_saved_under_its_user(aws):
    result = put_ride(ride_body())
    assert result["statusCode"] == 200
    assert json.loads(result["body"]) == {"rideId": RIDE, "applied": True}
    item = stored(aws, store.ride_key(USER, RIDE))
    assert item["name"] == "箱根" and item["status"] == "paused" and item["autoEnded"] is False
    assert item["segments"] == [{"startedAt": T0, "endedAt": "2026-10-18T10:00:00.000Z"}]
    assert item["updatedAt"] == "2026-10-18T10:00:00.000Z" and "savedAt" in item


def test_sending_the_same_ride_again_leaves_one_record(aws):
    put_ride(ride_body())
    # The same updatedAt is not newer: nothing changes, and the app treats it as sent.
    again = put_ride(ride_body())
    assert again["statusCode"] == 200 and json.loads(again["body"])["applied"] is False
    items = aws.table.scan()["Items"]
    assert [i["sk"] for i in items] == [f"RIDE#{RIDE}"]


def test_a_newer_ride_replaces_the_stored_one(aws):
    put_ride(ride_body())
    ended = ride_body(status="ended", name="箱根から御殿場へ", updatedAt="2026-10-18T11:00:00.000Z",
                      segments=[{"startedAt": T0, "endedAt": "2026-10-18T10:00:00.000Z"},
                                {"startedAt": "2026-10-18T10:30:00.000Z", "endedAt": "2026-10-18T11:00:00.000Z"}])
    assert json.loads(put_ride(ended)["body"])["applied"] is True
    item = stored(aws, store.ride_key(USER, RIDE))
    assert item["status"] == "ended" and item["name"] == "箱根から御殿場へ" and len(item["segments"]) == 2


def test_an_older_ride_is_ignored_with_200(aws):
    put_ride(ride_body(status="ended", updatedAt="2026-10-18T11:00:00.000Z"))
    result = put_ride(ride_body(name="古い名前", updatedAt="2026-10-18T10:00:00.000Z"))
    assert result["statusCode"] == 200 and json.loads(result["body"])["applied"] is False
    item = stored(aws, store.ride_key(USER, RIDE))
    assert item["status"] == "ended" and item["name"] == "箱根"


def test_times_with_another_zone_are_compared_in_utc(aws):
    put_ride(ride_body(updatedAt="2026-10-18T19:00:00.000+09:00"))
    # 10:30Z is later than 19:00+09:00 (10:00Z), though it sorts earlier as text.
    assert json.loads(put_ride(ride_body(name="新しい", updatedAt="2026-10-18T10:30:00Z"))["body"])["applied"] is True
    assert stored(aws, store.ride_key(USER, RIDE))["updatedAt"] == "2026-10-18T10:30:00.000Z"


def test_rides_are_kept_apart_by_user(aws):
    put_ride(ride_body())
    put_ride(ride_body(name="別の人"), user="rider02")
    assert stored(aws, store.ride_key(USER, RIDE))["name"] == "箱根"
    assert stored(aws, store.ride_key("rider02", RIDE))["name"] == "別の人"


def test_a_recording_ride_has_its_last_segment_open(aws):
    body = ride_body(status="recording", segments=[{"startedAt": T0, "endedAt": None}])
    assert put_ride(body)["statusCode"] == 200
    assert stored(aws, store.ride_key(USER, RIDE))["segments"] == [{"startedAt": T0}]


def test_a_bad_ride_is_400(aws):
    cases = [
        ("name must be", ride_body(name="  ")),
        ("name must be", ride_body(name="あ" * 41)),
        ("status must be", ride_body(status="stopped")),
        ("autoEnded must be", ride_body(autoEnded="no")),
        ("only an ended ride", ride_body(autoEnded=True)),
        ("updatedAt must be", ride_body(updatedAt="2026-10-18T10:00:00")),
        ("segments must be", ride_body(segments=[])),
        ("only the last segment", ride_body(segments=[{"startedAt": T0, "endedAt": None}])),
        ("must be open", ride_body(status="recording")),
        ("cannot end before", ride_body(segments=[{"startedAt": T0, "endedAt": "2026-10-18T08:00:00.000Z"}])),
        ("must not overlap", ride_body(segments=[{"startedAt": T0, "endedAt": "2026-10-18T10:00:00.000Z"},
                                                 {"startedAt": "2026-10-18T09:30:00.000Z", "endedAt": "2026-10-18T10:30:00.000Z"}])),
    ]
    for expected, body in cases:
        result = put_ride(body)
        assert result["statusCode"] == 400 and expected in message(result), (expected, message(result))
    assert aws.table.scan()["Items"] == []


def test_a_body_that_is_not_json_is_400(aws):
    event = {"headers": {"x-user-name": USER}, "pathParameters": {"rideId": RIDE}, "body": "not json"}
    assert rides.handler(event, None)["statusCode"] == 400
    event["pathParameters"]["seq"] = "0"
    assert rides.handler(event, None)["statusCode"] == 400
    # Refused before anything is written (Backend #13).
    assert aws.table.scan()["Items"] == []


def test_a_bad_ride_id_or_user_is_400(aws):
    assert put_ride(ride_body(), ride_id="ride-1")["statusCode"] == 400
    assert put_ride(ride_body(), ride_id=RIDE.upper())["statusCode"] == 400
    assert put_ride(ride_body(), user="X")["statusCode"] == 400


def test_a_route_chunk_is_saved_with_its_points(aws):
    result = put_route([point(0), point(5)], seq="3")
    assert result["statusCode"] == 200 and json.loads(result["body"]) == {"rideId": RIDE, "seq": 3}
    item = stored(aws, store.route_key(USER, RIDE, 3))
    assert item["sk"] == f"RIDE#{RIDE}#ROUTE#00003"
    assert item["points"] == [point(0), point(5)]


def test_a_chunk_may_arrive_before_its_ride(aws):
    assert put_route([point(0)], seq="0")["statusCode"] == 200
    assert put_ride(ride_body())["statusCode"] == 200
    assert {i["sk"] for i in aws.table.scan()["Items"]} == {f"RIDE#{RIDE}", f"RIDE#{RIDE}#ROUTE#00000"}


def test_sending_a_chunk_again_replaces_it(aws):
    put_route([point(0)], seq="0")
    put_route([point(0), point(1)], seq="0")
    items = aws.table.scan()["Items"]
    assert len(items) == 1 and len(items[0]["points"]) == 2


def test_a_point_without_accuracy_is_kept(aws):
    put_route([{**point(0), "accuracy": None}])
    assert stored(aws, store.route_key(USER, RIDE, 0))["points"] == [{k: v for k, v in point(0).items() if k != "accuracy"}]


def test_a_chunk_of_300_points_is_accepted_and_301_is_400(aws):
    assert put_route([point(i % 60) for i in range(300)])["statusCode"] == 200
    result = put_route([point(i % 60) for i in range(301)], seq="1")
    assert result["statusCode"] == 400 and "1-300" in message(result)


def test_a_bad_chunk_is_400(aws):
    cases = {
        "points": [],
        "lat and lon": [{**point(0), "lat": 91}],
        "accuracy": [{**point(0), "accuracy": -1}],
        "segment": [{**point(0), "segment": -1}],
        "t must": [{**point(0), "t": "yesterday"}],
    }
    for expected, points in cases.items():
        result = put_route(points)
        assert result["statusCode"] == 400 and expected in message(result), (expected, message(result))
    for seq in ("-1", "abc", "100000"):
        assert put_route([point(0)], seq=seq)["statusCode"] == 400
    assert aws.table.scan()["Items"] == []


def test_a_number_too_large_for_a_float_is_400_not_a_crash(aws):
    result = put_route([{**point(0), "lat": 10 ** 400}])
    assert result["statusCode"] == 400 and "lat and lon" in message(result)


def test_a_deleted_ride_is_not_written_back(aws):
    store.mark_deleted(USER, "ride", RIDE, "2026-10-21T00:00:00.000Z")
    result = put_ride(ride_body())
    assert result["statusCode"] == 410 and json.loads(result["body"]) == {"error": "deleted"}
    assert stored(aws, store.ride_key(USER, RIDE)) is None


def test_a_chunk_of_a_deleted_ride_is_410(aws):
    store.mark_deleted(USER, "ride", RIDE, "2026-10-21T00:00:00.000Z")
    result = put_route([point(0)])
    assert result["statusCode"] == 410
    assert stored(aws, store.route_key(USER, RIDE, 0)) is None


def test_another_users_deletion_mark_does_not_stop_the_ride(aws):
    store.mark_deleted("someone", "ride", RIDE, "2026-10-21T00:00:00.000Z")
    assert put_ride(ride_body())["statusCode"] == 200


def test_a_ride_memo_is_kept_with_the_ride_and_dropped_when_sent_without_one(aws):
    put_ride(ride_body(memo="  また来たい  "))
    assert stored(aws, store.ride_key(USER, RIDE))["memo"] == "また来たい"
    put_ride(ride_body(updatedAt="2026-10-18T10:05:00.000Z"))
    assert "memo" not in stored(aws, store.ride_key(USER, RIDE))


def test_a_ride_memo_of_2000_characters_is_kept_and_2001_is_400(aws):
    assert put_ride(ride_body(memo="あ" * 2000))["statusCode"] == 200
    result = put_ride(ride_body(memo="あ" * 2001, updatedAt="2026-10-18T10:05:00.000Z"))
    assert result["statusCode"] == 400 and "memo" in message(result)


def test_a_blank_ride_memo_is_no_memo(aws):
    put_ride(ride_body(memo="   "))
    assert "memo" not in stored(aws, store.ride_key(USER, RIDE))
