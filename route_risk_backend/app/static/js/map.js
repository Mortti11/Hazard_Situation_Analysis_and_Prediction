// ═════════════════════════════════════════════════════════════════════
// map.js — Map initialization, icons, pick mode, polyline decoder
// ═════════════════════════════════════════════════════════════════════

// ── Constants ───────────────────────────────────────────────────────
// FI_TZ is defined in helpers.js (loaded before this file)
const RISK_COLORS = {low:'#2ecc71', moderate:'#f1c40f', high:'#e67e22', critical:'#e74c3c'};
const RISK_WEIGHT = {low:4, moderate:5, high:7, critical:8};

// ── Map Init — centred on Finland ───────────────────────────────────
const map = L.map('map', {zoomControl: true}).setView([64.0, 26.0], 5);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  attribution: '&copy; OpenStreetMap contributors',
  maxZoom: 18
}).addTo(map);

// ── Layer groups for toggle control ─────────────────────────────────
const routeGroup    = L.layerGroup().addTo(map);
const darknessGroup = L.layerGroup().addTo(map);
const surfaceGroup  = L.layerGroup().addTo(map);
const speedGroup    = L.layerGroup().addTo(map);
const mooseGroup    = L.layerGroup().addTo(map);
const topRiskGroup  = L.layerGroup().addTo(map);
const weatherGroup  = L.layerGroup().addTo(map);
const incidentGroup = L.layerGroup().addTo(map);
const lightingGroup = L.layerGroup().addTo(map);

L.control.layers(null, {
  '&#x1F6E4;&#xFE0F; Route & Segments': routeGroup,
  '&#x1F319; Darkness / Light':          darknessGroup,
  '&#x1F4A1; Road Lighting':             lightingGroup,
  '&#x1F326;&#xFE0F; Weather Conditions': weatherGroup,
  '&#x1F6E3;&#xFE0F; Road Surface':      surfaceGroup,
  '&#x26A1; Speed Zones':                speedGroup,
  '&#x1F98C; Wildlife / Moose':          mooseGroup,
  '&#x26A0;&#xFE0F; Top Risk Areas':     topRiskGroup,
  '&#x1F6A8; Traffic Incidents':          incidentGroup,
}, {position: 'topright', collapsed: true}).addTo(map);

// ── Legend ───────────────────────────────────────────────────────────
const legend = L.control({position: 'bottomleft'});
legend.onAdd = function () {
  var d = L.DomUtil.create('div', 'map-legend');
  d.innerHTML =
    '<h4>Segment Risk Level</h4>' +
    '<div class="legend-grid">' +
    '<div class="legend-item"><span class="swatch" style="background:#2ecc71"></span> Low (&lt;0.25)</div>' +
    '<div class="legend-item"><span class="swatch" style="background:#f1c40f"></span> Moderate (0.25\u20130.49)</div>' +
    '<div class="legend-item"><span class="swatch" style="background:#e67e22"></span> High (0.50\u20130.74)</div>' +
    '<div class="legend-item"><span class="swatch" style="background:#e74c3c"></span> Critical (&ge;0.75)</div>' +
    '</div>' +
    '<div class="legend-divider"></div>' +
    '<h4>Map Markers</h4>' +
    '<div class="legend-grid cols-2">' +
    '<div class="legend-item"><span class="legend-dot" style="background:#27ae60"></span> Departure</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#e74c3c"></span> Destination</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#2c3e50"></span> Darkness</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#f39c12"></span> Daylight</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#795548"></span> Surface</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#2980b9"></span> Speed zone</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#2e7d32"></span> Wildlife</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#c0392b"></span> High risk</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#d32f2f"></span> Incident</div>' +
    '</div>' +
    '<div class="legend-divider"></div>' +
    '<h4>Road Lighting</h4>' +
    '<div class="legend-grid cols-2">' +
    '<div class="legend-item"><span class="swatch" style="background:linear-gradient(90deg,#ffb300,#ffd54f);border:1px solid #f9a825"></span> Lit road</div>' +
    '<div class="legend-item"><span class="swatch" style="background:#263238;border:1px solid #37474f;background-image:repeating-linear-gradient(90deg,#263238 0 4px,transparent 4px 7px)"></span> Unlit road</div>' +
    '</div>' +
    '<div class="legend-divider"></div>' +
    '<h4>Weather</h4>' +
    '<div class="legend-grid cols-3">' +
    '<div class="legend-item"><span class="legend-dot" style="background:#4fc3f7"></span> Snow</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#0984e3"></span> Rain</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#78909c"></span> Fog</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#00897b"></span> Wind</div>' +
    '<div class="legend-item"><span class="legend-dot" style="background:#7e57c2"></span> Friction</div>' +
    '</div>';
  return d;
};
legend.addTo(map);

// ═════════════════════════════════════════════════════════════════════
// ICON FACTORY — Professional SVG-based map markers
// Uses clean vector paths (Material Design, Apache 2.0) for consistent
// cross-platform rendering. No emoji — pure SVG.
// ═════════════════════════════════════════════════════════════════════
var _SVG = {
  truck:  '<path d="M20 8h-3V4H3c-1.1 0-2 .9-2 2v11h2c0 1.66 1.34 3 3 3s3-1.34 3-3h6c0 1.66 1.34 3 3 3s3-1.34 3-3h2v-5l-3-4zM6 18.5c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5zm13.5-9l1.96 2.5H17V9.5h2.5zm-1.5 9c-.83 0-1.5-.67-1.5-1.5s.67-1.5 1.5-1.5 1.5.67 1.5 1.5-.67 1.5-1.5 1.5z"/>',
  flag:   '<path d="M14.4 6L14 4H5v17h2v-7h5.6l.4 2h7V6z"/>',
  moon:   '<path d="M9.5 2c-1.82 0-3.53.5-5 1.35 2.99 1.73 5 5.01 5 8.65s-2.01 6.92-5 8.65C5.97 21.5 7.68 22 9.5 22c5.52 0 10-4.48 10-10S15.02 2 9.5 2z"/>',
  moonQ:  '<path d="M12 2C6.48 2 2 6.48 2 12s4.48 10 10 10 10-4.48 10-10S17.52 2 12 2zm0 18V4c4.41 0 8 3.59 8 8s-3.59 8-8 8z"/>',
  sun:    '<path d="M6.76 4.84l-1.8-1.79-1.41 1.41 1.79 1.79 1.42-1.41zM4 10.5H1v2h3v-2zm9-9.95h-2V3.5h2V.55zm7.45 3.91l-1.41-1.41-1.79 1.79 1.41 1.41 1.79-1.79zm-3.21 13.7l1.79 1.8 1.41-1.41-1.8-1.79-1.4 1.4zM20 10.5v2h3v-2h-3zm-8-5c-3.31 0-6 2.69-6 6s2.69 6 6 6 6-2.69 6-6-2.69-6-6-6zm-1 16.95h2V19.5h-2v2.95zm-7.45-3.91l1.41 1.41 1.79-1.8-1.41-1.41-1.79 1.8z"/>',
  road:   '<path d="M11 4h2v4h-2zm0 6h2v4h-2zm0 6h2v4h-2zM5 4l2.5 16h1.5L6.5 4zm8 0l2.5 16h1.5L14.5 4z"/>',
  bolt:   '<path d="M11 21h-1l1-7H7.5c-.58 0-.36-.53-.19-.78C8.48 10.94 10.42 7.54 13 3h1l-1 7h3.5c.4 0 .62.19.4.66C12.97 17.55 11 21 11 21z"/>',
  alert:  '<path d="M1 21h22L12 2 1 21zm12-3h-2v-2h2v2zm0-4h-2v-4h2v4z"/>',
  snow:   '<path d="M22 11h-4.17l3.24-3.24-1.41-1.42L15 11h-2V9l4.66-4.66-1.42-1.41L13 6.17V2h-2v4.17L7.76 2.93 6.34 4.34 11 9v2H9L4.34 6.34 2.93 7.76 6.17 11H2v2h4.17l-3.24 3.24 1.41 1.42L9 13h2v2l-4.66 4.66 1.42 1.41L11 17.83V22h2v-4.17l3.24 3.24 1.42-1.41L13 15v-2h2l4.66 4.66 1.41-1.42L17.83 13H22z"/>',
  drop:   '<path d="M12 2c-5.33 4.55-8 8.48-8 11.8 0 4.98 3.8 8.2 8 8.2s8-3.22 8-8.2c0-3.32-2.67-7.25-8-11.8z"/>',
  wind:   '<path d="M14.5 17c0 1.65-1.35 3-3 3s-3-1.35-3-3h2c0 .55.45 1 1 1s1-.45 1-1-.45-1-1-1H2v-2h9.5c1.65 0 3 1.35 3 3zM19 6.5C19 4.57 17.43 3 15.5 3S12 4.57 12 6.5h2c0-.83.67-1.5 1.5-1.5s1.5.67 1.5 1.5S16.33 8 15.5 8H2v2h13.5c1.93 0 3.5-1.57 3.5-3.5zm-2.5 6H2v2h14.5c.83 0 1.5.67 1.5 1.5s-.67 1.5-1.5 1.5-1.5-.67-1.5-1.5H13c0 1.93 1.57 3.5 3.5 3.5s3.5-1.57 3.5-3.5-1.57-3.5-3.5-3.5z"/>',
  crystal:'<path d="M12 2l-5.5 9L12 20l5.5-9z"/>',
  fog:    '<path d="M3 15h18v-2H3zm0 4h18v-2H3zm0-8h18V9H3zm0-6v2h18V5z"/>',
  deer:   '<path d="M18 4l-2 3-1-1-2 1h-2L9 6 7 7 5 4 3 6l3 3v3l-2 2v4.5c0 .83.67 1.5 1.5 1.5h2c.83 0 1.5-.67 1.5-1.5V16l2-1.5L13 16v2.5c0 .83.67 1.5 1.5 1.5h2c.83 0 1.5-.67 1.5-1.5V14l-2-2V9l3-3z"/>',
  incident:'<path d="M7 18c-1.1 0-1.99.9-1.99 2S5.9 22 7 22s2-.9 2-2-.9-2-2-2zm10 0c-1.1 0-1.99.9-1.99 2S15.9 22 17 22s2-.9 2-2-.9-2-2-2zm-1.45-5c.75 0 1.41-.41 1.75-1.03l3.58-6.49A1.003 1.003 0 0019 4H5.21l-.94-2H1v2h2l3.6 7.59-1.35 2.44C4.52 15.37 5.48 17 7 17h12v-2H7l1.1-2h7.45z"/>',
};

/**
 * Create a pin marker with tail (for key locations: departure, destination, top risk).
 * Renders a coloured circle with white SVG icon, plus a pointed tail below.
 */
function mkPin(svgInner, bg, sz) {
  sz = sz || 36;
  var r = sz / 2, tailH = Math.round(sz * 0.28), totalH = sz + tailH;
  var iconSz = Math.round(sz * 0.44), iconOff = (sz - iconSz) / 2;
  var sc = (iconSz / 24).toFixed(3);
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + sz + '" height="' + totalH +
    '" viewBox="0 0 ' + sz + ' ' + totalH + '" style="filter:drop-shadow(0 2px 4px rgba(0,0,0,.35))">' +
    '<circle cx="' + r + '" cy="' + r + '" r="' + (r - 1.5) + '" fill="' + bg + '" stroke="#fff" stroke-width="2.5"/>' +
    '<polygon points="' + (r - 5) + ',' + (sz - 4) + ' ' + r + ',' + totalH + ' ' + (r + 5) + ',' + (sz - 4) + '" fill="' + bg + '"/>' +
    '<g transform="translate(' + iconOff + ',' + iconOff + ') scale(' + sc + ')" fill="#fff">' + svgInner + '</g></svg>';
  return L.divIcon({
    className: '',
    html: svg,
    iconSize: [sz, totalH],
    iconAnchor: [r, totalH],
    popupAnchor: [0, -totalH + 4]
  });
}

/**
 * Create a dot marker (no tail) for condition indicators on the route.
 * Renders a coloured circle with a centred white SVG icon.
 */
function mkDot(svgInner, bg, sz) {
  sz = sz || 28;
  var r = sz / 2;
  var iconSz = Math.round(sz * 0.48), iconOff = (sz - iconSz) / 2;
  var sc = (iconSz / 24).toFixed(3);
  var svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + sz + '" height="' + sz +
    '" viewBox="0 0 ' + sz + ' ' + sz + '" style="filter:drop-shadow(0 1px 3px rgba(0,0,0,.3))">' +
    '<circle cx="' + r + '" cy="' + r + '" r="' + (r - 1) + '" fill="' + bg + '" stroke="#fff" stroke-width="2"/>' +
    '<g transform="translate(' + iconOff + ',' + iconOff + ') scale(' + sc + ')" fill="#fff">' + svgInner + '</g></svg>';
  return L.divIcon({
    className: '',
    html: svg,
    iconSize: [sz, sz],
    iconAnchor: [r, r],
    popupAnchor: [0, -r]
  });
}

const ICONS = {
  departure:       mkPin(_SVG.truck, '#27ae60', 42),
  destination:     mkPin(_SVG.flag, '#e74c3c', 42),
  entersDark:      mkDot(_SVG.moon, '#2c3e50', 30),
  entersTwilight:  mkDot(_SVG.moonQ, '#546e7a', 28),
  exitsDark:       mkDot(_SVG.sun, '#f39c12', 30),
  surfaceChange:   mkDot(_SVG.road, '#795548', 28),
  speedChange:     mkDot(_SVG.bolt, '#2980b9', 28),
  mooseRisk:       mkDot(_SVG.deer, '#2e7d32', 32),
  topRisk:         mkPin(_SVG.alert, '#c0392b', 34),
  checkpoint:      mkDot('<circle cx="12" cy="12" r="5"/>', '#607d8b', 18),
  // Weather overlay icons
  snow:            mkDot(_SVG.snow, '#4fc3f7', 26),
  rain:            mkDot(_SVG.drop, '#0984e3', 26),
  fog:             mkDot(_SVG.fog, '#78909c', 26),
  wind:            mkDot(_SVG.wind, '#00897b', 26),
  ice:             mkDot(_SVG.crystal, '#7e57c2', 26),
  // Traffic incidents
  incidentActive:  mkPin(_SVG.incident, '#d32f2f', 34),
  incidentEnded:   mkDot(_SVG.incident, '#78909c', 26),
};

// ═════════════════════════════════════════════════════════════════════
// PICK DEPARTURE / DESTINATION FROM MAP — smooth auto-advance flow
// ═════════════════════════════════════════════════════════════════════
let pickMode = null;
let pickDepMarker = null, pickDestMarker = null;

function startPick(type) {
  pickMode = type;
  document.getElementById('pick-dep-btn').classList.toggle('active', type === 'departure');
  document.getElementById('pick-dest-btn').classList.toggle('active', type === 'destination');
  map.getContainer().style.cursor = 'crosshair';
  document.getElementById('pick-hint').textContent = 'Click on the map to set ' + type;
  document.getElementById('pick-hint').style.opacity = '1';
}

function endPick() {
  pickMode = null;
  document.getElementById('pick-dep-btn').classList.remove('active');
  document.getElementById('pick-dest-btn').classList.remove('active');
  map.getContainer().style.cursor = '';
  document.getElementById('pick-hint').textContent = 'Click buttons then click map, or type addresses in sidebar';
}

function clearDeparture() {
  document.getElementById('departure').value = '';
  if (pickDepMarker) { map.removeLayer(pickDepMarker); pickDepMarker = null; }
}

function clearDestination() {
  document.getElementById('destination').value = '';
  if (pickDestMarker) { map.removeLayer(pickDestMarker); pickDestMarker = null; }
}

map.on('click', function (e) {
  if (!pickMode) return;
  var lat = e.latlng.lat, lng = e.latlng.lng;
  var type = pickMode;
  if (type === 'departure') {
    if (pickDepMarker) map.removeLayer(pickDepMarker);
    pickDepMarker = L.marker([lat, lng], {icon: ICONS.departure, draggable: true}).addTo(map);
    pickDepMarker.on('dragend', function () { reverseGeocode(pickDepMarker.getLatLng(), 'departure'); });
  } else {
    if (pickDestMarker) map.removeLayer(pickDestMarker);
    pickDestMarker = L.marker([lat, lng], {icon: ICONS.destination, draggable: true}).addTo(map);
    pickDestMarker.on('dragend', function () { reverseGeocode(pickDestMarker.getLatLng(), 'destination'); });
  }
  reverseGeocode({lat: lat, lng: lng}, type);
  endPick();

  // Auto-advance: after setting departure, jump to destination pick if empty
  if (type === 'departure' && !document.getElementById('destination').value.trim()) {
    setTimeout(function () { startPick('destination'); }, 300);
  }
});

document.addEventListener('keydown', function (e) { if (e.key === 'Escape') endPick(); });

async function reverseGeocode(ll, field) {
  var inp = document.getElementById(field);
  inp.value = ll.lat.toFixed(4) + ', ' + ll.lng.toFixed(4);  // immediate feedback
  try {
    var r = await fetch(
      'https://nominatim.openstreetmap.org/reverse?lat=' + ll.lat +
      '&lon=' + ll.lng + '&format=json&zoom=10&addressdetails=1&accept-language=en'
    );
    var d = await r.json();
    if (d.address) {
      var a = d.address;
      var city = a.city || a.town || a.village || a.municipality || '';
      var road = a.road || '';
      inp.value = city ? (road ? road + ', ' + city : city) : (d.display_name || '').split(',').slice(0, 3).join(',');
    }
  } catch (err) { console.warn('Reverse geocode failed:', err); }
}

// ═════════════════════════════════════════════════════════════════════
// POLYLINE DECODER (Google / ORS encoding)
// ═════════════════════════════════════════════════════════════════════
function decodePolyline(enc) {
  var pts = [], idx = 0, lat = 0, lng = 0;
  while (idx < enc.length) {
    for (var ci = 0; ci < 2; ci++) {
      var shift = 0, result = 0;
      while (true) {
        var b = enc.charCodeAt(idx++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
        if (b < 0x20) break;
      }
      var delta = (result & 1) ? ~(result >> 1) : (result >> 1);
      if (ci === 0) lat += delta; else lng += delta;
    }
    pts.push([lat / 1e5, lng / 1e5]);
  }
  return pts;
}
