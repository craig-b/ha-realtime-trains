# Use cases

## Commuting

Add a departure board for your home station and your destination station. Use the `next_departure` timestamp sensor to trigger a notification 15 minutes before your train departs. Use the `delay` sensor to get an early warning when your train is running late.

## Platform alerts

Add a departure board for your usual station. Use the `binary_sensor.<station>_platform_changes` entity in a state-trigger automation to get a phone notification when your train's platform changes from the advertised one.

## Cancellation alerts

Add a departure board for your station. Use `binary_sensor.<station>_cancellations` to trigger a notification when any tracked departure is cancelled, so you can plan alternative transport.

## Service tracking

Track a specific service by headcode and date. The `live_status` enum sensor transitions through `scheduled` → `in_run` → `completed` as the service progresses. Use this to trigger automations when the train starts its run, or when it arrives at its destination.

## Formation data

If your token has `allowAllocations` and `allowKnowYourTrain` entitlements, the service-tracker departure entity exposes rolling-stock formation data as attributes: `leading_class`, `passenger_vehicles`, `allocations` (one entry per allocation segment), and `know_your_train` (per-coach facilities including wifi, power, wheelchair accessibility).

## Rate-limit monitoring

Use the account device's rate-limit sensors in a template sensor or gauge card to visualise your API usage. Alert yourself when any remaining counter drops below a threshold.

## On-demand queries

Use the `realtime_trains.get_departures` service in scripts to fetch a board on demand without configuring a permanent departure-board subentry. Use `realtime_trains.get_service` to look up a service's full detail (including formation) on demand.
