from datetime import datetime

from pydantic import BaseModel, Field


class JourneyRequest(BaseModel):
    departure: str
    destination: str
    # Friendly labels shown in the UI / fed to the LLM. When the user picks on
    # the map, `departure`/`destination` carry the routing coordinates while
    # these labels carry the human-readable place names. Optional and falls
    # back to the routing strings.
    departure_label: str | None = None
    destination_label: str | None = None
    departure_time: datetime
    sampling_minutes: int = Field(default=5, ge=1, le=60)
    route_index: int = Field(default=0, ge=0, description="Which ORS route alternative to use")


class RoutePreview(BaseModel):
    index: int
    distance_km: float
    duration_minutes: float
    encoded_polyline: str


class RouteOptionsResponse(BaseModel):
    departure: str
    destination: str
    routes: list[RoutePreview]


class SampledPoint(BaseModel):
    index: int
    lat: float
    lon: float
    elapsed_minutes: float
    elapsed_seconds: float = 0.0
    estimated_timestamp: datetime | None = None
    cumulative_distance_km: float = 0.0


class RouteSummary(BaseModel):
    route_id: str
    departure: str
    destination: str
    departure_time: datetime
    arrival_time: datetime | None = None
    total_distance_km: float
    estimated_duration_minutes: float
    sampled_point_count: int
    encoded_polyline: str | None = None


class DarknessTransition(BaseModel):
    km: float
    timestamp: str
    event: str
    lat: float
    lon: float
    road_name: str = ""


class SurfaceChange(BaseModel):
    km: float
    timestamp: str
    from_condition: str
    to_condition: str
    lat: float
    lon: float
    road_name: str = ""


class SpeedZoneChange(BaseModel):
    km: float
    timestamp: str
    from_speed: float
    to_speed: float
    lat: float
    lon: float
    road_name: str = ""


class TrafficIncident(BaseModel):
    situation_id: str
    title: str
    announcement_type: str = ""
    start_time: str | None = None
    end_time: str | None = None
    status: str = "unknown"
    is_active: bool = True
    features: list[str] = Field(default_factory=list)
    lat: float = 0.0
    lon: float = 0.0
    distance_from_route_m: float = 0.0


class SegmentRisk(BaseModel):
    segment_id: int
    from_point_index: int
    to_point_index: int
    length_km: float
    speed_limit_kmh: float | None = None
    road_width_m: float | None = None
    is_dark: bool | None = None
    is_twilight: bool | None = None
    road_weather: str | None = None
    surface_condition: str | None = None
    grip: float | None = None
    grip_proxy: float | None = None
    solar_elevation_deg: float | None = None
    road_attribute_source: str | None = None
    road_attribute_match_distance_m: float | None = None
    overall_road_condition: str | None = None
    friction_condition: str | None = None
    winter_slipperiness: bool | None = None
    road_temperature_c: float | None = None
    air_temperature_c: float | None = None
    wind_speed_ms: float | None = None
    weather_source: str | None = None
    weather_match_distance_m: float | None = None
    weather_forecast_time: str | None = None
    weather_reliability: str | None = None
    weather_section_id: str | None = None
    weather_forecast_type: str | None = None
    weather_time_delta_minutes: float | None = None
    weather_usable_for_scoring: bool = False
    weather_confidence: str | None = None
    road_lit: bool | None = None
    moose_risk: bool = False
    recent_maintenance_task: str | None = None
    recent_maintenance_age_minutes: int | None = None
    recent_maintenance_distance_m: int | None = None
    risk_score: float
    risk_level: str
    reasons: list[str] = Field(default_factory=list)


class JourneyRiskSummary(BaseModel):
    overall_risk_score: float
    overall_risk_level: str
    highest_segment_score: float
    dark_segment_count: int = 0
    twilight_segment_count: int = 0
    poor_grip_segment_count: int = 0
    poor_weather_segment_count: int = 0
    slippery_segment_count: int = 0
    weak_weather_match_count: int = 0
    usable_weather_segment_count: int = 0
    darkness_total_km: float = 0.0
    darkness_total_minutes: float = 0.0
    daylight_total_km: float = 0.0
    daylight_total_minutes: float = 0.0
    darkness_start_time: str | None = None
    darkness_end_time: str | None = None
    darkness_start_road: str = ""
    darkness_end_road: str = ""
    daylight_start_time: str | None = None
    daylight_start_road: str = ""
    highest_risk_road: str = ""
    lit_road_segment_count: int = 0
    moose_risk_segment_count: int = 0


class TopRiskyPart(BaseModel):
    segment_id: int
    risk_score: float
    risk_level: str
    reasons: list[str]
    cumulative_distance_km: float = 0.0
    estimated_time: str | None = None
    road_name: str = ""


class EvidenceForLlm(BaseModel):
    journey: str
    departure_time_local: str
    total_segments: int
    overall_risk_score: float
    overall_risk_level: str
    dark_segment_count: int = 0
    twilight_segment_count: int = 0
    first_dark_timestamp: str | None = None
    weak_weather_match_count: int = 0
    usable_weather_segment_count: int = 0
    first_usable_slippery_weather_timestamp: str | None = None
    darkness_total_km: float = 0.0
    darkness_total_minutes: float = 0.0
    daylight_total_km: float = 0.0
    daylight_total_minutes: float = 0.0
    darkness_transitions: list[DarknessTransition] = Field(default_factory=list)
    surface_changes: list[SurfaceChange] = Field(default_factory=list)
    speed_zone_changes: list[SpeedZoneChange] = Field(default_factory=list)
    lit_road_segment_count: int = 0
    moose_risk_segment_count: int = 0
    top_risky_parts: list[TopRiskyPart] = Field(default_factory=list)
    conditions_summary: str = ""
    traffic_incidents: list[TrafficIncident] = Field(default_factory=list)


class JourneyPresentation(BaseModel):
    departure_place: str
    destination_place: str
    departure_local_time: str
    arrival_local_time: str
    total_distance: str
    total_duration: str
    route_checkpoints: int
    checkpoint_interval: str
    overall_risk: str
    risk_score: float
    top_risk_reasons: list[str] = Field(default_factory=list)
    extra_care_when: str = ""
    weather_coverage_note: str = ""
    trip_summary_line: str = ""
    has_daylight: bool = True
    dark_from: str | None = None
    dark_to: str | None = None
    twilight_from: str | None = None
    darkness_duration: str = ""
    daylight_duration: str = ""
    distance_in_dark: str = ""
    darkness_events: list[str] = Field(default_factory=list)
    surface_change_descriptions: list[str] = Field(default_factory=list)


class AiSummary(BaseModel):
    summary: str
    key_risks: list[str] = Field(default_factory=list)
    advice: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    confidence_note: str = ""


class JourneyAnalysisResponse(BaseModel):
    route_id: str
    overall_risk_score: float
    route_summary: RouteSummary
    sampled_points: list[SampledPoint]
    segment_risks: list[SegmentRisk]
    journey_risk_summary: JourneyRiskSummary
    evidence_for_llm: EvidenceForLlm
    journey_presentation: JourneyPresentation | None = None
    top_risky_parts: list[TopRiskyPart]
    traffic_incidents: list[TrafficIncident] = Field(default_factory=list)
    ai_summary: AiSummary | None = None
    ai_summary_error: str | None = None
