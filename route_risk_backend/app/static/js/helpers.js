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

function cleanReason(r) {
  return (r || '').replace(/_/g, ' ');
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

// HGV total stopping distance in metres (reaction 1.0s + air-brake lag 0.5s + v²/(2·μ·g)).
// μ values are HGV-specific conservative refs (SWOV / Finnish road-friction studies).
// Returns null if speed or surface is unknown — never fakes a number.
function hgvStopDist(speedKmh, surface, friction) {
  if (!speedKmh) return null;
  var s = (surface || '').toLowerCase();
  var f = (friction || '').toUpperCase();
  var mu;
  if (f === 'VERY_SLIPPERY' || s === 'ice' || s === 'frost' || s === 'partly_icy') mu = 0.10;
  else if (f === 'SLIPPERY' || s === 'snow' || s === 'slush') mu = 0.20;
  else if (s === 'wet' || s === 'moist') mu = 0.35;
  else if (s === 'dry') mu = 0.55;
  else return null;
  var v = speedKmh / 3.6;
  return Math.round(1.5 * v + (v * v) / (2 * mu * 9.81));
}

function stat(label, value, extra) {
  return '<div class="stat">' +
    '<div class="label">' + label + '</div>' +
    '<div class="value">' + (value != null ? value : '—') + (extra || '') + '</div>' +
    '</div>';
}
