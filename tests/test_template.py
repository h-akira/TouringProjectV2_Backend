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
