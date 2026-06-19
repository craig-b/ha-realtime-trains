"""Pytest configuration for the Realtime Trains integration.

Most test files are split into two flavours:

* Pure-Python (``test_models``, ``test_api``, ``test_fixtures``,
  ``test_live_api``) — load modules via ``importlib`` so they run
  without Home Assistant installed.
* Integration tests (``test_coordinator``, ``test_sensor_entities``,
  ``test_services``, ``test_diagnostics``, ``test_config_flow``) — these
  use ``pytest.importorskip("homeassistant")`` so they skip cleanly in
  local dev without HA. **In CI they MUST run** (HA is mounted by the
  workflow), so a ``pytest_sessionfinish`` hook below fails the run if
  any non-live test was skipped while the ``CI`` env var is set.

The live-API tests (``test_live_api.py``) are the only ones allowed to
skip — they need a real RTT token set via ``RTT_TOKEN``. They are
deselected by default via ``-m 'not live'`` in ``pyproject.toml``; run
them explicitly with::

    RTT_TOKEN=xxxx uv run pytest tests/test_live_api.py -m live -v
"""

from __future__ import annotations

import os

import pytest


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Fail the run if any tests were skipped in CI (excluding ``live``)."""
    if not os.environ.get("CI"):
        return

    # ``terminalreporter.stats`` is populated by the time this hook runs.
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return

    skipped_tests = reporter.stats.get("skipped", [])
    non_live_skipped: list[str] = []
    for report in skipped_tests:
        location = getattr(report, "location", ("", "", None))
        path = location[0] if location else ""
        # Live-API tests are allowed to skip when no token is set.
        if "test_live_api" in path:
            continue
        # Format the test id for the error message
        non_live_skipped.append(report.nodeid)

    if non_live_skipped:
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
        # Stash them so the workflow summary can pick them up.
        os.environ["RTT_SKIPPED_TESTS_IN_CI"] = ",".join(non_live_skipped)
        msg = (
            f"\n\n::error::{len(non_live_skipped)} test(s) skipped in CI "
            "environment — tests must not be skipped in CI. Skipping is "
            "only allowed for live-API tests without a token.\nSkipped:\n  "
            + "\n  ".join(non_live_skipped)
            + "\n"
        )
        # Reporter may not be flushed yet; print directly too.
        print(msg)
