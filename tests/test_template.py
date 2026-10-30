"""The stack's settings are chosen per environment (Backend #7)."""
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent
SSM_NAMES = ("AgentRuntimeArn", "ConversationResetParameter")


class _CfnLoader(yaml.SafeLoader):
    """Reads CloudFormation's short tags (!Ref, !Sub, ...) as plain values."""


_CfnLoader.add_multi_constructor("!", lambda loader, suffix, node: None)


def _template() -> dict:
    return yaml.load((ROOT / "template.yaml").read_text(encoding="utf-8"), Loader=_CfnLoader)


def _overrides() -> dict:
    config = tomllib.loads((ROOT / "samconfig.toml").read_text(encoding="utf-8"))
    pairs = config["default"]["deploy"]["parameters"]["parameter_overrides"].split()
    return dict(pair.split("=", 1) for pair in pairs)


def test_the_ssm_names_have_no_default():
    # A default names one environment's parameters; another environment would silently use them.
    parameters = _template()["Parameters"]
    assert all("Default" not in parameters[name] for name in SSM_NAMES)


def test_the_dev_deploy_names_the_dev_parameters():
    overrides = _overrides()
    assert overrides["Environment"] == "dev"
    assert overrides["AgentRuntimeArn"] == "/trv2/dev/agent-runtime-arn"
    assert overrides["ConversationResetParameter"] == "/trv2/dev/conversation-reset-minutes"


def test_the_stale_claim_time_fits_between_the_lambda_timeout_and_the_queue_visibility():
    # A claim older than STALE_CLAIM_SECONDS belongs to a worker that is gone (its Lambda timed out), and the queue
    # delivers again only after its visibility timeout.
    from lib import budget
    template = _template()["Resources"]
    timeout = template["WorkerFunction"]["Properties"]["Timeout"]
    visibility = template["AskQueue"]["Properties"]["VisibilityTimeout"]
    assert timeout < budget.STALE_CLAIM_SECONDS < visibility


def _functions() -> dict:
    return {name: r["Properties"] for name, r in _template()["Resources"].items() if r["Type"] == "AWS::Serverless::Function"}


def _actions(properties: dict) -> set:
    found = set()
    for policy in properties.get("Policies", []):
        statements = policy.get("Statement", []) if isinstance(policy, dict) else []
        for statement in statements:
            action = statement["Action"]
            found |= set(action if isinstance(action, list) else [action])
    return found


def test_a_function_that_deletes_a_recording_may_delete_one():
    # moto does not check IAM, so a missing s3:DeleteObject only shows after the deploy (R4-03, R4-04).
    import re
    for name, properties in _functions().items():
        module = properties["Handler"].rsplit(".", 1)[0].replace(".", "/")
        source = (ROOT / "src" / f"{module}.py").read_text(encoding="utf-8")
        if re.search(r"\.delete_object\(|discard_audio\(", source):
            assert "s3:DeleteObject" in _actions(properties), name


# The DynamoDB operations each function's code can reach. A transaction needs the operation of each item in it
# (Put -> PutItem, Update -> UpdateItem, ConditionCheck -> ConditionCheckItem); moto does not check IAM (R4-12).
EXPECTED_DYNAMODB = {
    "AskFunction": {"GetItem", "PutItem", "DeleteItem"},
    "ResultFunction": {"GetItem"},
    "RidesFunction": {"GetItem", "PutItem", "DeleteItem", "Query", "BatchGetItem", "BatchWriteItem", "ConditionCheckItem"},
    "AskEditFunction": {"GetItem", "PutItem", "DeleteItem", "UpdateItem", "BatchGetItem", "ConditionCheckItem"},
    "RecordsFunction": {"Query"},
    "TranscriptionsFunction": {"GetItem", "PutItem", "DeleteItem"},
    "WorkerFunction": {"UpdateItem"},
}


def test_no_function_uses_the_broad_dynamodb_policy_templates():
    # SAM expands DynamoDBCrudPolicy and DynamoDBReadPolicy with Scan and more (R4-12).
    for name, properties in _functions().items():
        for policy in properties.get("Policies", []):
            assert not (isinstance(policy, dict) and {"DynamoDBCrudPolicy", "DynamoDBReadPolicy"} & set(policy)), name


def test_each_function_may_use_the_dynamodb_operations_it_uses_and_no_scan():
    for name, expected in EXPECTED_DYNAMODB.items():
        granted = {a.split(":", 1)[1] for a in _actions(_functions()[name]) if a.startswith("dynamodb:")}
        assert granted == expected, name
    assert all("dynamodb:Scan" not in _actions(p) for p in _functions().values())
