// ═════════════════════════════════════════════════════════════════════
// overlays.js — Map overlay renderers + segment popup builder
// Depends on: map.js (map, layer groups, ICONS, decodePolyline, etc.)
// ═════════════════════════════════════════════════════════════════════

function clearMapOverlays() {
  [routeGroup, darknessGroup, surfaceGroup, speedGroup, mooseGroup, topRiskGroup, weatherGroup, incidentGroup, lightingGroup]
    .forEach(function (g) { g.clearLayers(); });
}

function renderMapOverlays(data) {
  clearMapOverlays();
  var pts  = data.sampled_points;
  var segs = data.segment_risks;
  var ev   = data.evidence_for_llm;
  var rs   = data.route_summary;
  if (!pts || pts.length < 2) return;

  // Remove pick markers (route markers replace them)
  if (pickDepMarker)  { map.removeLayer(pickDepMarker);  pickDepMarker = null; }
  if (pickDestMarker) { map.removeLayer(pickDestMarker); pickDestMarker = null; }

  // ── Decode full route polyline & map sampled-points to vertices ──
  // This lets every overlay follow the real road geometry instead of
  // drawing straight lines between sampled points kilometres apart.
  var decoded = rs.encoded_polyline ? decodePolyline(rs.encoded_polyline) : [];

  // Map each sampled point to its nearest vertex in the decoded polyline.
  // Both arrays are route-ordered, so we only scan forward.
  var ptVertexIdx = [];
  if (decoded.length > 0) {
    var searchStart = 0;
    for (var pi = 0; pi < pts.length; pi++) {
      var bestIdx = searchStart;
      var bestDsq = Infinity;
      for (var vi = searchStart; vi < decoded.length; vi++) {
        var dx = decoded[vi][0] - pts[pi].lat;
        var dy = decoded[vi][1] - pts[pi].lon;
        var dsq = dx * dx + dy * dy;
        if (dsq < bestDsq) { bestDsq = dsq; bestIdx = vi; }
        else if (dsq > bestDsq * 4 && vi > bestIdx + 5) break;
      }
      ptVertexIdx.push(bestIdx);
      searchStart = bestIdx;
    }
  }

  /** Return the polyline sub-path between two sampled-point indices. */
  function segPath(fromIdx, toIdx) {
    if (decoded.length === 0 || ptVertexIdx.length === 0) {
      return [[pts[fromIdx].lat, pts[fromIdx].lon],
              [pts[toIdx].lat,   pts[toIdx].lon]];
    }
    var vi1 = ptVertexIdx[fromIdx];
    var vi2 = ptVertexIdx[toIdx];
    if (vi2 <= vi1) vi2 = vi1 + 1;
    var path = [[pts[fromIdx].lat, pts[fromIdx].lon]];
    for (var v = vi1 + 1; v < vi2 && v < decoded.length; v++) {
      path.push(decoded[v]);
    }
    path.push([pts[toIdx].lat, pts[toIdx].lon]);
    return path;
  }

  // ── Full route polyline (gray base) ──
  if (decoded.length > 0) {
    L.polyline(decoded, {color: '#636e72', weight: 3, opacity: 0.3, dashArray: '6 4'}).addTo(routeGroup);
  }

  // ── Risk-colored segment lines ──
  for (var i = 0; i < segs.length; i++) {
    var s  = segs[i];
    var p1 = pts[s.from_point_index];
    var p2 = pts[s.to_point_index];
    if (!p1 || !p2) continue;
    var col = RISK_COLORS[s.risk_level] || '#95a5a6';
    var w   = RISK_WEIGHT[s.risk_level] || 4;
    var line = L.polyline(segPath(s.from_point_index, s.to_point_index), {
      color: col, weight: w, opacity: 0.85
    });
    line.bindPopup(buildSegPopup(s, p1));
    line.addTo(routeGroup);
  }

  // ── Road lighting layer (Digiroad dr_valaistu_tie) ──
  // Renders a wider underlay behind the risk-colored route.
  // Lit = warm bright amber with glow, Unlit = dark with dashed pattern.
  // Note: shows lighting *infrastructure* presence, not real-time lamp status.
  for (var li = 0; li < segs.length; li++) {
    var ls = segs[li];
    var lp1 = pts[ls.from_point_index];
    var lp2 = pts[ls.to_point_index];
    if (!lp1 || !lp2) continue;
    var coords = segPath(ls.from_point_index, ls.to_point_index);
    if (ls.road_lit) {
      // Lit: bright amber outer glow + solid inner
      L.polyline(coords, {
        color: '#ffb300', weight: 16, opacity: 0.25, lineCap: 'round', lineJoin: 'round'
      }).addTo(lightingGroup);
      L.polyline(coords, {
        color: '#ffd54f', weight: 8, opacity: 0.65, lineCap: 'round', lineJoin: 'round'
      }).addTo(lightingGroup);
    } else {
      // Unlit: dark dashed line — clearly different pattern
      L.polyline(coords, {
        color: '#263238', weight: 8, opacity: 0.35, lineCap: 'butt',
        dashArray: '8 6'
      }).addTo(lightingGroup);
    }
    var litLabel = ls.road_lit ? '&#x1F4A1; Lit road (Digiroad)' : '&#x1F311; Unlit road';
    // Invisible wide click target for popup
    var litHit = L.polyline(coords, {
      color: '#000', weight: 16, opacity: 0, interactive: true
    });
    litHit.bindPopup('<b>' + litLabel + '</b><br>Segment #' + (li + 1) +
      '<br><b>Speed:</b> ' + (ls.speed_limit_kmh || '?') + ' km/h' +
      '<br><span style="font-size:.72rem;color:#b2bec3">Source: Digiroad / V\u00e4yl\u00e4virasto (CC BY 4.0)</span>');
    litHit.addTo(lightingGroup);
  }

  // ── Departure & Destination markers ──
  L.marker([pts[0].lat, pts[0].lon], {icon: ICONS.departure})
    .bindPopup('<b>&#x1F69B; Departure</b><br>' + esc(rs.departure) + '<br>' + fmtTime(pts[0].estimated_timestamp))
    .addTo(routeGroup);
  var last = pts[pts.length - 1];
  L.marker([last.lat, last.lon], {icon: ICONS.destination})
    .bindPopup('<b>&#x1F3C1; Destination</b><br>' + esc(rs.destination) + '<br>' + fmtTime(last.estimated_timestamp))
    .addTo(routeGroup);

  // ── Darkness transition markers ──
  var darkTransitions = ev.darkness_transitions || [];
  for (var di = 0; di < darkTransitions.length; di++) {
    var t = darkTransitions[di];
    var isExit = t.event.indexOf('exits') >= 0;
    var isTwi  = t.event.indexOf('twilight') >= 0;
    var icon   = isExit ? ICONS.exitsDark : isTwi ? ICONS.entersTwilight : ICONS.entersDark;
    var labels = {
      enters_darkness:  '&#x1F319; Enters Darkness',
      enters_twilight:  '&#x1F317; Enters Twilight',
      exits_darkness:   '&#x2600;&#xFE0F; Returns to Daylight',
      exits_twilight:   '&#x2600;&#xFE0F; Returns to Daylight'
    };
    var lbl = labels[t.event] || t.event;
    var popup = '<b>' + lbl + '</b>' +
      '<br><b>Time:</b> ' + fmtTime(t.timestamp) +
      '<br><b>km:</b> ' + t.km +
      (t.road_name ? '<br><b>Near:</b> ' + esc(t.road_name) : '');
    L.marker([t.lat, t.lon], {icon: icon}).bindPopup(popup).addTo(darknessGroup);
  }

  // ── Darkness shading on segments (subtle overlay) ──
  for (var di2 = 0; di2 < segs.length; di2++) {
    var ds = segs[di2];
    if (!ds.is_dark && !ds.is_twilight) continue;
    var dp1 = pts[ds.from_point_index];
    var dp2 = pts[ds.to_point_index];
    if (!dp1 || !dp2) continue;
    var dCol = ds.is_dark ? '#1a1a2e' : '#2d3436';
    L.polyline(segPath(ds.from_point_index, ds.to_point_index), {
      color: dCol, weight: 12, opacity: 0.15
    }).addTo(darknessGroup);
  }

  // ── Surface change markers ──
  var surfaceChanges = ev.surface_changes || [];
  for (var si = 0; si < surfaceChanges.length; si++) {
    var c = surfaceChanges[si];
    var from_c = c.from_condition.replace(/_/g, ' ');
    var to_c   = c.to_condition.replace(/_/g, ' ');
    var sPopup = '<b>&#x1F6E3;&#xFE0F; Surface Change</b>' +
      '<br><b>From:</b> ' + esc(from_c) +
      '<br><b>To:</b> ' + esc(to_c) +
      '<br><b>Time:</b> ' + fmtTime(c.timestamp) +
      (c.road_name ? '<br><b>Near:</b> ' + esc(c.road_name) : '');
    L.marker([c.lat, c.lon], {icon: ICONS.surfaceChange}).bindPopup(sPopup).addTo(surfaceGroup);
  }

  // ── Speed zone change markers ──
  var speedChanges = ev.speed_zone_changes || [];
  for (var szi = 0; szi < speedChanges.length; szi++) {
    var sz    = speedChanges[szi];
    var arrow = sz.to_speed > sz.from_speed ? '&#x2B06;' : '&#x2B07;';
    var szPopup = '<b>&#x26A1; Speed Limit Change</b>' +
      '<br>' + sz.from_speed + ' &#x2192; ' + sz.to_speed + ' km/h ' + arrow +
      '<br><b>Time:</b> ' + fmtTime(sz.timestamp) +
      (sz.road_name ? '<br><b>Near:</b> ' + esc(sz.road_name) : '');
    L.marker([sz.lat, sz.lon], {icon: ICONS.speedChange}).bindPopup(szPopup).addTo(speedGroup);
  }

  // ── Moose / wildlife risk zones ──
  var prevMoose = false;
  for (var mi = 0; mi < segs.length; mi++) {
    var ms = segs[mi];
    if (ms.moose_risk && !prevMoose) {
      var mp = pts[ms.from_point_index];
      if (mp) {
        var mPopup = '<b>&#x1F98C; Wildlife / Moose Risk Zone</b>' +
          '<br><b>Speed:</b> ' + (ms.speed_limit_kmh || '?') + ' km/h' +
          '<br><b>Lighting:</b> ' + (ms.road_lit ? '&#x1F4A1; Lit' : 'Unlit road') +
          '<br><b>Time:</b> ' + fmtTime(mp.estimated_timestamp) +
          '<br><span style="font-size:.78rem;color:#636e72">' +
          'Sources: LUKE (Natural Resources Institute Finland),<br>' +
          'Finnish Transport Infrastructure Agency</span>';
        L.marker([mp.lat, mp.lon], {icon: ICONS.mooseRisk}).bindPopup(mPopup).addTo(mooseGroup);
      }
    }
    if (ms.moose_risk) {
      var mp1 = pts[ms.from_point_index];
      var mp2 = pts[ms.to_point_index];
      if (mp1 && mp2) {
        L.polyline(segPath(ms.from_point_index, ms.to_point_index), {
          color: '#d35400', weight: 10, opacity: 0.25, dashArray: '4 8'
        }).addTo(mooseGroup);
      }
    }
    prevMoose = ms.moose_risk;
  }

  // ── Top risky area markers ──
  var topRisky = data.top_risky_parts || [];
  for (var ti = 0; ti < topRisky.length; ti++) {
    var tp  = topRisky[ti];
    var tSeg = segs[tp.segment_id];
    var tPt  = tSeg ? pts[tSeg.from_point_index] : null;
    if (!tPt) continue;
    var tReasons = tp.reasons.map(cleanReason).filter(Boolean);
    var tPopup = '<b>&#x26A0;&#xFE0F; High Risk Area (#' + (ti + 1) + ')</b>' +
      (tp.road_name ? '<br>' + esc(tp.road_name) : '') +
      '<br><b>Score:</b> ' + tp.risk_score + ' (' + tp.risk_level + ')' +
      '<br><b>Time:</b> ' + fmtTime(tp.estimated_time) +
      (tReasons.length ? '<hr style="margin:4px 0">' + tReasons.map(function (r) { return '&bull; ' + esc(r); }).join('<br>') : '');
    L.marker([tPt.lat, tPt.lon], {icon: ICONS.topRisk}).bindPopup(tPopup).addTo(topRiskGroup);
  }

  // ── Weather condition markers (snow, rain, fog, wind, ice) ──
  var prevWxKey = '';
  for (var wi = 0; wi < segs.length; wi++) {
    var ws = segs[wi];
    var wp = pts[ws.from_point_index];
    if (!wp) continue;

    // Determine weather condition icon and label
    var wxIcon = null;
    var wxLabel = '';
    var wxKey = '';
    var surface = (ws.surface_condition || '').toLowerCase();
    var overallCond = (ws.overall_road_condition || '').toLowerCase();
    var frictionCond = (ws.friction_condition || '').toLowerCase();

    if (ws.winter_slipperiness || surface === 'snow' || surface === 'ice' || surface === 'frost') {
      wxIcon = ICONS.snow; wxLabel = '&#x2744;&#xFE0F; Snow/Ice'; wxKey = 'snow';
    } else if (surface === 'wet' || surface === 'slush' || overallCond.indexOf('rain') >= 0) {
      wxIcon = ICONS.rain; wxLabel = '&#x1F327;&#xFE0F; Rain/Wet'; wxKey = 'rain';
    } else if (frictionCond.indexOf('low') >= 0 || frictionCond === 'slippery') {
      wxIcon = ICONS.ice; wxLabel = '&#x1F9CA; Low Friction'; wxKey = 'ice';
    }
    // High wind (>10 m/s)
    if (ws.wind_speed_ms && ws.wind_speed_ms >= 10) {
      if (!wxIcon) { wxIcon = ICONS.wind; wxLabel = '&#x1F4A8; High Wind'; wxKey = 'wind'; }
      else { wxLabel += ' + &#x1F4A8; Wind'; wxKey += '+wind'; }
    }

    // Only place a marker when the condition changes (avoid flooding the map)
    if (wxIcon && wxKey !== prevWxKey) {
      var wxPopup = '<b>' + wxLabel + '</b>';
      if (ws.wind_speed_ms != null)
        wxPopup += '<br><b>Wind:</b> ' + ws.wind_speed_ms + ' m/s';
      if (ws.road_temperature_c != null)
        wxPopup += '<br><b>Road temp:</b> ' + ws.road_temperature_c + ' &deg;C';
      if (ws.air_temperature_c != null)
        wxPopup += '<br><b>Air temp:</b> ' + ws.air_temperature_c + ' &deg;C';
      if (ws.overall_road_condition)
        wxPopup += '<br><b>Condition:</b> ' + esc(ws.overall_road_condition.replace(/_/g, ' '));
      if (ws.friction_condition)
        wxPopup += '<br><b>Friction:</b> ' + esc(ws.friction_condition.replace(/_/g, ' '));
      wxPopup += '<br><b>Time:</b> ' + fmtTime(wp.estimated_timestamp);
      L.marker([wp.lat, wp.lon], {icon: wxIcon}).bindPopup(wxPopup).addTo(weatherGroup);
    }
    prevWxKey = wxKey || prevWxKey;
  }

  // ── Traffic incident markers (Fintraffic) ──
  var incidents = data.traffic_incidents || [];
  for (var ii = 0; ii < incidents.length; ii++) {
    var inc = incidents[ii];
    var incIcon = inc.is_active ? ICONS.incidentActive : ICONS.incidentEnded;
    var statusBadge;
    var st = (inc.status || 'unknown').toLowerCase();
    if (st === 'preliminary')
      statusBadge = '<span style="background:#ff9800;color:#fff;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600">PRELIMINARY</span>';
    else if (st === 'confirmed')
      statusBadge = '<span style="background:#d32f2f;color:#fff;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600">CONFIRMED</span>';
    else if (st === 'situation_over')
      statusBadge = '<span style="background:#78909c;color:#fff;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600">SITUATION OVER</span>';
    else
      statusBadge = '<span style="background:#546e7a;color:#fff;padding:1px 6px;border-radius:3px;font-size:.75rem;font-weight:600">UNKNOWN</span>';
    var incPopup = '<div style="font-size:.82rem;line-height:1.4">' +
      '<div style="font-weight:700;margin-bottom:4px">' + statusBadge + ' Traffic Incident</div>' +
      '<div>' + esc(inc.title) + '</div>';
    if (inc.features && inc.features.length) {
      incPopup += '<div style="margin-top:4px;color:#636e72">';
      for (var ifi = 0; ifi < inc.features.length; ifi++) {
        incPopup += '&bull; ' + esc(inc.features[ifi]) + '<br>';
      }
      incPopup += '</div>';
    }
    if (inc.start_time)
      incPopup += '<div style="margin-top:4px"><b>Started:</b> ' + fmtDateTime(inc.start_time) + '</div>';
    if (inc.end_time)
      incPopup += '<div><b>Ends:</b> ' + fmtDateTime(inc.end_time) + '</div>';
    incPopup += '<div style="font-size:.72rem;color:#b2bec3;margin-top:4px">' +
      Math.round(inc.distance_from_route_m) + ' m from route &bull; Source: Fintraffic (CC BY 4.0)</div>';
    incPopup += '</div>';
    L.marker([inc.lat, inc.lon], {icon: incIcon}).bindPopup(incPopup).addTo(incidentGroup);
  }

  // ── Fit map to route bounds ──
  var bounds = L.latLngBounds(pts.map(function (p) { return [p.lat, p.lon]; }));
  map.fitBounds(bounds, {padding: [40, 40]});
}

// ── Segment popup HTML builder ──────────────────────────────────────
function buildSegPopup(seg, pt) {
  var darkLabel = seg.is_dark ? '&#x1F311; Dark' : seg.is_twilight ? '&#x1F317; Twilight' : '&#x2600;&#xFE0F; Daylight';
  var litLabel  = seg.road_lit ? '&#x1F4A1; Lit road' : 'Unlit road';
  var surface   = (seg.surface_condition || 'unknown').replace(/_/g, ' ');
  var reasons   = seg.reasons.map(cleanReason).filter(Boolean);

  var h = '<div class="seg-popup">';
  h += '<div class="seg-popup-hdr"><span class="risk-badge risk-' + seg.risk_level + '">' +
       seg.risk_level + '</span> Score: ' + seg.risk_score + '</div>';
  h += '<table class="seg-props">';
  h += '<tr><td>&#x1F3CE;&#xFE0F; Speed limit</td><td>' + (seg.speed_limit_kmh || '?') + ' km/h</td></tr>';
  h += '<tr><td>&#x1F4CF; Road width</td><td>' + (seg.road_width_m || '?') + ' m</td></tr>';
  h += '<tr><td>&#x1F6E3;&#xFE0F; Surface</td><td>' + esc(surface) + '</td></tr>';
  h += '<tr><td>' + darkLabel + '</td><td>' + litLabel + '</td></tr>';
  if (seg.road_temperature_c !== null && seg.road_temperature_c !== undefined)
    h += '<tr><td>&#x1F321;&#xFE0F; Road temp</td><td>' + seg.road_temperature_c + ' &deg;C</td></tr>';
  if (seg.air_temperature_c !== null && seg.air_temperature_c !== undefined)
    h += '<tr><td>&#x1F32C;&#xFE0F; Air temp</td><td>' + seg.air_temperature_c + ' &deg;C</td></tr>';
  if (seg.wind_speed_ms !== null && seg.wind_speed_ms !== undefined)
    h += '<tr><td>&#x1F4A8; Wind</td><td>' + seg.wind_speed_ms + ' m/s</td></tr>';
  if (seg.overall_road_condition)
    h += '<tr><td>&#x1F6A7; Road cond.</td><td>' + esc(seg.overall_road_condition.replace(/_/g, ' ').toLowerCase()) + '</td></tr>';
  if (seg.friction_condition)
    h += '<tr><td>&#x1F9CA; Friction</td><td>' + esc(seg.friction_condition.replace(/_/g, ' ').toLowerCase()) + '</td></tr>';
  h += '<tr><td>&#x1F98C; Moose risk</td><td>' + (seg.moose_risk ? '<b style="color:#e74c3c">Yes</b>' : 'No') + '</td></tr>';
  if (seg.weather_confidence && seg.weather_confidence !== 'none')
    h += '<tr><td>&#x1F4E1; Wx confidence</td><td>' + seg.weather_confidence + '</td></tr>';
  if (seg.weather_source)
    h += '<tr><td>&#x1F4E1; Wx source</td><td>' + esc(seg.weather_source) + '</td></tr>';
  h += '</table>';
  if (reasons.length) {
    h += '<div class="seg-reasons">' + reasons.map(function (r) { return '<div>&bull; ' + esc(r) + '</div>'; }).join('') + '</div>';
  }
  h += '</div>';
  return h;
}
