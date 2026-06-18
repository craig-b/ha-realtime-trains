# Realtime Trains for Home Assistant

A Home Assistant integration for the [Realtime Trains](https://www.realtimetrains.co.uk) next-generation API (`data.rtt.io`). Brings live UK train departures, platform information, formation data and per-service tracking into Home Assistant, with sensible defaults, deep attributes for dashboards, and one-line automation triggers for the things people actually want to know.

> "Has my train been cancelled? Has the platform changed? Is it running late?
> Is it at the platform yet?" — answered without leaving Home Assistant.

## Highlights

- **Searchable station picker.** Pick a station by name ("Clapham Junction") — no CRS or TIPLOC codes required. The integration caches the full RTT station list and exposes it through a type-to-search `SelectSelector` in the config flow.
- **Rich departure sensors.** Each monitored station exposes the next *N* departures as timestamp sensors plus dedicated sensors for delay, cancellations, platform changes, and a live status enum (`scheduled` / `approaching` / `arriving` / `at_platform` / `departing`).
- **Service tracker.** Follow a single train by headcode (e.g. `1L40`) and date — useful for "the train I'm meeting someone off" or for observing a journey you're about to make.
- **Know-Your-Train & formation.** Where the API key is entitled, rolling-stock formation, coach letters, per-coach facilities (wifi, power, quiet, toilet, wheelchair, buffet, …), leading class and stock branding are exposed as attributes.
- **Token-aware.** Surfaces the entitlements returned by `/api/info` and respects `historyRestriction` / `historyRestrictToDays` / `namespaceRestriction` so the integration never wastes requests on disallowed queries.
- **Rate-limit aware.** Reads `X-RateLimit-Limit-*` / `X-RateLimit-Remaining-*` headers on every response, exposes them as diagnostic sensors, and serialises polls across all monitored boards under one account so a multi-station setup never bursts against the limit.
- **Smart polling.** Boards poll on a configurable cadence (default 90 s). When a tracked service is live, the cadence adapts; when services are off-run / cancelled / far in the future, the cadence relaxes.
- **Services (actions).** `realtime_trains.get_departures`, `realtime_trains.get_service`, `realtime_trains.find_station` and `realtime_trains.refresh_now` give scripts and dashboards on-demand lookups.
- **Translations & diagnostics.** Full English translations, a `diagnostics` download with redacted tokens for support, and a repair flow when a token expires or is revoked.

## Quick start

1. Register for an API token at <https://api-portal.rtt.io>. See [API credentials](docs/api-credentials.md).
2. Install via HACS: add this repository as a custom repository (category *Integration*), then install **Realtime Trains**.
3. Restart Home Assistant.
4. *Settings → Devices & Services → Add integration → Realtime Trains*.
5. Paste your token. The integration validates it against `/api/info` and shows your entitlements before saving.
6. Add **Departure board** or **Service tracker** sub-entries from the integration's device page.

Detailed walk-through: [Getting started](docs/getting-started.md).

## Documentation

- [Getting started](docs/getting-started.md)
- [API credentials](docs/api-credentials.md)
- [Entities reference](docs/entities.md)
- [Services reference](docs/services.md)
- [Automation recipes](docs/automation-recipes.md)
- [Architecture](docs/architecture.md)
- [FAQ & troubleshooting](docs/faq.md)

## Requirements

- Home Assistant 2025.8.0 or newer.
- A Realtime Trains next-generation API token from <https://api-portal.rtt.io>. The legacy `api.rtt.io` and `secure.realtimetrains.co.uk` endpoints are deprecated and not supported.

## Token handling

This integration is server-side software running on the user's own Home Assistant instance. The RTT token is stored in Home Assistant's encrypted config entry store and is **only ever sent to `data.rtt.io`**. No token is shipped with the integration, and no traffic is proxied through any third-party service. See [API credentials](docs/api-credentials.md) for the rationale.

## License

MIT — see [LICENSE](LICENSE). Data © Realtime Trains; this integration is an independent client and is not affiliated with Realtime Trains.
