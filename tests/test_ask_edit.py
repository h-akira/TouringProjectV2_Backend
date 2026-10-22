"""Tests for PUT /asks/{askId}/memo (moto)."""
import json

from handlers import ask_edit
from lib import store

USER, ASK = "rider01", "11111111-1111-4111-8111-111111111111"
T1, T2 = "2026-10-21T01:00:00.000Z", "2026-10-21T02:00:00.000Z"


def put_ask(**fields):
    store.create_ask({**store.ask_key(USER, ASK), "askId": ASK, "status": "completed", "answer": "A", **fields})


def put_memo(memo, updated_at=T1, ask_id=ASK, user=USER):
    event = {"httpMethod": "PUT", "headers": {"x-user-name": user}, "pathParameters": {"askId": ask_id},
             "body": json.dumps({"memo": memo, "updatedAt": updated_at})}
    return ask_edit.handler(event, None)


def test_a_memo_is_kept_on_the_ask(aws):
    put_ask()
    result = put_memo("また来たい")
    assert result["statusCode"] == 200 and json.loads(result["body"]) == {"askId": ASK, "applied": True}
    item = store.get_ask(USER, ASK)
    assert item["memo"] == "また来たい" and item["memoUpdatedAt"] == T1 and item["answer"] == "A"


def test_an_older_memo_is_ignored_with_200(aws):
    put_ask()
    put_memo("新しい", updated_at=T2)
    result = put_memo("古い", updated_at=T1)
    assert result["statusCode"] == 200 and json.loads(result["body"])["applied"] is False
    assert store.get_ask(USER, ASK)["memo"] == "新しい"


def test_sending_the_same_memo_again_changes_nothing(aws):
    put_ask()
    put_memo("同じ")
    assert json.loads(put_memo("同じ")["body"])["applied"] is False


def test_a_null_memo_removes_it(aws):
    put_ask()
    put_memo("消す前", updated_at=T1)
    assert json.loads(put_memo(None, updated_at=T2)["body"])["applied"] is True
    item = store.get_ask(USER, ASK)
    assert "memo" not in item and item["memoUpdatedAt"] == T2


def test_a_memo_for_a_missing_ask_is_404_and_writes_nothing(aws):
    result = put_memo("どこへ")
    assert result["statusCode"] == 404
    assert aws.table.scan()["Items"] == []


def test_a_memo_for_another_users_ask_is_404(aws):
    put_ask()
    assert put_memo("他人", user="someone")["statusCode"] == 404


def test_a_memo_for_a_deleted_ask_is_410(aws):
    store.mark_deleted(USER, "ask", ASK, T1)
    result = put_memo("戻らない", updated_at=T2)
    assert result["statusCode"] == 410 and json.loads(result["body"]) == {"error": "deleted"}


def test_a_bad_memo_is_400(aws):
    put_ask()
    assert put_memo("あ" * 2001)["statusCode"] == 400
    assert put_memo(123)["statusCode"] == 400
    assert put_memo("ok", updated_at="2026-10-21T01:00:00")["statusCode"] == 400
    assert put_memo("ok", ask_id="not-a-uuid")["statusCode"] == 400
    assert "memo" not in store.get_ask(USER, ASK)


def test_a_memo_of_2000_emoji_is_kept(aws):
    # Android counts an emoji as two characters, so it never sends more than the Backend takes.
    put_ask()
    assert put_memo("😀" * 2000)["statusCode"] == 200


def test_a_memo_of_2000_characters_and_a_trailing_newline_is_kept(aws):
    # The length is counted after the surrounding blanks are dropped (Backend #16).
    put_ask()
    assert put_memo("あ" * 2000 + "\n")["statusCode"] == 200
    assert store.get_ask(USER, ASK)["memo"] == "あ" * 2000
