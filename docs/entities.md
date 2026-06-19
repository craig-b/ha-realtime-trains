# Entities reference

The integration exposes **timestamp**, **duration**, **enum** and **binary** sensors grouped under devices that mirror how you configured the integration. All entities derive their state from a `DataUpdateCoordinator` so they update atomically on each poll.

## Device model

```
Realtime Trains (account device)        ← account config entry
├── Diagnostic sensors
├── Clapham Junction board (device)     ← departure board config entry
│   ├── sensor.clapham_junction_next_departure
│   ├── sensor.clapham_junction_departure_2 … _departure_N
│   ├── sensor.clapham_junction_delay
│   ├── sensor.clapham_junction_cancellations
│   ├── sensor.clapham_junction_platform_changes
│   └── sensor.clapham_junction_live_status
└── 1L40 2025-10-26 (device)            ← service tracker config entry
    ├── sensor.1l40_2025-10-26_departure
    ├── sensor.1l40_2025-10-26_arrival
    ├── sensor.1l40_2025-10-26_live_status
    └── sensor.1l40_2025-10-26_delay
```

Stations are slugified using Home Assistant's standard slug rules: lowercase, accents stripped, non-alphanumerics to underscores. Multiple-word station names (e.g. "Clapham Junction") produce `clapham_junction`.

## Departure board entities

### `sensor.<station>_next_departure`

The next service's departure as a timestamp sensor. Shows the **advertised** time unless a realtime value is available, in which case the realtime actual/forecast takes priority.

| Attribute | Type | Description |
|---|---|---|
| headcode | string | Train reporting identity (e.g. `1L40`). Available in `gb-nr`. |
| operator | string | Operator code + name (e.g. `SW — South Western Railway`). |
| origin | string | Origin station description(s). |
| destination | string | Destination description(s). |
| platform_planned | string \| null | Planned platform from the schedule. |
| platform_actual | string \| null | Actual or forecast platform once known. |
| delay | int | Delay in minutes (signed; negative = early). |
| status | string | Live status enum, see `live_status` below. |
| cancellation_reason | string \| null | Cancellation reason code, if cancelled at this location. |
| delay_reason | string \| null | Delay reason code, if delayed and detailed mode is enabled. |
| stp | string | STP indicator — `WTT`, `VAR`, `STP`, `CAN`, `VST`, `VVR`, `VCN`. Detailed mode only. |
| unique_identity | string | Full RTT unique ID (e.g. `gb-nr:L01525:2025-10-26`). |
| namespace | string | Operating namespace, e.g. `gb-nr`. |
| mode | string | `TRAIN`, `SHIP`, `BUS`, `SCHEDULED_BUS`, `REPLACEMENT_BUS`. |
| in_passenger_service | bool | Whether the service is currently in passenger service. |
| onboard_facilities | list[string] \| null | Always `null` on a board entity — only populated via the service-tracker flow (requires `allowKnowYourTrain`). |
| formation | list[dict] \| null | Always `null` on a board entity — only populated via the service-tracker flow (requires `allowAllocations`). See [Formation attributes](#formation-attributes). |

### `sensor.<station>_departure_2` … `_departure_N`

Identical schema to `next_departure`. Up to 10 slots per board, configured on the departure board entry.

### `sensor.<station>_delay`

Duration class, in minutes. The delay of the next departure. `native_unit_of_measurement` is `min`, with `suggested_unit_of_measurement` of `min`. Use for threshold automations ("notify me if delay > 5").

### `sensor.<station>_cancellations`

Binary sensor. `on` if any of the configured departure slots is cancelled at this station, `off` otherwise. Use `state_trigger` for a one-line alert.

### `sensor.<station>_platform_changes`

Binary sensor. `on` if the next departure's `platform_actual` differs from `platform_planned`. Resets to `off` when a new service becomes the next departure.

### `sensor.<station>_live_status`

Enum sensor mirroring the RTT `LocationStatus` field, normalised to lowercase:

| State | When |
|---|---|
| `approaching` | Train is approaching the location. |
| `arriving` | Train is arriving at the platform. |
| `at_platform` | Train is stopped at the platform. |
| `depart_preparing` | Train is preparing to depart. |
| `depart_ready` | Train is ready to depart. |
| `departing` | Train is leaving the platform. |

This is the single most automation-friendly sensor — a state change to `at_platform` means "the train is here now".

### Per-station attributes on the device

The station device itself exposes static metadata as device attributes:

- `station_code` — the long code (e.g. `CLPHMJN`).
- `station_description` — the long description (e.g. `Clapham Junction`).
- `namespace` — e.g. `gb-nr`.
- `filter_from` / `filter_to` — the configured filters, if any.

## Service tracker entities

For a tracked service with headcode `1L40` on `2025-10-26`:

### `sensor.<headcode>_<date>_departure`

Timestamp. The tracked service's departure from its **planned origin** (not from your nearest calling point). Use this for "when does this train start its journey".

### `sensor.<headcode>_<date>_arrival`

Timestamp. The tracked service's arrival at its **planned destination**.

### `sensor.<headcode>_<date>_live_status`

Enum. One of the standard service states:

| State | When |
|---|---|
| `scheduled` | Run is planned but has not started. |
| `in_run` | Service has reported at a location and is in progress. |
| `completed` | Service has arrived at its destination. |
| `cancelled` | Entire service is cancelled. |
| `unknown` | RTT has no realtime data and the run is past its scheduled end. |

### `sensor.<headcode>_<date>_delay`

Duration sensor in minutes. Current running lateness of the service computed from `realtimeInternalLateness` / `realtimeAdvertisedLateness` at the most recent reported location.

### Formation attributes

Attached to `sensor.<headcode>_<date>_departure` when `allowAllocations` is set on your token:

| Attribute | Type | Description |
|---|---|---|
| leading_class | string | e.g. `444`. |
| passenger_vehicles | int | Count of passenger-carrying vehicles. |
| allocations | list[dict] | One entry per allocation segment, each with `allocation_index`, `leading_class`, `passenger_vehicles`, `allocation_items`, and `know_your_train_data`. |
| stock_branding | string \| null | Branding of the stock where relevant. |
| know_your_train | dict \| null | Per-coach detail, if `allowKnowYourTrain`. See below. |

### Know-Your-Train attribute

Nested under `know_your_train`:

```json
{
  "stock_branding": "South Western Railway",
  "common_facilities": ["wifi", "power", "toilet", "aircon"],
  "groups": [
    {
      "identity": "444045",
      "group_facilities": ["wifi", "power", "quiet"],
      "vehicles": [
        {
          "coach_letter": "A",
          "is_passenger_vehicle": true,
          "individual_facilities": ["wifi", "power", "wheelchair"]
        }
      ]
    }
  ]
}
```

Exposed verbatim from `/gb-nr/service`'s `allocationData` block.

## Account diagnostic sensors

These diagnostic-category sensors live on the account device and reflect the most recent response from `/api/info` and the rate-limit headers of the last API call:

| Entity | Class | Description |
|---|---|---|
| `sensor.realtime_trains_rate_limit_minute` | number | `X-RateLimit-Limit-Minute`. |
| `sensor.realtime_trains_rate_limit_remaining_minute` | number | `X-RateLimit-Remaining-Minute`. |
| `sensor.realtime_trains_rate_limit_hour` | number | Hour-dimension limit. |
| `sensor.realtime_trains_rate_limit_remaining_hour` | number | Hour-dimension remaining. |
| `sensor.realtime_trains_rate_limit_day` | number | Day-dimension limit. |
| `sensor.realtime_trains_rate_limit_remaining_day` | number | Day-dimension remaining. |
| `sensor.realtime_trains_rate_limit_week` | number | Week-dimension limit. |
| `sensor.realtime_trains_rate_limit_remaining_week` | number | Week-dimension remaining. |
| `sensor.realtime_trains_api_version` | string | Current API version reported by `/api/info` (e.g. `2026-01-18`). |
| `binary_sensor.realtime_trains_history_restricted` | binary | `on` if your token has `historyRestriction: true`. |
| `binary_sensor.realtime_trains_namespace_restricted` | binary | `on` if your token has `namespaceRestriction: true`. |
| `sensor.realtime_trains_entitlements` | string | Comma-separated list of your entitlements, e.g. `allowDetailed, allowAllocations`. |

Diagnostic entities are excluded from the recorder by default; they exist for dashboards and troubleshooting.
