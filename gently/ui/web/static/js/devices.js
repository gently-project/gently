/**
 * Devices tab — read-only stream of MMCore device state.
 *
 * Two views:
 *   Map     — top-down XY stage map with the firmware-fence "optimal" box
 *             on a hatched "forbidden" envelope (default)
 *   Details — position cards + filterable properties table
 *
 * Both views are driven by the same DEVICE_STATE_UPDATE payload forwarded
 * from the device-layer SSE stream by DeviceStateMonitor. No write controls
 * — the optimal-zone outline reflects whatever the XYStage device reports
 * as its hardware soft limits (LowerLimX/UpperLimX/LowerLimY/UpperLimY in
 * the ASI adapter), which is the single source of truth.
 */
const DevicesManager = (function () {
    const STALE_AFTER_MS = 4000;
    const VIEWS = ['operate', 'map', 'details', 'optical3d'];
    const SVG_NS = 'http://www.w3.org/2000/svg';

    // Status / details DOM
    let _statusPill, _statusMeta, _statusDot;
    let _posX, _posY, _piezoZ, _galvoA, _galvoB;
    let _tbody, _filter;
    // Nodes cacheDom() has already wired one-shot listeners to (see cacheDom).
    let _observedSvg = null, _wiredFilter = null;

    // Map DOM
    let _mapSvg, _mapBg, _mapGridMinor, _mapGridMajor, _mapAxisEmphasis;
    let _mapBeyond, _mapCoverslip;
    let _mapZones, _mapZoneLabels, _mapOrigin, _mapAxes;
    let _mapRegionPreview;
    let _mapEmbryos;
    let _mapMarker, _mapMarkerPulse, _mapMarkerRing, _mapMarkerDot;
    let _mapReadoutX, _mapReadoutY;
    let _mapWrap;
    let _scalebarLabel, _scalebarTrack;

    // Embryo waypoints — driven by EMBRYOS_UPDATE events (the canonical bulk
    // mutation broadcast added by the embryos-broadcast commit) and the
    // initial /api/embryos/current snapshot. Each entry mirrors
    // EmbryoState.to_dict() (id, position_coarse, position_fine,
    // has_fine_position, nickname, role, ...). Role drives marker color
    // (mirrors the marking-window legend: magenta=test, cyan=calibration,
    // grey=unassigned). The STATUS_CHANGED listener stays
    // hooked as a belt-and-braces refresh path.
    let _embryos = [];

    // Map-side edit state. _selectedEmbryoId means "picked up": the next
    // click on empty map space drops it there (with a confirm), Delete /
    // Backspace removes it (with a confirm), Escape clears the selection.
    let _selectedEmbryoId = null;

    // Bottom-camera panel DOM + state
    let _camPanel, _camToggle, _camExpand, _camImg, _camPlaceholder, _camLed, _camMeta;
    let _camStage, _camCrosshair, _camCrosshairGroup;
    let _camStreaming = false;
    let _camLastFrameTs = 0;
    let _camHasFrame = false;
    let _camStaleTimer = null;
    const _CAM_FPS_WINDOW = 12;
    let _camFrameTimes = [];

    // Camera zoom / pan. Identity transform = (zoom 1, tx 0, ty 0); pan only
    // engages once zoom > 1. Reset on double-click and on stream-off.
    let _camZoom = 1;
    let _camTx = 0;
    let _camTy = 0;
    let _camPanLast = null;  // {x, y} clientX/Y of last pointermove during pan
    const _CAM_ZOOM_MIN = 1;
    const _CAM_ZOOM_MAX = 8;
    const _CAM_ZOOM_STEP = 1.15;  // multiplicative per wheel notch

    // Room-light toggle (header). Drives the SwitchBot Bot that switches the
    // diSPIM room light. State is the bot's cached on/off; hidden until the
    // device layer reports the accessory is configured.
    let _roomLightToggle, _roomLightLabel;
    let _roomLightState = 'unknown';
    let _roomLightAvailable = false;
    let _roomLightBusy = false;
    let _roomLightTimer = null;

    // Temperature-controller panel DOM + state
    let _tempEl, _tempReadout, _tempInput, _tempSet;
    let _tempState = 'unknown';
    let _tempAvailable = false;
    let _tempBusy = false;
    let _tempTimer = null;

    let _lastTs = 0;
    let _previousTs = 0;
    let _lastWallTs = 0;
    let _staleTimer = null;
    let _filterText = '';
    let _lastPropertyMap = {};
    let _lastXY = null;             // {X, Y} in stage µm, last seen
    let _currentView = 'operate';

    // Map geometry
    //   _optimalBox: { x: [min, max], y: [min, max] } in stage µm — the
    //   WORKING REGION: the box gently keeps inside, and the box the region
    //   editor edits. null when no region has been set, which draws no zone
    //   rather than shading the whole sheet green.
    //   _firmwareBox: the controller's own fence, drawn only when it is being
    //   enforced and differs from the region — it binds Micro-Manager too, so
    //   it is a separate fact from the region.
    //   _coverslip: optional {center_um, size_mm} from GET /api/devices/coverslip
    //   _viewBox: { xMin, xMax, yMin, yMax } in stage µm
    let _optimalBox = null;
    let _firmwareBox = null;
    let _coverslip = null;
    let _viewBox = null;

    // Resolve a cached node, re-querying when it was never found or has been
    // detached. Replaces the old `if (_statusPill) return;` latch, which made
    // the FIRST caller's snapshot permanent: anything mounted afterwards kept
    // a null ref forever, silently. Cost when everything is already mounted is
    // one `.isConnected` read per ref, so the hot handlePayload() path is
    // unchanged in practice.
    const alive = (node) => (node && node.isConnected) ? node : null;
    const grab = (node, elemId) => alive(node) || document.getElementById(elemId);

    function cacheDom() {
        _statusPill = grab(_statusPill, 'devices-stream-pill');
        _statusMeta = grab(_statusMeta, 'devices-status-meta');
        _statusDot  = grab(_statusDot, 'devices-status-dot');
        _posX       = grab(_posX, 'dev-pos-x');
        _posY       = grab(_posY, 'dev-pos-y');
        _piezoZ     = grab(_piezoZ, 'dev-pos-piezo');
        _galvoA     = grab(_galvoA, 'dev-pos-galvo-a');
        _galvoB     = grab(_galvoB, 'dev-pos-galvo-b');
        _tbody      = grab(_tbody, 'devices-tbody');
        _filter     = grab(_filter, 'devices-filter');

        _mapSvg           = grab(_mapSvg, 'devices-map-svg');
        _mapBg            = grab(_mapBg, 'devices-map-bg');
        _mapBeyond        = grab(_mapBeyond, 'devices-map-beyond');
        _mapGridMinor     = grab(_mapGridMinor, 'devices-map-grid-minor');
        _mapGridMajor     = grab(_mapGridMajor, 'devices-map-grid-major');
        _mapAxisEmphasis  = grab(_mapAxisEmphasis, 'devices-map-axis-emphasis');
        _mapCoverslip     = grab(_mapCoverslip, 'devices-map-coverslip');
        _mapZones         = grab(_mapZones, 'devices-map-zones');
        _mapZoneLabels    = grab(_mapZoneLabels, 'devices-map-zone-labels');
        _mapOrigin        = grab(_mapOrigin, 'devices-map-origin');
        _mapAxes          = grab(_mapAxes, 'devices-map-axes');
        _mapEmbryos       = grab(_mapEmbryos, 'devices-map-embryos');
        _mapMarker        = grab(_mapMarker, 'devices-map-marker');
        _mapMarkerPulse   = grab(_mapMarkerPulse, 'devices-map-marker-pulse');
        _mapMarkerRing    = grab(_mapMarkerRing, 'devices-map-marker-ring');
        _mapMarkerDot     = grab(_mapMarkerDot, 'devices-map-marker-dot');
        _mapReadoutX      = grab(_mapReadoutX, 'devices-map-x');
        _mapReadoutY      = grab(_mapReadoutY, 'devices-map-y');
        _mapWrap          = grab(_mapWrap, 'devices-map-wrap');
        _mapRegionPreview = grab(_mapRegionPreview, 'devices-map-region-preview');
        _scalebarLabel    = grab(_scalebarLabel, 'devices-scalebar-value');
        _scalebarTrack    = alive(_scalebarTrack) || document.querySelector('#devices-scalebar .devices-scalebar-track');

        _camPanel        = grab(_camPanel, 'devices-camera-panel');
        _camToggle       = grab(_camToggle, 'devices-camera-toggle');
        _camExpand       = grab(_camExpand, 'devices-camera-expand');
        _camImg          = grab(_camImg, 'devices-camera-img');
        _camPlaceholder  = grab(_camPlaceholder, 'devices-camera-placeholder');
        _camStage        = alive(_camStage) || (_camPanel ? _camPanel.querySelector('.devices-camera-stage') : null);
        _camCrosshair    = grab(_camCrosshair, 'devices-camera-crosshair');
        _camCrosshairGroup = grab(_camCrosshairGroup, 'devices-camera-crosshair-group');
        _camLed          = grab(_camLed, 'devices-camera-led');
        _camMeta         = grab(_camMeta, 'devices-camera-meta');

        _roomLightToggle = grab(_roomLightToggle, 'devices-room-light-toggle');
        _roomLightLabel  = grab(_roomLightLabel, 'devices-room-light-label');

        _tempEl      = grab(_tempEl, 'devices-temp');
        _tempReadout = grab(_tempReadout, 'devices-temp-readout');
        _tempInput   = grab(_tempInput, 'devices-temp-input');
        _tempSet     = grab(_tempSet, 'devices-temp-set');

        // Recompute the scale bar caption whenever the canvas resizes.
        // Keyed on the node, not on a run-once flag: one observer per SVG that
        // actually gets cached, so a re-resolved node is re-observed and the
        // same node is never observed twice.
        if (_mapSvg && _mapSvg !== _observedSvg && window.ResizeObserver) {
            _observedSvg = _mapSvg;
            new ResizeObserver(() => updateScalebar()).observe(_mapSvg);
        }

        if (_filter && _filter !== _wiredFilter) {
            _wiredFilter = _filter;
            _filter.addEventListener('input', () => {
                _filterText = _filter.value.trim().toLowerCase();
                renderPropertiesTable(_lastPropertyMap);
            });
        }
    }

    // =====================================================================
    // Status / formatting helpers
    // =====================================================================

    function fmtNumber(v, digits = 2) {
        if (v === null || v === undefined || Number.isNaN(v)) return '—';
        if (typeof v !== 'number') return String(v);
        return v.toFixed(digits);
    }

    function setStatus(klass, label, meta) {
        if (!_statusPill) return;
        _statusPill.classList.remove('live', 'stale', 'paused', 'error');
        _statusPill.classList.add(klass);
        _statusPill.textContent = label;
        if (_statusMeta) _statusMeta.textContent = meta || '';
        if (_statusDot) {
            _statusDot.classList.remove('live', 'stale', 'paused', 'error');
            _statusDot.classList.add(klass);
        }
    }

    function scheduleStaleCheck() {
        if (_staleTimer) clearTimeout(_staleTimer);
        _staleTimer = setTimeout(() => {
            const age = (Date.now() - _lastWallTs) / 1000;
            setStatus('stale', 'stale', `last ${age.toFixed(1)}s ago`);
        }, STALE_AFTER_MS);
    }

    function flashValue(el) {
        if (!el) return;
        el.classList.add('updating');
        setTimeout(() => el.classList.remove('updating'), 400);
    }

    function setAxis(el, value, digits) {
        if (!el) return;
        const formatted = fmtNumber(value, digits);
        if (el.textContent !== formatted) {
            el.textContent = formatted;
            flashValue(el);
        }
    }

    // =====================================================================
    // Live state handlers
    // =====================================================================

    function renderPositions(positions) {
        if (!positions) return;
        for (const devName of Object.keys(positions)) {
            const entry = positions[devName] || {};
            switch (entry.kind) {
                case 'xy_stage':
                    setAxis(_posX, entry.X, 2);
                    setAxis(_posY, entry.Y, 2);
                    _lastXY = { X: entry.X, Y: entry.Y };
                    // Publish for the other surfaces that keep their own copy
                    // (operate.js, occupancy3d.js, marking.js). devices.js stays
                    // the canonical owner; this is a broadcast, not a rewire.
                    // Non-finite readings are not published — they would render
                    // as NaN in a subscriber; here they already fall back to the
                    // neutral frame via computeViewBox().
                    if (Number.isFinite(entry.X) && Number.isFinite(entry.Y)) {
                        SharedState.set('stageXY', { x: entry.X, y: entry.Y });
                    }
                    if (computeViewBox()) renderMap();
                    else { updateMapMarker(); feedRegionEditor(); }
                    if (_mapReadoutX) _mapReadoutX.textContent = fmtNumber(entry.X, 1);
                    if (_mapReadoutY) _mapReadoutY.textContent = fmtNumber(entry.Y, 1);
                    break;
                case 'piezo':
                    setAxis(_piezoZ, entry.Position, 3);
                    break;
                case 'galvo':
                    setAxis(_galvoA, entry.A, 4);
                    setAxis(_galvoB, entry.B, 4);
                    break;
            }
        }
    }

    // Extract the optimal-box outline from the XYStage device's firmware-fence
    // properties (LowerLimX/UpperLimX/LowerLimY/UpperLimY, all in mm on the
    // ASI adapter). Single source of truth: these are what the controller
    // enforces against every motion source (joystick, MMCore, plans). When
    // their values change, the map redraws.
    /**
     * Adopt the working region as the zone the map calls optimal.
     *
     * This used to come from the controller's `LowerLimX(mm)` properties,
     * which was the same box while writing a region always wrote the
     * firmware. Since the firmware fence became opt-in it is not: with it off
     * those properties report the stage's whole travel, and the map shaded
     * the entire sheet "OPTIMAL" — so the region the operator edits and the
     * region the map drew were two different boxes.
     */
    function applyWorkingRegion(s) {
        const { box } = XYLimitsState.workingBox();
        const next = box
            ? { x: [box.x_min, box.x_max], y: [box.y_min, box.y_max] }
            : null;
        _firmwareBox = s && s.enforced && s.box
            ? { x: [s.box.x_min, s.box.x_max], y: [s.box.y_min, s.box.y_max] }
            : null;
        const prev = _optimalBox;
        const changed = (!prev !== !next)
            || (prev && next && (
                Math.abs(prev.x[0] - next.x[0]) > 1 || Math.abs(prev.x[1] - next.x[1]) > 1
                || Math.abs(prev.y[0] - next.y[0]) > 1 || Math.abs(prev.y[1] - next.y[1]) > 1));
        _optimalBox = next;
        if (changed || _firmwareBox) {
            computeViewBox();
            renderMap();
        }
    }

    // =====================================================================
    // Coverslip (decorative reference)
    // =====================================================================

    async function loadCoverslip() {
        try {
            const res = await fetch('/api/devices/coverslip');
            if (!res.ok) return;
            const data = await res.json();
            _coverslip = data.coverslip || null;
            computeViewBox();
            renderMap();
        } catch (err) {
            console.debug('coverslip fetch failed:', err);
        }
    }

    // Initial embryo snapshot — closes the gap for clients that connect
    // mid-session, after the last EMBRYOS_UPDATE has already been broadcast
    // and aged out of history. Subsequent updates arrive over the event bus.
    async function loadEmbryosSnapshot() {
        try {
            const res = await fetch('/api/embryos/current');
            if (!res.ok) return;
            const data = await res.json();
            handleEmbryosUpdate(data);
        } catch (err) {
            console.debug('embryos snapshot fetch failed:', err);
        }
    }

    function handleEmbryosUpdate(payload) {
        // .slice(): operate.js is handed the same payload.embryos object, so
        // assigning by reference let a write here appear in its roster.
        _embryos = (payload && Array.isArray(payload.embryos)) ? payload.embryos.slice() : [];
        // Recompute the frame so newly-arrived embryos are always in view.
        // computeViewBox() returns true when the bounds shifted (incl. the
        // first-ever compute); a wider frame needs a full redraw so grid/zones/
        // axes track the new bounds, otherwise just repaint the embryo layer.
        if (computeViewBox()) {
            renderMap();
        } else {
            renderEmbryos();
        }
    }

    // =====================================================================
    // Properties table (Details view)
    // =====================================================================

    const DEVICE_TYPE_LABEL = {
        0: 'Unknown', 1: 'Any', 2: 'Camera', 3: 'Shutter',
        4: 'XY', 5: 'Stage', 6: 'State', 7: 'Serial',
        8: 'Generic', 9: 'AutoFocus', 10: 'Core', 11: 'Image',
        12: 'Signal IO', 13: 'Magnifier', 14: 'SLM', 15: 'Hub',
        16: 'Galvo',
    };

    function flattenProperties(propsByDevice) {
        const rows = [];
        const prevMap = _lastPropertyMap;
        const devNames = Object.keys(propsByDevice).sort();
        for (const dev of devNames) {
            const bundle = propsByDevice[dev] || {};
            const typeCode = bundle.__type__;
            const type = (typeCode in DEVICE_TYPE_LABEL) ? DEVICE_TYPE_LABEL[typeCode] : String(typeCode ?? '');
            const prev = prevMap[dev] || {};
            const propNames = Object.keys(bundle).filter(k => k !== '__type__').sort();
            for (const prop of propNames) {
                const value = bundle[prop];
                const changed = prev[prop] !== undefined && prev[prop] !== value;
                rows.push({ device: dev, type, property: prop, value, changed });
            }
        }
        return rows;
    }

    function renderPropertiesTable(propsByDevice) {
        if (!_tbody || !propsByDevice) return;
        const rows = flattenProperties(propsByDevice);
        const filtered = _filterText
            ? rows.filter(r =>
                r.device.toLowerCase().includes(_filterText) ||
                r.property.toLowerCase().includes(_filterText) ||
                String(r.value).toLowerCase().includes(_filterText))
            : rows;
        if (!filtered.length) {
            _tbody.innerHTML = '<tr class="devices-empty-row"><td colspan="4">' +
                (rows.length ? 'No matches for filter' : 'No properties yet') + '</td></tr>';
            return;
        }
        const html = filtered.map(r =>
            '<tr>' +
                '<td class="dev-col-device">' + escapeHtml(r.device) + '</td>' +
                '<td class="dev-col-type">' + escapeHtml(r.type) + '</td>' +
                '<td class="dev-col-prop">' + escapeHtml(r.property) + '</td>' +
                '<td class="dev-col-value' + (r.changed ? ' changed' : '') + '">' + escapeHtml(r.value) + '</td>' +
            '</tr>'
        ).join('');
        _tbody.innerHTML = html;
    }

    // =====================================================================
    // Map view — geometry + rendering
    // =====================================================================

    // Compute the viewport extent. Fits the union of:
    //   - the optimal box (firmware fence), if known
    //   - the live stage XY, if known
    // Returns true if the viewBox changed meaningfully (≥0.5% drift) so the
    // caller knows to rebuild zones/grid/axes; cheap micro-jitter doesn't
    // trigger a full redraw.
    function computeViewBox() {
        let xMin = Infinity, xMax = -Infinity, yMin = Infinity, yMax = -Infinity;
        if (_optimalBox) {
            xMin = Math.min(xMin, _optimalBox.x[0]);
            xMax = Math.max(xMax, _optimalBox.x[1]);
            yMin = Math.min(yMin, _optimalBox.y[0]);
            yMax = Math.max(yMax, _optimalBox.y[1]);
        }
        if (_lastXY) {
            xMin = Math.min(xMin, _lastXY.X); xMax = Math.max(xMax, _lastXY.X);
            yMin = Math.min(yMin, _lastXY.Y); yMax = Math.max(yMax, _lastXY.Y);
        }
        // Always frame the marked embryos — they can sit well outside the fence
        // box / current stage position (e.g. SAM detections hundreds of µm away),
        // and omitting them clips them to the map edge (looks like a wrong
        // position even though their coords are correct).
        if (_embryos && _embryos.length) {
            _embryos.forEach(emb => {
                const xy = embryoResolvedXY(emb);
                if (!xy) return;
                xMin = Math.min(xMin, xy.x); xMax = Math.max(xMax, xy.x);
                yMin = Math.min(yMin, xy.y); yMax = Math.max(yMax, xy.y);
            });
        }
        // While a region is being walked, frame the box taking shape. Not
        // the controller's travel: with limits off that is its factory
        // default, ±110 mm on a stock Tiger, and a 3 mm region framed inside
        // it is a dot. The stage position is already in the union above, so
        // the box follows the joystick onto the sheet on its own.
        if (typeof RegionEditor !== 'undefined' && RegionEditor.isOpen()) {
            const b = RegionEditor.box();
            if (b) {
                xMin = Math.min(xMin, b.x_min); xMax = Math.max(xMax, b.x_max);
                yMin = Math.min(yMin, b.y_min); yMax = Math.max(yMax, b.y_max);
            }
        }
        if (!isFinite(xMin) || !isFinite(yMin)) {
            xMin = -100; xMax = 100; yMin = -100; yMax = 100;
        }
        if (xMax - xMin < 1) { const c = (xMax + xMin) / 2; xMin = c - 100; xMax = c + 100; }
        if (yMax - yMin < 1) { const c = (yMax + yMin) / 2; yMin = c - 100; yMax = c + 100; }
        const span = Math.max(xMax - xMin, yMax - yMin);
        const pad = span * 0.08;
        const next = {
            xMin: xMin - pad, xMax: xMax + pad,
            yMin: yMin - pad, yMax: yMax + pad,
        };
        const changed = !_viewBox ||
            Math.abs(next.xMin - _viewBox.xMin) > span * 0.005 ||
            Math.abs(next.xMax - _viewBox.xMax) > span * 0.005 ||
            Math.abs(next.yMin - _viewBox.yMin) > span * 0.005 ||
            Math.abs(next.yMax - _viewBox.yMax) > span * 0.005;
        _viewBox = next;
        return changed;
    }

    // Stage Y is positive-up; SVG Y is positive-down. Convert by negation.
    function svgY(stageY) { return -stageY; }

    function feedRegionEditor() {
        // The editor stamps the LIVE position, so it takes the same telemetry
        // the map draws from rather than reading the stage itself.
        if (typeof RegionEditor === 'undefined' || !_lastXY) return;
        // setPosition fires onChange when it moves, which redraws the strip
        // and the box — so there is nothing to do here but hand it over.
        RegionEditor.setPosition(_lastXY.X, _lastXY.Y);
    }

    function renderMap() {
        feedRegionEditor();
        if (!_mapSvg || !_viewBox) return;
        const { xMin, xMax, yMin, yMax } = _viewBox;
        const w = xMax - xMin, h = yMax - yMin;
        _mapSvg.setAttribute('viewBox', `${xMin} ${-yMax} ${w} ${h}`);

        const span = Math.max(w, h);
        if (_mapMarkerDot)   _mapMarkerDot.setAttribute('r',   span * 0.0045);
        if (_mapMarkerRing)  _mapMarkerRing.setAttribute('r',  span * 0.014);
        if (_mapMarkerPulse) _mapMarkerPulse.setAttribute('r', span * 0.014);

        renderBackground();
        renderBeyond();
        renderGrid();
        renderAxisEmphasis();
        renderCoverslip();
        renderZones();
        renderZoneLabels();
        renderOrigin();
        renderAxes();
        renderEmbryos();
        updateMapMarker();
        updateScalebar();
    }

    function handleStatusChanged(payload) {
        // Only the role-assignment variant is relevant to the map.
        if (!payload || payload.change !== 'role_assigned') return;
        const eid = payload.embryo_id;
        const newRole = payload.new_role;
        if (!eid || !newRole) return;
        const idx = _embryos.findIndex(e => e.id === eid);
        if (idx >= 0) {
            _embryos[idx] = Object.assign({}, _embryos[idx], { role: newRole });
            renderEmbryos();
        } else {
            // Embryo we haven't seen yet — refetch to be safe.
            loadEmbryosSnapshot();
        }
    }

    function renderBackground() {
        if (!_mapBg || !_viewBox) return;
        _mapBg.innerHTML = '';
        const { xMin, xMax, yMin, yMax } = _viewBox;
        const grain = document.createElementNS(SVG_NS, 'rect');
        grain.setAttribute('x', xMin);
        grain.setAttribute('y', svgY(yMax));
        grain.setAttribute('width',  xMax - xMin);
        grain.setAttribute('height', yMax - yMin);
        grain.setAttribute('fill', 'url(#devices-map-grain)');
        _mapBg.appendChild(grain);

        const vignette = document.createElementNS(SVG_NS, 'rect');
        vignette.setAttribute('x', xMin);
        vignette.setAttribute('y', svgY(yMax));
        vignette.setAttribute('width',  xMax - xMin);
        vignette.setAttribute('height', yMax - yMin);
        vignette.setAttribute('fill', 'url(#devices-map-vignette)');
        vignette.setAttribute('pointer-events', 'none');
        _mapBg.appendChild(vignette);
    }

    // "Forbidden" is implicit: paint the whole viewport with the red hatch
    // pattern. The optimal zone rect paints ABOVE this so the operator's safe
    // window looks carved out of a hatched danger envelope.
    //
    // Only paint the red envelope when we actually KNOW the safe window
    // (_optimalBox, from XYStage fence telemetry). With no working-region data —
    // device layer down, disconnected, or pre-calibration — an all-red map reads
    // as "everything is off-limits" when the truth is "no position data yet".
    // In that case leave a neutral grid instead of an alarming red field.
    function renderBeyond() {
        if (!_mapBeyond || !_viewBox) return;
        _mapBeyond.innerHTML = '';
        if (!_optimalBox) return;   // no fence data → neutral empty-state, not red
        const { xMin, xMax, yMin, yMax } = _viewBox;
        const span = Math.max(xMax - xMin, yMax - yMin);
        const tile = Math.max(8, span / 50);

        const pattern = document.getElementById('devices-map-hatch-red');
        if (pattern) {
            pattern.setAttribute('width',  tile);
            pattern.setAttribute('height', tile);
            const line = pattern.querySelector('line');
            if (line) line.setAttribute('y2', tile);
        }

        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', xMin);
        rect.setAttribute('y', svgY(yMax));
        rect.setAttribute('width',  xMax - xMin);
        rect.setAttribute('height', yMax - yMin);
        rect.setAttribute('class', 'devices-beyond-fill');
        _mapBeyond.appendChild(rect);
    }

    function renderCoverslip() {
        if (!_mapCoverslip) return;
        _mapCoverslip.innerHTML = '';
        const cs = _coverslip;
        if (!cs || !Array.isArray(cs.center_um) || !Array.isArray(cs.size_mm)) return;
        const [cx, cy] = cs.center_um;
        const [wMm, hMm] = cs.size_mm;
        const w = wMm * 1000, h = hMm * 1000;
        const x0 = cx - w / 2;
        const y1 = cy + h / 2;

        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', x0);
        rect.setAttribute('y', svgY(y1));
        rect.setAttribute('width',  w);
        rect.setAttribute('height', h);
        rect.setAttribute('class', 'devices-coverslip-outline');
        _mapCoverslip.appendChild(rect);

        const span = Math.max(_viewBox.xMax - _viewBox.xMin, _viewBox.yMax - _viewBox.yMin);
        const fs = span * 0.015;
        const label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('x', x0 + w - span * 0.008);
        label.setAttribute('y', svgY(y1) + fs * 1.1);
        label.setAttribute('class', 'devices-coverslip-label');
        label.setAttribute('font-size', fs);
        label.setAttribute('text-anchor', 'end');
        label.textContent = `coverslip · ${wMm}×${hMm} mm`;
        _mapCoverslip.appendChild(label);
    }

    function renderZones() {
        if (!_mapZones) return;
        _mapZones.innerHTML = '';
        if (!_optimalBox) return;
        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('x', _optimalBox.x[0]);
        rect.setAttribute('y', svgY(_optimalBox.y[1]));
        rect.setAttribute('width',  _optimalBox.x[1] - _optimalBox.x[0]);
        rect.setAttribute('height', _optimalBox.y[1] - _optimalBox.y[0]);
        rect.setAttribute('class', 'devices-zone devices-zone-green');
        _mapZones.appendChild(rect);

        // The controller's own fence, when it is being enforced and is not
        // simply the region. It binds every client of this stage, including
        // someone in Micro-Manager who can see none of this — so when the two
        // differ, the map shows both rather than implying one box.
        if (!_firmwareBox) return;
        const near = (a, b) => Math.abs(a - b) < 1;
        if (near(_firmwareBox.x[0], _optimalBox.x[0]) && near(_firmwareBox.x[1], _optimalBox.x[1])
            && near(_firmwareBox.y[0], _optimalBox.y[0]) && near(_firmwareBox.y[1], _optimalBox.y[1])) {
            return;
        }
        const fence = document.createElementNS(SVG_NS, 'rect');
        fence.setAttribute('x', _firmwareBox.x[0]);
        fence.setAttribute('y', svgY(_firmwareBox.y[1]));
        fence.setAttribute('width',  _firmwareBox.x[1] - _firmwareBox.x[0]);
        fence.setAttribute('height', _firmwareBox.y[1] - _firmwareBox.y[0]);
        fence.setAttribute('class', 'devices-zone devices-zone-firmware');
        const t = document.createElementNS(SVG_NS, 'title');
        t.textContent = 'Controller limits — enforced against every client, Micro-Manager included';
        fence.appendChild(t);
        _mapZones.appendChild(fence);
    }

    function renderZoneLabels() {
        if (!_mapZoneLabels || !_viewBox || !_optimalBox) return;
        _mapZoneLabels.innerHTML = '';
        const zw = _optimalBox.x[1] - _optimalBox.x[0];
        const zh = _optimalBox.y[1] - _optimalBox.y[0];
        const span = Math.max(_viewBox.xMax - _viewBox.xMin, _viewBox.yMax - _viewBox.yMin);
        const fontSize = span * 0.018;
        const inset    = span * 0.010;
        const text = 'OPTIMAL';
        const estTextWidth = text.length * fontSize * 0.78;
        if (zw < estTextWidth * 1.15 || zh < fontSize * 2.0) return;
        const tx = _optimalBox.x[0] + inset;
        const ty = _optimalBox.y[1] - inset;
        const t = document.createElementNS(SVG_NS, 'text');
        t.setAttribute('x', tx);
        t.setAttribute('y', svgY(ty) + fontSize * 0.85);
        t.setAttribute('class', 'devices-zone-label devices-zone-green');
        t.setAttribute('font-size', fontSize);
        t.setAttribute('text-anchor', 'start');
        t.textContent = text;
        _mapZoneLabels.appendChild(t);
    }

    function renderOrigin() {
        if (!_mapOrigin || !_viewBox) return;
        _mapOrigin.innerHTML = '';
        const { xMin, xMax, yMin, yMax } = _viewBox;
        if (xMin > 0 || xMax < 0 || yMin > 0 || yMax < 0) return;
        const span = Math.max(xMax - xMin, yMax - yMin);
        const arm = span * 0.012;
        const path = document.createElementNS(SVG_NS, 'path');
        path.setAttribute('d',
            `M ${-arm} 0 L ${arm} 0  M 0 ${-arm} L 0 ${arm}`);
        path.setAttribute('class', 'devices-origin-mark');
        _mapOrigin.appendChild(path);
        const label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('x', arm * 1.4);
        label.setAttribute('y', -arm * 0.6);
        label.setAttribute('class', 'devices-origin-label');
        label.setAttribute('font-size', span * 0.013);
        label.textContent = '0,0';
        _mapOrigin.appendChild(label);
    }

    function niceStep(span, divisions = 6) {
        const target = span / divisions;
        const pow = Math.pow(10, Math.floor(Math.log10(target)));
        const norm = target / pow;
        const step = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
        return step * pow;
    }

    function renderGrid() {
        if (!_mapGridMinor || !_mapGridMajor || !_viewBox) return;
        _mapGridMinor.innerHTML = '';
        _mapGridMajor.innerHTML = '';
        const { xMin, xMax, yMin, yMax } = _viewBox;
        const span = Math.max(xMax - xMin, yMax - yMin);
        const major = niceStep(span);
        const minor = major / 5;
        for (let x = Math.ceil(xMin / minor) * minor; x <= xMax; x += minor) {
            const isMajor = Math.abs(x % major) < minor * 0.001 || Math.abs(x % major - major) < minor * 0.001;
            const line = document.createElementNS(SVG_NS, 'line');
            line.setAttribute('x1', x); line.setAttribute('x2', x);
            line.setAttribute('y1', svgY(yMax)); line.setAttribute('y2', svgY(yMin));
            line.setAttribute('class', isMajor ? 'devices-grid-major' : 'devices-grid-minor');
            (isMajor ? _mapGridMajor : _mapGridMinor).appendChild(line);
        }
        for (let y = Math.ceil(yMin / minor) * minor; y <= yMax; y += minor) {
            const isMajor = Math.abs(y % major) < minor * 0.001 || Math.abs(y % major - major) < minor * 0.001;
            const line = document.createElementNS(SVG_NS, 'line');
            line.setAttribute('y1', svgY(y)); line.setAttribute('y2', svgY(y));
            line.setAttribute('x1', xMin); line.setAttribute('x2', xMax);
            line.setAttribute('class', isMajor ? 'devices-grid-major' : 'devices-grid-minor');
            (isMajor ? _mapGridMajor : _mapGridMinor).appendChild(line);
        }
    }

    function renderAxisEmphasis() {
        if (!_mapAxisEmphasis || !_viewBox) return;
        _mapAxisEmphasis.innerHTML = '';
        const { xMin, xMax, yMin, yMax } = _viewBox;
        if (xMin <= 0 && xMax >= 0) {
            const l = document.createElementNS(SVG_NS, 'line');
            l.setAttribute('x1', 0); l.setAttribute('x2', 0);
            l.setAttribute('y1', svgY(yMax)); l.setAttribute('y2', svgY(yMin));
            l.setAttribute('class', 'devices-axis-emphasis');
            _mapAxisEmphasis.appendChild(l);
        }
        if (yMin <= 0 && yMax >= 0) {
            const l = document.createElementNS(SVG_NS, 'line');
            l.setAttribute('y1', svgY(0)); l.setAttribute('y2', svgY(0));
            l.setAttribute('x1', xMin); l.setAttribute('x2', xMax);
            l.setAttribute('class', 'devices-axis-emphasis');
            _mapAxisEmphasis.appendChild(l);
        }
    }

    function renderAxes() {
        if (!_mapAxes || !_viewBox) return;
        _mapAxes.innerHTML = '';
        const { xMin, xMax, yMin, yMax } = _viewBox;
        const span = Math.max(xMax - xMin, yMax - yMin);
        const step = niceStep(span);
        const tickLen = span * 0.010;
        const fontSize = span * 0.018;
        const bottomSvg = svgY(yMin);
        for (let x = Math.ceil(xMin / step) * step; x <= xMax; x += step) {
            const t = document.createElementNS(SVG_NS, 'line');
            t.setAttribute('x1', x); t.setAttribute('x2', x);
            t.setAttribute('y1', bottomSvg); t.setAttribute('y2', bottomSvg - tickLen);
            t.setAttribute('class', 'devices-axis-tick');
            _mapAxes.appendChild(t);
            const label = document.createElementNS(SVG_NS, 'text');
            label.setAttribute('x', x);
            label.setAttribute('y', bottomSvg - tickLen * 1.8);
            label.setAttribute('class', 'devices-axis-label-svg');
            label.setAttribute('text-anchor', 'middle');
            label.setAttribute('font-size', fontSize);
            label.textContent = formatTickValue(x);
            _mapAxes.appendChild(label);
        }
        for (let y = Math.ceil(yMin / step) * step; y <= yMax; y += step) {
            const ySvg = svgY(y);
            const t = document.createElementNS(SVG_NS, 'line');
            t.setAttribute('y1', ySvg); t.setAttribute('y2', ySvg);
            t.setAttribute('x1', xMin); t.setAttribute('x2', xMin + tickLen);
            t.setAttribute('class', 'devices-axis-tick');
            _mapAxes.appendChild(t);
            const label = document.createElementNS(SVG_NS, 'text');
            label.setAttribute('x', xMin + tickLen * 1.8);
            label.setAttribute('y', ySvg);
            label.setAttribute('class', 'devices-axis-label-svg');
            label.setAttribute('text-anchor', 'start');
            label.setAttribute('dominant-baseline', 'middle');
            label.setAttribute('font-size', fontSize);
            label.textContent = formatTickValue(y);
            _mapAxes.appendChild(label);
        }
    }

    function formatTickValue(v) {
        const a = Math.abs(v);
        if (a >= 10000) return (v / 1000).toFixed(a >= 100000 ? 0 : 1) + 'k';
        return Math.round(v).toString();
    }

    // =====================================================================
    // Embryo waypoints
    // =====================================================================

    // "embryo_007" / "embryo_7" -> 7. Falls back to a 1-based index from the
    // caller so the label always shows *something*, even for stray ids.
    function embryoLabelText(id, fallbackIndex) {
        const m = id && String(id).match(/(\d+)/);
        if (m) {
            const n = parseInt(m[1], 10);
            if (Number.isFinite(n)) return String(n);
        }
        return String(fallbackIndex + 1);
    }

    // Resolve XY for rendering — fine if SPIM-aligned, else coarse. Returns
    // null when neither stage carries usable values so the entry is skipped
    // (e.g. an embryo whose detection record came in malformed).
    function embryoResolvedXY(emb) {
        const f = emb && emb.position_fine;
        if (f && Number.isFinite(f.x) && Number.isFinite(f.y)) return { x: f.x, y: f.y };
        const c = emb && emb.position_coarse;
        if (c && Number.isFinite(c.x) && Number.isFinite(c.y)) return { x: c.x, y: c.y };
        return null;
    }

    function renderEmbryos() {
        if (!_mapEmbryos || !_viewBox) return;
        _mapEmbryos.innerHTML = '';
        if (!_embryos || !_embryos.length) return;
        const span = Math.max(_viewBox.xMax - _viewBox.xMin,
                              _viewBox.yMax - _viewBox.yMin);
        const radius = span * 0.012;
        const fontSize = span * 0.015;

        _embryos.forEach((emb, i) => {
            const xy = embryoResolvedXY(emb);
            if (!xy) return;

            const isFine = !!emb.has_fine_position;
            const isSelected = _selectedEmbryoId !== null
                            && emb.id === _selectedEmbryoId;

            // Wrap circle + label in a group so a single closest() lookup
            // finds the embryo regardless of which child the click hit.
            const group = document.createElementNS(SVG_NS, 'g');
            group.setAttribute('class',
                'devices-embryo-group' + (isSelected ? ' devices-embryo-selected' : ''));
            group.setAttribute('data-embryo-id', emb.id || '');
            group.setAttribute('data-embryo-stage', isFine ? 'fine' : 'coarse');

            const circle = document.createElementNS(SVG_NS, 'circle');
            circle.setAttribute('cx', xy.x);
            circle.setAttribute('cy', svgY(xy.y));
            circle.setAttribute('r', radius);
            circle.setAttribute('class',
                isFine ? 'devices-embryo-disc' : 'devices-embryo-ring');
            group.appendChild(circle);

            const label = document.createElementNS(SVG_NS, 'text');
            label.setAttribute('x', xy.x);
            label.setAttribute('y', svgY(xy.y));
            label.setAttribute('class', 'devices-embryo-label');
            label.setAttribute('font-size', fontSize);
            label.textContent = embryoLabelText(emb.id, i);
            group.appendChild(label);

            _mapEmbryos.appendChild(group);
        });
    }

    // ---- Map-side edit interactions ------------------------------------
    // Convert a pointer event's client coords into stage µm. SVG y axis is
    // positive-down and stage y is positive-up, so the y component is
    // negated to match the convention used elsewhere in this module.
    function eventToStageXY(event) {
        if (!_mapSvg || !_mapSvg.getScreenCTM) return null;
        const ctm = _mapSvg.getScreenCTM();
        if (!ctm) return null;
        const pt = _mapSvg.createSVGPoint();
        pt.x = event.clientX;
        pt.y = event.clientY;
        const local = pt.matrixTransform(ctm.inverse());
        return { x: local.x, y: -local.y };
    }

    function findEmbryoIdAt(target) {
        if (!target) return null;
        const node = target.closest && target.closest('[data-embryo-id]');
        return node ? node.getAttribute('data-embryo-id') : null;
    }

    function embryoById(id) {
        return _embryos.find(e => e.id === id) || null;
    }

    function embryoNumberFor(emb) {
        return embryoLabelText(emb.id, _embryos.indexOf(emb));
    }

    function setSelectedEmbryo(id) {
        if (_selectedEmbryoId === id) return;
        _selectedEmbryoId = id;
        renderEmbryos();
    }

    function clearSelection() {
        if (_selectedEmbryoId === null) return;
        _selectedEmbryoId = null;
        renderEmbryos();
    }

    async function attemptMoveSelected(targetStage) {
        const id = _selectedEmbryoId;
        if (!id) return;
        const emb = embryoById(id);
        if (!emb) { clearSelection(); return; }
        const cur = embryoResolvedXY(emb);
        const num = embryoNumberFor(emb);
        const oldStr = cur ? `(${cur.x.toFixed(1)}, ${cur.y.toFixed(1)})` : '(unknown)';
        const newStr = `(${targetStage.x.toFixed(1)}, ${targetStage.y.toFixed(1)})`;
        if (!window.confirm(`Move embryo ${num} from ${oldStr} to ${newStr}?`)) {
            return;  // keep the embryo picked up so they can try again
        }
        try {
            const res = await fetch(`/api/embryos/${encodeURIComponent(id)}/position`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ x: targetStage.x, y: targetStage.y }),
            });
            if (!res.ok) {
                window.alert(`Move failed (${res.status}): ${await res.text()}`);
                return;
            }
            // EMBRYOS_UPDATE will arrive over the bus and refresh the layer;
            // dropping clears the picked-up state regardless.
            clearSelection();
        } catch (err) {
            console.error('move embryo:', err);
            window.alert(`Move failed: ${err.message}`);
        }
    }

    async function attemptDeleteSelected() {
        const id = _selectedEmbryoId;
        if (!id) return;
        const emb = embryoById(id);
        const num = emb ? embryoNumberFor(emb) : id;
        if (!window.confirm(`Remove embryo ${num} from the list?\n\n`
            + 'Nothing is deleted: its files are kept in the session, and it can be restored.')) return;
        try {
            const res = await fetch(`/api/embryos/${encodeURIComponent(id)}`, {
                method: 'DELETE',
            });
            if (!res.ok) {
                const d = await res.json().catch(() => ({}));
                window.alert(`Not removed: ${d.detail || res.status}`);
                return;
            }
            if (typeof showGentlyToast === 'function'
                && typeof OperateManager !== 'undefined' && OperateManager.roster) {
                showGentlyToast(`Removed embryo ${num}. Nothing was deleted.`, 'Undo',
                    () => OperateManager.roster.restore(id), 12000);
            }
            // The embryo is gone from the server snapshot; EMBRYOS_UPDATE
            // will arrive and drop it from _embryos. Clear locally too.
            _selectedEmbryoId = null;
        } catch (err) {
            console.error('delete embryo:', err);
            window.alert(`Delete failed: ${err.message}`);
        }
    }

    function onMapPointerDown(event) {
        // Ignore non-primary buttons so right-clicks etc. don't trigger UI.
        if (event.button !== undefined && event.button !== 0) return;
        const id = findEmbryoIdAt(event.target);
        if (id) {
            setSelectedEmbryo(id);
            return;
        }
        // Empty-space click: drop the picked-up embryo here.
        if (_selectedEmbryoId !== null) {
            const stage = eventToStageXY(event);
            if (stage) attemptMoveSelected(stage);
        }
    }

    function onMapKeyDown(event) {
        // Only honour keys when the operator is actually looking at the Map:
        // not on another top-level tab, not on the Details subview, and not
        // typing into an input / textarea / select / contenteditable.
        if (typeof state !== 'undefined' && typeof TABS !== 'undefined'
                && state.tab !== TABS.DEVICES) {
            return;
        }
        if (_currentView !== 'map') return;
        const a = document.activeElement;
        if (a && (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' ||
                  a.tagName === 'SELECT' || a.isContentEditable)) {
            return;
        }
        if (event.key === 'Escape') {
            if (_selectedEmbryoId !== null) {
                clearSelection();
                event.preventDefault();
            }
            return;
        }
        if (_selectedEmbryoId === null) return;
        if (event.key === 'Delete' || event.key === 'Backspace') {
            event.preventDefault();  // Backspace would otherwise navigate back
            attemptDeleteSelected();
        }
    }

    function updateMapMarker() {
        if (!_mapMarker || !_lastXY) return;
        const sx = _lastXY.X;
        const sy = svgY(_lastXY.Y);
        _mapMarkerDot.setAttribute('cx',   sx); _mapMarkerDot.setAttribute('cy',   sy);
        _mapMarkerRing.setAttribute('cx',  sx); _mapMarkerRing.setAttribute('cy',  sy);
        _mapMarkerPulse.setAttribute('cx', sx); _mapMarkerPulse.setAttribute('cy', sy);
        _mapMarker.classList.remove('hidden');
    }

    function updateScalebar() {
        if (!_scalebarLabel || !_mapSvg || !_viewBox) return;
        const rect = _mapSvg.getBoundingClientRect();
        if (!rect.width || !rect.height) return;
        const w = _viewBox.xMax - _viewBox.xMin;
        const h = _viewBox.yMax - _viewBox.yMin;
        const scale = Math.min(rect.width / w, rect.height / h);
        if (!isFinite(scale) || scale <= 0) return;
        // Measure the bar the caption describes rather than assuming its CSS
        // width: both rects carry any ancestor CSS transform, so the zoom
        // cancels out and the caption stays true under a scaled bench.
        const barRect = _scalebarTrack && _scalebarTrack.getBoundingClientRect();
        const targetPx = barRect && barRect.width ? barRect.width : 120;
        const rawUm = targetPx / scale;
        const pow = Math.pow(10, Math.floor(Math.log10(rawUm)));
        const norm = rawUm / pow;
        const snap = norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10;
        const um = snap * pow;
        _scalebarLabel.textContent = formatScale(um);
    }
    function formatScale(um) {
        if (um >= 1000) return (um / 1000).toFixed(um >= 10000 ? 0 : 1).replace(/\.0$/, '') + ' mm';
        return Math.round(um) + ' µm';
    }

    // =====================================================================
    // Bottom-camera panel
    // =====================================================================

    async function toggleCameraStream() {
        if (!_camToggle) return;
        _camToggle.disabled = true;
        try {
            const endpoint = _camStreaming
                ? '/api/devices/bottom_camera/stream/stop'
                : '/api/devices/bottom_camera/stream/start';
            const res = await fetch(endpoint, { method: 'POST' });
            if (!res.ok) {
                const detail = await res.text();
                console.error('Bottom-camera toggle failed:', detail);
                _camMeta.textContent = `error: ${res.status}`;
                return;
            }
            const data = await res.json();
            applyCameraState(!!data.streaming);
        } catch (err) {
            console.error('Bottom-camera toggle failed:', err);
            _camMeta.textContent = `error: ${err}`;
        } finally {
            _camToggle.disabled = false;
        }
    }

    function applyCameraState(streaming) {
        _camStreaming = streaming;
        if (_camToggle) {
            _camToggle.textContent = streaming ? 'Stop' : 'Start';
            _camToggle.classList.toggle('active', streaming);
        }
        if (_camLed) {
            _camLed.classList.toggle('live', streaming);
            _camLed.classList.remove('stale');
        }
        if (!streaming) {
            _camHasFrame = false;
            _camFrameTimes = [];
            if (_camImg) _camImg.classList.remove('has-frame');
            if (_camPlaceholder) _camPlaceholder.hidden = false;
            if (_camMeta) _camMeta.textContent = 'stream off';
            if (_camStaleTimer) { clearTimeout(_camStaleTimer); _camStaleTimer = null; }
            // Operator may have zoomed in; reset so the next stream session
            // starts at 1× rather than inheriting a stale view.
            resetCameraZoom();
        } else {
            _camFrameTimes = [];
            if (_camMeta) _camMeta.textContent = 'waiting…';
        }
    }

    function handleCameraFrame(payload) {
        if (!payload || !payload.jpeg_b64 || !_camImg) return;
        _camImg.src = `data:${payload.mime || 'image/jpeg'};base64,${payload.jpeg_b64}`;
        if (!_camHasFrame) {
            _camHasFrame = true;
            _camImg.classList.add('has-frame');
            if (_camPlaceholder) _camPlaceholder.hidden = true;
        }
        const now = performance.now();
        _camLastFrameTs = Date.now();
        _camFrameTimes.push(now);
        if (_camFrameTimes.length > _CAM_FPS_WINDOW) _camFrameTimes.shift();
        if (_camLed) {
            _camLed.classList.add('live');
            _camLed.classList.remove('stale');
        }
        if (_camMeta) {
            const shape = payload.shape || [];
            const dims = shape.length === 2 ? `${shape[1]}×${shape[0]}` : '';
            const fps = computeCameraFps();
            _camMeta.textContent = dims
                ? `${dims}  ·  ${fps != null ? fps.toFixed(1) + ' fps' : '…'}`
                : (fps != null ? `${fps.toFixed(1)} fps` : 'live');
        }
        scheduleCameraStaleCheck();
    }

    function computeCameraFps() {
        const n = _camFrameTimes.length;
        if (n < 2) return null;
        const span = _camFrameTimes[n - 1] - _camFrameTimes[0];
        if (span <= 0) return null;
        return ((n - 1) * 1000) / span;
    }

    function scheduleCameraStaleCheck() {
        if (_camStaleTimer) clearTimeout(_camStaleTimer);
        _camStaleTimer = setTimeout(() => {
            const age = (Date.now() - _camLastFrameTs) / 1000;
            if (_camMeta) _camMeta.textContent = `last frame ${age.toFixed(1)}s ago`;
            if (_camLed) _camLed.classList.add('stale');
        }, 1500);
    }

    async function syncInitialCameraState() {
        try {
            const res = await fetch('/api/devices/bottom_camera/status');
            if (!res.ok) return;
            const data = await res.json();
            applyCameraState(!!data.streaming);
        } catch (err) {
            console.debug('bottom-camera status check failed:', err);
        }
    }

    // ---- Camera zoom / pan ---------------------------------------------
    function applyCameraTransform() {
        if (!_camImg) return;
        _camImg.style.transform =
            `translate(${_camTx}px, ${_camTy}px) scale(${_camZoom})`;
        // Reticle uses an SVG transform attribute on the inner <g> instead
        // of a CSS transform on the SVG element — same geometric effect,
        // but the SVG renderer re-rasterises at the new zoom so the 1px
        // strokes stay crisp instead of getting bitmap-scaled.
        if (_camCrosshairGroup && _camStage) {
            // Convert pixel-space translation to viewBox units (viewBox is
            // 0..100 in both axes, preserveAspectRatio=none). Use the layout
            // size, not getBoundingClientRect: _camTx is in the stage's own
            // px, so a CSS transform on an ancestor must not enter here.
            const stageW = _camStage.offsetWidth;
            const stageH = _camStage.offsetHeight;
            const txV = stageW > 0 ? (_camTx * 100) / stageW : 0;
            const tyV = stageH > 0 ? (_camTy * 100) / stageH : 0;
            // translate(50+tx, 50+ty) scale(zoom) translate(-50, -50) keeps
            // the viewBox centre (50, 50) as the zoom anchor and offsets by
            // the converted pixel translation.
            _camCrosshairGroup.setAttribute(
                'transform',
                `translate(${50 + txV} ${50 + tyV}) ` +
                `scale(${_camZoom}) ` +
                `translate(-50 -50)`
            );
        }
    }

    function resetCameraZoom() {
        _camZoom = 1;
        _camTx = 0;
        _camTy = 0;
        applyCameraTransform();
        if (_camStage) _camStage.classList.remove('camera-zoomed', 'camera-panning');
    }

    // Keep at least the image centre within the visible window so the
    // operator can't accidentally pan the entire frame off-screen. At
    // zoom 1 this collapses to (0, 0).
    function clampCameraPan() {
        if (!_camStage) return;
        // Layout size, not the client rect: the bounds are compared against
        // _camTx/_camTy, which live in the stage's own untransformed px.
        const maxX = (_camStage.offsetWidth  * (_camZoom - 1)) / 2;
        const maxY = (_camStage.offsetHeight * (_camZoom - 1)) / 2;
        _camTx = Math.max(-maxX, Math.min(maxX, _camTx));
        _camTy = Math.max(-maxY, Math.min(maxY, _camTy));
    }

    function onCameraWheel(event) {
        if (!_camStage) return;
        // Always preventDefault so the page doesn't scroll under the
        // operator while they're framing a sample.
        event.preventDefault();
        const rect = _camStage.getBoundingClientRect();
        // rect carries any ancestor CSS transform; _camTx/_camTy do not, so
        // divide the cursor offset by the live scale before anchoring.
        const sx = _camStage.offsetWidth  ? rect.width  / _camStage.offsetWidth  : 1;
        const sy = _camStage.offsetHeight ? rect.height / _camStage.offsetHeight : 1;
        const cx = (event.clientX - rect.left - rect.width  / 2) / sx;
        const cy = (event.clientY - rect.top  - rect.height / 2) / sy;
        const oldZoom = _camZoom;
        const factor = event.deltaY < 0 ? _CAM_ZOOM_STEP : 1 / _CAM_ZOOM_STEP;
        const newZoom = Math.max(_CAM_ZOOM_MIN,
                                 Math.min(_CAM_ZOOM_MAX, oldZoom * factor));
        if (newZoom === oldZoom) return;

        // Keep the image point under the cursor anchored under the cursor
        // across the zoom: cursor_new = cursor_old after the transform
        // change, which means newT = cursor - (cursor - oldT) * (new/old).
        const ratio = newZoom / oldZoom;
        _camTx = cx - (cx - _camTx) * ratio;
        _camTy = cy - (cy - _camTy) * ratio;
        _camZoom = newZoom;

        if (Math.abs(_camZoom - 1) < 0.001) {
            resetCameraZoom();
            return;
        }
        clampCameraPan();
        applyCameraTransform();
        _camStage.classList.add('camera-zoomed');
    }

    function onCameraPointerDown(event) {
        if (event.button !== 0) return;
        if (_camZoom <= 1) return;
        _camPanLast = { x: event.clientX, y: event.clientY };
        try { _camStage.setPointerCapture(event.pointerId); } catch (_) {}
        _camStage.classList.add('camera-panning');
        event.preventDefault();
    }

    function onCameraPointerMove(event) {
        if (!_camPanLast) return;
        // Pointer deltas are screen px; the translate they feed is in the
        // stage's own px, so divide out any ancestor CSS transform scale.
        const rect = _camStage.getBoundingClientRect();
        const sx = _camStage.offsetWidth  ? rect.width  / _camStage.offsetWidth  : 1;
        const sy = _camStage.offsetHeight ? rect.height / _camStage.offsetHeight : 1;
        _camTx += (event.clientX - _camPanLast.x) / sx;
        _camTy += (event.clientY - _camPanLast.y) / sy;
        _camPanLast = { x: event.clientX, y: event.clientY };
        clampCameraPan();
        applyCameraTransform();
    }

    function onCameraPointerEnd(event) {
        if (!_camPanLast) return;
        _camPanLast = null;
        try { _camStage.releasePointerCapture(event.pointerId); } catch (_) {}
        if (_camStage) _camStage.classList.remove('camera-panning');
    }

    function onCameraDoubleClick(event) {
        if (_camZoom !== 1 || _camTx !== 0 || _camTy !== 0) {
            event.preventDefault();
            resetCameraZoom();
        }
    }

    function toggleCameraExpand() {
        if (!_camPanel) return;
        const expanded = _camPanel.classList.toggle('expanded');
        if (_camExpand) {
            _camExpand.classList.toggle('active', expanded);
            _camExpand.setAttribute('aria-pressed', expanded ? 'true' : 'false');
            _camExpand.title = expanded ? 'Shrink view' : 'Enlarge view';
            _camExpand.textContent = expanded ? '⤡' : '⤢';
        }
    }

    function setupCameraWiring() {
        if (!_camToggle) return;
        _camToggle.addEventListener('click', toggleCameraStream);
        if (_camExpand) _camExpand.addEventListener('click', toggleCameraExpand);
        applyCameraState(false);
        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('BOTTOM_CAMERA_FRAME', handleCameraFrame);
        }
        // Camera zoom/pan. wheel needs passive:false so we can preventDefault
        // and stop the page from scrolling beneath the FOV.
        if (_camStage) {
            _camStage.addEventListener('wheel', onCameraWheel, { passive: false });
            _camStage.addEventListener('pointerdown', onCameraPointerDown);
            _camStage.addEventListener('pointermove', onCameraPointerMove);
            _camStage.addEventListener('pointerup', onCameraPointerEnd);
            _camStage.addEventListener('pointercancel', onCameraPointerEnd);
            _camStage.addEventListener('dblclick', onCameraDoubleClick);
        }
    }

    // =====================================================================
    // Room-light toggle
    // =====================================================================

    function applyRoomLight(state, available) {
        _roomLightState = state || 'unknown';
        _roomLightAvailable = !!available;
        if (!_roomLightToggle) return;
        _roomLightToggle.hidden = !_roomLightAvailable;
        _roomLightToggle.disabled = !_roomLightAvailable || _roomLightBusy;
        const on = _roomLightState === 'on';
        _roomLightToggle.classList.toggle('is-on', on);
        _roomLightToggle.setAttribute('aria-pressed', on ? 'true' : 'false');
        if (_roomLightLabel && !_roomLightBusy) {
            _roomLightLabel.textContent = on ? 'Room light: on'
                : (_roomLightState === 'off' ? 'Room light: off' : 'Room light');
        }
    }

    async function loadRoomLightStatus() {
        if (!_roomLightToggle || _roomLightBusy) return;
        try {
            const res = await fetch('/api/devices/room_light/status');
            if (!res.ok) { applyRoomLight('unknown', false); return; }
            const data = await res.json();
            applyRoomLight(data.state, data.available);
        } catch (err) {
            console.debug('room light status fetch failed:', err);
            applyRoomLight('unknown', false);
        }
    }

    async function toggleRoomLight() {
        if (!_roomLightToggle || _roomLightBusy || !_roomLightAvailable) return;
        const next = _roomLightState === 'on' ? 'off' : 'on';
        _roomLightBusy = true;
        _roomLightToggle.classList.add('is-busy');
        _roomLightToggle.disabled = true;
        if (_roomLightLabel) {
            _roomLightLabel.textContent = next === 'on' ? 'Turning on…' : 'Turning off…';
        }

        // Settle back to the resolved state, or surface a transient message
        // (insufficient control / error) for 2 s before reverting.
        const finish = (msg) => {
            _roomLightBusy = false;
            _roomLightToggle.classList.remove('is-busy');
            if (msg) {
                if (_roomLightLabel) _roomLightLabel.textContent = msg;
                _roomLightToggle.disabled = false;
                setTimeout(() => applyRoomLight(_roomLightState, _roomLightAvailable), 2000);
            } else {
                applyRoomLight(_roomLightState, _roomLightAvailable);
            }
        };

        try {
            const res = await fetch('/api/devices/room_light/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ state: next }),
            });
            if (res.status === 401 || res.status === 403) { finish('Need control'); return; }
            if (!res.ok) {
                console.error('room light set failed:', await res.text());
                finish('Error');
                return;
            }
            const data = await res.json();
            _roomLightState = data.state || next;
            finish(null);
        } catch (err) {
            console.error('room light toggle failed:', err);
            finish('Error');
        }
    }

    function setupRoomLight() {
        if (!_roomLightToggle) return;
        _roomLightToggle.addEventListener('click', toggleRoomLight);
        loadRoomLightStatus();
        // Light periodic refresh: state can also change from agent plans
        // (e.g. brightfield imaging turns it on). Status read is cached at the
        // device layer (no BLE), so polling is cheap; it also makes the toggle
        // appear automatically once the device layer connects.
        if (_roomLightTimer) clearInterval(_roomLightTimer);
        _roomLightTimer = setInterval(loadRoomLightStatus, 15000);
    }

    // =====================================================================
    // Temperature controller (ACUITYnano) — readout + setpoint
    // =====================================================================

    function fmtTemp(v) {
        return (v === null || v === undefined || isNaN(v)) ? '—' : Number(v).toFixed(1) + '°';
    }

    function applyTemperature(data) {
        _tempAvailable = !!(data && data.available);
        if (!_tempEl) return;
        _tempEl.hidden = !_tempAvailable;
        if (!_tempAvailable) return;
        _tempState = (data && data.state) || 'unknown';
        const locked = /LOCK/i.test(_tempState);
        _tempEl.classList.toggle('is-locked', locked);
        if (_tempBusy) return;  // a set() is in flight; leave its transient label
        const cur = fmtTemp(data.temperature_c);
        const hasSp = data.setpoint_c !== null && data.setpoint_c !== undefined;
        const sp = hasSp ? fmtTemp(data.setpoint_c) : null;
        _tempReadout.textContent = sp ? (cur + ' → ' + sp) : cur;
        _tempReadout.title = 'Water ' + cur + (sp ? (', setpoint ' + sp) : '')
            + (locked ? ' (locked)' : '');
        // Seed the input with the current setpoint once, while untouched, so the
        // operator sees where it is before nudging it.
        if (_tempInput && document.activeElement !== _tempInput && _tempInput.value === '' && hasSp) {
            _tempInput.value = Number(data.setpoint_c).toFixed(1);
        }
    }

    async function loadTemperatureStatus() {
        if (!_tempEl || _tempBusy) return;
        try {
            const res = await fetch('/api/devices/temperature/status');
            if (!res.ok) { applyTemperature({ available: false }); return; }
            applyTemperature(await res.json());
        } catch (err) {
            console.debug('temperature status fetch failed:', err);
            applyTemperature({ available: false });
        }
    }

    async function setTemperature() {
        if (!_tempEl || _tempBusy || !_tempAvailable) return;
        const target = parseFloat(_tempInput && _tempInput.value);
        if (isNaN(target) || target < 0 || target > 99.9) {
            _tempReadout.textContent = '0–99.9 °C';
            setTimeout(loadTemperatureStatus, 1500);
            return;
        }
        _tempBusy = true;
        _tempEl.classList.add('is-busy');
        if (_tempSet) _tempSet.disabled = true;
        _tempReadout.textContent = 'Set ' + target.toFixed(1) + '°…';

        // Settle back to the resolved state, or surface a transient message
        // (insufficient control / error) for 2 s before reverting.
        const finish = (msg) => {
            _tempBusy = false;
            _tempEl.classList.remove('is-busy');
            if (_tempSet) _tempSet.disabled = false;
            if (msg) {
                _tempReadout.textContent = msg;
                setTimeout(loadTemperatureStatus, 2000);
            } else {
                loadTemperatureStatus();  // controller ramps; poll shows progress
            }
        };

        try {
            const res = await fetch('/api/devices/temperature/set', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ target_c: target }),
            });
            if (res.status === 401 || res.status === 403) { finish('Need control'); return; }
            if (!res.ok) {
                console.error('temperature set failed:', await res.text());
                finish('Error');
                return;
            }
            await res.json();
            finish(null);
        } catch (err) {
            console.error('temperature set failed:', err);
            finish('Error');
        }
    }

    function setupTemperature() {
        if (!_tempEl) return;
        if (_tempSet) _tempSet.addEventListener('click', setTemperature);
        if (_tempInput) {
            _tempInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') { e.preventDefault(); setTemperature(); }
            });
        }
        loadTemperatureStatus();
        // Periodic refresh: the setpoint can also change from agent plans, and a
        // commanded ramp settles over time. Status is cached at the device layer,
        // so polling is cheap; it also reveals the control once the layer connects.
        if (_tempTimer) clearInterval(_tempTimer);
        _tempTimer = setInterval(loadTemperatureStatus, 15000);
    }

    // =====================================================================
    // View switching
    // =====================================================================

    function switchView(viewName) {
        if (!VIEWS.includes(viewName)) return;
        _currentView = viewName;
        for (const v of VIEWS) {
            const el = document.getElementById(`devices-view-${v}`);
            if (el) el.style.display = (v === viewName) ? '' : 'none';
        }
        // Operate has no button of its own in this strip: its three surfaces
        // sit beside it in the toolbar and mark themselves (operate.js), so
        // with Operate up nothing here is lit.
        if (typeof updateViewButtons === 'function') {
            updateViewButtons('devices-view-switcher', viewName);
        }
        // The page's padding is the view's to set: the Operate workspace
        // takes the room to its edges (operate.css).
        const box = document.querySelector('#devices-content .devices-container');
        if (box) box.dataset.view = viewName;
        // The 3D optical-space view owns its own WebGL module. Build it lazily
        // on first activation (the panel was display:none, so its container had
        // no size until now); init() is idempotent and resizes on re-entry.
        if (viewName === 'optical3d' && typeof Occupancy3DManager !== 'undefined') {
            Occupancy3DManager.init();
        }
        // The properties are read while the table is on screen, and not otherwise.
        watchProperties(viewName === 'details');
        // Initialize temperature graph for the active view. The TemperatureGraph
        // is a singleton; reinit on view switch ensures only one graph target
        // is live at a time. ClientEventBus.off/on in TemperatureGraph.init
        // makes re-init safe (idempotent).
        if (window.TemperatureGraph) {
            const el = document.getElementById('devices-temp-graph');
            if (el) TemperatureGraph.init(el, 'current');
        }
        // The Operate view owns its own module; activate/deactivate it so its
        // camera + SPIM streams only run while it's the visible view.
        if (typeof OperateManager !== 'undefined') {
            if (viewName === 'operate') OperateManager.activate();
            else OperateManager.deactivate();
        }
    }

    function setupViewSwitcher() {
        if (typeof initViewSwitcher === 'function') {
            initViewSwitcher('devices-view-switcher', switchView);
        }
        document.addEventListener('keydown', (e) => {
            if (typeof state !== 'undefined' && typeof TABS !== 'undefined' && state.tab !== TABS.DEVICES) return;
            if (e.target.matches('input, textarea, select, [contenteditable]')) return;
            if (e.key === 'o') { e.preventDefault(); switchView('operate'); }
            else if (e.key === 'm') { e.preventDefault(); switchView('map'); }
            else if (e.key === 'd') { e.preventDefault(); switchView('details'); }
            else if (e.key === 'v') { e.preventDefault(); switchView('optical3d'); }
        });
    }

    // =====================================================================
    // Top-level event handlers
    // =====================================================================

    function handlePayload(payload) {
        if (!payload) return;
        cacheDom();
        _lastTs = payload.t || 0;
        _lastWallTs = Date.now();

        if (payload.heartbeat || payload.paused) {
            setStatus('paused', 'paused', payload.reason ? `reason: ${payload.reason}` : 'updates paused');
        } else {
            const interval = _lastTs && _previousTs ? (_lastTs - _previousTs).toFixed(2) + 's' : '';
            setStatus('live', 'live', interval ? `Δt ${interval}` : 'streaming');
        }
        _previousTs = _lastTs;

        renderPositions(payload.positions);
        // A poll tick carries positions only. The properties arrive when they
        // have been read: at the device layer's start, and on request (below).
        if (payload.properties && Object.keys(payload.properties).length) {
            // The controller's own limits are drawn separately; the working
            // region comes from the shared store, not from these properties.
            renderPropertiesTable(payload.properties);
            _lastPropertyMap = payload.properties;
            _propsReadAt = Date.now();
            renderPropsAge();
        }
        scheduleStaleCheck();
    }

    // =====================================================================
    // Properties — read when someone is looking
    // =====================================================================
    // The device layer does not sweep every property on a timer any more: a
    // sweep holds the controller's serial port for about two seconds, behind
    // which every button on this page waited, and a tick that carried the
    // result had each browser redraw this table six times a second. So the
    // table is read on opening Details, on "Read again", and every
    // PROPS_EVERY_MS while Details stays on screen. The device layer
    // broadcasts what it read, which is what draws the table — here and on
    // any other screen showing it.
    const PROPS_EVERY_MS = 15000;
    let _propsReadAt = 0;
    let _propsBusy = false;
    let _propsTimer = null;

    function detailsOnScreen() {
        const el = document.getElementById('devices-view-details');
        return !!(el && el.offsetParent !== null);
    }

    function renderPropsAge() {
        const el = document.getElementById('devices-props-age');
        if (!el) return;
        if (_propsBusy) { el.textContent = 'reading…'; return; }
        if (!_propsReadAt) { el.textContent = 'not read yet'; return; }
        const s = Math.round((Date.now() - _propsReadAt) / 1000);
        el.textContent = s < 2 ? 'read just now' : `read ${s} s ago`;
    }

    /** The snapshot as the device layer holds it; `fresh` has every property read now. */
    async function readProperties(fresh) {
        if (_propsBusy) return;
        _propsBusy = true;
        renderPropsAge();
        try {
            const r = await fetch(`/api/devices/state${fresh ? '?refresh=1' : ''}`);
            if (!r.ok) return;                     // no microscope: the table keeps what it has
            const d = await r.json();
            // On the bus rather than straight into handlePayload: the 3D view
            // takes the stage's firmware box from the same properties.
            if (d && typeof ClientEventBus !== 'undefined') ClientEventBus.emit('DEVICE_STATE_UPDATE', d);
        } catch (_) { /* the next read, or the next broadcast, fills it */ }
        finally { _propsBusy = false; renderPropsAge(); }
    }

    function watchProperties(on) {
        if (_propsTimer) { clearInterval(_propsTimer); _propsTimer = null; }
        if (!on) return;
        readProperties(true);
        _propsTimer = setInterval(() => {
            renderPropsAge();
            if (detailsOnScreen() && Date.now() - _propsReadAt >= PROPS_EVERY_MS) readProperties(true);
        }, 1000);
    }

    // Single availability signal (from the launcher's device-layer watcher).
    // When the layer goes away, drop the stale working-region so the map reverts
    // to the neutral no-position state instead of a frozen red/green field. Live
    // data repopulates _optimalBox via DEVICE_STATE_UPDATE once it's back.
    function handleAvailability(d) {
        if (d && d.available === false && _optimalBox) {
            _optimalBox = null;
            renderMap();
        }
    }

    // =====================================================================
    // XY limits — the controller's fence, not ours
    // =====================================================================
    // `set_firmware_limits` writes into the ASI Tiger, which enforces against
    // EVERY motion source — so the region drawn on this map also stops the
    // stage for someone driving it from Micro-Manager, with nothing on their
    // screen to explain it. This switch hands the stage back.
    function setupLimitsSwitch() {
        const btn = document.getElementById('devices-limits-toggle');
        const note = document.getElementById('devices-limits-note');
        if (!btn || !note || typeof XYLimitsState === 'undefined') return;

        // The map draws the same region this switch describes — one store,
        // so the zone and the switch cannot disagree about where the fence is.
        XYLimitsState.subscribe(applyWorkingRegion);

        XYLimitsState.subscribe(s => {
            if (s.enforced === null) {
                btn.disabled = true;
                btn.textContent = 'XY limits —';
                btn.setAttribute('aria-pressed', 'false');
                note.textContent = s.reason || 'reading…';
                return;
            }
            // Pressed means "off", the state worth seeing across the room.
            btn.disabled = !!s.busy;
            btn.setAttribute('aria-pressed', s.enforced ? 'false' : 'true');
            btn.textContent = s.enforced ? 'XY limits enforced' : 'XY limits OFF';
            note.textContent = s.busy
                ? 'Writing to the controller…'
                : (s.reason || (s.enforced
                    ? 'The controller stops the stage at this region — for every client, Micro-Manager included.'
                    : 'Controller defaults. Only the limit switches stop the joystick now — the holder can reach the optics.'));
        });

        btn.addEventListener('click', () => {
            XYLimitsState.write(btn.getAttribute('aria-pressed') === 'true');
        });

        XYLimitsState.read();
    }

    // =====================================================================
    // Region editor — the map is the form
    // =====================================================================
    // The old wizard walked two corners in a 300px column floating over the
    // map, and opened taller than the card it lived in, so its own Start
    // button sat off the bottom of the window. RegionEditor owns the state;
    // this owns the drawing and the clicks.
    const EDGE_HIT = 14;   // px of slop around a line, at map scale

    function setupRegionEditor() {
        const btn = document.getElementById('devices-region-edit');
        const strip = document.getElementById('region-strip');
        if (!btn || !strip || typeof RegionEditor === 'undefined') return;

        const el = id => document.getElementById(id);
        const wrap = document.getElementById('devices-map-wrap');

        // One place decides what "editing" looks like, so the strip, the
        // button and the overlays it displaces can never disagree.
        const showEditing = on => {
            strip.hidden = !on;
            btn.hidden = on;
            if (wrap) wrap.classList.toggle('is-editing', on);
            // Opening took the fence down and closing put it back or wrote a new
            // region; the limits card and the OPTIMAL box read the same state.
            if (typeof XYLimitsState !== 'undefined') XYLimitsState.read();
            // Opening and closing both change what the sheet has to frame, and
            // the next telemetry tick may be a second away. renderMap() draws
            // from _viewBox rather than recomputing it, so refresh that first.
            computeViewBox();
            renderMap();
            renderEditLayer();
        };

        RegionEditor.onChange(() => { renderStrip(); renderEditLayer(); });

        btn.addEventListener('click', async () => {
            // It says why it refused; the map stays as it was.
            if (!await RegionEditor.open({ startCamera: startRegionCam })) return;
            showEditing(true);
            renderStrip();
        });

        el('region-capture').addEventListener('click', async () => {
            // One button, whose job changes with the step — so there is never
            // a choice to make about which control the walk wants next.
            if (RegionEditor.step() === 'review') {
                if (await RegionEditor.apply({ stopCamera: stopRegionCam })) showEditing(false);
                return;
            }
            RegionEditor.capture();
        });

        el('region-back').addEventListener('click', () => RegionEditor.back());

        el('region-cancel').addEventListener('click', async () => {
            await RegionEditor.cancel({ stopCamera: stopRegionCam });
            showEditing(false);
        });

        el('region-history-btn').addEventListener('click', () => {
            const host = el('region-history');
            host.hidden = !host.hidden;
            if (!host.hidden) renderHistory();
        });

        el('region-history').addEventListener('click', async e => {
            const row = e.target.closest('[data-at]');
            if (row) await RegionEditor.restore(row.dataset.at);
        });

        // Typing a bound, and snapping one to the stage, are the same edit.
        el('region-bounds').addEventListener('change', e => {
            const inp = e.target.closest('input[data-bound]');
            if (inp) RegionEditor.setBound(inp.dataset.bound, parseFloat(inp.value));
        });
        el('region-bounds').addEventListener('click', e => {
            const snap = e.target.closest('button[data-bound]');
            if (snap) RegionEditor.useStage(snap.dataset.bound);
        });

        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('BOTTOM_CAMERA_FRAME', p => {
                if (!RegionEditor.isOpen() || !p || !p.jpeg_b64) return;
                const img = el('region-cam-img');
                const ph = el('region-cam-ph');
                img.src = `data:image/jpeg;base64,${p.jpeg_b64}`;
                img.style.display = 'block';
                if (ph) ph.hidden = true;
            });
        }
    }

    async function startRegionCam() {
        await fetch('/api/devices/bottom_camera/stream/start', { method: 'POST' });
    }
    async function stopRegionCam() {
        await fetch('/api/devices/bottom_camera/stream/stop', { method: 'POST' });
        const img = document.getElementById('region-cam-img');
        const ph = document.getElementById('region-cam-ph');
        if (img) { img.removeAttribute('src'); img.style.display = 'none'; }
        if (ph) ph.hidden = false;
    }

    const BOUND_LABEL = { x_min: '−X', x_max: '+X', y_min: '−Y', y_max: '+Y' };
    const STEP_TITLE = { a: 'Step 1 of 2', b: 'Step 2 of 2', review: 'Your region' };

    function renderStrip() {
        if (!RegionEditor.isOpen()) return;
        const step = RegionEditor.step();
        const review = step === 'review';
        const box = RegionEditor.box();
        const p = RegionEditor.position();

        const title = document.getElementById('region-step');
        if (title) title.textContent = STEP_TITLE[step];

        const say = document.getElementById('region-say');
        if (say) {
            say.textContent = RegionEditor.prompt();
            say.dataset.bad = RegionEditor.isBad() ? '1' : '0';
        }
        const note = document.getElementById('region-note');
        if (note) {
            note.textContent = RegionEditor.note();
            note.hidden = !note.textContent;
        }

        // The live position is the number about to be captured, so it reads as
        // an instrument value rather than as prose. In review it gives way to
        // the size, which is what you check a region by.
        const live = document.getElementById('region-live');
        if (live) {
            if (review && box) {
                live.textContent = `${Math.round(box.x_max - box.x_min)} × `
                    + `${Math.round(box.y_max - box.y_min)} µm`;
            } else {
                live.textContent = p
                    ? `stage ${p.x.toFixed(1)}, ${p.y.toFixed(1)} µm`
                    : 'stage — (no position yet)';
            }
        }

        const go = document.getElementById('region-capture');
        if (go) {
            go.textContent = review ? 'Apply' : 'Capture';
            go.disabled = !p && !review;
        }
        const back = document.getElementById('region-back');
        if (back) back.hidden = step === 'a';

        renderSchematic(step);

        // The four numbers only exist once there is a box to correct.
        const host = document.getElementById('region-bounds');
        if (!host) return;
        if (!review || !box) { host.innerHTML = ''; return; }
        const applied = RegionEditor.applied() || {};
        host.innerHTML = ['x_min', 'x_max', 'y_min', 'y_max'].map(b => {
            const changed = Math.abs((box[b] ?? 0) - (applied[b] ?? 0)) > 0.05;
            return `<label class="region-bound${changed ? ' is-changed' : ''}">
                <span>${BOUND_LABEL[b]}</span>
                <input type="number" step="1" data-bound="${b}" value="${box[b].toFixed(1)}">
                <button type="button" class="region-snap" data-bound="${b}"
                        title="Move this edge to where the stage is now">⌖</button>
            </label>`;
        }).join('');
    }

    /**
     * The corner being asked for, drawn and pulsing.
     *
     * The sentence says what to do; this shows where, which is the part that
     * reads from across the bench with a joystick in hand. In review it stops
     * asking for anything and is just the box.
     */
    function renderSchematic(step) {
        const svg = document.getElementById('region-schem');
        if (!svg) return;
        const corner = step === 'a' ? [12, 52] : step === 'b' ? [72, 12] : null;
        const rect = '<rect x="12" y="12" width="60" height="40" class="rs-box"/>';
        if (!corner) {
            svg.innerHTML = rect + '<path class="rs-tick" d="M32 32 l7 8 l14 -17"/>';
            return;
        }
        svg.innerHTML = rect
            + `<circle cx="${corner[0]}" cy="${corner[1]}" r="6" class="rs-target"/>`
            + `<circle cx="${corner[0]}" cy="${corner[1]}" r="2.6" class="rs-dot"/>`;
    }

    function renderHistory() {
        const host = document.getElementById('region-history');
        if (!host) return;
        const rows = RegionEditor.history();
        if (!rows.length) {
            host.innerHTML = '<p class="region-empty">No earlier regions yet. The first Apply starts the list.</p>';
            return;
        }
        host.innerHTML = rows.map(h => {
            const when = (h.applied_at || '').replace('T', ' ').slice(0, 16);
            const size = `${Math.round(h.x_max - h.x_min)} × ${Math.round(h.y_max - h.y_min)} µm`;
            return `<button type="button" class="region-hrow" data-at="${h.applied_at}">
                <span class="region-hwhen">${when}</span>
                <span class="region-hsize">${size}</span>
                <span class="region-hgo">Restore</span></button>`;
        }).join('');
    }

    /**
     * The region taking shape on the sheet.
     *
     * The first corner is a mark; the second is wherever the stage is, so the
     * box follows the joystick until it is captured. Watching it grow is what
     * makes "bottom-left, then top-right" mean something.
     */
    function renderEditLayer() {
        const layer = document.getElementById('devices-map-edit');
        if (!layer) return;
        layer.innerHTML = '';
        if (!RegionEditor.isOpen() || !_viewBox) return;

        const span = Math.max(_viewBox.xMax - _viewBox.xMin, 1);
        const r = span * 0.012;
        const { a, b } = RegionEditor.corners();
        const box = RegionEditor.box();

        if (box) {
            const face = document.createElementNS(SVG_NS, 'rect');
            face.setAttribute('x', box.x_min);
            face.setAttribute('y', svgY(box.y_max));
            face.setAttribute('width', Math.max(box.x_max - box.x_min, 0));
            face.setAttribute('height', Math.max(box.y_max - box.y_min, 0));
            face.setAttribute('class', 'region-face'
                + (RegionEditor.step() === 'b' ? ' is-live' : ''));
            layer.appendChild(face);
        }

        [a, b].forEach(c => {
            if (!c) return;
            const dot = document.createElementNS(SVG_NS, 'circle');
            dot.setAttribute('cx', c.x);
            dot.setAttribute('cy', svgY(c.y));
            dot.setAttribute('r', r);
            dot.setAttribute('class', 'region-corner-dot');
            layer.appendChild(dot);
        });
    }

    // Leaving Devices for another tab is leaving every surface in it. The
    // rail switched tabs without telling Operate, so a camera started here
    // kept streaming behind Embryos or Home. Coming back re-enters the
    // surface; it does not start a camera.
    function onTabChanged(tab) {
        if (typeof OperateManager === 'undefined') return;
        if (tab !== 'devices') OperateManager.deactivate();
        else if (_currentView === 'operate') OperateManager.activate();
    }

    function init() {
        cacheDom();
        setupViewSwitcher();
        setupRegionEditor();
        setupLimitsSwitch();
        setupCameraWiring();
        setupRoomLight();
        setupTemperature();
        loadCoverslip();
        loadEmbryosSnapshot();
        switchView(_currentView);
        // Once, as the device layer holds them: the 3D view's stage box and a
        // table that is not empty on first opening. No controller traffic.
        readProperties(false);
        const readBtn = document.getElementById('devices-props-read');
        if (readBtn) readBtn.addEventListener('click', () => readProperties(true));
        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('TAB_CHANGED', onTabChanged);
            ClientEventBus.on('DEVICE_STATE_UPDATE', handlePayload);
            ClientEventBus.on('DEVICE_LAYER_AVAILABILITY', handleAvailability);
            ClientEventBus.on('EMBRYOS_UPDATE', handleEmbryosUpdate);
            ClientEventBus.on('STATUS_CHANGED', handleStatusChanged);
        }
        // Map-side edit handlers. Pointer events on the SVG cover both
        // "click an embryo" (selects it) and "click empty map" (drops the
        // selected embryo). Keyboard listener is document-wide but guards
        // against firing while an input is focused.
        if (_mapSvg) {
            _mapSvg.addEventListener('pointerdown', onMapPointerDown);
        }
        document.addEventListener('keydown', onMapKeyDown);
        setStatus('stale', 'waiting', 'no payload yet');
        syncInitialCameraState();
        // Stop the camera stream if the tab is closed while running, so
        // MMCore isn't held by a disconnected browser.
        window.addEventListener('beforeunload', () => {
            if (_camStreaming) {
                try { navigator.sendBeacon('/api/devices/bottom_camera/stream/stop'); } catch (_) {}
            }
        });
    }

    return { init, handlePayload, switchView };
})();

document.addEventListener('DOMContentLoaded', () => DevicesManager.init());
