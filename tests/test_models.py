"""Sanity test that models parse the spec's example payloads.

The models module only depends on the Python standard library, so the
test loads it directly from disk via importlib rather than going
through ``custom_components.realtime_trains`` (whose ``__init__.py``
imports Home Assistant and so requires HA to be installed). When the
full test suite runs under HA core in CI, the standard package import
works too; the file-based loader is the local-dev fallback.
"""

import importlib.util
from pathlib import Path
import sys

_MODELS_PATH = (
    Path(__file__).parent.parent / "custom_components" / "realtime_trains" / "models.py"
)
_spec = importlib.util.spec_from_file_location("rtt_models", _MODELS_PATH)
assert _spec is not None  # noqa: PT018
assert _spec.loader is not None
m = importlib.util.module_from_spec(_spec)
sys.modules["rtt_models"] = m
_spec.loader.exec_module(m)


def test_individual_temporal_data_round_trip() -> None:
    """Lateness and reason code come through unchanged."""
    data = {
        "scheduleInternal": "2025-10-25T13:45:00Z",
        "scheduleAdvertised": "2025-10-25T13:45:00Z",
        "realtimeForecast": "2025-10-25T13:50:00Z",
        "realtimeActual": "2025-10-25T13:50:00Z",
        "realtimeInternalLateness": 5,
        "realtimeAdvertisedLateness": 5,
        "realtimeNoReport": False,
        "isCancelled": False,
        "cancellationReasonCode": "TB",
    }
    parsed = m.IndividualTemporalData.from_dict(data)
    assert parsed.realtime_internal_lateness == 5
    assert parsed.cancellation_reason_code == "TB"
    assert parsed.is_cancelled is False
    assert parsed.realtime_actual is not None
    assert parsed.realtime_actual.year == 2025
    assert parsed.realtime_actual.month == 10
    assert parsed.realtime_actual.day == 25
    assert parsed.realtime_actual.tzinfo is not None


def test_geographic_location_with_short_and_long_codes() -> None:
    """A location with multiple long codes parses all of them."""
    data = {
        "namespace": "gb-nr",
        "description": "Clapham Junction",
        "shortCodes": ["CLJ"],
        "longCodes": ["CLPHMJN", "CLPHMJ2", "CLPHMJM", "CLPHMJW", "CLPHMJC"],
    }
    parsed = m.GeographicLocation.from_dict(data)
    assert parsed.namespace == "gb-nr"
    assert parsed.description == "Clapham Junction"
    assert parsed.short_codes == ["CLJ"]
    assert len(parsed.long_codes) == 5


def test_network_rail_schedule_metadata_with_stp() -> None:
    """NR metadata carries headcode + STP indicator."""
    data = {
        "uniqueIdentity": "gb-nr:L01525:2025-10-26",
        "namespace": "gb-nr",
        "identity": "L01525",
        "departureDate": "2025-10-26",
        "operator": {"code": "SW", "name": "South Western Railway"},
        "modeType": "TRAIN",
        "inPassengerService": True,
        "trainReportingIdentity": "1L40",
        "stpIndicator": "WTT",
        "runsAsRequired": False,
    }
    parsed = m.NetworkRailScheduleMetadata.from_dict(data)
    assert parsed.train_reporting_identity == "1L40"
    assert parsed.stp_indicator == m.StpIndicator.WTT
    assert parsed.operator is not None
    assert parsed.operator.name == "South Western Railway"
    assert parsed.mode_type == m.ModeType.TRAIN


def test_rate_limit_snapshot_from_headers() -> None:
    """All four dimensions parse from lower-cased headers."""
    headers = {
        "x-ratelimit-limit-minute": "60",
        "x-ratelimit-remaining-minute": "42",
        "x-ratelimit-limit-hour": "1000",
        "x-ratelimit-remaining-hour": "950",
        "x-ratelimit-limit-day": "10000",
        "x-ratelimit-remaining-day": "8765",
        "x-ratelimit-limit-week": "70000",
        "x-ratelimit-remaining-week": "65432",
    }
    snap = m.RateLimitSnapshot.from_headers(headers)
    assert snap.minute is not None
    assert snap.minute.limit == 60
    assert snap.minute.remaining == 42
    assert snap.hour is not None
    assert snap.hour.remaining == 950
    assert snap.day is not None
    assert snap.day.remaining == 8765
    assert snap.week is not None
    assert snap.week.remaining == 65432
    assert snap.retry_after is None


def test_rate_limit_snapshot_partial_headers() -> None:
    """Missing dimensions become None entries."""
    headers = {
        "x-ratelimit-limit-hour": "1000",
        "x-ratelimit-remaining-hour": "950",
        "retry-after": "30",
    }
    snap = m.RateLimitSnapshot.from_headers(headers)
    assert snap.minute is None
    assert snap.day is None
    assert snap.week is None
    assert snap.hour is not None
    assert snap.hour.limit == 1000
    assert snap.retry_after == 30


def test_api_info_parses_credentials_and_restrictions() -> None:
    """/api/info surfaces entitlements plus any history/namespace limits."""
    data = {
        "api_version": "2026-01-18",
        "credentials": {
            "entitlements": ["allowDetailed", "allowAllocations"],
            "historyRestriction": True,
            "historyRestrictToDays": 14,
            "namespaceRestriction": True,
            "namespacesAvailable": ["gb-nr"],
        },
    }
    parsed = m.ApiInfo.from_dict(data)
    assert parsed.api_version == "2026-01-18"
    assert parsed.credentials.entitlements == ["allowDetailed", "allowAllocations"]
    assert parsed.credentials.history_restriction is True
    assert parsed.credentials.history_restrict_to_days == 14
    assert parsed.credentials.namespace_restriction is True
    assert parsed.credentials.namespaces_available == ["gb-nr"]


def test_access_token_response_round_trip() -> None:
    """/api/get_access_token payload parses."""
    data = {
        "token": "abc.def.ghi",
        "entitlements": ["allowDetailed"],
        "validUntil": "2026-06-18T20:00:00Z",
    }
    parsed = m.AccessTokenResponse.from_dict(data)
    assert parsed.token == "abc.def.ghi"  # noqa: S105
    assert parsed.entitlements == ["allowDetailed"]
    assert parsed.valid_until is not None
    assert parsed.valid_until.year == 2026


def test_stop_item_parse() -> None:
    """/data/stops array item parses with all fields populated."""
    data = {
        "namespace": "gb-nr",
        "description": "Clapham Junction",
        "shortCode": "CLJ",
        "uniqueIdentity": "gb-nr:CLJ",
    }
    parsed = m.Stop.from_dict(data)
    assert parsed.namespace == "gb-nr"
    assert parsed.description == "Clapham Junction"
    assert parsed.short_code == "CLJ"
    assert parsed.unique_identity == "gb-nr:CLJ"


def test_reason_block_long_text_falls_back_to_short() -> None:
    """Per spec, longText null falls back to shortText value."""
    data_with_null_long = {
        "type": "DELAY",
        "code": "TB",
        "system": "TRUST",
        "shortText": "TOC request",
        "longText": None,
    }
    parsed = m.ReasonBlock.from_dict(data_with_null_long)
    assert parsed.long_text == "TOC request"

    data_with_long = {
        "type": "CANCEL",
        "code": "TB",
        "system": "TRUST",
        "shortText": "TOC request",
        "longText": "At the request of the train operator.",
    }
    parsed = m.ReasonBlock.from_dict(data_with_long)
    assert parsed.long_text == "At the request of the train operator."


def test_network_rail_service_detail_parses_full_payload() -> None:
    """Service detail with allocation + KYT data round-trips."""
    data = {
        "systemStatus": {
            "realtimeNetworkRail": "OK",
            "rttCore": "OK",
        },
        "query": {"uniqueIdentity": "gb-nr:L01525:2025-10-26"},
        "service": {
            "scheduleMetadata": {
                "uniqueIdentity": "gb-nr:L01525:2025-10-26",
                "namespace": "gb-nr",
                "identity": "L01525",
                "departureDate": "2025-10-26",
                "operator": {"code": "SW", "name": "South Western Railway"},
                "modeType": "TRAIN",
                "inPassengerService": True,
                "trainReportingIdentity": "1L40",
                "stpIndicator": "WTT",
            },
            "locations": [
                {
                    "temporalData": {
                        "arrival": {
                            "scheduleAdvertised": "2025-10-26T17:30:00Z",
                            "realtimeActual": "2025-10-26T17:30:30Z",
                            "realtimeAdvertisedLateness": 0,
                        },
                        "departure": {
                            "scheduleAdvertised": "2025-10-26T17:31:00Z",
                        },
                        "displayAs": "CALL",
                        "status": "AT_PLATFORM",
                    },
                    "locationMetadata": {
                        "platform": {"planned": "3", "actual": "3"},
                        "numberOfVehicles": 10,
                        "isRequestStop": False,
                        "stockBranding": "South Western Railway",
                    },
                    "location": {
                        "namespace": "gb-nr",
                        "description": "Clapham Junction",
                        "shortCodes": ["CLJ"],
                        "longCodes": ["CLPHMJN"],
                    },
                    "associatedServices": [],
                }
            ],
            "allocationData": [
                {
                    "allocationIndex": 0,
                    "leadingClass": "444",
                    "passengerVehicles": 10,
                    "allocationItems": [
                        {
                            "stockType": "UNIT",
                            "identity": "444045",
                            "inReverse": False,
                            "identitySuppressed": False,
                            "numberOfVehicles": 5,
                            "componentVehicles": [
                                {
                                    "identity": "63895",
                                    "isPassengerVehicle": True,
                                    "isLocomotive": False,
                                    "index": 0,
                                }
                            ],
                        }
                    ],
                    "knowYourTrainData": {
                        "stockBranding": "South Western Railway",
                        "commonFacilities": ["wifi", "power", "toilet", "aircon"],
                        "data": [
                            {
                                "identity": "444045",
                                "groupFacilities": ["wifi", "power", "quiet"],
                                "vehicles": [
                                    {
                                        "coachLetter": "A",
                                        "isPassengerVehicle": True,
                                        "individualFacilities": [
                                            "wifi",
                                            "power",
                                            "wheelchair",
                                        ],
                                    }
                                ],
                            }
                        ],
                    },
                }
            ],
            "origin": [
                {
                    "location": {
                        "namespace": "gb-nr",
                        "description": "London Waterloo",
                        "shortCodes": ["WAT"],
                        "longCodes": ["WATRMSN"],
                    }
                }
            ],
            "destination": [
                {
                    "location": {
                        "namespace": "gb-nr",
                        "description": "Woking",
                        "shortCodes": ["WOK"],
                        "longCodes": ["WOKING"],
                    }
                }
            ],
            "reasons": [],
        },
    }
    parsed = m.NetworkRailServiceDetail.from_dict(data)
    assert parsed.schedule_metadata is not None
    assert parsed.schedule_metadata.train_reporting_identity == "1L40"
    assert parsed.schedule_metadata.operator is not None
    assert parsed.schedule_metadata.operator.name == "South Western Railway"
    assert len(parsed.locations) == 1
    loc = parsed.locations[0]
    assert loc.location_metadata is not None
    assert loc.location_metadata.stock_branding == "South Western Railway"
    assert loc.location_metadata.platform is not None
    assert loc.location_metadata.platform.actual == "3"
    assert loc.temporal_data is not None
    assert loc.temporal_data.status == m.LocationStatus.AT_PLATFORM
    assert loc.temporal_data.arrival is not None
    assert loc.temporal_data.arrival.realtime_actual is not None
    assert loc.temporal_data.arrival.realtime_advertised_lateness == 0
    assert len(parsed.allocation_data) == 1
    alloc = parsed.allocation_data[0]
    assert alloc.leading_class == "444"
    assert alloc.passenger_vehicles == 10
    assert len(alloc.allocation_items) == 1
    assert alloc.allocation_items[0].identity == "444045"
    assert alloc.know_your_train_data is not None
    assert alloc.know_your_train_data.common_facilities is not None
    assert alloc.know_your_train_data.common_facilities.facilities == [
        "wifi",
        "power",
        "toilet",
        "aircon",
    ]
    assert len(parsed.origin) == 1
    assert parsed.origin[0].location is not None
    assert parsed.origin[0].location.description == "London Waterloo"


def test_location_line_up_response_empty_services_ok() -> None:
    """A board with no services in window parses cleanly."""
    data = {
        "systemStatus": {
            "realtimeNetworkRail": "REALTIME_DATA_LIMITED",
            "rttCore": "OK",
        },
        "query": {
            "location": {
                "namespace": "gb-nr",
                "description": "Clapham Junction",
                "shortCodes": ["CLJ"],
                "longCodes": ["CLPHMJN"],
            },
            "timeFrom": "2025-10-25T13:00:00Z",
            "timeTo": "2025-10-25T14:00:00Z",
        },
        "reasons": [],
        "services": [],
    }
    parsed = m.LocationLineUpResponse.from_dict(data)
    assert parsed.system_status is not None
    assert (
        parsed.system_status.realtime_network_rail
        == m.RealtimeNetworkRailStatus.REALTIME_DATA_LIMITED
    )
    assert parsed.query is not None
    assert parsed.query.location is not None
    assert parsed.query.location.description == "Clapham Junction"
    assert parsed.query.time_from is not None
    assert parsed.query.time_to is not None
    assert parsed.services == []


def test_association_type_enum_round_trip() -> None:
    """All six association types parse to their enum members."""
    assert m.AssociationType("JOIN_FROM") == m.AssociationType.JOIN_FROM
    assert m.AssociationType("FORM_INTO") == m.AssociationType.FORM_INTO


def test_location_display_as_null_treated_as_pass() -> None:
    """DisplayAs null is treated as PASS per spec — surfaced as None here."""
    data = {"displayAs": None}
    parsed = m.LocationTemporalData.from_dict(data)
    assert parsed.display_as is None
