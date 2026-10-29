"""The time one ask may take, from the moment it is accepted (adr/0014)."""
from datetime import datetime, timedelta, timezone

from lib import budget, clients

T0 = datetime(2026, 10, 16, 3, 0, tzinfo=timezone.utc)


def test_the_deadline_is_110_seconds_after_the_acceptance():
    assert budget.deadline_for(T0) == T0 + timedelta(seconds=110)


def test_the_agent_gets_what_is_left_less_the_margin_for_the_speech():
    # 100 s left to the deadline, 10 s kept for Polly and the writes.
    assert budget.agent_seconds(T0 + timedelta(seconds=110), T0 + timedelta(seconds=10)) == 90


def test_the_lambdas_own_time_limits_it_too():
    deadline = T0 + timedelta(seconds=110)
    # 40 s left in the Lambda, 5 s kept: 35 s, less 10 s for the speech.
    assert budget.agent_seconds(deadline, T0, lambda_ms=40_000) == 25
    # A Lambda with more time left than the deadline does not stretch the deadline.
    assert budget.agent_seconds(deadline, T0, lambda_ms=500_000) == 100


def test_nothing_is_left_after_the_deadline():
    assert budget.agent_seconds(T0, T0 + timedelta(seconds=30)) < budget.MIN_AGENT_SECONDS


def test_the_agent_is_read_for_longer_than_it_may_run():
    assert budget.AGENT_READ_TIMEOUT_SECONDS > budget.DEADLINE_SECONDS - budget.SYNTHESIS_MARGIN_SECONDS


def test_the_agent_client_waits_for_the_agents_own_timeout_error(aws):
    assert clients.agentcore().meta.config.read_timeout == budget.AGENT_READ_TIMEOUT_SECONDS
