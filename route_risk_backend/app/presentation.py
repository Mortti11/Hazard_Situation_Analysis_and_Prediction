from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from .schemas import JourneyPresentation

_FINLAND_TZ = ZoneInfo("Europe/Helsinki")


def to_fi_local(ts):
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_FINLAND_TZ)
    return dt.astimezone(_FINLAND_TZ)


def fmt_time(ts):
    dt = to_fi_local(ts)
    return dt.strftime("%H:%M") if dt else ""


def fmt_datetime_label(ts):
    dt = to_fi_local(ts)
    return f"{dt.day} {dt.strftime('%b')} at {dt.strftime('%H:%M')}" if dt else ""


def fmt_duration(minutes):
    h, m = divmod(int(round(minutes)), 60)
    if h and m:
        return f"{h}h {m}min"
    if h:
        return f"{h}h"
    return f"{m}min"


_REASON_CLEAN = {
    "driving in darkness": "Driving in darkness",
    "driving in twilight": "Driving in twilight",
    "extremely poor road condition": "Extremely poor road condition",
    "poor road condition": "Poor road condition",
    "very slippery friction condition": "Very slippery road surface",
    "slippery friction condition": "Slippery road surface",
    "winter slipperiness warning": "Winter slipperiness",
    "high speed in darkness, unlit road": "High speed in darkness (unlit road)"}


def _clean_reason(reason):
    low = reason.lower().strip()
    if low in _REASON_CLEAN:
        return _REASON_CLEAN[low]
    if low.startswith("surface condition: "):
        return f"{reason.split(': ', 1)[1].replace('_', ' ').capitalize()} road surface"
    if "moose" in low or "wildlife" in low:
        return "Moose/wildlife risk in twilight" if "twilight" in low else "Moose/wildlife risk in darkness"
    if "narrow road" in low:
        return "Narrow road at high speed"
    if "high speed" in low and "darkness" in low:
        return "High speed in darkness (unlit road)"
    if "not scored" in low or "confidence=" in low:
        return ""
    if "grip" in low and "(" in low:
        return "Reduced road grip"
    return reason.strip().capitalize()


_TRANSITION_LABELS = {
    "enters_darkness": "Darkness from",
    "enters_twilight": "Twilight from",
    "exits_darkness": "Returns to daylight at",
}


def _darkness_event_sentence(transition):
    label = _TRANSITION_LABELS.get(transition.event, f"{transition.event.replace('_', ' ').title()} at")
    msg = f"{label} {fmt_time(transition.timestamp)}"
    return f"{msg} near {transition.road_name}" if transition.road_name else msg


def _surface_change_sentence(change):
    where = change.road_name or f"km {change.km}"
    before = change.from_condition.replace("_", " ").lower()
    after = change.to_condition.replace("_", " ").lower()
    return f"Around {fmt_time(change.timestamp)} near {where}, the road changes from {before} to {after}."


def _collect_top_reasons(top_risky, max_reasons=4):
    seen = Counter(
        cleaned
        for part in top_risky
        for reason in part.reasons
        if "no adverse" not in reason.lower()
        if (cleaned := _clean_reason(reason))
    )
    return [reason for reason, _ in sorted(seen.items(), key=lambda item: (-item[1], item[0]))[:max_reasons]]


def _extra_care_sentence(top_risky):
    if not top_risky:
        return ""
    part = top_risky[0]
    time_str = fmt_time(part.estimated_time) if part.estimated_time else ""
    pieces = [p for p in (f"around {time_str}" if time_str else "", f"near {part.road_name}" if part.road_name else "") if p]
    return f"Most care needed {' '.join(pieces)}" if pieces else ""


def _trip_summary_line(risk_level, dark_min, total_min, daylight_min, dark_duration):
    if total_min <= 0:
        return ""
    dark_pct = dark_min / total_min
    light = (
        "an almost entirely night-time drive" if dark_pct >= 0.9
        else "mostly a night drive" if dark_pct >= 0.6
        else "a drive with significant night-time sections" if dark_pct >= 0.3
        else "a daytime drive" if daylight_min >= total_min * 0.9
        else "a drive with mixed light conditions")
    risk_phrase = {
        "low": "with low overall risk",
        "moderate": "with moderate risk",
        "high": "with elevated risk",
        "critical": "with critical risk",
    }.get(risk_level, "")
    suffix = f", {risk_phrase}" if risk_phrase else ""
    extra = f" ({dark_duration} in darkness or twilight)" if dark_pct >= 0.3 and dark_duration else ""
    return f"This is {light}{extra}{suffix}."


def _weather_coverage_note(usable, total):
    if total > 0 and usable >= total * 0.7:
        return f"Weather data available for {usable} of {total} checkpoints - good coverage."
    if usable > 0:
        return f"Weather data available for {usable} of {total} checkpoints - partial coverage."
    return "No usable weather data for this route."


def build_journey_presentation(route, journey_risk, evidence, top_risky, total_segments, sampling_minutes=5):
    transitions = evidence.darkness_transitions
    dark_from = next((fmt_time(t.timestamp) + (f" near {t.road_name}" if t.road_name else "")
                      for t in transitions if t.event == "enters_darkness"), None)
    twilight_from = next((fmt_time(t.timestamp) + (f" near {t.road_name}" if t.road_name else "")
                          for t in transitions if t.event == "enters_twilight"), None)
    dark_to = next((fmt_time(t.timestamp) + (f" near {t.road_name}" if t.road_name else "")
                    for t in transitions if t.event == "exits_darkness"), None)

    dark_dur = fmt_duration(journey_risk.darkness_total_minutes)
    light_dur = fmt_duration(journey_risk.daylight_total_minutes)

    return JourneyPresentation(
        departure_place=route.departure,
        destination_place=route.destination,
        departure_local_time=fmt_time(route.departure_time.isoformat() if route.departure_time else None),
        arrival_local_time=fmt_time(route.arrival_time.isoformat() if route.arrival_time else None),
        total_distance=f"{route.total_distance_km} km",
        total_duration=fmt_duration(route.estimated_duration_minutes),
        route_checkpoints=total_segments,
        checkpoint_interval=f"about every {sampling_minutes} minutes",
        overall_risk=journey_risk.overall_risk_level,
        risk_score=journey_risk.overall_risk_score,
        top_risk_reasons=_collect_top_reasons(top_risky),
        extra_care_when=_extra_care_sentence(top_risky),
        weather_coverage_note=_weather_coverage_note(journey_risk.usable_weather_segment_count, total_segments),
        trip_summary_line=_trip_summary_line(
            journey_risk.overall_risk_level,
            journey_risk.darkness_total_minutes,
            route.estimated_duration_minutes,
            journey_risk.daylight_total_minutes,
            dark_dur),

        has_daylight=journey_risk.daylight_total_minutes > 0,
        dark_from=dark_from,
        dark_to=dark_to,
        twilight_from=twilight_from,
        darkness_duration=dark_dur,
        daylight_duration=light_dur,
        distance_in_dark=f"{journey_risk.darkness_total_km} km",
        darkness_events=[_darkness_event_sentence(transition) for transition in evidence.darkness_transitions],
        surface_change_descriptions=[_surface_change_sentence(change) for change in evidence.surface_changes])
