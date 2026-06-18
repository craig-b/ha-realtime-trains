# FAQ & troubleshooting

## Setup

### "Invalid token" on initial setup

- Confirm the token hasn't expired. Refresh tokens are long-life but not infinite.
- Confirm the token is for the next-generation API at `data.rtt.io`, not the legacy `api.rtt.io` or `secure.realtimetrains.co.uk` portals. The latter are deprecated and this integration does not support them.
- Check for stray whitespace or quotes when pasting. The integration trims whitespace, but a literal quote character at the start will fail.
- If you pasted a refresh token, the integration tries `/api/info`; if that fails it tries `/api/get_access_token`. A genuine refresh token should work — if both fail, the token itself is invalid.

### The config flow shows "rate_limited" during setup

You've hit your token's rate limit. Wait a few minutes and retry. The error message normally includes a `Retry-After` value indicating how long to wait.

### I don't see the station I want in the picker

- The station list is cached locally and refreshed weekly. Force an immediate refresh by calling the `realtime_trains.find_station` action with `query` set to a fragment of the station name; the first call after install refreshes the cache.
- Some locations appear under multiple long codes (e.g. Clapham Junction has five). The picker shows the primary description; selecting any of them works because the API accepts either short or long code.
- Small halts and freight-only locations are not in `/data/stops` (which is *passenger* stops only). For those, switch the board's *advanced* options to *manual code* and type the short/long code directly.

### The config flow says "history_not_allowed"

Your token has `historyRestriction` and you tried to set up a service tracker for a date older than the limit. Either upgrade your token plan or pick a more recent date.

## Operation

### Entities are `unknown` / `unavailable` after setup

- Check the integration's repair issues. A token failure produces a repair with a reauth link.
- Check `sensor.rtt_api_version`. If it's `unknown`, the account coordinator couldn't reach `/api/info` — your Home Assistant may have no internet, or `data.rtt.io` is down.
- Check the rate-limit diagnostic sensors. If `remaining` is 0 for any dimension, the integration is paused pending limit reset.

### The next departure sensor shows the wrong time

The sensor prefers realtime values over scheduled. If a train is running late, the sensor shows the realtime estimate; the planned time is preserved in the `planned_time` attribute. If you want the planned time as the state, use a template sensor:

```yaml
template:
  - sensor:
      - name: "Planned next departure"
        state: "{{ state_attr('sensor.clapham_junction_next_departure', 'planned_time') }}"
```

### The delay sensor shows `unknown` when the train hasn't started

Until a service reports at its origin, the API returns no realtime data. The integration surfaces `unknown` rather than 0, because 0 means "on time" which is a different statement. Once the service reports, `delay` updates within one poll.

### Polling seems to have stopped

The integration backs off aggressively under rate-limit pressure. Check `sensor.rtt_rate_limit_remaining_hour` — if it's near zero, the integration will resume once the limit resets. You can also see this in the integration logs (`realtime_trains` logger).

### A service tracker didn't find my train

- Service tracker is keyed on headcode + departure date **from the train's planned origin**, not from your boarding station. If you're tracking a service that divides or joins, use the headcode of the segment you actually want — the schedule metadata block returned by `get_service` shows you which segment you've retrieved.
- The train may not be in the working timetable for that date (e.g. a special or replacement service). Try the next-day's date if the train runs past midnight.
- Use `realtime_trains.get_service` with the `unique_identity` form for ambiguous cases: `gb-nr:1L40:2026-06-18`.

## Privacy & token

### Where is my token stored?

In Home Assistant's config entry store, which is part of HA's `.storage/` directory. Access is gated by HA's standard permissions. The token is **not** written to any YAML file, log file, or diagnostics download.

### Is my token ever sent anywhere other than `data.rtt.io`?

No. The integration talks only to `data.rtt.io`. There is no analytics, telemetry, or shared proxy. Each user runs their own copy of the integration against their own token.

### I shared my diagnostics download — does it contain my token?

No. Diagnostics replaces the token with `****` and strips `Authorization` / `Cookie` headers from any cached API response. The download is safe to attach to a GitHub issue.

### I think my token has been compromised

- Revoke it at <https://api-portal.rtt.io> and issue a new one.
- Run the reauth flow on the integration to replace the token. Your monitored items (boards, service trackers) are preserved.
- Check the integration's logs for any 401 responses — those indicate RTT revoked the token.

## Performance

### Can I monitor many stations?

Yes. The integration serialises polls across all boards on the same account to avoid bursting against your rate limit. With the default 90-second interval and ~5 boards, you'll make ~3 requests per minute outbound — well within personal-tier limits. If you exceed the limit, the integration relaxes polling automatically.

### The integration is using too many API calls

- Reduce the configured `polling_interval` cadence on each board (minimum 30 s).
- Reduce the number of slots — each additional slot does not add a call, but more boards do.
- Use the service tracker sparingly — a tracked live service polls every 30 s.

### Can I turn off the rate-limit diagnostic sensors?

They're marked as diagnostic category, so they don't appear on the dashboard by default and aren't recorded by the recorder if you have `exclude_domains` or similar in your recorder config. There's no toggle to disable them outright — they're cheap (no API calls) and necessary for the integration's own rate-limit handling.

## Compatibility

### Which Home Assistant versions are supported?

2025.8.0 and newer. The integration uses the `runtime_data` config entry pattern and the modern entity description sensor model, both stabilised in that version.

### Can I install this without HACS?

You can, by copying `custom_components/realtime_trains/` into your `custom_components/` directory and restarting Home Assistant. HACS is recommended for upgrades.

### Will this be added to Home Assistant core?

The integration is built to core's platinum quality bar with that path in mind. The constraint is HA core's preference that integrations consume a published PyPI library rather than an in-tree API client; before proposing to core we'd extract `api.py` and `models.py` into a `pyrealtimetrains` package and add it to the manifest's `requirements`. The internal structure is already set up for that extraction.

### Is this affiliated with Realtime Trains?

No. This is an independent client of the public API and is not affiliated with or endorsed by Realtime Trains. Data © Realtime Trains.
