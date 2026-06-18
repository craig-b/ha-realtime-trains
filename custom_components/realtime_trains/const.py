"""Constants for the Realtime Trains integration."""

DOMAIN = "realtime_trains"

BASE_URL = "https://data.rtt.io"

# API version pinned to a known-good release. See
# https://github.com/realtimetrains/api-specification for the changelog.
API_VERSION = "2026-04-09"

# Default config entry data keys.
CONF_TOKEN = "token"  # noqa: S105
CONF_DEFAULT_SLOT_COUNT = "default_slot_count"

# Subentry types.
SUBENTRY_TYPE_DEPARTURE_BOARD = "departure_board"
SUBENTRY_TYPE_SERVICE_TRACKER = "service_tracker"

# Departure board subentry keys.
CONF_STATION = "station"
CONF_STATION_DESCRIPTION = "station_description"
CONF_FILTER_FROM = "filter_from"
CONF_FILTER_TO = "filter_to"
CONF_TIME_WINDOW = "time_window"
CONF_SLOT_COUNT = "slot_count"
CONF_DETAILED = "detailed"
CONF_POLLING_INTERVAL = "polling_interval"
CONF_STP_FILTER = "stp_filter"
CONF_NAMESPACE = "namespace"

# Service tracker subentry keys.
CONF_HEADCODE = "headcode"
CONF_DATE = "date"
CONF_UNIQUE_IDENTITY = "unique_identity"

# Defaults.
DEFAULT_SLOT_COUNT = 3
DEFAULT_TIME_WINDOW = 60
DEFAULT_POLLING_INTERVAL = 90
DEFAULT_NAMESPACE = "gb-nr"

# Bounds.
MIN_SLOT_COUNT = 1
MAX_SLOT_COUNT = 10
MIN_TIME_WINDOW = 15
MAX_TIME_WINDOW = 1440
MIN_POLLING_INTERVAL = 30
MAX_POLLING_INTERVAL = 3600
MAX_QUERY_WINDOW_MINUTES = 23 * 60 + 59

# Stops cache refresh interval.
STOPS_CACHE_TTL_DAYS = 7

# Account coordinator info refresh interval.
ACCOUNT_INFO_REFRESH_SECONDS = 60 * 60

# Token refresh lead time (seconds before expiry to refresh).
TOKEN_REFRESH_LEAD_TIME = 60

# Entitlements returned by /api/info.
ENTITLEMENT_DETAILED = "allowDetailed"
ENTITLEMENT_ALLOCATIONS = "allowAllocations"
ENTITLEMENT_KNOW_YOUR_TRAIN = "allowKnowYourTrain"
ENTITLEMENT_FULL_ALLOCATION_LISTING = "allowFullAllocationListing"

# Platforms exposed by the integration.
PLATFORMS = []
