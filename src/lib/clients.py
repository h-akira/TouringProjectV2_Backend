"""AWS clients, created lazily and cached per container; reset() is for tests."""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Any

import boto3
from botocore.config import Config


def _region() -> str:
    return os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION") or "ap-northeast-1"


@lru_cache(maxsize=None)
def table() -> Any:
    return boto3.resource("dynamodb", region_name=_region()).Table(os.environ["TABLE_NAME"])


@lru_cache(maxsize=None)
def s3() -> Any:
    # Regional virtual-hosted endpoint, so presigned URLs work without a redirect.
    return boto3.client("s3", region_name=_region(), config=Config(signature_version="s3v4", s3={"addressing_style": "virtual"}))


@lru_cache(maxsize=None)
def sqs() -> Any:
    return boto3.client("sqs", region_name=_region())


@lru_cache(maxsize=None)
def ssm() -> Any:
    return boto3.client("ssm", region_name=_region())


@lru_cache(maxsize=None)
def polly() -> Any:
    return boto3.client("polly", region_name=_region())


@lru_cache(maxsize=None)
def geo() -> Any:
    return boto3.client("geo-places", region_name=os.environ.get("GEO_REGION", _region()))


@lru_cache(maxsize=None)
def agentcore() -> Any:
    # The agent lives in another region; its stream can take a while, so allow a long read,
    # but never let botocore resend on its own: a second call would repeat the question in
    # the conversation, and two long reads would outlive the worker's 120 s timeout.
    return boto3.client(
        "bedrock-agentcore",
        region_name=os.environ.get("AGENT_REGION", "us-east-1"),
        config=Config(read_timeout=90, retries={"total_max_attempts": 1}),
    )


def reset() -> None:
    for factory in (table, s3, sqs, ssm, polly, geo, agentcore):
        factory.cache_clear()
