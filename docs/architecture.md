# Architecture

This document describes how the integration is structured internally. It is intended for contributors and for anyone curious about why the code looks the way it does.

## Top-level structure

```
custom_components/realtime_trains/
  __init__.py          # async_setup_entry, runtime_data pattern
  manifest.json        # HA manifest (domain, quality_scale, config_flow, etc.)
  config_flow.py      # Account + monitored-item config flows, reauth
  coordinator.py      # DataUpdateCoordinator(s)
  api.py               # In-tree API client
  models.py            # Typed dataclass models for API responses
  sensor.py            # SensorEntity + SensorEntityDescription definitions
  services.py          # Action handlers (get_departures, get_service, ...)
  services.yaml        # Service schemas
  diagnostics.py       # Diagnostics platform with token redaction
  const.py             # Constants (CONF_*, DOMAIN)
  strings.json         # Translation keys
  icons.json           # Per-state icons
  translations/en.json # Generated from strings.json
```

```
tests/
  fixtures/                     # Captured live API responses
    location_clapham_junction.json
    service_1L40_2025-10-26.json
    stops_list.json
    api_info.json
  snapshots/                    # syrupy entity snapshots
  conftest.py
  test_api.py
  test_config_flow.py
  test_coordinator.py
  test_sensor.py
  test_services.py
  test_diagnostics.py
```

```
scripts/
  capture_live_fixtures.py      # reads RTT_TOKEN from env, records fixtures
```

## Config flow model

The integration uses **two config entry types**: an *account* entry (the user's token and account-level defaults) and *monitored-item* entries (departure boards and service trackers). The account entry is the parent; monitored items reference the account entry through a config entry link so a single token refresh serves everything.

### Account entry

```
User step: token + default slot count
  → validate via /api/info
  → store entitlements, historyRestriction, namespacesAvailable in entry.data
  → sub-entries register themselves via runtime_data.coordinator
```

### Departure board entry

```
User step 1: station (type-to-search via /data/stops), filter_from, filter_to
  → selection cached for re-display on retry
User step 2 (advanced): time_window, slot_count, detailed, polling_interval
```

### Service tracker entry

```
User step: headcode + date (or unique_identity)
  → fetch service once via /gb-nr/service to verify it exists
  → derive unique_id from the returned uniqueIdentity (not user input)
```

### Reauth

A reauth flow is triggered when the account coordinator reports `invalid_auth` during a poll. The flow replaces the token in-place (preserving the entry's monitored items) and triggers a forced refresh of every child coordinator.

### Migrations

Config entry versions are bumped on schema changes. `async_migrate_entry` performs in-place updates to `entry.data` only; entity registries are migrated separately if unique IDs need to change.

## Coordinator model

Two coordinator types share polling logic:

### `RealtimeTrainsAccountCoordinator`

- Owns the API client and the cached `/data/stops` list.
- Runs `/api/info` on a slow cadence (60 min) to refresh entitlements and API version.
- Exposes rate-limit diagnostic data as `coordinator.data.rate_limits`.
- Holds a reference to each monitored-item coordinator so it can introspect aggregate rate-limit pressure.

### `RealtimeTrainsBoardCoordinator` / `RealtimeTrainsServiceCoordinator`

Each per-device coordinator polls the API on its own cadence but **delegates the actual HTTP call** to the account coordinator's API client. The account coordinator uses a mutex to serialise requests so concurrent polls from multiple boards are spaced out by minimum ~1 s.

Polling cadence is dynamic:

| Situation | Poll interval |
|---|---|
| Board, no realtime data yet (far-future services) | `polling_interval * 4` |
| Board, standard polling | configured `polling_interval` (default 90 s) |
| Board, any service in window is live | `polling_interval / 2` |
| Service tracker, scheduled (no realtime) | 15 min |
| Service tracker, in_run | 30 s |
| Rate-limit pressure < 10 % remaining (most constrained dim) | Relax to `polling_interval * 3` minimum |
| `429 Too Many Requests` with `Retry-After` | Respect header |

All coordinators extend `DataUpdateCoordinator[T]` and surface errors as:

| API exception | HA exception |
|---|---|
| `RttAuthError` | `ConfigEntryError` with `translation_key=invalid_auth` (also raises repair) |
| `RttRateLimitError` | `UpdateFailed` with `translation_key=rate_limited` |
| `RttConnectionError` | `ConfigEntryNotReady` / `UpdateFailed` with `translation_key=cannot_connect` |
| `RttNotFoundError` | `UpdateFailed` with `translation_key=not_found` |
| `RttError` | `UpdateFailed` with `translation_key=unknown` |

## API client

The client lives in `custom_components/realtime_trains/api.py`. It is a plain `class RealtimeTrainsApi` with an injected `aiohttp.ClientSession` (no PyPI dependency, no global state). It:

- Sends the `Authorization: Bearer <token>` header.
- Sends the optional `Version` header pinned to the API version known to work with this integration (recorded in `const.py`).
- Captures rate-limit headers on every response into `self.rate_limits`.
- Handles refresh tokens: calls `/api/get_access_token` and caches `(token, valid_until)`. On the next call, if `valid_until` is < 60 s away, refreshes first.
- Raises typed exceptions on non-2xx responses (mapped from status + JSON `error` field).
- Provides typed return values: `get_location() -> LocationLineup`, `get_service() -> ServiceDetail`, `get_info() -> ApiInfo`, etc. These are dataclasses defined in `models.py`, not raw dicts — the coordinator and entity layers never peek into dict shapes.

The client is **flat** — no inheritance, no ABCs. The typed return values are `@dataclass(slots=True, frozen=True)` classes derived directly from the OpenAPI schemas.

## Models

`models.py` mirrors the OpenAPI components one-for-one:

- `GeographicLocation`, `LocationMetadata`, `NetworkRailLocationMetadata`
- `IndividualTemporalData`, `LocationTemporalData`
- `LocationPair`, `LocationLineUp`, `NetworkRailLocationLineUp`
- `ScheduleMetadata`, `NetworkRailScheduleMetadata`
- `ReasonBlock`, `LocationReasonContainer`
- `ServiceLocations`, `NetworkRailServiceLocations`
- `AssociatedService`, `AssociationData`
- `NetworkRailAllocation`, `NetworkRailAllocationItem`
- `KnowYourTrainDataGroup`, `KnowYourTrainFacilityList`
- `SystemStatus`, `LocationCallType`, `LocationDisplayAs`, `LocationStatus`
- `EntitlementList`, `ApiInfo`

Parsing is one-shot from `dict[str, Any]` to the typed class with explicit null handling — the spec marks several fields nullable, and we surface those as `T | None` rather than sentinel values.

## Entity layer

Entities follow the `swiss_public_transport` pattern: a tuple of `SensorEntityDescription` instances, a single `CoordinatorEntity` subclass, and a `value_fn` on the description that picks the value from coordinator data.

```python
@dataclass(kw_only=True, frozen=True)
class RealtimeTrainsSensorEntityDescription(SensorEntityDescription):
    value_fn: Callable[[BoardData], StateType | datetime]
    slot: int = 0
```

Entities pull everything from `self.coordinator.data`; no `hass.data` reads. Unique IDs are derived from immutable API data — e.g. `gb-nr:CLPHMJN:departure:0` for the first slot of a Clapham Junction board — so reloading/restoring a config entry re-attaches to the same entity history.

### State icons

Per-state icons (e.g. `mdi:train-alert` for cancelled, `mdi:train-car` for at-platform) are declared in `icons.json` keyed by `state`. No `if/else` icon logic in entity code.

## Services

`services.py` defines the action handlers referenced by `services.yaml`. Each handler:

- Resolves the account from the `account` entity id (looks up which config entry owns it via the entity registry).
- Calls the API client directly (no round-trip through the coordinator) for on-demand queries.
- Surfaces errors as `ServiceValidationError` with `translation_domain=DOMAIN` + `translation_key`.
- Returns a plain `dict` payload — no custom response types — so templates can index into it.

`find_station` is the exception: it hits the account coordinator's cached stops list and does not call the API at all (except for the weekly refresh).

## Diagnostics

`diagnostics.py` implements the standard HA diagnostics platform. The payload is:

- The config entry data, with the bearer token redacted (`****`).
- The most recent API response cached by the coordinator, with any `Authorization` and `Cookie` headers stripped.
- The current rate-limit snapshot (limits only — no tokens appear in rate limits).

This is what users attach to bug reports. It contains everything needed to reproduce an issue, nothing secret.

## Testing

Tests are pytest + syrupy, mirroring the HA core test suite:

- `tests/fixtures/*.json` — captured live responses. `scripts/capture_live_fixtures.py` populates these by calling each endpoint with a real token and recording the JSON. The token is never written to disk.
- `tests/conftest.py` — `aiohttp` mock fixture that serves the recorded JSON for each URL pattern.
- `tests/snapshots/*.ambr` — entity snapshot golden files.
- Entity tests assert against the snapshot, not against individual attribute keys — when the API model grows, the snapshot diff surfaces exactly what changed.

`scripts/capture_live_fixtures.py` reads the token from `RTT_TOKEN` env var and refuses to run if it's missing.

## CI

GitHub Actions workflows run on every push and PR:

- `hassfest` — validates `manifest.json` and integration metadata.
- `hacs` — validates repository structure for HACS distribution.
- `pytest` — runs the test suite against pinned HA core.
- `ruff` / `black` / `mypy` — quality checks.

The `hassfest` and HACS workflows gate releases; the `pytest` and lint workflows gate merges.
