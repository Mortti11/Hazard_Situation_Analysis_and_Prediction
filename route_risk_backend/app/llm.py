import json
import os
from openai import OpenAI
from .presentation import fmt_datetime_label, fmt_time
from .schemas import AiSummary

# Here I am gonna descripe to gpt its tasks 
_SYSTEM_PROMPT = """You write a short, friendly safety briefing for a heavy-truck driver in Finland.

The sidebar already shows every number, time, distance, percentage, and risk score.
Your job is to INTERPRET, not to repeat. Tell the driver what to actually do.

HARD RULES (a violation is a failure):
- Use only the JSON evidence. If a field is missing, treat it as unknown.
- Never invent a place, road, time, weather, or condition that is not in the evidence.
- Do NOT include numbers, percentages, scores, or risk-level words ("low", "moderate", "high", "critical") in `summary`, `key_risks`, or `advice`.
- Do NOT use any technical labels like POOR_CONDITION, OBSERVATION, FORECAST, EPSG, etc.
- Use plain, everyday English. Short sentences. No marketing tone, no "please", no "kindly".
- Aim for a 7th-grader reading level. A non-native English speaker should understand it.
- Times in the evidence are already Europe/Helsinki local time -- you may mention them only inside `summary` if it adds real value, never duplicate the schedule.
- If weather coverage is partial or missing, say so honestly in `confidence_note` and add the affected area to `unknowns`.
- Refer to places by name (`route.from`, `route.to`, road names from transitions/top_risky_parts). Never repeat coordinates.

WRITING STYLE:
- `summary`: 2-3 sentences. Say what kind of trip this is and the one or two real things to watch out for. No numbers.
- `key_risks`: 2-4 short phrases. Each one is a real driving hazard, not a data point. Bad: "15 segments in darkness". Good: "Long stretches with no street lighting".
- `advice`: 2-4 short, doable actions. Bad: "be cautious". Good: "Slow down on the unlit forest section after sunset".
- `unknowns`: list only data the evidence cannot answer (e.g. "no live weather along the southern half"). Empty list if nothing is missing.
- `confidence_note`: one sentence. Say how trustworthy the picture is, and why.

Return ONLY this JSON object, with at most 5 items per list:
{
  "summary": "...",
  "key_risks": ["..."],
  "advice": ["..."],
  "unknowns": ["..."],
  "confidence_note": "..."
}

EXAMPLE of the right tone (do not copy the words, only the style):
{
  "summary": "This is mostly a night drive on quiet rural roads in northern Finland. The biggest worry is wildlife crossing on the unlit stretches around the middle of the trip.",
  "key_risks": ["Unlit rural road in the dark", "Possible moose on forested sections", "Tired-driving zone after midnight"],
  "advice": ["Keep speed down on the unlit section before Pudasjarvi", "Watch the verges for moose between sunset and sunrise", "Plan a short break around the halfway point"],
  "unknowns": ["No live road-surface data for the last hour of the trip"],
  "confidence_note": "Most of the route has live weather and road data; the final stretch relies on darkness and road-type only."}
"""

# Converting the data into json, gpt will read as user message. 
# here are three parameters: route, risk and evidence.
#  route :where the trip goes, how long it takes, when it arrives.
# risk:  weather data. 

def _build_evidence_payload(route, journey_risk, evidence):
    payload = {
        "route":{
            "from":route.departure,
            "to": route.destination,
            "distance_km":route.total_distance_km,
            "duration_hours":round(route.estimated_duration_minutes / 60, 1),
            "departure_time_local":fmt_datetime_label(evidence.departure_time_local) or None,
            "arrival_time_local":fmt_datetime_label(route.arrival_time.isoformat()) if route.arrival_time else None},

        "risk":{
            "overall_score":evidence.overall_risk_score,
            "overall_level":evidence.overall_risk_level,
            "total_segments":evidence.total_segments,
            "dark_segments": evidence.dark_segment_count,
            "twilight_segments": evidence.twilight_segment_count,
            "first_dark_time_local": fmt_time(evidence.first_dark_timestamp) or None,
            "darkness_total_km": evidence.darkness_total_km,
            'darkness_total_minutes':evidence.darkness_total_minutes,
            "daylight_total_km": evidence.daylight_total_km,
            "daylight_total_minutes": evidence.daylight_total_minutes,
            "usable_weather_segments":evidence.usable_weather_segment_count,
            "weak_weather_matches": evidence.weak_weather_match_count,
            "first_slippery_time_local":fmt_time(evidence.first_usable_slippery_weather_timestamp) or None,
            "lit_road_segments": evidence.lit_road_segment_count,
            "moose_risk_segments": evidence.moose_risk_segment_count},


        "journey_summary":{"poor_weather_segments":journey_risk.poor_weather_segment_count,
                          "slippery_segments":journey_risk.slippery_segment_count,
                          "poor_grip_segments":journey_risk.poor_grip_segment_count},

        "darkness_transitions":[{"event":t.event,"time_local":fmt_time(t.timestamp) or None, "road": t.road_name, "km": t.km}
                               for t in evidence.darkness_transitions[:6]],

        "surface_changes":[{"from": c.from_condition, "to":c.to_condition, "time_local":fmt_time(c.timestamp) or None, "road": c.road_name, "km":c.km}
                            for c in evidence.surface_changes[:6]],

        "speed_zone_changes":[{"from_speed": s.from_speed, "to_speed":s.to_speed, "time_local":fmt_time(s.timestamp) or None, "road":s.road_name}
            for s in evidence.speed_zone_changes[:6]],

        "top_risky_parts":[{"road": p.road_name, "time_local":fmt_time(p.estimated_time) or None, "score": p.risk_score, "level": p.risk_level, "reasons": p.reasons}
                          for p in evidence.top_risky_parts],

        "conditions_summary":evidence.conditions_summary}
    return json.dumps(payload,ensure_ascii=False)




def generate_ai_summary(route_summary, journey_risk, evidence):
    api_key = os.getenv("Open_ai_key")
    completion = OpenAI(api_key=api_key).chat.completions.parse(
        model="gpt-4o-mini",temperature=0.3, max_tokens=500,
        messages=[{"role": "system", "content": _SYSTEM_PROMPT},
                  {"role": "user", "content":_build_evidence_payload(route_summary, journey_risk,evidence)}], response_format=AiSummary,)

    return completion.choices[0].message.parsed or None

# I used copilot here to quickly build the evidence payload. 