// ═════════════════════════════════════════════════════════════════════
// helpers.js — Formatting & utility functions
// No dependencies
// ═════════════════════════════════════════════════════════════════════

var FI_TZ = 'Europe/Helsinki';

function fmtTime(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleTimeString('fi-FI', {timeZone: FI_TZ, hour: '2-digit', minute: '2-digit'});
}

function fmtDateTime(ts) {
  if (!ts) return '—';
  return new Date(ts).toLocaleString('fi-FI', {
    timeZone: FI_TZ, day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit'
  });
}

function fmtHours(seconds) {
  if (seconds == null) return '—';
  var h = seconds / 3600;
  return h < 1 ? Math.round(h * 60) + ' min' : h.toFixed(1) + ' h';
}

var REASON_CLEAN = [
  [/^speed_limit_low$/i,          'Low speed-limit zone (possible hazard area)'],
  [/^narrow_road$/i,              'Narrow road'],
  [/^darkness$/i,                 'Driving in darkness'],
  [/^twilight$/i,                 'Twilight conditions'],
  [/^unlit_road_dark$/i,          'Unlit road in darkness'],
  [/^poor_surface$/i,             'Poor road surface condition'],
  [/^slippery_surface$/i,         'Slippery / winter surface'],
  [/^high_wind$/i,                'High wind speed'],
  [/^low_road_temp$/i,            'Low road temperature'],
  [/^moose_risk$/i,               'Wildlife / moose risk zone'],
  [/^low_friction$/i,             'Low friction condition'],
  [/^poor_visibility$/i,          'Poor visibility'],
  [/^heavy_precipitation$/i,      'Heavy precipitation'],
  [/^weather_confidence_low$/i,   'Weather forecast confidence low'],
  [/^no_weather$/i,               'No weather data available'],
  [/^combined_darkness_surface$/i,'Combined darkness + poor surface'],
];

function cleanReason(r) {
  for (var i = 0; i < REASON_CLEAN.length; i++) {
    if (REASON_CLEAN[i][0].test(r)) return REASON_CLEAN[i][1];
  }
  return r.replace(/_/g, ' ');
}

function riskClass(level) {
  return 'risk-' + (level || 'unknown').toLowerCase();
}

function esc(str) {
  if (!str) return '';
  var d = document.createElement('div');
  d.appendChild(document.createTextNode(str));
  return d.innerHTML;
}

function stat(label, value, extra) {
  return '<div class="stat">' +
    '<div class="label">' + label + '</div>' +
    '<div class="value">' + (value != null ? value : '—') + (extra || '') + '</div>' +
    '</div>';
}
