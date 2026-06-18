# AGENTS.md

Guidance for opencode and other code agents working in this repository.

## What this is

A Home Assistant custom integration for the Realtime Trains next-generation API
(`https://data.rtt.io`). Distributed via HACS. The integration lives in
`custom_components/realtime_trains/`. The API client is **in-tree** (no PyPI
dependency) so HACS users install with zero pip friction.

## Layout

```
custom_components/realtime_trains/   # the integration
  __init__.py  config_flow.py  coordinator.py  const.py  sensor.py
  services.py  services.yaml   models.py  api.py  diagnostics.py
  manifest.json  strings.json  icons.json  translations/en.json
docs/                                # user & contributor docs
tests/                               # pytest + syrupy snapshots
scripts/                             # capture_live_fixtures.py
```

## Reference materials

- API spec: https://github.com/realtimetrains/api-specification (`specification/main.yml`)
- HA core integration patterns: https://github.com/home-assistant/core (`homeassistant/components/`)
- Reference integration to imitate: `swiss_public_transport` (config_flow +
  DataUpdateCoordinator + CoordinatorEntity + entity_description model).
- HA contributor guide: https://github.com/home-assistant/core/blob/dev/CLAUDE.md
  (Python 3.14 assumed; PEP 649 lazy annotations allowed; no pointless
  restate-comments).

## Quality bar

The integration is built to a **platinum** quality scale (see
`manifest.json` `quality_scale`). That means:

- `config_flow: true`, `integration_type: service`, `iot_class: cloud_polling`.
- `runtime_data` pattern on the config entry (no `hass.data` mutation).
- Errors translated via `ConfigEntryError` / `ConfigEntryNotReady` with
  `translation_domain` + `translation_key`.
- Diagnostics platform with **token redaction**.
- Tests use pytest + syrupy; entity snapshots under `tests/snapshots/`.
- No `hass.data` reads in entity code; everything flows through the coordinator.

## Commands

Run from the repo root against a checked-out Home Assistant core (typically
cloned alongside this repo):

```bash
# Lint / format / type (run on HA core with this integration mounted in custom_components)
uv run prek run --all-files             # ruff + black + mypy + hassfest

# Tests
uv run pytest tests/

# hassfest (validates manifest.json etc.)
python -m script.hassfest

# Capture fresh fixtures from the live API (token from env, never committed)
RTT_TOKEN=xxxx scripts/capture_live_fixtures.py
```

If lint/type/test commands differ when concretised, prefer the ones from
the HA core contributor guide and update this file.

## Conventions

- Entity IDs: `sensor.<station_slug>_next_departure`,
  `sensor.<station_slug>_departureN`, `sensor.<headcode>_<date>_<kind>`.
- Unique IDs: derived from immutable API data (e.g.
  `gb-nr:CLPHMJN:departure:0`), never from user input alone.
- Tokens: never log, never print, never commit. Diagnostics redacts the
  bearer token and any `Authorization` / `Cookie` headers in cached responses.
- API errors raised as typed exceptions (`RttAuthError`, `RttConnectionError`,
  `RttRateLimitError`, `RttNotFoundError`) and mapped at the coordinator level
  to `UpdateFailed` / `ConfigEntryNotReady` / `ConfigEntryError`.
- No restating comments. Comments explain *why*, not *what*.
- Every new public string goes through `strings.json` with a translation key;
  `translations/en.json` is generated from it.

## Things that are deliberately not done

- No public proxy of the RTT API. Each user uses their own token for their
  own home server. This matches the "server-side application" clause in the
  RTT API spec.
- No bundled shared token, ever.
- No support for the deprecated `api.rtt.io` or
  `secure.realtimetrains.co.uk` services.
