"""Tests for the conversation reset minutes read from SSM."""
import boto3
import pytest

from lib import conversation

PARAM = "/trv2/test/conversation-reset-minutes"


def put(value):
    boto3.client("ssm", region_name="ap-northeast-1").put_parameter(Name=PARAM, Value=value, Type="String", Overwrite=True)


def test_reads_value(aws):
    assert conversation.reset_minutes() == 15


@pytest.mark.parametrize("value, expected", [("30", 30), ("90", 55), ("0", 1), ("abc", 15), (" 20 ", 20)])
def test_clamps_and_defaults(aws, value, expected):
    put(value)
    assert conversation.reset_minutes() == expected


def test_cached_for_a_minute(aws):
    now = [0.0]
    assert conversation.reset_minutes(clock=lambda: now[0]) == 15
    put("30")
    now[0] = 59
    assert conversation.reset_minutes(clock=lambda: now[0]) == 15
    now[0] = 61
    assert conversation.reset_minutes(clock=lambda: now[0]) == 30


def test_missing_parameter_falls_back(aws, monkeypatch):
    monkeypatch.setenv("CONVERSATION_RESET_PARAMETER", "/trv2/test/missing")
    assert conversation.reset_minutes() == conversation.DEFAULT_MINUTES
