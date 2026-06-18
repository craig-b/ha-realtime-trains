# Services reference

The integration registers four actions (services) under the `realtime_trains` domain. They are enabled by default and are intended for scripts, template triggers and dashboard cards.

## `realtime_trains.get_departures`

Fetch a departure board on demand, independent of any configured entry.

| Field | Type | Required | Description |
|---|---|---|---|
| `account` | entity_id | yes | Any entity from the account whose token should be used. |
| `station` | string | yes | Short or long code (e.g. `CLPHMJN`) — or the full `namespace:code` form (`gb-nr:CLPHMJN`). |
| `time_from` | datetime | no | ISO 8601 start of the query window. Defaults to now. |
| `time_to` | datetime | no | End of the query window. Mutually exclusive with `time_window`. |
| `time_window` | integer | no | Window width in minutes. Defaults to 60. Max 1439. |
| `filter_from` | string | no | Only return trains that previously called here. |
| `filter_to` | string | no | Only return trains that subsequently call here. |
| `detailed` | boolean | no | Enable detailed mode. Requires `allowDetailed`. |
| `limit` | integer | no | Truncate the result list. Default 10. |

Returns a response payload with `services` (a list of objects mirroring the [`next_departure` attributes](entities.md#sensorstation_next_departure)), plus a `query` block containing the parsed window.

```yaml
action: realtime_trains.get_departures
data:
  account: sensor.rtt_api_version
  station: CLPHMJN
  filter_to: WOK
  time_window: 90
```

## `realtime_trains.get_service`

Fetch the full detail of a single service, including formation and Know-Your-Train data where entitled.

| Field | Type | Required | Description |
|---|---|---|---|
| `account` | entity_id | yes | Account entity. |
| `unique_identity` | string | one of | Full ID, e.g. `gb-nr:L01525:2025-10-26`. |
| `headcode` | string | one of | Train reporting identity, e.g. `1L40`. Requires `date`. |
| `date` | date | one of | Departure date from origin. Required with `headcode`. |
| `namespace` | string | no | Defaults to `gb-nr`. |

Returns a `service` object with `schedule_metadata`, `locations`, `origin`, `destination`, `reasons` and (where entitled) `allocation_data`. The schema mirrors the `/gb-nr/service` and `/rtt/service` responses verbatim.

```yaml
action: realtime_trains.get_service
data:
  account: sensor.rtt_api_version
  headcode: 1L40
  date: "2026-06-18"
```

## `realtime_trains.find_station`

Search the cached RTT stops list without going to the network.

| Field | Type | Required | Description |
|---|---|---|---|
| `query` | string | yes | Substring to match against station descriptions or codes. Case-insensitive. |
| `namespace` | string | no | Filter to one namespace. Defaults to your token's first available namespace. |
| `limit` | integer | no | Max results. Default 10. |

Returns `stops` as a list of `{ namespace, description, short_code, unique_identity }`. The stops list is cached for a week and refreshed in the background; the very first call after install will hit `/data/stops` once.

```yaml
action: realtime_trains.find_station
data:
  query: Clapham
  limit: 5
```

## `realtime_trains.refresh_now`

Force an immediate refresh of a specific departure board or service tracker, bypassing the normal polling cadence. Useful before a dashboard is shown.

| Field | Type | Required | Description |
|---|---|---|---|
| `device_id` | string | yes | The device ID of the board or service tracker to refresh. |

Returns `ok: true` on success or raises a service error with a translated message if the underlying poll fails (e.g. rate-limited).

```yaml
action: realtime_trains.refresh_now
data:
  device_id: <your board device id>
```

## Errors

All actions raise Home Assistant service errors with translated messages on failure:

| Translation key | Cause |
|---|---|
| `cannot_connect` | Network or timeout error reaching `data.rtt.io`. |
| `invalid_auth` | Token is no longer valid. Triggers the reauth repair. |
| `rate_limited` | API returned 429. Wait for `Retry-After` and retry. |
| `not_found` | Service or station could not be located. |
| `history_not_allowed` | The requested date is outside your token's `historyRestrictToDays` window. |
| `unknown` | Unexpected response; see logs. |
