# Automation recipes

Copy-paste automations for common scenarios. All recipes assume you have a departure board configured at your station (recipe entity ids use `clapham_junction` as an example slug — substitute your own station).

## Notify me when the next train is delayed by more than 5 minutes

Uses the dedicated `delay` sensor as a numeric state trigger.

```yaml
alias: "Train delay alert"
trigger:
  - platform: numeric_state
    entity_id: sensor.clapham_junction_delay
    above: 5
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "Train delayed"
      message: >
        Next train from Clapham Junction is {{ trigger.to_state.state }} min late.
        Platform {{ state_attr('sensor.clapham_junction_next_departure', 'platform_actual') }}
        at {{ trigger.to_state.state | as_timestamp | timestamp_custom('%H:%M') }}.
```

## Notify me when my train is at the platform

The `live_status` enum sensor changes to `at_platform` the moment the train pulls in. Great for "leave the house now".

```yaml
alias: "Train at platform"
trigger:
  - platform: state
    entity_id: sensor.clapham_junction_live_status
    to: at_platform
    for: 0:00:30
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "Train at platform"
      message: >
        Your {{ state_attr('sensor.clapham_junction_next_departure', 'destination') }}
        service is at platform {{ state_attr('sensor.clapham_junction_next_departure', 'platform_actual') }}.
```

The 30-second `for` guard avoids spurious notifications on momentary intermediate states.

## Notify me when the platform changes

The `platform_changes` binary sensor flips to `on` whenever the actual platform differs from the planned one.

```yaml
alias: "Platform change"
trigger:
  - platform: state
    entity_id: binary_sensor.clapham_junction_platform_changes
    to: "on"
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "Platform change"
      message: >
        Train to {{ state_attr('sensor.clapham_junction_next_departure', 'destination') }}
        now departs platform {{ state_attr('sensor.clapham_junction_next_departure', 'platform_actual') }}
        (planned {{ state_attr('sensor.clapham_junction_next_departure', 'platform_planned') }}).
```

## Notify me when the next train is cancelled

```yaml
alias: "Train cancelled"
trigger:
  - platform: state
    entity_id: binary_sensor.clapham_junction_cancellations
    to: "on"
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "Train cancelled"
      message: >
        The {{ state_attr('sensor.clapham_junction_next_departure', 'headcode') }}
        to {{ state_attr('sensor.clapham_junction_next_departure', 'destination') }}
        is cancelled.
        {{ state_attr('sensor.clapham_junction_next_departure', 'cancellation_reason') }}
```

## Conditional dashboard refresh

Refresh a board immediately before showing the dashboard, then let polling take over:

```yaml
alias: "Refresh board on dashboard open"
trigger:
  - platform: event
    event_type: lovelace_updated
condition:
  - condition: template
    value_template: "{{ trigger.event.data.view_path in ['trains', 'commute'] }}"
action:
  - action: realtime_trains.refresh_now
    data:
      device_id: <your board device id>
```

## Countdown to next departure

A template sensor showing minutes to departure, useful in dashboards and conditions:

```yaml
template:
  - sensor:
      - name: "Minutes to next train"
        icon: mdi:train-clock
        unit_of_measurement: min
        state: >
          {% set dep = states('sensor.clapham_junction_next_departure') %}
          {% if dep in ['unknown', 'unavailable'] %}{{ dep }}
          {% else %}
            {{ ((as_timestamp(dep) - now().timestamp()) / 60) | round(0) }}
          {% endif %}
```

## Only notify during commuting hours

A blueprint-style conditional that gates notifications on time-of-day:

```yaml
alias: "Commute delays only"
trigger:
  - platform: numeric_state
    entity_id: sensor.clapham_junction_delay
    above: 5
condition:
  - condition: time
    after: "07:00:00"
    before: "09:30:00"
    weekday: [mon, tue, wed, thu, fri]
action:
  - action: notify.mobile_app_your_phone
    data:
      message: "Heading to work? Train is {{ trigger.to_state.state }} min late."
```

## Track a specific train's progress

If you have set up a service tracker for headcode `1L40`, fire an automation when it arrives at its destination:

```yaml
alias: "1L40 arrived"
trigger:
  - platform: state
    entity_id: sensor.1l40_2025_10_26_live_status
    to: completed
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "1L40 arrived"
      message: "Service arrived at destination."
```

## React to a service starting its run

```yaml
alias: "1L40 started"
trigger:
  - platform: state
    entity_id: sensor.1l40_2025_10_26_live_status
    to: in_run
action:
  - action: notify.mobile_app_your_phone
    data:
      title: "1L40 on its way"
      message: "Service departed origin."
```

## Watch your rate limits (for power users)

Add a gauge card to the dashboard showing daily rate-limit headroom:

```yaml
type: gauge
entity: sensor.rtt_rate_limit_remaining_day
min: 0
max: 1000  # set to your actual `X-RateLimit-Limit-Day` value
name: "RTT daily quota"
severity:
  green: 100
  yellow: 30
  red: 10
```

## Combine multiple sensors in a glance

An Entities card with templates gives a quick board:

```yaml
type: entities
title: Clapham Junction — next 3 trains
entities:
  - sensor.clapham_junction_next_departure
  - sensor.clapham_junction_departure_2
  - sensor.clapham_junction_departure_3
  - sensor.clapham_junction_delay
  - sensor.clapham_junction_live_status
  - type: divider
  - binary_sensor.clapham_junction_cancellations
  - binary_sensor.clapham_junction_platform_changes
```
