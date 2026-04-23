// ═════════════════════════════════════════════════════════════════════
// form.js — Form handling, route preview, submit, error display
// Depends on: map.js, helpers.js, overlays.js, results.js
// ═════════════════════════════════════════════════════════════════════

var selectedRouteIndex = 0;
var routePreviewGroup = L.layerGroup().addTo(map);

function showError(msg) {
  var el = document.getElementById('results');
  el.innerHTML = '<div class="error-box fatal">' + esc(msg) + '</div>';
  el.style.display = 'block';
}

// ── Route preview & choice ──────────────────────────────────────────
async function showRouteOptions() {
  var dep  = document.getElementById('departure').value.trim();
  var dest = document.getElementById('destination').value.trim();
  if (!dep || !dest) { showError('Please set both departure and destination first.'); return; }

  var routeBar = document.getElementById('route-options-bar');
  routeBar.innerHTML = '<span class="loading-sm">Loading routes&hellip;</span>';
  routeBar.style.display = 'block';
  routePreviewGroup.clearLayers();

  try {
    var url = '/api/v1/route-options?departure=' + encodeURIComponent(dep) +
              '&destination=' + encodeURIComponent(dest);
    var res = await fetch(url);
    if (!res.ok) {
      var err = await res.json().catch(function () { return {detail: res.statusText}; });
      throw new Error(err.detail || 'Failed to load routes');
    }
    var data = await res.json();
    var routes = data.routes || [];
    if (routes.length === 0) { routeBar.innerHTML = '<span>No routes found</span>'; return; }

    // Draw all route polylines on map
    var previewColors = ['#0984e3', '#e17055', '#00b894'];
    var bounds = L.latLngBounds([]);
    for (var i = 0; i < routes.length; i++) {
      var pts = decodePolyline(routes[i].encoded_polyline);
      var isSelected = (i === selectedRouteIndex);
      var line = L.polyline(pts, {
        color: previewColors[i % previewColors.length],
        weight: isSelected ? 6 : 3,
        opacity: isSelected ? 0.9 : 0.4,
        dashArray: isSelected ? null : '8 6',
      });
      line._routeIndex = i;
      line.on('click', function (e) {
        selectRoute(e.target._routeIndex, routes);
      });
      line.addTo(routePreviewGroup);
      bounds.extend(line.getBounds());
    }
    map.fitBounds(bounds, {padding: [40, 40]});

    // Build route option buttons
    var html = '';
    for (var j = 0; j < routes.length; j++) {
      var r = routes[j];
      var label = 'Route ' + (j + 1) + ' — ' + r.distance_km + ' km, ' + Math.round(r.duration_minutes) + ' min';
      var cls = j === selectedRouteIndex ? 'route-opt selected' : 'route-opt';
      html += '<button class="' + cls + '" data-idx="' + j + '" style="border-left-color:' + previewColors[j % previewColors.length] + '">' + label + '</button>';
    }
    routeBar.innerHTML = html;

    // Bind button clicks
    var btns = routeBar.querySelectorAll('.route-opt');
    btns.forEach(function (btn) {
      btn.addEventListener('click', function () {
        selectRoute(parseInt(this.getAttribute('data-idx')), routes);
      });
    });

  } catch (e) {
    routeBar.innerHTML = '<span class="error">' + esc(e.message) + '</span>';
  }
}

function selectRoute(idx, routes) {
  selectedRouteIndex = idx;
  // Update button styles
  var btns = document.querySelectorAll('.route-opt');
  btns.forEach(function (b) { b.classList.toggle('selected', parseInt(b.getAttribute('data-idx')) === idx); });
  // Update polyline styles
  var previewColors = ['#0984e3', '#e17055', '#00b894'];
  routePreviewGroup.eachLayer(function (layer) {
    var isSelected = (layer._routeIndex === idx);
    layer.setStyle({
      weight: isSelected ? 6 : 3,
      opacity: isSelected ? 0.9 : 0.4,
      dashArray: isSelected ? null : '8 6',
    });
    if (isSelected) layer.bringToFront();
  });
}

// ── Submit full analysis ────────────────────────────────────────────
async function submitAnalysis() {
  var dep  = document.getElementById('departure').value.trim();
  var dest = document.getElementById('destination').value.trim();
  var dt   = document.getElementById('departure_time').value;

  if (!dep || !dest) { showError('Please select both departure and destination on the map (or type addresses).'); return; }
  if (!dt) { showError('Please choose a departure date / time.'); return; }

  var resultsEl = document.getElementById('results');
  var btn = document.getElementById('submit-btn');
  resultsEl.innerHTML = '<div class="loading"><div class="spinner"></div><div>Analysing route&hellip; this may take 10-20 s</div></div>';
  resultsEl.style.display = 'block';
  btn.disabled = true;

  // Clear route previews when full analysis starts
  routePreviewGroup.clearLayers();
  document.getElementById('route-options-bar').style.display = 'none';

  try {
    var sampling = parseInt(document.getElementById('sampling').value) || 5;
    var includeAi = document.getElementById('include_ai').checked;
    var url = '/api/v1/route-analysis' + (includeAi ? '?include_ai=true' : '');
    var res = await fetch(url, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        departure: dep,
        destination: dest,
        departure_time: dt + ':00',
        sampling_minutes: sampling,
        route_index: selectedRouteIndex,
      })
    });
    if (!res.ok) {
      var err = await res.json().catch(function () { return {detail: res.statusText}; });
      throw new Error(err.detail || JSON.stringify(err));
    }
    var data = await res.json();
    renderMapOverlays(data);
    renderResults(data);
  } catch (e) {
    showError('Error: ' + e.message);
  } finally {
    btn.disabled = false;
  }
}

// ── Finnish date/time helpers ────────────────────────────────────────
// Finnish format: dd.mm.yyyy — users type naturally in their locale.
// Time: 24-hour HH:MM — Finland uses 24h clock exclusively.
// We sync to the hidden #departure_time field as ISO yyyy-mm-ddTHH:MM.

function _pad2(n) { return n < 10 ? '0' + n : '' + n; }

function _syncDepartureTime() {
  var dateStr = (document.getElementById('departure_date').value || '').trim();
  var timeStr = (document.getElementById('departure_time_input').value || '').trim();
  if (!dateStr || !timeStr) { document.getElementById('departure_time').value = ''; return; }
  // Parse dd.mm.yyyy
  var parts = dateStr.split('.');
  if (parts.length !== 3) { document.getElementById('departure_time').value = ''; return; }
  var day = parseInt(parts[0], 10);
  var month = parseInt(parts[1], 10);
  var year = parseInt(parts[2], 10);
  if (!day || !month || !year) { document.getElementById('departure_time').value = ''; return; }
  // Parse HH:MM
  var tp = timeStr.split(':');
  if (tp.length !== 2) { document.getElementById('departure_time').value = ''; return; }
  var hh = parseInt(tp[0], 10);
  var mm = parseInt(tp[1], 10);
  if (isNaN(hh) || isNaN(mm) || hh < 0 || hh > 23 || mm < 0 || mm > 59) {
    document.getElementById('departure_time').value = ''; return;
  }
  var iso = year + '-' + _pad2(month) + '-' + _pad2(day) + 'T' + _pad2(hh) + ':' + _pad2(mm);
  document.getElementById('departure_time').value = iso;
}

function _formatFinnishDate(d) {
  return _pad2(d.getDate()) + '.' + _pad2(d.getMonth() + 1) + '.' + d.getFullYear();
}

// Auto-format: insert dots as user types digits (dd.mm.yyyy)
function _onDateInput(e) {
  var el = e.target;
  var raw = el.value.replace(/[^\d.]/g, '');
  // Auto-insert dots after day and month digits
  var digits = raw.replace(/\./g, '');
  if (digits.length >= 3 && raw.indexOf('.') === -1) {
    raw = digits.slice(0, 2) + '.' + digits.slice(2);
  }
  if (digits.length >= 5) {
    var p = raw.split('.');
    if (p.length < 3) {
      raw = digits.slice(0, 2) + '.' + digits.slice(2, 4) + '.' + digits.slice(4, 8);
    }
  }
  el.value = raw.slice(0, 10);
  _syncDepartureTime();
}

// Auto-format: insert colon as user types digits (HH:MM, 24h)
function _onTimeInput(e) {
  var el = e.target;
  var raw = el.value.replace(/[^\d:]/g, '');
  var digits = raw.replace(/:/g, '');
  // Auto-insert colon after 2 digits
  if (digits.length >= 3 && raw.indexOf(':') === -1) {
    raw = digits.slice(0, 2) + ':' + digits.slice(2);
  }
  el.value = raw.slice(0, 5);
  _syncDepartureTime();
}

// ── Initialise form ─────────────────────────────────────────────────
(function initForm() {
  // Default departure time: next full hour in Finnish format
  var now = new Date();
  now.setMinutes(0, 0, 0);
  now.setHours(now.getHours() + 1);
  document.getElementById('departure_date').value = _formatFinnishDate(now);
  document.getElementById('departure_time_input').value = _pad2(now.getHours()) + ':' + _pad2(now.getMinutes());
  _syncDepartureTime();

  // Sync on every keystroke / change
  document.getElementById('departure_date').addEventListener('input', _onDateInput);
  document.getElementById('departure_time_input').addEventListener('input', _onTimeInput);

  document.getElementById('submit-btn').addEventListener('click', submitAnalysis);
  document.getElementById('show-routes-btn').addEventListener('click', showRouteOptions);

  // Pick-on-map buttons
  document.getElementById('pick-dep-btn').addEventListener('click', function () { startPick('departure'); });
  document.getElementById('pick-dest-btn').addEventListener('click', function () { startPick('destination'); });

  // Clear buttons
  document.getElementById('clear-dep').addEventListener('click', clearDeparture);
  document.getElementById('clear-dest').addEventListener('click', clearDestination);
})();
