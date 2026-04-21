import json as _json
import os

from .presentation import fmt_datetime_label, fmt_time
from .schemas import AiSummary

_SYSTEM_PROMPT = """You summarise deterministic route-risk evidence for a driver.

Rules:
- Use only the JSON evidence. Do not invent facts.
- If a value is missing, say it is unknown.
- Keep the risk realistic. Do not exaggerate.
- Keep all numbers, times, distances, and conditions unchanged.
- All times are already Europe/Helsinki local time.
- Use road names when available. Do not show coordinates.
- Mention weak or partial weather coverage in confidence_note.

Return valid JSON:
{
  "summary": "One short paragraph under 100 words.",
  "key_risks": ["risk 1", "risk 2"],
  "advice": ["advice 1", "advice 2"],
  "unknowns": ["unknown 1"],
  "confidence_note": "Short note about data quality."
}
Use at most 5 items per list.
"""


def _build_evidence_payload(route, journey_risk, evidence):
    arrival_iso = route.arrival_time.isoformat() if route.arrival_time else None

    return _json.dumps({
        "route": {
            "from": route.departure,
            "to": route.destination,
            "distance_km": route.total_distance_km,
            "duration_hours": round(route.estimated_duration_minutes / 60, 1),
            "departure_time_local": fmt_datetime_label(evidence.departure_time_local) or None,
            "arrival_time_local": fmt_datetime_label(arrival_iso) or None,
        },
        "risk": {
            "overall_score": evidence.overall_risk_score,
            "overall_level": evidence.overall_risk_level,
            "total_segments": evidence.total_segments,
            "dark_segments": evidence.dark_segment_count,
            "twilight_segments": evidence.twilight_segment_count,
            "first_dark_time_local": fmt_time(evidence.first_dark_timestamp) or None,
            "darkness_total_km": evidence.darkness_total_km,
            "darkness_total_minutes": evidence.darkness_total_minutes,
            "daylight_total_km": evidence.daylight_total_km,
            "daylight_total_minutes": evidence.daylight_total_minutes,
            "usable_weather_segments": evidence.usable_weather_segment_count,
            "weak_weather_matches": evidence.weak_weather_match_count,
            "first_slippery_time_local": fmt_time(evidence.first_usable_slippery_weather_timestamp) or None,
            "lit_road_segments": evidence.lit_road_segment_count,
            "moose_risk_segments": evidence.moose_risk_segment_count,
        },
        "journey_summary": {
            "poor_weather_segments": journey_risk.poor_weather_segment_count,
            "slippery_segments": journey_risk.slippery_segment_count,
            "poor_grip_segments": journey_risk.poor_grip_segment_count,
        },
        "darkness_transitions": [
            {"event": item.event, "time_local": fmt_time(item.timestamp) or None, "road": item.road_name, "km": item.km}
            for item in evidence.darkness_transitions[:6]
        ],
        "surface_changes": [
            {"from": item.from_condition, "to": item.to_condition,
             "time_local": fmt_time(item.timestamp) or None, "road": item.road_name, "km": item.km}
            for item in evidence.surface_changes[:6]
        ],
        "speed_zone_changes": [
            {"from_speed": item.from_speed, "to_speed": item.to_speed,
             "time_local": fmt_time(item.timestamp) or None, "road": item.road_name}
            for item in evidence.speed_zone_changes[:6]],
        "top_risky_parts": [
            {"road": part.road_name, "time_local": fmt_time(part.estimated_time) or None,
             "score": part.risk_score, "level": part.risk_level, "reasons": part.reasons}
            for part in evidence.top_risky_parts],
        "conditions_summary": evidence.conditions_summary}, default=str)


def generate_ai_summary(route_summary, journey_risk, evidence):
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return None

    from openai import OpenAI

    response = OpenAI(api_key=api_key).chat.completions.create(
        model="gpt-4o-mini",
        temperature=0.3,
        max_tokens=500,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": _build_evidence_payload(route_summary, journey_risk, evidence),
            },
        ],
    )
    data = _json.loads(response.choices[0].message.content)
    return AiSummary(
        summary=data.get("summary", ""),
        key_risks=data.get("key_risks", []),
        advice=data.get("advice", []),
        unknowns=data.get("unknowns", []),
        confidence_note=data.get("confidence_note", ""),
    )
