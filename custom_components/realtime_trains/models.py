"""Typed models for the Realtime Trains API.

One class per OpenAPI schema in
https://github.com/realtimetrains/api-specification/blob/main/specification/main.yml

The models are immutable (frozen) value types with one-shot
``from_dict`` classmethods that honour the spec's nullable fields as
``T | None``. The API client (``api.py``) returns these classes; the
coordinator and entity layers consume them and never peek into raw
dicts.

``from_dict`` methods are intentionally undocumented beyond their type
signature: the name plus ``dict -> Self`` contract is self-documenting,
and docstrings would only restate the parser logic.
"""

# ruff: noqa: D102

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


def _str(d: dict[str, Any], key: str) -> str | None:
    return d.get(key)


def _req_str(d: dict[str, Any], key: str) -> str:
    return str(d[key])


def _int(d: dict[str, Any], key: str) -> int | None:
    v = d.get(key)
    if v is None:
        return None
    return int(v)


def _bool(d: dict[str, Any], key: str) -> bool | None:
    v = d.get(key)
    if v is None:
        return None
    return bool(v)


def _datetime(d: dict[str, Any], key: str) -> datetime | None:
    # Python 3.11+ ``datetime.fromisoformat`` accepts the trailing 'Z'
    # used by RTT, so no normalisation is needed.
    v = d.get(key)
    if v is None:
        return None
    return datetime.fromisoformat(v)


def _list_str(d: dict[str, Any], key: str) -> list[str]:
    v = d.get(key)
    if not v:
        return []
    return list(v)


# --- System status -----------------------------------------------------------


class RealtimeNetworkRailStatus(StrEnum):
    """State of the real-time data ingress."""

    OK = "OK"
    REALTIME_DATA_LIMITED = "REALTIME_DATA_LIMITED"
    REALTIME_DATA_NONE = "REALTIME_DATA_NONE"


class RttCoreStatus(StrEnum):
    """State of the RTT core service."""

    OK = "OK"
    REALTIME_DEGRADED = "REALTIME_DEGRADED"
    SCHEDULE_ONLY = "SCHEDULE_ONLY"


@dataclass(kw_only=True, frozen=True, slots=True)
class SystemStatus:
    """Per-response system health snapshot."""

    realtime_network_rail: RealtimeNetworkRailStatus | None = None
    rtt_core: RttCoreStatus | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SystemStatus:
        return cls(
            realtime_network_rail=RealtimeNetworkRailStatus(d["realtimeNetworkRail"])
            if "realtimeNetworkRail" in d and d["realtimeNetworkRail"] is not None
            else None,
            rtt_core=RttCoreStatus(d["rttCore"])
            if "rttCore" in d and d["rttCore"] is not None
            else None,
        )


# --- Location reference ------------------------------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class GeographicLocation:
    """A station or location entity."""

    namespace: str
    description: str | None
    short_codes: list[str]
    long_codes: list[str]

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> GeographicLocation:
        return cls(
            namespace=d.get("namespace", "gb-nr"),
            description=_str(d, "description"),
            short_codes=_list_str(d, "shortCodes"),
            long_codes=_list_str(d, "longCodes"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class Stop:
    """Item from /data/stops — a passenger-stop entry."""

    namespace: str
    description: str | None
    short_code: str | None
    unique_identity: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Stop:
        return cls(
            namespace=d.get("namespace", "gb-nr"),
            description=_str(d, "description"),
            short_code=_str(d, "shortCode"),
            unique_identity=_str(d, "uniqueIdentity"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class Location:
    """Item from /data/locations_ungrouped — a single location entry."""

    namespace: str
    description: str | None
    short_code: str | None
    long_code: str | None
    unique_identity: str | None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Location:
        return cls(
            namespace=d.get("namespace", "gb-nr"),
            description=_str(d, "description"),
            short_code=_str(d, "shortCode"),
            long_code=_str(d, "longCode"),
            unique_identity=_str(d, "uniqueIdentity"),
        )


# --- Location call / display / status enums ---------------------------------


class LocationCallType(StrEnum):
    """Nature of the call at a location, when not null."""

    OPERATIONAL_ONLY = "OPERATIONAL_ONLY"
    ADVERTISED_OPEN = "ADVERTISED_OPEN"
    ADVERTISED_SET_DOWN = "ADVERTISED_SET_DOWN"
    ADVERTISED_PICK_UP = "ADVERTISED_PICK_UP"


class LocationDisplayAs(StrEnum):
    """Display type for a location entry. Null is treated as PASS."""

    CALL = "CALL"
    CANCELLED = "CANCELLED"
    DIVERTED = "DIVERTED"
    STARTS = "STARTS"
    TERMINATES = "TERMINATES"
    PASS = "PASS"  # noqa: S105


class LocationStatus(StrEnum):
    """Realtime status at a location. Not all values supported by all services."""

    APPROACHING = "APPROACHING"
    ARRIVING = "ARRIVING"
    AT_PLATFORM = "AT_PLATFORM"
    DEPART_PREPARING = "DEPART_PREPARING"
    DEPART_READY = "DEPART_READY"
    DEPARTING = "DEPARTING"


# --- Temporal data -----------------------------------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class IndividualTemporalData:
    """Times and lateness for a single activity (arrival / departure / pass).

    Per the spec, ``realtimeEstimate`` is only populated if you have the
    correct entitlement and the service has not reported at this activity.
    """

    schedule_internal: datetime | None = None
    schedule_advertised: datetime | None = None
    realtime_forecast: datetime | None = None
    realtime_estimate: datetime | None = None
    realtime_no_report: bool | None = None
    realtime_actual: datetime | None = None
    realtime_internal_lateness: int | None = None
    realtime_advertised_lateness: int | None = None
    is_cancelled: bool | None = None
    cancellation_reason_code: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> IndividualTemporalData:
        return cls(
            schedule_internal=_datetime(d, "scheduleInternal"),
            schedule_advertised=_datetime(d, "scheduleAdvertised"),
            realtime_forecast=_datetime(d, "realtimeForecast"),
            realtime_estimate=_datetime(d, "realtimeEstimate"),
            realtime_no_report=_bool(d, "realtimeNoReport"),
            realtime_actual=_datetime(d, "realtimeActual"),
            realtime_internal_lateness=_int(d, "realtimeInternalLateness"),
            realtime_advertised_lateness=_int(d, "realtimeAdvertisedLateness"),
            is_cancelled=_bool(d, "isCancelled"),
            cancellation_reason_code=_str(d, "cancellationReasonCode"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationTemporalData:
    """Arrival, departure and pass times plus call/display/status for a location."""

    arrival: IndividualTemporalData | None = None
    departure: IndividualTemporalData | None = None
    pass_: IndividualTemporalData | None = None
    scheduled_call_type: LocationCallType | None = None
    realtime_call_type: LocationCallType | None = None
    display_as: LocationDisplayAs | None = None
    status: LocationStatus | None = None
    is_interpolated: bool | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationTemporalData:
        arrival = d.get("arrival")
        departure = d.get("departure")
        pass_ = d.get("pass")
        sct = d.get("scheduledCallType")
        rct = d.get("realtimeCallType")
        da = d.get("displayAs")
        st = d.get("status")
        return cls(
            arrival=IndividualTemporalData.from_dict(arrival) if arrival else None,
            departure=IndividualTemporalData.from_dict(departure)
            if departure
            else None,
            pass_=IndividualTemporalData.from_dict(pass_) if pass_ else None,
            scheduled_call_type=LocationCallType(sct) if sct is not None else None,
            realtime_call_type=LocationCallType(rct) if rct is not None else None,
            display_as=LocationDisplayAs(da) if da is not None else None,
            status=LocationStatus(st) if st is not None else None,
            is_interpolated=_bool(d, "isInterpolated"),
        )


# --- Planned/actual values (platform, line, path) ----------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class PlannedActualData:
    """Planned / forecast / actual values for a metadata field (e.g. platform)."""

    planned: str | None = None
    forecast: str | None = None
    actual: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PlannedActualData:
        return cls(
            planned=_str(d, "planned"),
            forecast=_str(d, "forecast"),
            actual=_str(d, "actual"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class TimingAllowances:
    """Per-location engineering / pathing / performance allowances, in seconds.

    May be null per-field when not applicable; the whole object is only
    present on service queries, not on location line-up searches.
    """

    engineering: int | None = None
    pathing: int | None = None
    performance: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TimingAllowances:
        return cls(
            engineering=_int(d, "engineering"),
            pathing=_int(d, "pathing"),
            performance=_int(d, "performance"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationMetadata:
    """Platform, line, path, vehicles and request-stop info for a location."""

    platform: PlannedActualData | None = None
    line: PlannedActualData | None = None
    path: PlannedActualData | None = None
    number_of_vehicles: int | None = None
    allocation_index: int | None = None
    is_request_stop: bool | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationMetadata:
        platform = d.get("platform")
        line = d.get("line")
        path = d.get("path")
        return cls(
            platform=PlannedActualData.from_dict(platform) if platform else None,
            line=PlannedActualData.from_dict(line) if line else None,
            path=PlannedActualData.from_dict(path) if path else None,
            number_of_vehicles=_int(d, "numberOfVehicles"),
            allocation_index=_int(d, "allocationIndex"),
            is_request_stop=_bool(d, "isRequestStop"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailLocationMetadata(LocationMetadata):
    """Network-Rail-specific metadata: branding + timing allowances."""

    stock_branding: str | None = None
    allowances: TimingAllowances | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailLocationMetadata:
        platform = d.get("platform")
        line = d.get("line")
        path = d.get("path")
        allowances = d.get("allowances")
        return cls(
            platform=PlannedActualData.from_dict(platform) if platform else None,
            line=PlannedActualData.from_dict(line) if line else None,
            path=PlannedActualData.from_dict(path) if path else None,
            number_of_vehicles=_int(d, "numberOfVehicles"),
            allocation_index=_int(d, "allocationIndex"),
            is_request_stop=_bool(d, "isRequestStop"),
            stock_branding=_str(d, "stockBranding"),
            allowances=TimingAllowances.from_dict(allowances) if allowances else None,
        )


# --- Reason codes ------------------------------------------------------------


class ReasonType(StrEnum):
    """Type of reason block."""

    DELAY = "DELAY"
    CANCEL = "CANCEL"


@dataclass(kw_only=True, frozen=True, slots=True)
class ReasonBlock:
    """A delay or cancellation reason from the providing system."""

    type: ReasonType | None = None
    code: str | None = None
    system: str | None = None
    short_text: str | None = None
    long_text: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ReasonBlock:
        rt = d.get("type")
        lt = d.get("longText")
        return cls(
            type=ReasonType(rt) if rt is not None else None,
            code=_str(d, "code"),
            system=_str(d, "system"),
            short_text=_str(d, "shortText"),
            long_text=lt if lt is not None else _str(d, "shortText"),
        )


# --- Location pairs (origin / destination summaries) -------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationPair:
    """A location plus its single activity's temporal data, for origin/destination."""

    location: GeographicLocation | None = None
    temporal_data: IndividualTemporalData | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationPair:
        loc = d.get("location")
        td = d.get("temporalData")
        return cls(
            location=GeographicLocation.from_dict(loc) if loc else None,
            temporal_data=IndividualTemporalData.from_dict(td) if td else None,
        )


# --- Schedule metadata -------------------------------------------------------


class ModeType(StrEnum):
    """Form of transport. BUS is deprecated and is only present transiently."""

    TRAIN = "TRAIN"
    SHIP = "SHIP"
    BUS = "BUS"
    SCHEDULED_BUS = "SCHEDULED_BUS"
    REPLACEMENT_BUS = "REPLACEMENT_BUS"


class StpIndicator(StrEnum):
    """STP indicator. Only populated in detailed mode."""

    WTT = "WTT"
    VAR = "VAR"
    STP = "STP"
    CAN = "CAN"
    VST = "VST"
    VVR = "VVR"
    VCN = "VCN"


@dataclass(kw_only=True, frozen=True, slots=True)
class Operator:
    """Train operator. The name must not be cached by code (per the spec)."""

    code: str | None = None
    name: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Operator:
        return cls(
            code=_str(d, "code"),
            name=_str(d, "name"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class ScheduleMetadata:
    """Generic per-service schedule metadata."""

    unique_identity: str | None = None
    namespace: str | None = None
    identity: str | None = None
    departure_date: str | None = None
    operator: Operator | None = None
    mode_type: ModeType | None = None
    in_passenger_service: bool | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ScheduleMetadata:
        op = d.get("operator")
        mt = d.get("modeType")
        return cls(
            unique_identity=_str(d, "uniqueIdentity"),
            namespace=_str(d, "namespace"),
            identity=_str(d, "identity"),
            departure_date=_str(d, "departureDate"),
            operator=Operator.from_dict(op) if op else None,
            mode_type=ModeType(mt) if mt is not None else None,
            in_passenger_service=_bool(d, "inPassengerService"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailScheduleMetadata(ScheduleMetadata):
    """Schedule metadata with NR-specific fields (headcode + STP indicator)."""

    train_reporting_identity: str | None = None
    stp_indicator: StpIndicator | None = None
    runs_as_required: bool | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailScheduleMetadata:
        op = d.get("operator")
        mt = d.get("modeType")
        stp = d.get("stpIndicator")
        return cls(
            unique_identity=_str(d, "uniqueIdentity"),
            namespace=_str(d, "namespace"),
            identity=_str(d, "identity"),
            departure_date=_str(d, "departureDate"),
            operator=Operator.from_dict(op) if op else None,
            mode_type=ModeType(mt) if mt is not None else None,
            in_passenger_service=_bool(d, "inPassengerService"),
            train_reporting_identity=_str(d, "trainReportingIdentity"),
            stp_indicator=StpIndicator(stp) if stp is not None else None,
            runs_as_required=_bool(d, "runsAsRequired"),
        )


# --- Associations ------------------------------------------------------------


class AssociationType(StrEnum):
    """Type of association between two services at a location."""

    JOIN_FROM = "JOIN_FROM"
    JOIN_INTO = "JOIN_INTO"
    DIVIDE_INTO = "DIVIDE_INTO"
    DIVIDE_FROM = "DIVIDE_FROM"
    FORM_INTO = "FORM_INTO"
    FORM_FROM = "FORM_FROM"


@dataclass(kw_only=True, frozen=True, slots=True)
class AssociationData:
    """How two services are associated at a location."""

    association_type: AssociationType | None = None
    is_public: bool | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssociationData:
        at = d.get("associationType")
        return cls(
            association_type=AssociationType(at) if at is not None else None,
            is_public=_bool(d, "isPublic"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class AssociatedService:
    """An associated service (join / divide / form) with generic metadata."""

    association_data: AssociationData | None = None
    schedule_metadata: ScheduleMetadata | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssociatedService:
        ad = d.get("associationData")
        sm = d.get("scheduleMetadata")
        return cls(
            association_data=AssociationData.from_dict(ad) if ad else None,
            schedule_metadata=ScheduleMetadata.from_dict(sm) if sm else None,
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailAssociatedService:
    """Associated service with Network Rail specific metadata."""

    association_data: AssociationData | None = None
    schedule_metadata: NetworkRailScheduleMetadata | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailAssociatedService:
        ad = d.get("associationData")
        sm = d.get("scheduleMetadata")
        return cls(
            association_data=AssociationData.from_dict(ad) if ad else None,
            schedule_metadata=NetworkRailScheduleMetadata.from_dict(sm) if sm else None,
        )


# --- Service locations (the locations[] block of a service detail) -----------


@dataclass(kw_only=True, frozen=True, slots=True)
class ServiceLocation:
    """A single location entry on a service detail response."""

    temporal_data: LocationTemporalData | None = None
    location_metadata: LocationMetadata | None = None
    location: GeographicLocation | None = None
    associated_services: list[AssociatedService] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ServiceLocation:
        td = d.get("temporalData")
        lm = d.get("locationMetadata")
        loc = d.get("location")
        as_ = d.get("associatedServices") or []
        return cls(
            temporal_data=LocationTemporalData.from_dict(td) if td else None,
            location_metadata=LocationMetadata.from_dict(lm) if lm else None,
            location=GeographicLocation.from_dict(loc) if loc else None,
            associated_services=[AssociatedService.from_dict(item) for item in as_],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailServiceLocation:
    """A Network-Rail-flavoured single location entry on a service detail."""

    temporal_data: LocationTemporalData | None = None
    location_metadata: NetworkRailLocationMetadata | None = None
    location: GeographicLocation | None = None
    associated_services: list[NetworkRailAssociatedService] = field(
        default_factory=list
    )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailServiceLocation:
        td = d.get("temporalData")
        lm = d.get("locationMetadata")
        loc = d.get("location")
        as_ = d.get("associatedServices") or []
        return cls(
            temporal_data=LocationTemporalData.from_dict(td) if td else None,
            location_metadata=NetworkRailLocationMetadata.from_dict(lm) if lm else None,
            location=GeographicLocation.from_dict(loc) if loc else None,
            associated_services=[
                NetworkRailAssociatedService.from_dict(item) for item in as_
            ],
        )


# --- Location line-up (departure board entries) ------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationLineUp:
    """Generic-namespace departure board entry."""

    temporal_data: LocationTemporalData | None = None
    location_metadata: LocationMetadata | None = None
    reasons: list[ReasonBlock] = field(default_factory=list)
    origin: list[LocationPair] = field(default_factory=list)
    destination: list[LocationPair] = field(default_factory=list)
    schedule_metadata: ScheduleMetadata | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationLineUp:
        td = d.get("temporalData")
        lm = d.get("locationMetadata")
        sm = d.get("scheduleMetadata")
        reasons = d.get("reasons") or []
        return cls(
            temporal_data=LocationTemporalData.from_dict(td) if td else None,
            location_metadata=LocationMetadata.from_dict(lm) if lm else None,
            reasons=[ReasonBlock.from_dict(item) for item in reasons],
            origin=[LocationPair.from_dict(item) for item in (d.get("origin") or [])],
            destination=[
                LocationPair.from_dict(item) for item in (d.get("destination") or [])
            ],
            schedule_metadata=ScheduleMetadata.from_dict(sm) if sm else None,
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailLocationLineUp:
    """Network-Rail-specific departure board entry (with headcode + STP)."""

    temporal_data: LocationTemporalData | None = None
    location_metadata: NetworkRailLocationMetadata | None = None
    reasons: list[ReasonBlock] = field(default_factory=list)
    origin: list[LocationPair] = field(default_factory=list)
    destination: list[LocationPair] = field(default_factory=list)
    schedule_metadata: NetworkRailScheduleMetadata | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailLocationLineUp:
        sm = d.get("scheduleMetadata")
        td = d.get("temporalData")
        lm = d.get("locationMetadata")
        reasons = d.get("reasons") or []
        return cls(
            temporal_data=LocationTemporalData.from_dict(td) if td else None,
            location_metadata=NetworkRailLocationMetadata.from_dict(lm) if lm else None,
            reasons=[ReasonBlock.from_dict(item) for item in reasons],
            origin=[LocationPair.from_dict(item) for item in (d.get("origin") or [])],
            destination=[
                LocationPair.from_dict(item) for item in (d.get("destination") or [])
            ],
            schedule_metadata=NetworkRailScheduleMetadata.from_dict(sm) if sm else None,
        )


# --- Rolling stock allocation ------------------------------------------------


class StockType(StrEnum):
    """Allocation-item stock type. UNIT/SET describe multiple vehicles."""

    UNIT = "UNIT"
    LOCO = "LOCO"
    WAGON = "WAGON"
    CARRIAGE = "CARRIAGE"
    SET = "SET"


@dataclass(kw_only=True, frozen=True, slots=True)
class ComponentVehicle:
    """An individual vehicle inside an allocation item."""

    identity: str | None = None
    is_passenger_vehicle: bool | None = None
    is_locomotive: bool | None = None
    index: int | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ComponentVehicle:
        return cls(
            identity=_str(d, "identity"),
            is_passenger_vehicle=_bool(d, "isPassengerVehicle"),
            is_locomotive=_bool(d, "isLocomotive"),
            index=_int(d, "index"),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailAllocationItem:
    """A single allocation item — UNIT/LOCO/WAGON/CARRIAGE/SET, with vehicles."""

    stock_type: StockType | None = None
    identity: str | None = None
    in_reverse: bool | None = None
    identity_suppressed: bool | None = None
    number_of_vehicles: int | None = None
    component_vehicles: list[ComponentVehicle] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailAllocationItem:
        st = d.get("stockType")
        cv = d.get("componentVehicles") or []
        return cls(
            stock_type=StockType(st) if st is not None else None,
            identity=_str(d, "identity"),
            in_reverse=_bool(d, "inReverse"),
            identity_suppressed=_bool(d, "identitySuppressed"),
            number_of_vehicles=_int(d, "numberOfVehicles"),
            component_vehicles=[ComponentVehicle.from_dict(item) for item in cv],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class KnowYourTrainFacilityList:
    """Per-spec: a list of facility short-codes (wifi, power, etc.)."""

    facilities: list[str]

    @classmethod
    def from_dict(cls, d: list[str] | None) -> KnowYourTrainFacilityList:
        if d is None:
            return cls(facilities=[])
        return cls(facilities=list(d))


@dataclass(kw_only=True, frozen=True, slots=True)
class KnowYourTrainVehicle:
    """A vehicle entry in a Know-Your-Train group."""

    graphic: str | None = None
    is_passenger_vehicle: bool | None = None
    coach_letter: str | None = None
    individual_facilities: KnowYourTrainFacilityList | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KnowYourTrainVehicle:
        if_ = d.get("individualFacilities")
        return cls(
            graphic=_str(d, "graphic"),
            is_passenger_vehicle=_bool(d, "isPassengerVehicle"),
            coach_letter=_str(d, "coachLetter"),
            individual_facilities=KnowYourTrainFacilityList.from_dict(if_)
            if if_ is not None
            else None,
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class KnowYourTrainDataGroup:
    """A group of vehicles in a Know-Your-Train block."""

    identity: str | None = None
    group_facilities: KnowYourTrainFacilityList | None = None
    vehicles: list[KnowYourTrainVehicle] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> KnowYourTrainDataGroup:
        gf = d.get("groupFacilities")
        vs = d.get("vehicles") or []
        return cls(
            identity=_str(d, "identity"),
            group_facilities=KnowYourTrainFacilityList.from_dict(gf)
            if gf is not None
            else None,
            vehicles=[KnowYourTrainVehicle.from_dict(item) for item in vs],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailKnowYourTrainData:
    """Know-Your-Train payload returned from /gb-nr/service."""

    stock_branding: str | None = None
    common_facilities: KnowYourTrainFacilityList | None = None
    groups: list[KnowYourTrainDataGroup] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailKnowYourTrainData:
        cf = d.get("commonFacilities")
        gs = d.get("data") or []
        return cls(
            stock_branding=_str(d, "stockBranding"),
            common_facilities=KnowYourTrainFacilityList.from_dict(cf)
            if cf is not None
            else None,
            groups=[KnowYourTrainDataGroup.from_dict(item) for item in gs],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailAllocation:
    """A complete allocation segment for a service."""

    allocation_index: int | None = None
    leading_class: str | None = None
    passenger_vehicles: int | None = None
    allocation_items: list[NetworkRailAllocationItem] = field(default_factory=list)
    know_your_train_data: NetworkRailKnowYourTrainData | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailAllocation:
        ai = d.get("allocationItems") or []
        kyt = d.get("knowYourTrainData")
        return cls(
            allocation_index=_int(d, "allocationIndex"),
            leading_class=_str(d, "leadingClass"),
            passenger_vehicles=_int(d, "passengerVehicles"),
            allocation_items=[NetworkRailAllocationItem.from_dict(item) for item in ai],
            know_your_train_data=NetworkRailKnowYourTrainData.from_dict(kyt)
            if kyt
            else None,
        )


# --- Top-level response envelopes -------------------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationQuery:
    """The parsed query block returned alongside a location line-up."""

    location: GeographicLocation | None = None
    time_from: datetime | None = None
    time_to: datetime | None = None
    stp_filter: dict[str, bool] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationQuery:
        loc = d.get("location")
        stp = d.get("stpFilter")
        return cls(
            location=GeographicLocation.from_dict(loc) if loc else None,
            time_from=_datetime(d, "timeFrom"),
            time_to=_datetime(d, "timeTo"),
            stp_filter=stp if isinstance(stp, dict) else None,
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationLineUpResponse:
    """Top-level response from /rtt/location."""

    system_status: SystemStatus | None = None
    query: LocationQuery | None = None
    reasons: list[ReasonBlock] = field(default_factory=list)
    services: list[LocationLineUp] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationLineUpResponse:
        ss = d.get("systemStatus")
        q = d.get("query")
        return cls(
            system_status=SystemStatus.from_dict(ss) if ss else None,
            query=LocationQuery.from_dict(q) if q else None,
            reasons=[ReasonBlock.from_dict(item) for item in (d.get("reasons") or [])],
            services=[
                LocationLineUp.from_dict(item) for item in (d.get("services") or [])
            ],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailLocationLineUpResponse:
    """Top-level response from /gb-nr/location."""

    system_status: SystemStatus | None = None
    query: LocationQuery | None = None
    reasons: list[ReasonBlock] = field(default_factory=list)
    services: list[NetworkRailLocationLineUp] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailLocationLineUpResponse:
        ss = d.get("systemStatus")
        q = d.get("query")
        return cls(
            system_status=SystemStatus.from_dict(ss) if ss else None,
            query=LocationQuery.from_dict(q) if q else None,
            reasons=[ReasonBlock.from_dict(item) for item in (d.get("reasons") or [])],
            services=[
                NetworkRailLocationLineUp.from_dict(item)
                for item in (d.get("services") or [])
            ],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class ServiceQuery:
    """The query block on a service-detail response."""

    unique_identity: str | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ServiceQuery:
        return cls(unique_identity=_str(d, "uniqueIdentity"))


@dataclass(kw_only=True, frozen=True, slots=True)
class ServiceDetail:
    """Top-level service response from /rtt/service."""

    system_status: SystemStatus | None = None
    query: ServiceQuery | None = None
    schedule_metadata: ScheduleMetadata | None = None
    locations: list[ServiceLocation] = field(default_factory=list)
    origin: list[LocationPair] = field(default_factory=list)
    destination: list[LocationPair] = field(default_factory=list)
    reasons: list[ReasonBlock] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ServiceDetail:
        ss = d.get("systemStatus")
        q = d.get("query")
        svc = d.get("service") or {}
        sm = svc.get("scheduleMetadata")
        return cls(
            system_status=SystemStatus.from_dict(ss) if ss else None,
            query=ServiceQuery.from_dict(q) if q else None,
            schedule_metadata=ScheduleMetadata.from_dict(sm) if sm else None,
            locations=[
                ServiceLocation.from_dict(item) for item in svc.get("locations") or []
            ],
            origin=[LocationPair.from_dict(item) for item in svc.get("origin") or []],
            destination=[
                LocationPair.from_dict(item) for item in svc.get("destination") or []
            ],
            reasons=[ReasonBlock.from_dict(item) for item in svc.get("reasons") or []],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class NetworkRailServiceDetail:
    """Top-level service response from /gb-nr/service — includes allocations."""

    system_status: SystemStatus | None = None
    query: ServiceQuery | None = None
    schedule_metadata: NetworkRailScheduleMetadata | None = None
    locations: list[NetworkRailServiceLocation] = field(default_factory=list)
    allocation_data: list[NetworkRailAllocation] = field(default_factory=list)
    origin: list[LocationPair] = field(default_factory=list)
    destination: list[LocationPair] = field(default_factory=list)
    reasons: list[ReasonBlock] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NetworkRailServiceDetail:
        ss = d.get("systemStatus")
        q = d.get("query")
        svc = d.get("service") or {}
        sm = svc.get("scheduleMetadata")
        return cls(
            system_status=SystemStatus.from_dict(ss) if ss else None,
            query=ServiceQuery.from_dict(q) if q else None,
            schedule_metadata=NetworkRailScheduleMetadata.from_dict(sm) if sm else None,
            locations=[
                NetworkRailServiceLocation.from_dict(item)
                for item in svc.get("locations") or []
            ],
            allocation_data=[
                NetworkRailAllocation.from_dict(item)
                for item in svc.get("allocationData") or []
            ],
            origin=[LocationPair.from_dict(item) for item in svc.get("origin") or []],
            destination=[
                LocationPair.from_dict(item) for item in svc.get("destination") or []
            ],
            reasons=[ReasonBlock.from_dict(item) for item in svc.get("reasons") or []],
        )


# --- /api/info and /api/get_access_token -------------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class Credentials:
    """Token credentials profile returned by /api/info."""

    entitlements: list[str] = field(default_factory=list)
    history_restriction: bool | None = None
    history_restrict_to_days: int | None = None
    namespace_restriction: bool | None = None
    namespaces_available: list[str] | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Credentials:
        na = d.get("namespacesAvailable")
        return cls(
            entitlements=list(d.get("entitlements") or []),
            history_restriction=_bool(d, "historyRestriction"),
            history_restrict_to_days=_int(d, "historyRestrictToDays"),
            namespace_restriction=_bool(d, "namespaceRestriction"),
            namespaces_available=list(na) if isinstance(na, list) else None,
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class ApiInfo:
    """Top-level /api/info response."""

    api_version: str | None = None
    credentials: Credentials = field(default_factory=Credentials)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ApiInfo:
        creds = d.get("credentials") or {}
        return cls(
            api_version=_str(d, "api_version"),
            credentials=Credentials.from_dict(creds) if creds else Credentials(),
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class AccessTokenResponse:
    """Response from /api/get_access_token."""

    token: str
    entitlements: list[str] = field(default_factory=list)
    valid_until: datetime | None = None

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AccessTokenResponse:
        raw_token = _req_str(d, "token")
        return cls(
            token=raw_token,  # noqa: S105
            entitlements=list(d.get("entitlements") or []),
            valid_until=_datetime(d, "validUntil"),
        )


# --- /data/locations_ungrouped and /data/stops -------------------------------


@dataclass(kw_only=True, frozen=True, slots=True)
class StopsResponse:
    """Top-level /data/stops response."""

    stops: list[Stop] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> StopsResponse:
        return cls(
            stops=[Stop.from_dict(item) for item in d.get("stops") or []],
        )


@dataclass(kw_only=True, frozen=True, slots=True)
class LocationsUngroupedResponse:
    """Top-level /data/locations_ungrouped response."""

    locations: list[Location] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> LocationsUngroupedResponse:
        return cls(
            locations=[Location.from_dict(item) for item in d.get("locations") or []],
        )


# --- Rate limit snapshot (not an API response; populated from headers) -------


class RateLimitDimension(StrEnum):
    """Time dimension for the X-RateLimit-* headers."""

    MINUTE = "Minute"
    HOUR = "Hour"
    DAY = "Day"
    WEEK = "Week"


@dataclass(kw_only=True, frozen=True, slots=True)
class RateLimitEntry:
    """One dimension's limit + remaining count."""

    limit: int | None
    remaining: int | None


@dataclass(kw_only=True, frozen=True, slots=True)
class RateLimitSnapshot:
    """Per-call snapshot of all four X-RateLimit dimensions."""

    minute: RateLimitEntry | None = None
    hour: RateLimitEntry | None = None
    day: RateLimitEntry | None = None
    week: RateLimitEntry | None = None
    retry_after: int | None = None

    @classmethod
    def from_headers(cls, headers: dict[str, str]) -> RateLimitSnapshot:
        """Parse X-RateLimit-* headers into a snapshot.

        Header names are case-insensitive per RFC 7230; callers should pass
        a lower-cased mapping for performance.
        """

        def entry(dim: RateLimitDimension) -> RateLimitEntry | None:
            lim = headers.get(f"x-ratelimit-limit-{dim.value.lower()}")
            rem = headers.get(f"x-ratelimit-remaining-{dim.value.lower()}")
            if lim is None and rem is None:
                return None
            return RateLimitEntry(
                limit=int(lim) if lim is not None else None,
                remaining=int(rem) if rem is not None else None,
            )

        retry_after_raw = headers.get("retry-after")
        return cls(
            minute=entry(RateLimitDimension.MINUTE),
            hour=entry(RateLimitDimension.HOUR),
            day=entry(RateLimitDimension.DAY),
            week=entry(RateLimitDimension.WEEK),
            retry_after=int(retry_after_raw) if retry_after_raw is not None else None,
        )
