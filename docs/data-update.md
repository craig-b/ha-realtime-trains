# Data update

The integration polls the Realtime Trains API on a fixed schedule. There is no push/websocket mechanism — all data is fetched via HTTP GET requests to `https://data.rtt.io`.

## Polling cadence

| Component | Interval | Endpoint |
|---|---|---|
| Account coordinator | 60 minutes | `/api/info` |
| Departure board | 90 seconds (configurable, 30–3600s) | `/gb-nr/location` or `/rtt/location` |
| Service tracker (scheduled) | 15 minutes | `/gb-nr/service` |
| Service tracker (in run) | 30 seconds | `/gb-nr/service` |
| Service tracker (terminal) | 1 hour | `/gb-nr/service` |

The service tracker cadence adapts automatically: when the API reports a `LocationStatus` other than `None`, polling switches to 30-second intervals. When the service is cancelled or completed, it drops to hourly.

## Rate limiting

The API enforces per-minute, per-hour, per-day and per-week rate limits via `X-RateLimit-*` headers. The client captures these on every response and exposes them as diagnostic sensors on the account device. If a 429 is returned, the client raises `RttRateLimitError` which surfaces as an `UpdateFailed` — HA retries on the next scheduled poll.

## Stops cache

The `/data/stops` response (the full list of UK passenger stops) is cached for 7 days. It is refreshed on first use after the cache expires — either when a departure-board subentry flow searches for a station, or when the `find_station` service is called. The cache is not refreshed on the account coordinator's polling schedule.

## Token refresh

If the supplied token is a refresh token (detected on the first `/api/info` call), the client automatically calls `/api/get_access_token` to mint a short-life access token. The access token is refreshed 60 seconds before its `validUntil` expiry. No user intervention is required.
