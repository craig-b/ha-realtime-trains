# Known limitations

## History restriction

Some tokens have `historyRestriction: true`, which limits lookback to `historyRestrictToDays` days. The integration surfaces this as a `binary_sensor.realtime_trains_history_restricted` diagnostic entity. If you query a service with a date outside your lookback window, the API returns a 400 error.

## Namespace restriction

Some tokens have `namespaceRestriction: true`, restricting access to one namespace. The integration surfaces this as a `binary_sensor.realtime_trains_namespace_restricted` diagnostic entity. If your token is restricted, you can only query the namespace(s) listed in your credentials.

## No formation data on departure boards

The `/gb-nr/location` endpoint does not return rolling-stock formation or Know-Your-Train data. These are only available via the service-tracker flow (`/gb-nr/service`), and only if your token has the `allowAllocations` and `allowKnowYourTrain` entitlements. Departure-board entities therefore expose no formation or Know-Your-Train attributes.

## Entitlement-gated features

| Feature | Required entitlement |
|---|---|
| Detailed mode (internal times, STP indicators) | `allowDetailed` |
| Rolling-stock formation data | `allowAllocations` |
| Per-coach Know-Your-Train data | `allowKnowYourTrain` |
| Full allocation listing | `allowFullAllocationListing` |

If your token lacks an entitlement, the corresponding attributes are `null` and the service-tracker detail response omits the relevant blocks.

## API rate limits

The API enforces per-minute, per-hour, per-day and per-week request limits. If you configure many departure boards with short polling intervals, you may hit the rate limit. The rate-limit diagnostic sensors on the account device show your current usage. When rate-limited (HTTP 429), the board and service-tracker coordinators widen their poll interval before the next attempt — honouring the API's `Retry-After` hint when present, otherwise doubling the interval (capped at 3600 s). The configured cadence is restored after the next successful poll.

## No push notifications

All data is polled. There is no websocket or webhook mechanism. The minimum polling interval is 30 seconds (configurable per board). Realtime updates may lag by up to one polling interval.

## Single namespace per token

The integration defaults to the `gb-nr` (Network Rail) namespace for all queries. Generic-namespace boards (`/rtt/location`) are supported but the departure-board subentry flow does not expose a namespace selector — all boards are created under `gb-nr`.

## No offline mode

The integration requires network connectivity to `data.rtt.io`. When the network is unavailable, entities show `unavailable` until connectivity is restored.
