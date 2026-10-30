"""The time one ask may take, from the moment it is accepted (adr/0014). Android waits 120 s for the answer; the
Backend and the agent stop earlier, so that a cut-off ask is told to the rider as a failure, not left running."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

# From the acceptance to the written answer.
DEADLINE_SECONDS = 110
# Kept for Polly and the writes after the agent has answered.
SYNTHESIS_MARGIN_SECONDS = 10
# Kept from the worker Lambda's own remaining time.
LAMBDA_MARGIN_SECONDS = 5
# An agent call with less than this is not worth starting.
MIN_AGENT_SECONDS = 5
# The most a transcription may take; a memo or a question is at most a minute of speech.
TRANSCRIBE_SECONDS = 30
# A claim older than this belongs to a worker that is gone: longer than the worker Lambda's own time (120 s), shorter
# than the queue's visibility timeout (180 s), after which the message is delivered again.
STALE_CLAIM_SECONDS = 130
# One read from the agent's stream. Longer than the agent may run, so that the agent's own timeout error is what the
# worker reads, not a socket timeout.
AGENT_READ_TIMEOUT_SECONDS = 105


def deadline_for(received_at: datetime) -> datetime:
    return received_at + timedelta(seconds=DEADLINE_SECONDS)


def agent_seconds(deadline: datetime, now: datetime, lambda_ms: Optional[int] = None) -> float:
    """How long the agent may take: what is left to the deadline, or of the Lambda's time, less the margin for the
    speech. Below MIN_AGENT_SECONDS there is no time for it."""
    left = (deadline - now).total_seconds()
    if lambda_ms is not None:
        left = min(left, lambda_ms / 1000 - LAMBDA_MARGIN_SECONDS)
    return left - SYNTHESIS_MARGIN_SECONDS
