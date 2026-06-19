# Troubleshooting

## Setup fails with "invalid_auth"

Your token was rejected by `/api/info`. Ensure you're using a next-generation API token from [api-portal.rtt.io](https://api-portal.rtt.io), not a legacy `api.rtt.io` key. Both long-life access tokens and refresh tokens are accepted; the integration auto-detects which type you supplied.

## Setup fails with "cannot_connect"

The integration couldn't reach `data.rtt.io`. Check your network connectivity, DNS resolution, and any firewall rules that might block outbound HTTPS to `data.rtt.io`.

## Entities show "unavailable"

1. Check the integration's config entry state in Settings → Devices → Realtime Trains. If it shows "Setup error", check the Home Assistant logs for the specific exception.
2. If the entry is loaded but entities are unavailable, the coordinator's last poll may have failed. Check the logs for `UpdateFailed` messages.
3. If you're being rate-limited, the `sensor.realtime_trains_rate_limit_remaining_minute` entity will show `0`. Wait for the rate limit window to reset.

## Departure board shows no departures

1. Verify the station code is correct (use the `find_station` service to search).
2. Check the time window — if it's late at night, there may be no services in the next 60 minutes. Increase the time window in the subentry options.
3. If using a `filter_from` or `filter_to`, the filter may be too restrictive. Remove filters and retry.

## Service tracker shows "not found"

1. Verify the headcode is correct — the API expects the schedule identity (e.g. `W00001`), not the train reporting identity / headcode (e.g. `1L40`). The subentry flow handles this automatically when you enter a headcode.
2. Verify the date is within your token's history lookback window. Check `binary_sensor.realtime_trains_history_restricted` — if `on`, look up how many days your token allows.
3. The service may not have run on that date (engineering works, cancellation, etc.).

## Rate-limited (HTTP 429)

The API returned 429. Check the rate-limit diagnostic sensors on the account device:
- `sensor.realtime_trains_rate_limit_remaining_minute`
- `sensor.realtime_trains_rate_limit_remaining_hour`
- `sensor.realtime_trains_rate_limit_remaining_day`
- `sensor.realtime_trains_rate_limit_remaining_week`

Reduce your polling intervals or remove boards you no longer need. The rate limit resets automatically on the next window.

## Token classified as refresh token unexpectedly

If your token is being refreshed on every call (visible in logs as `/api/get_access_token` calls), your token may be a refresh token rather than a long-life access token. This is expected behaviour — the refresh token is exchanged for a short-life access token that the client caches until expiry. No action needed.

## Diagnostics

Download a diagnostics dump from the config entry's three-dots menu → Download diagnostics. The dump includes the account's API info, rate-limit snapshot, and per-board/service-tracker coordinator state. All tokens and `Authorization`/`Cookie` headers are redacted.
