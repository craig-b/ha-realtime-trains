# Getting started

This walk-through takes you from a fresh Home Assistant install to a populated Realtime Trains dashboard.

## 1. Get an API token

You need a Realtime Trains next-generation API token. These are free for personal, non-commercial use from the API portal: <https://api-portal.rtt.io>.

You will receive **either** a long-life access token **or** a refresh token. The integration detects which and handles refreshes transparently. See [API credentials](api-credentials.md) for details and entitlements.

> [!IMPORTANT]
> Treat your token like a password. You'll paste it into the config flow UI during setup; it is then stored encrypted in Home Assistant's config entry store and never written to YAML.

## 2. Install the integration via HACS

1. In HACS → *Settings* → *Custom repositories*, add the URL of this repository with category **Integration**.
2. In HACS → *Integrations*, search for **Realtime Trains** and install.
3. Restart Home Assistant.

## 3. Add your account

*Settings → Devices & Services → Add integration → Realtime Trains.*

The first step creates your **account** config entry:

| Field | Description |
|---|---|
| Token | Your Realtime Trains API token. Refresh tokens and long-life access tokens are both accepted. |
| Default number of departures | How many upcoming departures each departure board exposes by default (1–10). |

On submit, the integration calls `/api/info` to validate the token and reads back your entitlements. The next screen confirms what your key can do, e.g.:

> ✅ Detailed mode · Allocation data · Know-Your-Train · History lookback: 14 days · Namespaces: gb-nr

If the token is invalid, expired, or rate-limited, the flow returns a translated error and stays on the form.

## 4. Add monitored items

Your account entry creates a **device** with the account-level diagnostic entities (rate-limit sensors, etc.). To get departures, add sub-entries:

### Departure board

From the Realtime Trains device page → *Add departure board*.

| Field | Description |
|---|---|
| Station | Type-to-search picker backed by the cached RTT stops list. |
| Filter *from* | Optional. Only show trains that previously called at this station (e.g. "trains from Waterloo"). |
| Filter *to* | Optional. Only show trains that subsequently call at this station (e.g. "trains to Woking"). |
| Time window | Width of the look-ahead window in minutes (15–1440, default 60). |
| Slot count | Number of departure sensors to expose (1–10). Overridden by the account default if left blank. |
| Detailed mode | Toggle internal times and STP indicators. Requires the `allowDetailed` entitlement. |
| Polling interval | Seconds between polls (30–3600, default 90). |

Each departure board is its own device, grouped under the account.

### Service tracker

From the Realtime Trains device page → *Add service tracker*.

| Field | Description |
|---|---|
| Headcode | The train's reporting identity, e.g. `1L40`. Required unless *Unique identity* is provided. |
| Date | The departure date of the service from its planned origin. Defaults to today. |
| Unique identity | Optional alternative — the full `namespace:identity:date` string. |

The service tracker polls every 15 minutes by default while the service is scheduled but not yet running, switches to every 30 seconds once the service is in run, and drops to hourly once it completes or is cancelled.

## 5. Use it

You'll now have entities like:

- `sensor.clapham_junction_next_departure` — timestamp of the next train
- `sensor.clapham_junction_departure_2` … `_departure_5`
- `sensor.clapham_junction_delay` — the next train's delay in minutes
- `sensor.clapham_junction_cancellations` — `on` if the next train is cancelled
- `sensor.clapham_junction_live_status` — `scheduled` / `approaching` / `arriving` / `at_platform` / `departing`
- `sensor.clapham_junction_platform_changes` — `on` if the next train's platform changed from its planned value

See [Entities reference](entities.md) for the full list and attributes. See [Automation recipes](automation-recipes.md) for ready-to-paste automations.

## 6. Optional: add to a dashboard

A typical Lovelace card combining the next departure with its attributes:

```yaml
type: entity
entity: sensor.clapham_junction_next_departure
name: Next train
unit: ''
icon: mdi:train
```

For multi-departure timelines, an [Entities card](https://www.home-assistant.io/dashboards/entities/) listing `sensor.<station>_departure_N` works well.

## 7. Optional: enable services

The `realtime_trains.get_departures`, `realtime_trains.get_service`, `realtime_trains.find_station` and `realtime_trains.refresh_now` actions are enabled by default. See [Services reference](services.md).

## Reauth & repairs

If your token is revoked or expires, the integration raises a repair issue and offers a reauth flow that reuses your existing monitored items. Replacing the token does not require deleting boards.
