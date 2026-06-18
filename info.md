# Realtime Trains for Home Assistant

Live UK train departures, platform information and per-service tracking in Home Assistant, powered by the Realtime Trains next-generation API.

- Searchable station picker (no CRS/TIPLOC codes to look up)
- Rich departure sensors: delay, cancellations, platform changes, live status enum
- Per-train service tracker with rolling-stock formation and Know-Your-Train facilities
- Smart polling that adapts to live services and respects your API rate limits
- Works with refresh tokens (auto-refresh) and long-life access tokens
- On-demand `get_departures`, `get_service`, and `find_station` actions for scripts and dashboards

## Quick start

1. Register a token at <https://api-portal.rtt.io>.
2. Install via HACS (add this repo as a custom repository, category *Integration*).
3. Restart Home Assistant, then *Settings → Devices & Services → Add integration → Realtime Trains*.

See the [README](README.md) and [docs](docs/) for full documentation.
