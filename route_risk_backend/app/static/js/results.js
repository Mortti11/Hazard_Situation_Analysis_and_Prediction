// ═════════════════════════════════════════════════════════════════════
// results.js — Sidebar result renderer (full)
// Depends on: helpers.js (fmtTime, fmtDateTime, fmtHours, stat, esc, riskClass, cleanReason)
// ═════════════════════════════════════════════════════════════════════

function renderResults(data) {
  var el = document.getElementById('results');
  var rs = data.route_summary;
  var jr = data.journey_risk_summary;
  var ev = data.evidence_for_llm;
  var jp = data.journey_presentation || null;
  var html = '';

  // ── Trip summary banner ──
  if (jp && jp.trip_summary_line)
    html += '<div class="trip-summary-banner">' + esc(jp.trip_summary_line) + '</div>';

  // ── Journey at a Glance ──
  html += '<div class="result-card"><h2>Journey at a Glance</h2><div class="stat-grid">';
  html += stat('From',      jp ? jp.departure_place   : rs.departure);
  html += stat('To',        jp ? jp.destination_place  : rs.destination);
  html += stat('Leaving',   jp ? jp.departure_local_time : fmtTime(rs.departure_time));
  html += stat('Arrival',   jp ? jp.arrival_local_time   : fmtTime(rs.arrival_time));
  html += stat('Distance',  jp ? jp.total_distance       : rs.total_distance_km + ' km');
  html += stat('Duration',  jp ? jp.total_duration        : rs.estimated_duration_minutes + ' min');
  html += stat('Checkpoints', jp ? jp.route_checkpoints  : ev.total_segments);
  html += stat('Spacing',     jp ? jp.checkpoint_interval : '~every 5 min');
  html += '</div></div>';

  // ── Risk Assessment ──
  html += '<div class="result-card card-risk"><h2>Risk Assessment</h2><div class="stat-grid">';
  var rl = jp ? jp.overall_risk : jr.overall_risk_level;
  html += '<div class="stat"><div class="label">Overall risk</div><div class="value">' +
          '<span class="risk-badge ' + riskClass(rl) + '">' + rl.charAt(0).toUpperCase() + rl.slice(1) + '</span>' +
          ' (' + (jp ? jp.risk_score : jr.overall_risk_score) + ')' +
          '</div></div>';
  var reasons = jp && jp.top_risk_reasons && jp.top_risk_reasons.length ? jp.top_risk_reasons : [];
  if (reasons.length) {
    html += '<div class="stat" style="grid-column:1/-1"><div class="label">Main reasons</div>' +
            '<ul style="margin:.2rem 0 0 1rem;font-size:.83rem">';
    for (var ri = 0; ri < reasons.length; ri++) html += '<li>' + esc(reasons[ri]) + '</li>';
    html += '</ul></div>';
  }
  if (jp && jp.extra_care_when)       html += stat('Extra care needed', jp.extra_care_when);
  if (jp && jp.weather_coverage_note) html += stat('Weather coverage',  jp.weather_coverage_note);
  if (jr.poor_weather_segment_count > 0) html += stat('Poor road cond.', jr.poor_weather_segment_count + ' checkpoints');
  if (jr.slippery_segment_count > 0)     html += stat('Slippery',        jr.slippery_segment_count + ' checkpoints');
  html += '</div></div>';

  // ── Weather Details (new: snow/rain/fog/wind breakdown) ──
  var wxSegs = data.segment_risks || [];
  var wxS = {snowIce:0, wet:0, highWind:0, lowFric:0, minRoadT:null, maxWind:null};
  for (var wi = 0; wi < wxSegs.length; wi++) {
    var ws = wxSegs[wi];
    var sf = (ws.surface_condition || '').toLowerCase();
    if (ws.winter_slipperiness || sf === 'snow' || sf === 'ice' || sf === 'frost') wxS.snowIce++;
    if (sf === 'wet' || sf === 'slush') wxS.wet++;
    if (ws.wind_speed_ms && ws.wind_speed_ms >= 10) wxS.highWind++;
    var fc = (ws.friction_condition || '').toLowerCase();
    if (fc.indexOf('low') >= 0 || fc === 'slippery') wxS.lowFric++;
    if (ws.road_temperature_c != null && (wxS.minRoadT === null || ws.road_temperature_c < wxS.minRoadT))
      wxS.minRoadT = ws.road_temperature_c;
    if (ws.wind_speed_ms != null && (wxS.maxWind === null || ws.wind_speed_ms > wxS.maxWind))
      wxS.maxWind = ws.wind_speed_ms;
  }
  if (wxS.snowIce || wxS.wet || wxS.highWind || wxS.lowFric) {
    html += '<div class="result-card card-weather"><h2>&#x1F321;&#xFE0F; Weather Conditions</h2><div class="stat-grid">';
    if (wxS.snowIce)  html += stat('&#x2744;&#xFE0F; Snow/Ice', wxS.snowIce + ' segs');
    if (wxS.wet)      html += stat('&#x1F327;&#xFE0F; Wet/Slush', wxS.wet + ' segs');
    if (wxS.highWind) html += stat('&#x1F4A8; High wind', wxS.highWind + ' segs');
    if (wxS.lowFric)  html += stat('&#x1F9CA; Low friction', wxS.lowFric + ' segs');
    if (wxS.minRoadT !== null) html += stat('&#x1F321;&#xFE0F; Min road temp', wxS.minRoadT + ' &deg;C');
    if (wxS.maxWind !== null)  html += stat('&#x1F4A8; Max wind', wxS.maxWind + ' m/s');
    html += '</div></div>';
  }

  // ── Top Risky Locations ──
  if (data.top_risky_parts && data.top_risky_parts.length) {
    html += '<div class="result-card"><h2>Top Risky Locations</h2>';
    for (var tri = 0; tri < data.top_risky_parts.length; tri++) {
      var p  = data.top_risky_parts[tri];
      var sr = data.segment_risks ? data.segment_risks[p.segment_id] : null;
      var road = p.road_name || 'Unknown road';
      var ts   = p.estimated_time ? fmtTime(p.estimated_time) : '';
      var meta = [];
      if (sr && sr.speed_limit_kmh) meta.push(sr.speed_limit_kmh + ' km/h');
      if (sr) meta.push(sr.road_lit ? 'lit' : 'unlit');
      html += '<div class="risky-part border-' + (p.risk_level || 'moderate').toLowerCase() + '">';
      html += '<div class="seg-header">' + esc(road) + ' &mdash; <span class="risk-badge ' + riskClass(p.risk_level) + '">' +
              p.risk_level + '</span>' + (meta.length ? ' — ' + meta.join(', ') : '') + '</div>';
      if (ts) html += '<div class="seg-time">Around ' + ts + '</div>';
      var cr = p.reasons.map(cleanReason).filter(Boolean);
      if (cr.length) html += '<ul>' + cr.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
      html += '</div>';
    }
    html += '</div>';
  }

  // ── Darkness & Light ──
  var hasDk   = jp && ((jp.darkness_events && jp.darkness_events.length) || jp.dark_from || jp.twilight_from);
  var hasDkFb = ev.darkness_transitions && ev.darkness_transitions.length;
  if (hasDk || hasDkFb) {
    html += '<div class="result-card card-dark"><h2>&#x1F319; Darkness &amp; Light</h2>';
    var dkD = jp ? jp.darkness_duration : fmtHours((ev.darkness_total_minutes || 0) * 60);
    var dkK = jp ? jp.distance_in_dark  : (ev.darkness_total_km || 0) + ' km';
    var dyD = jp ? jp.daylight_duration  : fmtHours((ev.daylight_total_minutes || 0) * 60);
    var dyK = ev.daylight_total_km || 0;
    var noDay = jp && jp.has_daylight === false;
    html += '<p style="font-size:.84rem;color:#636e72;margin-bottom:.6rem">' +
            'Dark/twilight: <strong>' + dkD + '</strong> (' + dkK + ') &bull; ' +
            (noDay ? '<em>No daylight on this journey</em>' :
                     'Daylight: <strong>' + dyD + '</strong> (' + dyK + ' km)') + '</p>';
    if (jp && jp.darkness_events && jp.darkness_events.length) {
      for (var dei = 0; dei < jp.darkness_events.length; dei++) {
        var s = jp.darkness_events[dei];
        var ico = s.indexOf('Dark') === 0 ? '&#x263E; ' : s.indexOf('Twi') === 0 ? '&#x1F318; ' : '&#x2600;&#xFE0F; ';
        html += '<div class="risky-part"><div class="seg-header">' + ico + esc(s) + '</div></div>';
      }
    } else if (hasDkFb) {
      var labels2 = {enters_darkness: 'Darkness begins', enters_twilight: 'Twilight begins',
                     exits_darkness: 'Returns to daylight', exits_twilight: 'Returns to daylight'};
      for (var dt2 = 0; dt2 < ev.darkness_transitions.length; dt2++) {
        var t2 = ev.darkness_transitions[dt2];
        var ico2 = t2.event.indexOf('enters') >= 0 ? (t2.event.indexOf('twilight') >= 0 ? '&#x1F318;' : '&#x263E;') : '&#x2600;&#xFE0F;';
        var lbl2 = labels2[t2.event] || t2.event;
        html += '<div class="risky-part"><div class="seg-header">' + ico2 + ' ' + lbl2 + ' at ' +
                fmtTime(t2.timestamp) + (t2.road_name ? ' near ' + esc(t2.road_name) : '') + '</div></div>';
      }
    }
    if (jr.moose_risk_segment_count > 0) {
      var pct = Math.round(jr.moose_risk_segment_count / ev.total_segments * 100);
      html += '<div class="wildlife-warning">&#x26A0;&#xFE0F; Wildlife/moose risk on ' +
              pct + '% of the route (' + jr.moose_risk_segment_count + ' checkpoints on unlit rural roads)</div>';
    }
    html += '</div>';
  }

  // ── Road Surface Changes ──
  var hasSJ = jp && jp.surface_change_descriptions && jp.surface_change_descriptions.length;
  var hasSF = ev.surface_changes && ev.surface_changes.length;
  if (hasSJ || hasSF) {
    html += '<div class="result-card card-surface"><h2>&#x1F6E3;&#xFE0F; Road Surface Changes</h2>';
    if (hasSJ) {
      for (var sci = 0; sci < jp.surface_change_descriptions.length; sci++)
        html += '<div class="risky-part">' + esc(jp.surface_change_descriptions[sci]) + '</div>';
    } else {
      for (var sc2 = 0; sc2 < ev.surface_changes.length; sc2++) {
        var cv = ev.surface_changes[sc2];
        html += '<div class="risky-part">Around ' + fmtTime(cv.timestamp) + ' near ' +
                esc(cv.road_name || 'km ' + cv.km) + ', road changes from ' +
                esc(cv.from_condition.replace(/_/g, ' ')) + ' to ' +
                esc(cv.to_condition.replace(/_/g, ' ')) + '</div>';
      }
    }
    html += '</div>';
  }

  // ── Speed Limit Changes ──
  if (ev.speed_zone_changes && ev.speed_zone_changes.length) {
    html += '<div class="result-card card-speed"><details><summary><h2 style="display:inline">&#x26A1; Speed Limit Changes (' +
            ev.speed_zone_changes.length + ')</h2></summary><div style="margin-top:.5rem">';
    for (var szi2 = 0; szi2 < ev.speed_zone_changes.length; szi2++) {
      var sz2   = ev.speed_zone_changes[szi2];
      var isUp  = sz2.to_speed > sz2.from_speed;
      var arr2  = isUp ? '<span class="speed-up">&#x25B2;</span>' : '<span class="speed-down">&#x25BC;</span>';
      html += '<div class="risky-part">' + arr2 + ' ' + sz2.from_speed + ' &#x2192; ' +
              sz2.to_speed + ' km/h at ' + fmtTime(sz2.timestamp) +
              (sz2.road_name ? ' near ' + esc(sz2.road_name) : '') + '</div>';
    }
    html += '</div></details></div>';
  }

  // ── Traffic Incidents (Fintraffic) ──
  var incidents = data.traffic_incidents || [];
  if (incidents.length) {
    html += '<div class="result-card card-incidents"><h2>&#x1F6A8; Traffic Incidents Near Route</h2>';
    html += '<p style="font-size:.78rem;color:#636e72;margin-bottom:.6rem">' +
            incidents.length + ' incident' + (incidents.length > 1 ? 's' : '') +
            ' within 5 km of your route (Source: Fintraffic, CC BY 4.0)</p>';
    for (var inci = 0; inci < incidents.length; inci++) {
      var inc = incidents[inci];
      var incSt = (inc.status || 'unknown').toLowerCase();
      var statusCls, statusTxt;
      if (incSt === 'preliminary')      { statusCls = 'risk-high';     statusTxt = 'Preliminary'; }
      else if (incSt === 'confirmed')   { statusCls = 'risk-critical'; statusTxt = 'Confirmed'; }
      else if (incSt === 'situation_over') { statusCls = 'risk-low';   statusTxt = 'Situation Over'; }
      else                              { statusCls = 'risk-moderate'; statusTxt = 'Unknown'; }
      html += '<div class="risky-part">';
      html += '<div class="seg-header"><span class="risk-badge ' + statusCls + '">' + statusTxt + '</span> ' + esc(inc.title) + '</div>';
      if (inc.features && inc.features.length) {
        html += '<ul>';
        for (var ifi = 0; ifi < inc.features.length; ifi++) {
          html += '<li>' + esc(inc.features[ifi]) + '</li>';
        }
        html += '</ul>';
      }
      var incMeta = [];
      if (inc.start_time) incMeta.push('Started: ' + fmtDateTime(inc.start_time));
      if (inc.end_time) incMeta.push('Ends: ' + fmtDateTime(inc.end_time));
      incMeta.push(Math.round(inc.distance_from_route_m) + ' m from route');
      html += '<div style="font-size:.75rem;color:#636e72">' + incMeta.join(' &bull; ') + '</div>';
      html += '</div>';
    }
    html += '</div>';
  }

  // ── AI Summary ──
  if (data.ai_summary) {
    var ai = data.ai_summary;
    html += '<div class="result-card ai-card"><h2>&#x2728; AI Summary</h2>';
    html += '<p>' + esc(ai.summary) + '</p>';
    if (ai.key_risks && ai.key_risks.length) {
      html += '<div class="ai-label">Key Risks</div><ul>' +
              ai.key_risks.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
    }
    if (ai.advice && ai.advice.length) {
      html += '<div class="ai-label">Advice</div><ul>' +
              ai.advice.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
    }
    if (ai.unknowns && ai.unknowns.length) {
      html += '<div class="ai-label">Unknowns</div><ul>' +
              ai.unknowns.map(function (r) { return '<li>' + esc(r) + '</li>'; }).join('') + '</ul>';
    }
    if (ai.confidence_note) {
      html += '<div class="confidence">' + esc(ai.confidence_note) + '</div>';
    }
    html += '</div>';
  } else if (data.ai_summary_error) {
    html += '<div class="error-box">' + esc(data.ai_summary_error) + '</div>';
  }

  el.innerHTML = html;
  el.style.display = 'block';
}
