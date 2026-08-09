"""Polling helper used by the outbox tests."""

import time

POLL_INTERVAL = 0.05
MAX_POLLS = 40


def wait_until_drained(outbox) -> None:
    """Block until `outbox` reports that it has drained.

    Polls at POLL_INTERVAL and gives up after MAX_POLLS attempts.
    """
    for _ in range(MAX_POLLS):
        time.sleep(POLL_INTERVAL)
        if outbox.is_drained():
            return
    raise TimeoutError("outbox did not drain within the poll budget")
