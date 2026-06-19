# Supported devices

The integration creates three types of device in the Home Assistant device registry:

## Account device

One per Realtime Trains API token. Named "Realtime Trains". Holds diagnostic sensors (rate limits, API version, entitlements, restrictions).

| Entity | Type | Description |
|---|---|---|
| `sensor.realtime_trains_rate_limit_minute` | number | Per-minute request limit |
| `sensor.realtime_trains_rate_limit_remaining_minute` | number | Per-minute remaining |
| `sensor.realtime_trains_rate_limit_hour` | number | Per-hour limit |
| `sensor.realtime_trains_rate_limit_remaining_hour` | number | Per-hour remaining |
| `sensor.realtime_trains_rate_limit_day` | number | Per-day limit |
| `sensor.realtime_trains_rate_limit_remaining_day` | number | Per-day remaining |
| `sensor.realtime_trains_rate_limit_week` | number | Per-week limit |
| `sensor.realtime_trains_rate_limit_remaining_week` | number | Per-week remaining |
| `sensor.realtime_trains_api_version` | string | API version from `/api/info` |
| `sensor.realtime_trains_entitlements` | string | Comma-separated entitlements |
| `binary_sensor.realtime_trains_history_restricted` | binary | `on` if token has history restriction |
| `binary_sensor.realtime_trains_namespace_restricted` | binary | `on` if token has namespace restriction |

## Departure board device

One per station you add as a subentry. Named after the station (e.g. "Clapham Junction"). Holds departure-slot sensors and board-level binary sensors.

| Entity | Type | Description |
|---|---|---|
| `sensor.<station>_next_departure` | timestamp | Next departure time (realtime if available) |
| `sensor.<station>_departure_1` … `_departure_9` | timestamp | 2nd through 10th departure slots |
| `sensor.<station>_delay` | duration (min) | Delay of next departure |
| `sensor.<station>_live_status` | enum | Live status (approaching, departing, etc.) |
| `binary_sensor.<station>_cancellations` | binary | `on` if any departure is cancelled |
| `binary_sensor.<station>_platform_changes` | binary | `on` if platform changed from planned |

## Service tracker device

One per tracked service. Named after the headcode and date (e.g. "1L40 2026-06-19"). Holds service-level sensors and formation attributes.

| Entity | Type | Description |
|---|---|---|
| `sensor.<headcode>_<date>_departure` | timestamp | Departure from planned origin |
| `sensor.<headcode>_<date>_arrival` | timestamp | Arrival at planned destination |
| `sensor.<headcode>_<date>_delay` | duration (min) | Current running lateness |
| `sensor.<headcode>_<date>_live_status` | enum | scheduled, in_run, completed, cancelled, unknown |
