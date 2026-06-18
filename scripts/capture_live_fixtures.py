"""Capture fresh fixtures from the live Realtime Trains API.

Reads a token from the ``RTT_TOKEN`` environment variable and records
``json`` snapshots under ``tests/fixtures/`` for each endpoint the
integration uses. The token is **never** written to disk.

The captured fixtures are committed (the API responses contain no
secrets) and consumed by ``tests/conftest.py`` to mock ``aiohttp`` in
unit tests.

Full implementation arrives in M3. This scaffold refuses to run and
points the user at the implementation note.
"""

import sys


def main() -> int:
    """Refuse to run until the M3 implementation lands."""
    print(
        "capture_live_fixtures is not implemented yet (M3).\n"
        "See IMPLEMENTATION_PLAN.md for the build order.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
