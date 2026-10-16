"""Shared fixtures: fake credentials and moto-backed AWS resources."""
import os
from types import SimpleNamespace

import boto3
import pytest

os.environ.pop("AWS_PROFILE", None)
os.environ.update({
    "AWS_ACCESS_KEY_ID": "testing",
    "AWS_SECRET_ACCESS_KEY": "testing",
    "AWS_SESSION_TOKEN": "testing",
    "AWS_DEFAULT_REGION": "ap-northeast-1",
    "AWS_REGION": "ap-northeast-1",
    "TABLE_NAME": "test-records",
    "AUDIO_BUCKET": "test-audio",
    "CONVERSATION_RESET_PARAMETER": "/trv2/test/conversation-reset-minutes",
    "AGENT_ARN": "arn:aws:bedrock-agentcore:us-east-1:000000000000:runtime/test",
})

REGION = "ap-northeast-1"


@pytest.fixture
def aws(monkeypatch):
    from moto import mock_aws

    from lib import clients, conversation

    with mock_aws():
        dynamodb = boto3.resource("dynamodb", region_name=REGION)
        table = dynamodb.create_table(
            TableName="test-records",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"}, {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="test-audio", CreateBucketConfiguration={"LocationConstraint": REGION})
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="test-ask")["QueueUrl"]
        monkeypatch.setenv("QUEUE_URL", queue_url)
        boto3.client("ssm", region_name=REGION).put_parameter(
            Name="/trv2/test/conversation-reset-minutes", Value="15", Type="String"
        )
        clients.reset()
        conversation.reset_cache()
        yield SimpleNamespace(table=table, s3=s3, sqs=sqs, queue_url=queue_url, bucket="test-audio")
        clients.reset()
        conversation.reset_cache()
