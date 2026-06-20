# API credentials

## Getting a token

1. Create a Realtime Trains unified login at <https://api-portal.rtt.io>.
2. Subscribe to the API plan that matches your use:
   - **Personal / enthusiast** — free, sufficient for a single Home Assistant instance.
   - **Power / commercial** — higher rate limits and history depth if you need it.
3. Generate a token in the portal. You will see one of:
   - A **long-life access token** — paste this directly into the Home Assistant config flow.
   - A **refresh token** — paste this; the integration exchanges it for short-life access tokens automatically and refreshes them before they expire.

## Long-life access token vs refresh token

| Feature | Long-life access token | Refresh token |
|---|---|---|
| Lifetime | Set by RTT (months/years) | Long-life, but issues short-life access tokens |
| Refresh logic | None needed | `/api/get_access_token` called before each access token expires |
| Config entry shows | Single field | Single field; access token + `validUntil` cached internally |
| Reauth needed | When token expires | Only if refresh token itself is revoked |

The integration detects which type you've entered by attempting `/api/info` with the token. If the response is an auth error, it falls back to treating the token as a refresh token and tries `get_access_token`.

## Entitlements

An access token grants access to a subset of the API. The integration surfaces the entitlements returned by `/api/info` and uses them to decide what features are available without wasting API calls on disallowed queries.

| Entitlement | Effect in the integration |
|---|---|
| `allowDetailed` | Enables detailed mode (internal times, STP indicators) for boards and services. Exposed as a toggle on departure boards. |
| `allowAllocations` | Enables rolling-stock allocation data on the service tracker. Surface as attributes on the service entities. |
| `allowKnowYourTrain` | Enables per-coach facilities (wifi, power, quiet, etc.) and coach letters on the service tracker. |
| `allowFullAllocationListing` | Not used by the integration (we never query the per-TOC listing endpoint); surfaced in the entitlements display only. |

Additional restrictions returned by `/api/info`:

| Restriction | Effect |
|---|---|
| `historyRestriction: true` | Service tracker refuses dates earlier than `historyRestrictToDays` days ago. Returns a translated error in the service action rather than a 4xx from the API. |
| `namespaceRestriction: true` | Only the listed `namespacesAvailable` are offered as options when adding monitored items. Defaults to `gb-nr`. |

## Rate limits

Every API response includes rate-limit headers. The integration consumes them transparently:

- `X-RateLimit-Limit-Minute` / `X-RateLimit-Remaining-Minute`
- `X-RateLimit-Limit-Hour` / `X-RateLimit-Remaining-Hour`
- `X-RateLimit-Limit-Day` / `X-RateLimit-Remaining-Day`
- `X-RateLimit-Limit-Week` / `X-RateLimit-Remaining-Week`

These are exposed as diagnostic sensors under the account device (see [Entities reference](entities.md#account-diagnostic-sensors)) so you can monitor headroom. A `429 Too Many Requests` response makes the affected coordinator back off before its next poll — waiting for the `Retry-After` hint when present, otherwise doubling its interval (capped at 3600 s) — and the configured cadence resumes after the next successful poll.

## Token handling & privacy

The Realtime Trains API specification states that *"no token is placed in a distributable user application… end-user applications are expected to proxy their requests through a server-side application such that token is not available publicly."*

Home Assistant **is** a server-side application running in the user's own home or self-hosted server. This integration:

- Stores the token in Home Assistant's encrypted config entry store.
- Sends the token only to `data.rtt.io` over HTTPS.
- Never logs it, never prints it, never includes it in diagnostics downloads (the `Authorization` and `Cookie` headers are stripped from cached responses — see [Architecture](architecture.md#diagnostics)).
- Ships no shared/bundled token. Every user uses their own key.

This matches the intended use case. The integration does **not** provide a public proxy of the RTT API; each user polls the API directly from their own Home Assistant instance using their own token.
