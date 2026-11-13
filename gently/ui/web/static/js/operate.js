/**
 * Operate — one workspace, and two surfaces beside it.
 *
 *   Scope        the dish, what the rig sees and the instrument, on one
 *                screen: find embryos on the bottom camera, bring the head
 *                down, look through either light-sheet camera
 *   Calibration  the piezo–galvo fit for an embryo
 *   Acquisition  the embryo roster and what to run on it
 *
 * Scope shows one frame at a time, from the camera chosen in the strip above
 * it: the bottom camera, or the light sheet from side A, side B or both.
 * `_pane` still names the camera surface ('bottom' or 'spim'), because the
 * cameras contend for MMCore and one may stream at a time. What changed on
 * 2026-11-13 is that the two are one section of the page, with one rail and
 * the same instrument panels in the same places (index.html, "SCOPE"). They
 * used to be two panes, each assembling its own rail around its own frame.
 *
 * There are no steps, no phases and no progress ladder. Every surface is
 * fully live whenever it is visible.
 *
 * THE INVARIANT: no control anywhere reads `_pane`. It is consulted by exactly
 * two things — render dispatch (which section is on screen, and inside Scope
 * which camera's frame, caption, verbs and display panel), and which camera
 * stream owns MMCore. If a `disabled` or an early-return ever starts keying
 * off `_pane`, the step model has grown back and this rewrite has been undone.
 *
 * Gating comes from live hardware state only: the F-drive floor
 * (OperateMath.stepAllowed). Selection is a cursor — it parameterises requests
 * and never disables anything. (An XY interlock against the F-drive used to
 * stand here too; see moveStageTo for why it went.)
 *
 * Pure geometry and banding live in operate-math.js so they can be
 * unit-tested (tests/js/operate-math.test.mjs).
 */
const OperateManager = (function () {
    const M = (typeof OperateMath !== 'undefined') ? OperateMath : null;
    // Canvas CSS pixels — NOT screen pixels. onCanvasClick divides the ancestor
    // scale out first, so a click stays on the same embryo whatever the bench is
    // zoomed to.
    const MARK_HIT_PX = 14;
    // The radius a registered embryo is DRAWN at. One symbol feeds the arc and
    // the hit test below, so the click target cannot drift away from the glyph
    // again.
    const EMB_R = 13;
    // A registered embryo is hit anywhere on its ring plus the same slop every
    // other target gets. Testing it against MARK_HIT_PX alone made the target
    // (14) smaller than the glyph (13 plus a label at +16): an operator aiming
    // at an embryo, missing by ~18 canvas px but still visually on the ring, got
    // a pending marker they never asked for — and Register turned it into a
    // duplicate embryo ~30 µm from the original.
    //
    // ponytail: the cost is that two embryos cannot be hand-marked within 27
    // canvas px of each other. If operators need that, the honest fix is to stop
    // overloading the click — delete the centre-on-embryo branch and let the
    // roster's Centre button own that verb.
    const EMB_HIT_PX = EMB_R + MARK_HIT_PX;

    let _wired = false, _active = false;

    // ── navigation: the ONLY navigation state in this file ──────────────────
    let _pane = 'bottom';
    // The camera surface Scope last showed: "Scope" in the toolbar comes back
    // to it from Calibration or Acquisition.
    let _scope = 'bottom';

    // ── session facts (owned by the bus, mirrored here) ─────────────────────
    let _embryos = [];
    // A CURSOR, not a step. It parameterises request bodies and readouts. It
    // must never appear in a `disabled` or visibility expression.
    // Mirrors SharedState 'selectedEmbryoId' (see wire()): this file both
    // publishes it and follows it, so a selection made in another surface lands
    // here too instead of the two drifting apart.
    let _selected = null;

    // ── device state ────────────────────────────────────────────────────────
    // {x, y}. Fed from SharedState 'stageXY' (see wire()); DEVICE_STATE_UPDATE
    // publishes into the store rather than writing here directly.
    let _xy = null;
    // Last bottom-cam frame. Kept because the marking canvas needs its geometry
    // and capture position; the SPIM frame is only ever displayed, so it isn't.
    let _lastBottom = null;

    // ── stream ownership, per pane ──────────────────────────────────────────
    // A live view is on only while its surface is, and only because someone
    // pressed Start. These used to come with a "was on" each, so returning
    // to a surface restarted its camera — which, fourteen minutes into a
    // timelapse, started the SPIM camera streaming under the run.
    let _bottomOn = false;
    let _spimOn = false;

    // ── marking ─────────────────────────────────────────────────────────────
    // Markers are held in STAGE coordinates and re-projected onto whatever frame
    // is current, so they stay attached to the sample instead of the viewport.
    // That is what lets marking be always-on rather than a mode you enter.
    let _markers = [];

    // ── emitters / run ──────────────────────────────────────────────────────
    let _acquiring = false;
    // The selection set. `_selected` is the primary member of it.
    let _targets = [];
    // Which embryos a run targets. 'all' is the default and is what this pane
    // has always done — a plain click must never silently narrow a timelapse
    // from every subject to one, so the narrowing is a thing you say.
    let _targetScope = 'all';

    // ── AGENT-INITIATED MARKING ─────────────────────────────────────────────
    // The agent can ask the operator to mark embryos on an image it pushes
    // (server.start_marking_session -> a `marking_image` websocket frame, and
    // it waits for `marking_done` keyed by session_id).
    //
    // That request used to land on a SECOND marking implementation —
    // static/js/marking.js, 452 lines with its own canvas, its own hit-test
    // and its own list, in the Embryos tab. So every fix to marking landed on
    // one of two surfaces: the zoom, the display range, #105's hit-test and
    // #126's aliasing all existed here and none of them there. Whether an
    // operator got the corrected behaviour depended on who had asked them to
    // mark.
    //
    // One surface now, two invocations. The pushed image is adapted into the
    // frame shape this pane already understands, so all of that geometry
    // applies unchanged.
    let _markSession = null;

    /** The µm/px this session declares, or the rig default. */
    function pxBase() {
        return _markSession ? _markSession.pixelSizeUm : undefined;
    }
    // Read back from the Light panel's device read, never remembered here.
    const ledIsOpen = () => (SharedState.get('light') || {}).led === 'Open';
    // The live sheet's pose, per side: B's scanner and piezo are different
    // devices with their own numbers, so switching sides must not carry A's.
    // Both axes start at 0, the origin the ASIdiSPIM plugin's Home goes to.
    let _side = 'A';
    const _pose = { A: { galvo: 0.0, piezo: 0.0 }, B: { galvo: 0.0, piezo: 0.0 } };
    // The axes' extents per side, from the controller (fetchRange); until
    // read, a span to draw the line with.
    const _range = { A: null, B: null };
    const RANGE_DEFAULT = { galvo: [-5, 5], piezo: [-100, 100] };
    // When this pane last chose a side. A frame of the old side that lands
    // inside the window was grabbed before the switch and is dropped; outside
    // the window, a frame of another side means the device layer is on a side
    // this pane never chose, and the pane follows it (adoptLsParams).
    const SIDE_SWITCH_MS = 2000;
    let _sideChangedAt = 0;
    let _mode = 'adaptive';
    let _selectedLib = null;
    let _runPaused = false;

    // ── primitives ──────────────────────────────────────────────────────────
    function $(id) { return document.getElementById(id); }
    function toast(m) { if (typeof showGentlyToast === 'function') showGentlyToast(m); }
    // Same funnel, error styling — a failure must not read as a confirmation.
    // Longer than a success toast: a failure carries a reason now, and a reason
    // takes longer to read than "Volume acquired".
    function toastFail(m) { if (typeof showGentlyToast === 'function') showGentlyToast(m, null, null, 10000, 'error'); }

    // The reason a request failed, not the number it failed with.
    //
    // Every route already answers with one — FastAPI's HTTPException writes
    // `{detail: ...}` and the device layer writes `{error: ...}`. postJSON kept
    // the body on the error, but every call site formatted `${e.status ||
    // e.message}`, so an operator at the scope read "Detect failed (502)" while
    // the server had said exactly what went wrong. That is most of a debugging
    // round trip thrown away at the last step.
    const WHY_MAX = 200;
    function why(e) {
        const d = (e && e.data) || {};
        let msg = d.detail != null ? d.detail : d.error;
        // FastAPI answers 422 with a list of validation objects.
        if (Array.isArray(msg)) msg = msg.map(x => (x && x.msg) || JSON.stringify(x)).join('; ');
        else if (msg && typeof msg === 'object') msg = JSON.stringify(msg);
        msg = msg == null ? '' : String(msg).trim();
        if (!msg) return String((e && (e.status || e.message)) || 'unknown error');
        // The full text always reaches the console; the toast gets a readable cut.
        if (e && e.status) console.warn(`[gently] ${e.status}: ${msg}`);
        const short = msg.length > WHY_MAX ? `${msg.slice(0, WHY_MAX - 1)}…` : msg;
        return e && e.status ? `${e.status} — ${short}` : short;
    }
    function escapeHtml(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }

    async function postJSON(url, body) {
        const res = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        });
        const text = await res.text().catch(() => '');
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (_) { /* not JSON */ }
        if (!res.ok) {
            const e = new Error(`${res.status} ${data.error || text}`);
            e.status = res.status;
            // A fenced nudge answers 400 but still reports where the axis
            // actually is. Carry the body so the caller can re-absorb it
            // instead of leaving the gauge stale.
            e.data = data;
            throw e;
        }
        return data;
    }
    async function deleteJSON(url) {
        const res = await fetch(url, { method: 'DELETE' });
        const text = await res.text().catch(() => '');
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (_) { /* not JSON */ }
        if (!res.ok) {
            const e = new Error(`${res.status} ${data.detail || data.error || text}`);
            e.status = res.status;
            e.data = data;
            throw e;
        }
        return data;
    }
    async function getJSON(url) {
        const res = await fetch(url);
        const text = await res.text().catch(() => '');
        let data = {};
        try { data = text ? JSON.parse(text) : {}; } catch (_) { /* not JSON */ }
        if (!res.ok) { const e = new Error(String(res.status)); e.status = res.status; e.data = data; throw e; }
        return data;
    }

    function labelFor(emb) {
        const m = emb && emb.id && String(emb.id).match(/(\d+)/);
        return m ? m[1] : '?';
    }
    function resolveXY(emb) {
        const f = emb && emb.position_fine;
        if (f && Number.isFinite(f.x) && Number.isFinite(f.y)) return { x: f.x, y: f.y };
        const c = emb && emb.position_coarse;
        if (c && Number.isFinite(c.x) && Number.isFinite(c.y)) return { x: c.x, y: c.y };
        return null;
    }

    // Is the light-sheet frame on screen actually the selected embryo's?
    //
    // The caption and the pixels are two independent channels: selecting a
    // different embryo rewrote the caption and left the previous embryo's frame
    // in place, so the view claimed embryo 3 while showing embryo 1. Both facts
    // needed to answer this were already in hand — _xy and the embryo position.
    //
    // "No embryo selected" is not a claim about an embryo, so the frame stands.
    // Anything else must be confirmable, or the caller blanks it.
    function atSelected() {
        if (!_selected) return true;
        const emb = _embryos.find(e => e.id === _selected);
        const xy = emb ? resolveXY(emb) : null;
        return M ? M.atPosition(_xy, xy) : true;
    }

    // ══ THE RUN OWNS THE INSTRUMENT ═════════════════════════════════════
    // While a timelapse is running, a verb here that would take the instrument
    // from it asks first: the stage, the head, a live view, a calibration.
    // The run drives the stage to each embryo and takes the cameras on its own
    // clock, so a hand on them mid-run is either undone by the next round or
    // meets the one in progress.
    //
    // Gated on the rig's state, which the shell keeps on <body> for every
    // surface (data-run, from the run's own events), and never on which
    // surface is on screen. A paused run is held on purpose and asks nothing.
    // One yes holds for a minute, so a correction of several presses is one
    // question and not several.
    const HANDS_ON_MS = 60000;
    let _handsOnUntil = 0;
    function mayTakeFromRun(what) {
        if (document.body.dataset.run !== 'running') return true;
        if (Date.now() < _handsOnUntil) return true;
        const ok = window.confirm(`A run is going. ${what} takes the instrument from it.`
            + '\n\nPause the run first if this is more than a nudge. Go ahead anyway?');
        if (ok) _handsOnUntil = Date.now() + HANDS_ON_MS;
        return ok;
    }

    // ══ THE XY CHOKEPOINT ═══════════════════════════════════════════════════
    // The ONLY caller of /api/devices/stage/move in this file. Nothing
    // interlocks XY against the F-drive: the server validates that x and y are
    // floats and nothing else, and the page's own lock — XY refused, a banner
    // and a Back off button in every pane whenever the head was within
    // 1000 µm of its floor — was taken out on 2026-11-08 at the operator's
    // request: the rig images at ~85 µm to floor, so it refused every
    // drive-to-embryo during a run. The chokepoint stays: one caller, and
    // grep the URL string before touching XY motion.
    // `said` is what to toast on success. It was named `why`, which shadowed
    // the why() helper the catch calls — so every failed move threw a second
    // time, inside its own handler, and the operator saw no toast at all.
    async function moveStageTo(x, y, said) {
        if (!mayTakeFromRun('Moving the stage')) return false;
        try {
            await postJSON('/api/devices/stage/move', { x, y });
            if (said) toast(said);
            return true;
        } catch (e) {
            toastFail(`Move failed (${why(e)})`);
            return false;
        }
    }
    // ══ Z INSTRUMENT ════════════════════════════════════════════════════════
    // One factory, two instances. The axes differ enormously in scale — the
    // bottom objective has a ~200 µm throw, the F-drive runs 30→25000 µm onto a
    // sample sitting at ~50 — so the F-drive gets position-banded steps and a
    // log track, and the bottom axis a fixed ladder on a linear one.
    //
    // The track lies along the panel, its low end at the left. It stood
    // upright, 84 px for the whole of the F-drive's travel, which gave the
    // last few hundred µm (where the head is driven by hand) about 20 px.
    function makeZAxis(cfg) {
        const st = { pos: null, min: null, max: null, floor: null, status: 'unknown', said: {} };
        let busy = false;

        const num = v => (v == null || !Number.isFinite(Number(v))) ? null : Number(v);

        function absorb(d) {
            if (!d) return;
            if (num(d.position) != null) st.pos = num(d.position);
            if (num(d.min) != null) st.min = num(d.min);
            if (num(d.max) != null) st.max = num(d.max);
            if (num(d.distance_to_floor) != null) st.floor = num(d.distance_to_floor);
            else if (st.pos != null && st.min != null) st.floor = st.pos - st.min;
            if (num(d.goto_min) != null) st.said.goto_min = num(d.goto_min);
            if (st.pos != null) st.status = 'ok';
            render();
            if (cfg.onRead) cfg.onRead(st);
        }
        // 1 Hz position stream. Without this the gauge goes stale the moment
        // someone drives the axis at the controller box instead of from here.
        function absorbTelemetry(val) {
            if (!Number.isFinite(val)) return;
            st.pos = val;
            if (st.min != null) st.floor = val - st.min;
            if (st.status !== 'absent') st.status = 'ok';
            render();
        }
        function fail(e) {
            const msg = String((e && e.data && e.data.error) || (e && e.message) || '');
            // An axis this rig does not have is a FACT, not an error: the device
            // layer 503s with "device not found". Render it as absent, quietly.
            st.status = (e && e.status === 503 && /not found/i.test(msg)) ? 'absent' : 'error';
            render();
        }

        function steps() {
            if (!cfg.bands) return cfg.steps;
            return (M ? M.fdBand(st.pos) : { steps: cfg.steps }).steps;
        }
        function bandLabel() {
            if (!cfg.bands) return '';
            if (st.pos == null) return 'position unknown';
            return (M ? M.fdBand(st.pos).label : '');
        }

        function renderNudges() {
            const host = $(cfg.root + '-nudge');
            if (!host) return;
            if (st.status === 'absent') { host.innerHTML = ''; host.dataset.band = ''; return; }
            const s = steps();
            const key = s.join(',');
            if (host.dataset.band !== key) {
                host.dataset.band = key;
                host.style.gridTemplateColumns = `repeat(${s.length}, minmax(0, 1fr))`;
                // Ups on the top row, downs on the bottom, columns aligned by
                // magnitude, so the control maps to the motion.
                // Signed, because on the call "▲ 5000" read as the diSPIM
                // plugin's "bring to 5000" — an absolute go-to. +/− says relative.
                host.innerHTML =
                    s.map(v => `<button class="op-nbtn" data-nudge="${v}" type="button" title="Raise ${v} µm">▲&nbsp;+${v}</button>`).join('') +
                    s.map(v => `<button class="op-nbtn" data-nudge="${-v}" type="button" title="Lower ${v} µm">▼&nbsp;−${v}</button>`).join('');
            }
            host.querySelectorAll('[data-nudge]').forEach(b => {
                const d = Number(b.dataset.nudge);
                b.disabled = busy || (M ? !M.stepAllowed(d, st.floor) : false);
            });
        }

        function renderTicks() {
            const host = $(cfg.root + '-ticks');
            if (!host || !cfg.ticks) return;
            const key = `${st.min},${st.max}`;
            if (host.dataset.k === key) return;
            host.dataset.k = key;
            if (st.status !== 'ok' || st.min == null || st.max == null) { host.innerHTML = ''; return; }
            host.innerHTML = cfg.ticks
                .filter(t => t > st.min && t < st.max)
                .map(t => {
                    const f = M ? M.gaugeFraction(t, st.min, st.max, cfg.scale) : null;
                    return f == null ? '' : `<span style="left:${(f * 100).toFixed(2)}%">${t}</span>`;
                }).join('');
        }

        function render() {
            const g = $(cfg.gauge);
            if (g) {
                g.dataset.status = st.status;
                // Only an axis whose floor is something to hit says so. The
                // bottom objective's lower limit is the far end of its focus
                // travel, and it used to wear the same amber mark whenever it
                // was within 100 µm of it, which was most of the time.
                g.classList.toggle('is-near-floor', cfg.warnBelow != null
                    && st.status === 'ok' && st.floor != null && st.floor < cfg.warnBelow);
                // In flight: the nudges going pale said nothing (#109). Now the
                // gauge says so, and the caption below it names the state.
                g.classList.toggle('is-moving', busy);
            }
            const read = $(cfg.root + '-pos');
            if (read) {
                read.textContent = st.status === 'absent' ? 'n/a'
                    : (st.pos == null ? '—' : st.pos.toFixed(1));
            }
            const mark = $(cfg.root + '-mark');
            // Null fraction means "do not draw a marker" — a marker parked at
            // the bottom of the track reads as "at the limit", which is a lie
            // when the truth is that nothing is known yet.
            const frac = (st.status === 'ok' && M)
                ? M.gaugeFraction(st.pos, st.min, st.max, cfg.scale) : null;
            if (mark) {
                if (frac == null) mark.style.display = 'none';
                else { mark.style.display = 'block'; mark.style.left = `${(frac * 100).toFixed(2)}%`; }
            }
            const lo = $(cfg.root + '-min'), hi = $(cfg.root + '-max');
            if (lo) lo.textContent = st.min == null ? '—' : Math.round(st.min);
            if (hi) hi.textContent = st.max == null ? '—' : Math.round(st.max);

            const track = $(cfg.root + '-track');
            if (track) {
                track.setAttribute('aria-valuetext',
                    st.status === 'absent' ? 'axis not present'
                        : st.pos == null ? 'unknown' : `${st.pos.toFixed(1)} micrometres`);
            }
            // An absent or unreachable axis says so wherever this gauge has room
            // for a line of text — the banded axis uses its band caption, the
            // plain one its foot.
            const statusText = st.status === 'absent' ? 'axis not present on this rig'
                : st.status === 'error' ? 'position unavailable' : null;
            const band = $(cfg.root + '-band');
            if (band) band.textContent = statusText || (busy ? 'moving…' : bandLabel());
            const floor = $(cfg.root + '-floor');
            if (floor) floor.textContent = st.floor == null ? '—' : Math.round(st.floor);
            const foot = $(cfg.root + '-foot');
            if (foot) foot.textContent = statusText || '';
            renderTicks();
            renderNudges();
        }

        async function nudge(delta) {
            if (M && !M.stepAllowed(delta, st.floor)) {
                toastFail('Too close to the floor for that step');
                return;
            }
            // The head's gauge says what a step of it would take from a run;
            // the bottom objective's focus is not the run's and says nothing.
            if (cfg.takes && !mayTakeFromRun(cfg.takes)) return;
            busy = true; render();
            try {
                absorb(await postJSON(cfg.nudge, { delta }));
                if (cfg.onDown && delta < 0) cfg.onDown();
                if (cfg.onUp && delta > 0) cfg.onUp(st);
            } catch (e) {
                // Even a refused nudge reports the real position — take it.
                if (e && e.data && e.data.position != null) absorb(e.data);
                toastFail(`${cfg.label} nudge blocked (${why(e)})`);
            } finally { busy = false; render(); }
        }

        async function refresh() {
            try { absorb(await getJSON(cfg.get)); } catch (e) { fail(e); }
        }

        function wire() {
            const host = $(cfg.root + '-nudge');
            if (host) {
                host.addEventListener('click', e => {
                    const b = e.target.closest('[data-nudge]');
                    if (b && !b.disabled) nudge(Number(b.dataset.nudge));
                });
            }
            const track = $(cfg.root + '-track');
            if (track) {
                track.addEventListener('keydown', e => {
                    const s = steps();
                    const fine = s[s.length - 1], coarse = s[0];
                    const map = { ArrowUp: fine, ArrowDown: -fine, PageUp: coarse, PageDown: -coarse };
                    if (map[e.key] == null) return;
                    e.preventDefault();
                    nudge(map[e.key]);
                });
            }
        }

        return {
            wire, refresh, absorb, absorbTelemetry, render, nudge,
            pos: () => st.pos,
            floor: () => st.floor,
            status: () => st.status,
            max: () => st.max,
            // What the read said besides the position (a typed go-to's floor).
            said: key => st.said[key],
        };
    }

    const bz = makeZAxis({
        root: 'op-bz', gauge: 'op-gauge-bz', label: 'Bottom-Z',
        get: '/api/devices/stage/bottom_z',
        nudge: '/api/devices/stage/bottom_z/nudge',
        steps: [10, 1], scale: 'linear', bands: false,
    });
    const fd = makeZAxis({
        root: 'op-fd', gauge: 'op-gauge-fd', label: 'F-drive',
        get: '/api/devices/spim/fdrive',
        nudge: '/api/devices/spim/fdrive/nudge',
        bands: true, scale: 'log', ticks: [100, 1000, 10000],
        steps: [50, 10, 5],
        // What a step of it would take from a run that is going (mayTakeFromRun).
        takes: 'Moving the head',
        // The sample: within this of the F-drive's floor the panel says so.
        warnBelow: 100,
        // The head's height is one of the lines said before a run starts.
        onRead: () => { renderGoto(); if (_pane === 'acquire') renderPreflight(); },
    });

    /**
     * The SPIM head fully up, to the F-drive's top limit. A long move — the
     * button says so while it travels, and HALT stays live beside it.
     */
    /**
     * The SPIM head to a height, by name: "To 1000 µm". A long move from the
     * load height, so the button says it is travelling and HALT stays live.
     */
    async function headTo(um, b) {
        if (!mayTakeFromRun('Moving the head')) return;
        const was = b ? b.textContent : '';
        if (b) { b.disabled = true; b.textContent = 'Going…'; }
        try {
            const r = await postJSON('/api/devices/spim/fdrive/goto', { position: um });
            const at = r && r.position != null ? Math.round(r.position) : null;
            toast(at != null ? `SPIM head at ${at} µm` : `SPIM head sent to ${um} µm`);
            return true;
        } catch (e) {
            toastFail(`Move to ${um} µm failed (${why(e)})`);
            return false;
        } finally {
            if (b) { b.disabled = false; b.textContent = was; }
            fd.refresh();
        }
    }
    /**
     * The SPIM head to a height that was typed. The box takes a height from
     * the typed floor up to the F-drive's top, both as the server gave them
     * (the floor comes with the F-drive read, `goto_min`): below the floor
     * the head is brought down by the steps, watching the picture, so a
     * slipped digit cannot put it on the sample. A height outside that is
     * refused here, in words, and the server refuses it as well.
     */
    function gotoLimits() {
        const lo = fd.said('goto_min'), hi = fd.max();
        return { lo: Number.isFinite(lo) ? lo : null, hi: Number.isFinite(hi) ? hi : null };
    }
    function renderGoto() {
        const box = $('op-fd-goto');
        if (!box) return;
        const { lo, hi } = gotoLimits();
        box.placeholder = lo != null && hi != null ? `${Math.round(lo)}–${Math.round(hi)}`
            : lo != null ? `${Math.round(lo)} or more` : 'height';
        box.title = lo != null
            ? `A height from ${Math.round(lo)} µm up. Below ${Math.round(lo)} µm the head comes down by the steps.`
            : 'A height in µm';
    }
    async function goHeadTyped() {
        const box = $('op-fd-goto');
        if (!box) return;
        const um = typeof NumRow !== 'undefined' ? NumRow.parse(box.value) : Number(box.value);
        if (um == null || !Number.isFinite(um)) {
            if (String(box.value).trim()) toastFail('That is not a height: type a number of µm');
            box.focus();
            return;
        }
        const { lo, hi } = gotoLimits();
        if (lo != null && um < lo) {
            toastFail(`A typed height stops at ${Math.round(lo)} µm. Below that, bring the head down with the steps.`);
            box.select();
            return;
        }
        if (hi != null && um > hi) {
            toastFail(`The head's top is ${Math.round(hi)} µm`);
            box.select();
            return;
        }
        if (await headTo(um, $('op-fd-go'))) box.value = '';
    }
    async function raiseHead() {
        const b = $('op-fd-raise');
        if (b) { b.disabled = true; b.textContent = 'Raising…'; }
        try {
            const r = await postJSON('/api/devices/spim/fdrive/raise', {});
            const at = r && r.position != null ? Math.round(r.position) : null;
            toast(at != null ? `SPIM head raised to ${at} µm` : 'SPIM head raised');
        } catch (e) {
            toastFail(`Raise failed (${why(e)})`);
        } finally {
            if (b) { b.disabled = false; b.textContent = 'Raise head'; }
            fd.refresh();
        }
    }

    async function haltMotion() {
        try {
            const r = await postJSON('/api/devices/motion/halt', {});
            const stopped = (r.halted || []).join(', ');
            // success with nothing halted means no positioner was registered to
            // halt — not "everything is stopped". Say the difference.
            if (stopped) toast(`Halted: ${stopped}`);
            else toastFail('HALT reached no positioners — none are registered');
        } catch (e) {
            // A refusal carries its body: which axes stopped, which did not and
            // why. Naming the ones still moving is the whole point of the
            // control — "HALT failed" alone leaves the operator guessing.
            const d = (e && e.data) || {};
            const failed = Object.keys(d.errors || {});
            const stopped = (d.halted || []).join(', ');
            if (failed.length) {
                toastFail(`HALT: ${failed.join(', ')} did NOT stop`
                    + (stopped ? ` · stopped: ${stopped}` : ''));
            } else {
                toastFail(`HALT failed (${why(e)})`);
            }
        } finally {
            fd.refresh(); bz.refresh();
        }
    }
    // ══ VIEWPORT ════════════════════════════════════════════════════════════
    // ── what is arriving ────────────────────────────────────────────────────
    // Frames a second reaching this page, counted from the arrivals of the
    // last few seconds, and the frame's size. In the bar above the frame, so
    // "is the view slow, or is it the exposure" has a number. Written at most
    // once a second: a per-frame text change is one more thing for the page
    // (and the session recorder) to do on every frame.
    const ARRIVAL_WINDOW_MS = 4000;
    const _arrivals = { bottom: [], spim: [] };
    // The sensor's size as the pixel fetch states it (showFrame). The frame
    // event carries only the preview's size and its downsample, whose product
    // overstates a sensor the downsample does not divide (2050 for 2048).
    const _frameDims = { bottom: null, spim: null };
    let _viewMetaAt = 0;
    function noteFrame(pane) {
        const now = performance.now();
        const a = _arrivals[pane];
        a.push(now);
        while (a.length && now - a[0] > ARRIVAL_WINDOW_MS) a.shift();
        if (now - _viewMetaAt >= 1000) renderViewMeta();
    }
    function renderViewMeta() {
        const el = $('op-view-meta');
        if (!el) return;
        _viewMetaAt = performance.now();
        const pane = _pane === 'spim' ? 'spim' : 'bottom';
        const on = pane === 'spim' ? _spimOn : _bottomOn;
        const a = _arrivals[pane];
        const bits = [];
        if (on && a.length >= 2) {
            const span = (a[a.length - 1] - a[0]) / 1000;
            if (span > 0) bits.push(`${((a.length - 1) / span).toFixed(1)} fps`);
        }
        if (_frameDims[pane]) bits.push(_frameDims[pane]);
        const text = bits.join(' · ');
        if (el.textContent !== text) el.textContent = text;
    }

    function frameOf(p) {
        if (!p || !Array.isArray(p.shape)) return null;
        return { w: p.shape[1], h: p.shape[0], downsample: p.downsample || 1 };
    }
    function stageOf(p) {
        if (p && Array.isArray(p.stage_position) && p.stage_position.length === 2) return p.stage_position;
        // The device layer OMITS stage_position rather than defaulting it to
        // [0,0] when it cannot know it. Honour that: fall back to the position
        // stream, never to the origin.
        if (_xy && Number.isFinite(_xy.x) && Number.isFinite(_xy.y)) return [_xy.x, _xy.y];
        return null;
    }
    function setImg(imgId, phId, p) {
        const img = $(imgId), ph = $(phId);
        if (!img || !p || !p.jpeg_b64) return;
        img.src = `data:${p.mime || 'image/jpeg'};base64,${p.jpeg_b64}`;
        if (!img.classList.contains('has-frame')) {
            img.classList.add('has-frame');
            if (ph) ph.style.display = 'none';
        }
        // Match the viewport box to the frame's aspect so the border hugs the
        // image. naturalWidth is 0 until the data URL decodes, so fall back to a
        // one-shot load listener.
        if (img.naturalWidth && img.naturalHeight) setCamAspect(img);
        else img.addEventListener('load', () => setCamAspect(img), { once: true });
    }
    // The frame's aspect, on the fit box and on the viewport box around it:
    // the fit draws its chrome to it, and Scope sizes the box from it
    // (operate.css, "Scope"); the fit inherits what the box has.
    function setCamAr(fit, ar) {
        fit.style.setProperty('--cam-ar', ar);
        const box = fit.closest('.op-cam');
        if (box) box.style.setProperty('--cam-ar', ar);
    }
    function setCamAspect(img) {
        const fit = img.closest('.op-cam-fit');
        if (fit && img.naturalWidth && img.naturalHeight) {
            setCamAr(fit, `${img.naturalWidth} / ${img.naturalHeight}`);
        }
    }

    // ── the frame as its numbers ────────────────────────────────────────────
    // The stream's JSON frame stays the trigger and the geometry (shape,
    // downsample, stage position, focus score); the pixels come as uint16
    // bytes from the device layer's last grab and are drawn by a U16View in
    // the fit box, under the marker canvas, with a window that stays where
    // the operator put it (#149). A rig that has no pixels to give — an older
    // device layer, a pushed marking still — shows the JPEG as before.
    const FRAME_SRC = {
        bottom: { img: 'op-img-bottom', ph: 'op-ph-bottom', box: 'op-cam-bottom', url: '/api/devices/bottom_camera/frame.u16' },
        spim: { img: 'op-img-spim', ph: 'op-ph-spim', box: 'op-cam-spim', url: '/api/devices/lightsheet/frame.u16' },
    };
    const _pull = {};
    function fitOf(pane) { const img = $(FRAME_SRC[pane].img); return img ? img.closest('.op-cam-fit') : null; }
    function viewFor(pane) {
        const fit = fitOf(pane);
        if (!fit) return null;
        if (!fit._u16) {
            const host = document.createElement('div');
            host.className = 'op-cam-pix';
            fit.insertBefore(host, $(FRAME_SRC[pane].img).nextSibling);
            fit._u16 = U16View.create(host, { bar: false });
        }
        return fit._u16;
    }
    async function showFrame(pane, p, pixels = true) {
        const { img: imgId, ph: phId, url, box } = FRAME_SRC[pane];
        if (!pixels || typeof U16View === 'undefined') { setImg(imgId, phId, p); return; }
        // One fetch in flight per pane; a frame that lands meanwhile waits its turn,
        // and only the newest does, so a slow link shows the frames it can.
        if (_pull[pane]) { _pull[pane].next = p; return; }
        const job = _pull[pane] = { next: null };
        try {
            // ÷2: a 2048² sensor is 2 MB a frame and the box shows it well under
            // 1024 px; the readout says the value is a mean of 2×2.
            const r = await fetch(`${url}?scale=2`, { cache: 'no-store' });
            if (!r.ok) throw new Error(`HTTP ${r.status}`);
            const meta = U16Math.parseHeaders(k => r.headers.get(k));
            const buf = await r.arrayBuffer();
            const view = viewFor(pane);
            if (!view) throw new Error('no fit box');
            view.set(new Uint16Array(buf), meta);
            const fit = fitOf(pane), ph = $(phId);
            fit.classList.add('has-pixels');
            setCamAr(fit, `${meta.width} / ${meta.height}`);
            if (meta.sourceWidth && meta.sourceHeight) _frameDims[pane] = `${meta.sourceWidth}×${meta.sourceHeight}`;
            if (ph) ph.style.display = 'none';
            if (typeof ImageView !== 'undefined' && ImageView.frameArrived) ImageView.frameArrived(box);
        } catch (_) {
            const fit = fitOf(pane);
            if (fit) fit.classList.remove('has-pixels');
            setImg(imgId, phId, p);
        } finally {
            _pull[pane] = null;
            if (job.next) showFrame(pane, job.next, true);
        }
    }
    // A frame is on the surface: the JPEG, or the pixels.
    function frameShown(imgId) {
        const img = $(imgId), fit = img && img.closest('.op-cam-fit');
        return !!((img && img.classList.contains('has-frame')) || (fit && fit.classList.contains('has-pixels')));
    }
    // The value under the cursor, read off the pixels the view holds. The
    // marker canvas takes the mouse, so it is asked from here, in the same
    // frame fractions a click is mapped in.
    function readUnderCursor(e) {
        const fit = fitOf('bottom'), view = fit && fit._u16;
        if (!view || !view.data || !fit.classList.contains('has-pixels')) return;
        const r = renderedRect(), c = $('op-mark-canvas');
        if (!r || !c) return;
        const rect = c.getBoundingClientRect();
        const sx = rect.width / c.offsetWidth, sy = rect.height / c.offsetHeight;
        if (!(sx > 0 && sy > 0)) return;
        const x = (e.clientX - rect.left) / sx, y = (e.clientY - rect.top) / sy;
        view.readAt(Math.floor((x - r.x) / r.w * view.w), Math.floor((y - r.y) / r.h * view.h));
    }
    // ══ REACTIVE PREVIEW ════════════════════════════════════════════════════
    // A routine that takes seconds and produces images has to show them where it
    // was started. Calibrate used to be one blocking POST: the montage it builds
    // was pushed to the viz server with nobody listening, so the only way to see
    // what the sweep did was to decide, unprompted, to go and open the
    // Calibration tab. The operator is watching the microscope, not hunting tabs.
    //
    // Presence-driven: it seats itself when images arrive and retires when they
    // stop. There is deliberately no open or close control — an observer should
    // be able to stand and watch without touching anything.
    //
    // RIG-NOTE: 45s is a guess at how long someone wants a finished sweep to stay
    // readable before the pane goes quiet again. Tune it against real use; too
    // short and the result vanishes mid-read, too long and a stale montage sits
    // next to a live view.
    const PREVIEW_IDLE_MS = 45000;
    let _previewTimer = null;

    function showPreview(title, meta, src) {
        const fig = $('op-preview'), img = $('op-preview-img');
        if (!fig || !img) return;
        if (src) img.src = src;
        const t = $('op-preview-title'), m = $('op-preview-meta');
        if (t) t.textContent = title || '';
        if (m) m.textContent = meta || '';
        fig.hidden = false;
        // Next frame, so the transition runs from the hidden state.
        requestAnimationFrame(() => fig.classList.add('is-live'));
        clearTimeout(_previewTimer);
        _previewTimer = setTimeout(retirePreview, PREVIEW_IDLE_MS);
    }

    function retirePreview() {
        const fig = $('op-preview');
        clearTimeout(_previewTimer);
        _previewTimer = null;
        if (!fig || fig.hidden) return;
        fig.classList.remove('is-live');
        // Hide only after the fade, or it disappears with a jump.
        setTimeout(() => { if (!fig.classList.contains('is-live')) fig.hidden = true; }, 300);
    }

    // Every image the server pushes lands here; we take the ones this pane is
    // responsible for. Filtering on data_type rather than uid keeps a new routine
    // one string away from having a preview.
    const PREVIEW_KINDS = {
        focus_montage: 'Focus sweep',
    };

    function onPushedImage(d) {
        if (!d || !d.base64_png) return;
        const title = PREVIEW_KINDS[d.data_type];
        if (!title) return;
        const md = d.metadata || {};
        const bits = [];
        if (md.pick) bits.push(`pick ${md.pick}`);
        if (md.method) bits.push(md.method === 'vision' ? 'chosen by vision' : 'chosen by FFT');
        if (Array.isArray(md.offsets) && md.offsets.length) {
            bits.push(`${md.offsets.length} offsets, ${md.offsets[0]} to ${md.offsets[md.offsets.length - 1]} µm`);
        }
        if (md.reasoning) bits.push(String(md.reasoning));
        showPreview(title, bits.join(' · '), `data:image/png;base64,${d.base64_png}`);
    }

    function clearImg(imgId, phId, text) {
        const img = $(imgId), ph = $(phId), fit = img && img.closest('.op-cam-fit');
        if (img) img.classList.remove('has-frame');
        if (fit) fit.classList.remove('has-pixels');
        if (ph) { ph.style.display = ''; if (text) ph.textContent = text; }
    }
    // Stopping the stream freezes the last frame in place rather than clearing
    // it: an operator wants to keep reading what is on the sample surface after
    // ending live view. Only fall back to the placeholder when no frame was
    // ever shown. The "LIVE" badge dropping (renderSubnavMeta) is the cue that
    // the frame is now static.
    function freezeImg(imgId, phId, text) {
        if (frameShown(imgId)) return;
        clearImg(imgId, phId, text);
    }

    // Letterbox geometry for an object-fit: contain image, in CSS pixels.
    // Taken off the CANVAS, not its host: it is the element being drawn into,
    // and using one source for geometry and for the backing store keeps them
    // from disagreeing.
    // The LAYOUT box, never getBoundingClientRect: an ancestor `scale()` (the
    // Atrium bench) inflates the measured rect but not offsetWidth/offsetHeight,
    // and a transform-inclusive geometry feeding a transform-blind backing store
    // is exactly how the overlay drifts off the image. Everything downstream —
    // markers, glyph radii, hit tests — is in these canvas CSS pixels.
    function renderedRect() {
        const c = $('op-mark-canvas');
        if (!c) return null;
        const bw = c.offsetWidth, bh = c.offsetHeight;
        if (!(bw > 0 && bh > 0)) return null;
        const f = frameOf(_lastBottom);
        const fw = f ? f.w : bw, fh = f ? f.h : bh;
        const ar = fw / fh, sar = bw / bh;
        let w, h;
        if (ar > sar) { w = bw; h = bw / ar; }
        else { h = bh; w = bh * ar; }
        return { x: (bw - w) / 2, y: (bh - h) / 2, w, h, fw, fh };
    }
    function canvasCtx() {
        const c = $('op-mark-canvas');
        if (!c) return null;
        const bw = c.offsetWidth, bh = c.offsetHeight;
        if (!(bw > 0 && bh > 0)) return null;
        // The backing store must track the CSS box or everything drawn is
        // scaled — a stale height renders circles as ellipses. Scaling by dpr
        // keeps it crisp on fractional-ratio displays; the transform then lets
        // every drawing call stay in CSS pixels. Sizing off the layout box also
        // keeps a bench zoom from reallocating (and past ~16384px, failing to
        // allocate) the store on every step.
        const dpr = window.devicePixelRatio || 1;
        const w = Math.round(bw * dpr), h = Math.round(bh * dpr);
        if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
        const ctx = c.getContext('2d');
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        ctx.clearRect(0, 0, bw, bh);
        return ctx;
    }
    // Project a stage-space marker onto the current frame, then onto the canvas.
    function markerToCanvas(m, r) {
        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        if (!f || !cap || !M) return null;
        const px = M.stageToFrame(m.stageX, m.stageY, f, cap, pxBase());
        if (!px) return null;
        return { cx: r.x + (px[0] / r.fw) * r.w, cy: r.y + (px[1] / r.fh) * r.h, px };
    }
    // Registered embryos, projected onto the current frame. These are the
    // click-to-center targets; pending markers are a separate, editable set.
    function embryoPoints(r) {
        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        if (!f || !cap || !M) return [];
        const out = [];
        _embryos.forEach(emb => {
            const xy = resolveXY(emb);
            if (!xy) return;
            const px = M.stageToFrame(xy.x, xy.y, f, cap, pxBase());
            if (!px) return;
            out.push({ emb, cx: r.x + (px[0] / r.fw) * r.w, cy: r.y + (px[1] / r.fh) * r.h });
        });
        return out;
    }

    function drawMarkers() {
        // Render dispatch, not gating: the canvas has no size while its pane is
        // hidden, so there is nothing to draw onto.
        if (_pane !== 'bottom') return;
        const ctx = canvasCtx();
        if (!ctx) return;
        const r = renderedRect();
        if (!r) return;

        // Registered embryos first, so pending markers draw over them.
        embryoPoints(r).forEach(({ emb, cx, cy }) => {
            const sel = emb.id === _selected;
            ctx.save();
            ctx.strokeStyle = sel ? '#93c5fd' : '#60a5fa';
            ctx.fillStyle = ctx.strokeStyle;
            ctx.lineWidth = sel ? 2.5 : 1.2;
            ctx.beginPath(); ctx.arc(cx, cy, EMB_R, 0, Math.PI * 2); ctx.stroke();
            if (sel) {
                // Selected: dashed outer halo so the state reads as shape, not only shade.
                ctx.setLineDash([3, 3]); ctx.lineWidth = 1.2;
                ctx.beginPath(); ctx.arc(cx, cy, EMB_R + 4, 0, Math.PI * 2); ctx.stroke();
                ctx.setLineDash([]);
            }
            ctx.beginPath(); ctx.arc(cx, cy, 2.5, 0, Math.PI * 2); ctx.fill();
            ctx.font = '600 11px Inter Tight, sans-serif';
            ctx.fillText(labelFor(emb), cx + EMB_R + 3, cy + 4);
            ctx.restore();
        });
        const colour = '#4ade80';
        _markers.forEach((m, i) => {
            const p = markerToCanvas(m, r);
            if (!p) return;
            const { cx, cy } = p;
            ctx.save();
            ctx.strokeStyle = colour;
            // One look for a pending mark. There were two: greyed and dashed
            // while the XY lock was engaged. The lock went on 2026-11-08 and
            // its variable with it, but these lines went on reading it, so
            // drawing the first mark threw and no mark could be placed.
            ctx.lineWidth = 2;
            ctx.beginPath(); ctx.arc(cx, cy, 11, 0, Math.PI * 2); ctx.stroke();
            ctx.beginPath();
            ctx.moveTo(cx - 6, cy); ctx.lineTo(cx + 6, cy);
            ctx.moveTo(cx, cy - 6); ctx.lineTo(cx, cy + 6);
            ctx.stroke();
            ctx.fillStyle = colour;
            ctx.font = '600 11px Inter Tight, sans-serif';
            // During an agent-initiated session each marker carries a role that
            // goes back in the answer, so a reference must be distinguishable
            // on the image and not only in the panel.
            const tag = (_markSession && m.role === 'calibration') ? `${i + 1}·ref` : String(i + 1);
            ctx.fillText(tag, cx + 13, cy - 8);
            ctx.restore();
        });
    }

    function onCanvasClick(e) {
        const r = renderedRect();
        const c = $('op-mark-canvas');
        if (!r || !c) return;
        const rect = c.getBoundingClientRect();
        // rect is transform-inclusive, offsetWidth is not, so their ratio IS the
        // live ancestor scale. Dividing by it lands the click in the same canvas
        // CSS-pixel space renderedRect() drew into. Both are 1 when unscaled.
        const sx = rect.width / c.offsetWidth, sy = rect.height / c.offsetHeight;
        if (!(sx > 0 && sy > 0)) return;
        const cxv = (e.clientX - rect.left) / sx, cyv = (e.clientY - rect.top) / sy;

        // Click a pending marker to remove it.
        for (let i = 0; i < _markers.length; i++) {
            const p = markerToCanvas(_markers[i], r);
            if (p && Math.hypot(cxv - p.cx, cyv - p.cy) <= MARK_HIT_PX) {
                // Editing the set invalidates the "N candidates added" note — it
                // was the detection-time count, not the current one.
                _markers.splice(i, 1); drawMarkers(); renderMarkCount(); setDetectNote(''); return;
            }
        }
        // Click a registered embryo to select it and centre the stage on it.
        // Always available — the interlock lives in moveStageTo, not here.
        for (const p of embryoPoints(r)) {
            if (Math.hypot(cxv - p.cx, cyv - p.cy) <= EMB_HIT_PX) {
                centerOnEmbryo(p.emb);
                return;
            }
        }
        if (cxv < r.x || cxv > r.x + r.w || cyv < r.y || cyv > r.y + r.h) return;

        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        if (!f) { toastFail('Start the camera first'); return; }
        // NEVER default the capture position to [0,0]: that silently converts
        // clicks into offsets from stage origin, so embryos land hundreds of µm
        // away and calibration images empty field. Refuse to mark instead.
        if (!cap) { toastFail('Stage position unknown — wait for the readout, then mark'); return; }

        const fx = ((cxv - r.x) / r.w) * r.fw, fy = ((cyv - r.y) / r.h) * r.fh;
        const s = M && M.frameToStage(fx, fy, f, cap, pxBase());
        if (!s) { toastFail('Cannot place a marker without a stage position'); return; }
        _markers.push({ stageX: s[0], stageY: s[1], source: 'manual' });
        drawMarkers(); renderMarkCount();
    }

    // ── SPIM alignment ──────────────────────────────────────────────────────
    // An embryo's position is the stage XY at which it sits at the BOTTOM
    // CAMERA's centre. The SPIM head need not look at that same point, and
    // until this offset existed the code assumed it did — so centring could
    // put an embryo outside the light sheet and the pre-calibration check
    // would report "No object visible" with every instrument check passing.
    let _align = null;   // null until fetched; {dx_um, dy_um, is_measured, ...}

    async function loadAlignment() {
        try {
            const d = await getJSON('/api/devices/spim/alignment');
            _align = d && d.current ? d.current : null;
        } catch (e) { _align = null; }   // unmeasured: behave as before
        renderAlignment();
    }

    function renderAlignment() {
        const value = $('op-align-value');
        if (value) {
            value.textContent = _align && _align.is_measured
                ? `${_align.dx_um.toFixed(1)}, ${_align.dy_um.toFixed(1)} µm`
                : 'not measured';
        }
        const line = $('op-align-line');
        if (!line) return;
        if (!_align || !_align.is_measured) {
            // Rule 6: an instrument nobody has aligned has nothing to report
            // here, and a row saying "0, 0" would imply someone checked.
            line.hidden = true;
            return;
        }
        const when = (_align.set_at || '').replace('T', ' ').slice(0, 16);
        const sess = _align.session_id ? `, session ${_align.session_id}` : '';
        line.hidden = false;
        line.textContent = `SPIM offset ${_align.dx_um.toFixed(1)}, `
            + `${_align.dy_um.toFixed(1)} µm (set ${when}${sess})`;
    }

    async function centerOnEmbryo(emb) {
        const xy = resolveXY(emb);
        if (!xy) { toastFail('That embryo has no recorded position'); return; }
        selectEmbryo(emb.id);
        // Through the offset, so "centre" means "under the SPIM", not "at the
        // bottom camera's centre pixel". Zero offset leaves it unchanged.
        // Through `M`, the module's guarded alias: if operate-math.js failed to
        // load, centring must fall back to the raw position rather than throw.
        const [tx, ty] = M ? M.centreTarget(xy.x, xy.y, _align) : [xy.x, xy.y];
        await moveStageTo(tx, ty, `Centred on embryo ${labelFor(emb)}`);
    }

    async function setSpimCentre() {
        if (!_selected) { toastFail('Select the embryo you aligned on first'); return; }
        const b = $('op-align-set');
        if (b) b.disabled = true;
        try {
            const d = await postJSON('/api/devices/spim/alignment',
                { embryo_id: _selected, note: '' });
            _align = d && d.current ? d.current : null;
            renderAlignment();
            renderAlignHistory(d);
            toast(`SPIM centre set — offset ${_align.dx_um.toFixed(1)}, ${_align.dy_um.toFixed(1)} µm`);
        } catch (e) {
            toastFail(`Could not set the SPIM centre (${why(e)})`);
        } finally {
            if (b) b.disabled = false;
        }
    }

    function renderAlignHistory(d) {
        const host = $('op-align-history');
        if (!host) return;
        const rows = (d && Array.isArray(d.history) ? d.history : []).slice().reverse();
        if (!rows.length) { host.innerHTML = ''; host.hidden = true; return; }
        host.hidden = false;
        host.innerHTML = rows.map(h => {
            const when = h.set_at ? h.set_at.replace('T', ' ').slice(0, 16) : 'never measured';
            const val = `${(h.dx_um || 0).toFixed(1)}, ${(h.dy_um || 0).toFixed(1)} µm`;
            return `<div class="al-row"><span class="al-when">${escapeHtml(when)}</span>`
                + `<span class="al-val">${val}</span>`
                + `<button class="op-btn op-btn-quiet al-restore" type="button"`
                + ` data-at="${escapeHtml(h.set_at || '')}">Restore</button></div>`;
        }).join('');
    }

    async function restoreAlignment(setAt) {
        try {
            const d = await postJSON('/api/devices/spim/alignment/restore', { set_at: setAt || null });
            _align = d && d.current ? d.current : null;
            renderAlignment();
            renderAlignHistory(d);
            toast('SPIM alignment restored');
        } catch (e) {
            toastFail(`Could not restore that alignment (${why(e)})`);
        }
    }

    function renderMarkCount() {
        const n = _markers.length;
        const c = $('op-mark-count'); if (c) c.textContent = n;
        const ok = $('op-confirm'); if (ok) ok.disabled = n === 0;
        const cl = $('op-clear'); if (cl) cl.disabled = n === 0;
        publishMarking();
    }
    function setDetectNote(text) {
        const note = $('op-detect-note'); if (note) note.textContent = text || '';
        _markNote = text || '';
        publishMarking();
    }

    // ── marking state, for panels/marking.js ────────────────────────────────
    // Pending marks and a registered roster are DIFFERENT counts. Conflating
    // them is why Register and Clear sat greyed out reading "MARKED 0" while
    // the caption said "Registered 4 embryos", with no way to act on the
    // roster that existed (#113).
    let _markNote = '';
    let _detecting = false;
    let _detectStartedAt = 0;

    function publishMarking() {
        SharedState.set('marking', {
            marked: _markers.length,
            registered: _embryos.length,
            detecting: _detecting,
            startedAt: _detectStartedAt,
            note: _markNote,
            // Present only while the agent is waiting on an answer. The panel
            // renders the pending markers and their roles from this, because
            // the contract carries a role per marker.
            session: _markSession ? {
                pending: _markers.map((m, i) => ({
                    index: i,
                    role: m.role || _markSession.defaultRole,
                    source: m.source || 'manual',
                })),
            } : null,
        });
    }

    function clearMarks() {
        _markers = [];
        drawMarkers();
        renderMarkCount();
        setDetectNote('');
    }

    // ══ BOTTOM PANE ═════════════════════════════════════════════════════════
    // A stream that takes a second to come up needs the button to say so. The
    // old behaviour was to disable it and leave the label alone, so for the
    // whole wait it read "Start camera" at 40% opacity with a not-allowed
    // cursor — the visual language of "you may not press this", used to mean
    // "your press is being carried out". Now it names the verb in progress and
    // spins, stays at full strength, and only the cursor says "wait".
    // A state that flashes past is not feedback. When the device layer is warm
    // the stream call answers in tens of milliseconds, so the honest "Starting…"
    // rendered for a frame and the operator saw only an abrupt flip — the
    // complaint that started this. Hold it long enough to be read.
    const MIN_PENDING_MS = 320;

    function pending(btn, verb) {
        if (!btn) return settle => { if (settle) settle(); };
        const t0 = (window.performance && performance.now) ? performance.now() : Date.now();
        const label = btn.textContent;
        btn.disabled = true;
        btn.classList.add('is-pending');
        btn.textContent = '';
        const spin = document.createElement('span');
        spin.className = 'op-btn-spin';
        spin.setAttribute('aria-hidden', 'true');
        btn.appendChild(spin);
        btn.appendChild(document.createTextNode(verb));
        // Screen readers get the same fact, not just the spinner.
        btn.setAttribute('aria-busy', 'true');
        // Restores the label the operator pressed. On success the caller's
        // applyX() overwrites it with the new one a beat later; on failure it
        // is what the button should have said all along.
        // `settle` is the caller's state change (applyX). It runs when the
        // pending state has had its minimum time, so the label goes
        // "Start camera" → "Starting…" → "Stop camera" in that order, never
        // skipping the middle.
        return settle => {
            const now = (window.performance && performance.now) ? performance.now() : Date.now();
            const left = Math.max(0, MIN_PENDING_MS - (now - t0));
            setTimeout(() => {
                btn.disabled = false;
                btn.classList.remove('is-pending');
                btn.removeAttribute('aria-busy');
                btn.textContent = label;
                if (settle) settle();
            }, left);
        };
    }

    async function toggleBottomCam() {
        if (!_bottomOn && !mayTakeFromRun('Starting the bottom camera')) return;
        const b = $('op-cam-toggle');
        const done = pending(b, _bottomOn ? 'Stopping…' : 'Starting…');
        try {
            const ep = _bottomOn ? '/api/devices/bottom_camera/stream/stop'
                : '/api/devices/bottom_camera/stream/start';
            const d = await postJSON(ep, {});
            done(() => {
                applyBottomCam(!!d.streaming);
            });
        } catch (e) { done(); toastFail(`Camera toggle failed (${why(e)})`); }
    }
    function applyBottomCam(on) {
        _bottomOn = on;
        const b = $('op-cam-toggle');
        if (b) { b.textContent = on ? 'Stop camera' : 'Start camera'; b.classList.toggle('is-on', on); }
        if (!on) { freezeImg('op-img-bottom', 'op-ph-bottom', 'Camera off'); _arrivals.bottom.length = 0; }
        renderSubnavMeta();
        renderViewMeta();
    }

    // Name the stages that are actually running: "blobs" and "blobs + Claude +
    // SAM" take very different amounts of time, and a caption that says only
    // "Detecting…" leaves an operator watching a spinner with no idea whether
    // 20 seconds is normal.
    function detectingCaption(tune) {
        const parts = [tune.method === 'dark' ? 'dark blobs' : 'blobs'];
        if (tune.use_claude_review !== false) parts.push('Claude');
        if (tune.use_sam !== false) parts.push('SAM');
        return `Detecting… ${parts.join(' + ')}`;
    }

    function setBusyText(t) {
        const el = document.querySelector('#op-busy-bottom .op-cam-busy-txt');
        if (el) el.textContent = t;
    }
    /**
     * Run the detector with the pipeline the panel chose.
     *
     * `opts` comes from MarkingPanel.detectOptions(): which of the two optional
     * stages run (Claude classification, SAM refinement), how permissive the
     * blob finder should be, and whether to capture a new frame instead of
     * detecting on the one already on screen. Absent (an agent-initiated
     * detect, or an older caller), the server defaults apply.
     */
    async function runDetect(opts) {
        const cfg = (opts && typeof opts === 'object') ? opts : {};
        const tune = {};
        if (typeof cfg.use_claude_review === 'boolean') tune.use_claude_review = cfg.use_claude_review;
        if (typeof cfg.use_sam === 'boolean') tune.use_sam = cfg.use_sam;
        if (typeof cfg.min_relative_peak === 'number') tune.min_relative_peak = cfg.min_relative_peak;
        if (cfg.method === 'dark' || cfg.method === 'bright') tune.method = cfg.method;
        // Finding is in the rail beside whichever camera is up, and what it
        // finds is drawn on the bottom camera's frame: that frame comes up.
        showPane('bottom');
        const b = $('op-detect');
        if (b) { b.disabled = true; b.textContent = 'Detecting…'; }
        _detecting = true;
        _detectStartedAt = Date.now();
        // Whatever the last attempt said is not about this one. A refusal from
        // a press made while the rig was still coming up used to sit under
        // the next, succeeding, detect — "unavailable on this rig" beside
        // four fresh candidates.
        setDetectNote('');
        publishMarking();
        const busy = $('op-busy-bottom'); if (busy) busy.hidden = false;
        // Detect on the frame already on screen when there is one — the operator
        // is looking at it, and re-capturing would disturb the LED/room light.
        let hasFrame = !cfg.fresh && frameShown('op-img-bottom');
        try {
            // Phase 1 — when the viewport is empty, capture and SHOW the image
            // FIRST (no SAM yet), so the operator sees what detection will run on
            // before it runs, rather than the image appearing only at the end.
            if (!hasFrame) {
                setBusyText('Capturing…');
                const cap = await postJSON('/api/devices/detect_embryos',
                    Object.assign({ capture_only: true }, tune));
                if (cap.frame && cap.frame.jpeg_b64) {
                    _lastBottom = cap.frame;
                    showFrame('bottom', cap.frame);
                    hasFrame = true;
                }
            }
            // Phase 2 — run SAM on the frame now on screen, then overlay results.
            setBusyText(detectingCaption(tune));
            const d = await postJSON('/api/devices/detect_embryos',
                Object.assign({ use_last_frame: hasFrame }, tune));
            if (d.frame && d.frame.jpeg_b64) {
                _lastBottom = d.frame;
                showFrame('bottom', d.frame);
            }
            const cands = Array.isArray(d.embryos) ? d.embryos : [];
            const f = frameOf(_lastBottom);
            const cap = d.stage_position || stageOf(_lastBottom);
            // A fresh detection REPLACES the previous auto-detected set rather
            // than piling onto it (re-running would otherwise double the marks).
            // Manual marks are kept — only 'sam' ones are cleared.
            _markers = _markers.filter(m => m.source !== 'sam');
            let added = 0;
            cands.forEach(c => {
                let sx = c.stage_x_um, sy = c.stage_y_um;
                if ((sx == null || sy == null) && f && cap && M && c.pixel_x != null && c.pixel_y != null) {
                    const s = M.frameToStage(c.pixel_x / f.downsample, c.pixel_y / f.downsample, f, cap, pxBase());
                    if (s) { sx = s[0]; sy = s[1]; }
                }
                if (sx == null || sy == null) return;
                _markers.push({ stageX: sx, stageY: sy, source: 'sam' });
                added++;
            });
            drawMarkers(); renderMarkCount();
            setDetectNote(`${added} candidate${added === 1 ? '' : 's'} added — edit them on the image, then register.`);
            toast(`Detected ${added} candidate${added === 1 ? '' : 's'}`);
        } catch (e) {
            if (e.status === 503) {
                // Two different 503s. One is the rig still attaching after a
                // launch — try again in a moment. The other is a device layer
                // with no SAM, which is this rig's shape and will not change
                // by waiting. They were one sentence, and it was the wrong one
                // for the case people actually hit.
                const detail = String((e.data && e.data.detail) || '');
                setDetectNote(/not connected/i.test(detail)
                    ? 'The microscope is still coming up — try again in a moment, or mark by clicking the image.'
                    : 'Automatic detection is unavailable on this rig — mark by clicking the image.');
            } else {
                toastFail(`Detect failed (${why(e)})`);
            }
        } finally {
            if (b) { b.disabled = false; b.textContent = 'Detect automatically'; }
            if (busy) busy.hidden = true;
            _detecting = false;
            publishMarking();
        }
    }

    async function confirmMarks() {
        if (!_markers.length) return;
        // While the agent is waiting on these marks, Register IS the answer.
        // Registering them through the pane's own route instead left the
        // agent's session open with nothing in it: Done then told the agent
        // "0 embryos" while four sat in the roster, and it detected again.
        if (_markSession) { finishMarkingSession(); return; }
        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        if (!cap) { toastFail('Stage position unknown — cannot register markers'); return; }
        const b = $('op-confirm'); if (b) b.disabled = true;
        try {
            // The payload shape is a hard contract with _persist_detection_labels
            // (routes/data.py), which turns every confirm into training data for
            // the localiser that will replace SAM. Pixel coords are projected
            // from stage space against the frame being submitted.
            const markers = _markers.map(m => {
                const px = (f && M) ? M.stageToFrame(m.stageX, m.stageY, f, cap, pxBase()) : null;
                return {
                    stage_x_um: m.stageX, stage_y_um: m.stageY,
                    pixel_x: px ? px[0] : undefined, pixel_y: px ? px[1] : undefined,
                    source: m.source,
                };
            });
            const d = await postJSON('/api/devices/embryos/confirm', {
                markers,
                image_b64: _lastBottom ? _lastBottom.jpeg_b64 : undefined,
                frame: f ? { w: f.w, h: f.h, downsample: f.downsample } : undefined,
                stage_position: cap,
            });
            const n = (d.registered || []).length;
            _markers = [];
            drawMarkers(); renderMarkCount();
            setDetectNote(`Registered ${n} embryo${n === 1 ? '' : 's'} — ${n === 1 ? 'it is' : 'they are'} in the list below.`);
            toast(`Registered ${n} embryo${n === 1 ? '' : 's'}`);
        } catch (e) {
            toastFail(`Register failed (${why(e)})`);
            if (b) b.disabled = false;
        }
    }

    // ══ SPIM PANE ═══════════════════════════════════════════════════════════
    async function toggleSpim() {
        if (!_spimOn && !mayTakeFromRun('Starting the light-sheet view')) return;
        const b = $('op-spim-toggle');
        const done = pending(b, _spimOn ? 'Stopping…' : 'Starting…');
        try {
            const ep = _spimOn ? '/api/devices/lightsheet/live/stop' : '/api/devices/lightsheet/live/start';
            // Before the first frame: the side and pose the device layer is
            // on, so the frames that follow are the ones this pane shows.
            if (!_spimOn) await adoptLsParams();
            const d = await postJSON(ep, {});
            done(() => {
                applySpim(!!d.streaming);
            });
        } catch (e) { done(); toastFail(`SPIM view toggle failed (${why(e)})`); }
    }
    function applySpim(on) {
        _spimOn = on;
        const b = $('op-spim-toggle');
        if (b) { b.textContent = on ? 'Stop view' : 'Start view'; b.classList.toggle('is-on', on); }
        if (!on) { freezeImg('op-img-spim', 'op-ph-spim', 'View off'); _arrivals.spim.length = 0; }
        renderSubnavMeta();
        renderViewMeta();
    }

    let _lsTimer = null;
    function postLsParams() {
        if (_lsTimer) clearTimeout(_lsTimer);
        _lsTimer = setTimeout(() => {
            // Multi has no sheet of its own: the device layer keeps A and B
            // where they were, so only the view changes hands.
            const body = _side === 'Multi'
                ? { side: _side }
                : { galvo: _pose[_side].galvo, piezo: _pose[_side].piezo, side: _side };
            postJSON('/api/devices/lightsheet/live/params', body).catch(() => {});
        }, 120);
    }
    // Whose sheet the Sheet panel's two lines move, said in its heading.
    const SIDE_SAYS = {
        A: 'side A · scanner AB · piezo P',
        B: 'side B · scanner CD · piezo Q',
        Multi: 'no side chosen',
    };
    function renderPose() {
        const multi = _side === 'Multi';
        const p = _pose[multi ? 'A' : _side];
        const r = _range[multi ? 'A' : _side] || RANGE_DEFAULT;
        renderAxis('op-gv', _axisRow.galvo, r.galvo, p.galvo, multi);
        renderAxis('op-pz', _axisRow.piezo, r.piezo, p.piezo, multi);
        const note = $('op-spim-multi-note'); if (note) note.hidden = !multi;
        const says = $('op-sheet-side'); if (says) says.textContent = SIDE_SAYS[_side] || '';
        renderSource();
        const img = $('op-img-spim');
        if (img) img.alt = multi ? 'Light-sheet view, both sides: A red, B green' : `Light-sheet view, side ${_side}`;
    }

    // ── which camera is on screen ───────────────────────────────────────────
    // The strip above the frame. The bottom camera is its own surface; the
    // three light-sheet choices are the SPIM surface on a side.
    function renderSource() {
        const on = _pane === 'bottom' ? 'bottom' : _pane === 'spim' ? _side : _pane === 'cal' ? 'fit' : null;
        document.querySelectorAll('#op-source [data-source]').forEach(b => {
            const is = b.dataset.source === on;
            b.classList.toggle('is-on', is);
            b.setAttribute('aria-pressed', is ? 'true' : 'false');
        });
    }
    function chooseSource(src) {
        if (src === 'bottom') { showPane('bottom'); return; }
        // Not a camera: what the selected embryo's calibration looks at.
        if (src === 'fit') { showPane('cal'); return; }
        // A side pressed is the side wanted. It is told to the device layer
        // BEFORE the surface is entered, so the read on entering finds this
        // page's own switch a moment old and leaves it be (adoptLsParams).
        // The same side as before is not re-sent: entering reads what the
        // device layer is on, and the strip shows that.
        if (src !== _side) setSpimSide(src);
        showPane('spim');
    }
    function setSpimSide(side) {
        if (side !== 'A' && side !== 'B' && side !== 'Multi') return;
        if (side === _side) return;
        _side = side;
        _sideChangedAt = Date.now();
        renderPose();
        fetchRange(side);
        // The frame on screen is the other side's until the next one lands.
        if (_spimOn) clearImg('op-img-spim', 'op-ph-spim', side === 'Multi' ? 'Switching to Multi…' : `Switching to side ${side}…`);
        postLsParams();
    }
    // One axis row: the line's ends are the extent, its knob the pose, the
    // box the same number, typed (panels/numrow.js: the two are one control,
    // and a pose read back does not land under a drag or a half-typed
    // number). Multi has no sheet of its own: the line is off and the box
    // blank.
    const _axisRow = { galvo: null, piezo: null };
    function renderAxis(id, row, ext, v, off) {
        const inp = $(id + '-in'), box = $(id);
        if (inp) { inp.min = ext[0]; inp.max = ext[1]; inp.disabled = off; }
        if (box) box.disabled = off;
        const lo = $(id + '-min'), hi = $(id + '-max');
        if (lo) lo.textContent = fmtExt(ext[0]);
        if (hi) hi.textContent = fmtExt(ext[1]);
        if (row) row.show(v);
        else if (inp) inp.value = v;
        if (off && box) box.value = '—';
    }
    const fmtExt = x => (x > 0 ? '+' : x < 0 ? '−' : '') + String(Number(Math.abs(x).toFixed(2)));
    // The extents, from the controller, once per side: the micro-mirror card's
    // deflection limits on the slice axis and the piezo's soft limits, the
    // same source the plugin bounds its sliders by. A pose outside them is
    // pulled inside.
    async function fetchRange(side) {
        if ((side !== 'A' && side !== 'B') || _range[side]) return;
        try {
            const r = await getJSON(`/api/devices/lightsheet/live/range?side=${side}`);
            if (!r || !Array.isArray(r.galvo) || !Array.isArray(r.piezo)) return;
            _range[side] = r;
            const p = _pose[side];
            p.galvo = Math.min(r.galvo[1], Math.max(r.galvo[0], p.galvo));
            p.piezo = Math.min(r.piezo[1], Math.max(r.piezo[0], p.piezo));
            renderPose();
        } catch (_) { /* no controller to ask: the default span stands */ }
    }
    // The device layer outlives this page (an app restart, a reload, a second
    // browser on the rig) and keeps the live side and pose it was last given.
    // The pane takes them from it rather than assuming A at 0/0: assumed, the
    // stream came tagged with a side the pane had not chosen and every frame
    // was dropped as the other side's, the view blank for good. Read-only:
    // nothing on the rig moves. Asked when the view starts, when the pane is
    // entered and when the stream says otherwise; one read in flight at a
    // time, and none inside a switch this pane has just made, whose post is
    // the truth then.
    let _adopting = null;
    function adoptLsParams() {
        if (_adopting) return _adopting;
        _adopting = (async () => {
            try {
                if (Date.now() - _sideChangedAt < SIDE_SWITCH_MS) return;
                const r = await getJSON('/api/devices/lightsheet/live/params');
                // Asked again after the wait: a side pressed while this read
                // was in flight is newer than its answer, which would put the
                // strip back on the side just left.
                if (Date.now() - _sideChangedAt < SIDE_SWITCH_MS) return;
                const p = r && r.params;
                if (!p || (p.side !== 'A' && p.side !== 'B' && p.side !== 'Multi')) return;
                if (p.side !== 'Multi') {
                    const pose = _pose[p.side];
                    if (Number.isFinite(p.galvo)) pose.galvo = p.galvo;
                    if (Number.isFinite(p.piezo)) pose.piezo = p.piezo;
                }
                _side = p.side;
                renderPose();
                fetchRange(p.side);
            } catch (_) { /* no device layer to ask: the pane's own side stands */ }
            finally { _adopting = null; }
        })();
        return _adopting;
    }
    // The knob moved: the pose takes the number, line and readout follow, and
    // the device layer hears it on the debounce tick.
    function setAxis(key, v) {
        if (_side === 'Multi' || !Number.isFinite(v)) return;
        _pose[_side][key] = v;
        renderPose();
        postLsParams();
    }
    // The LED has ONE control, in the Light panel. There used to be a second
    // button here with its own `_ledOn` belief, and the two did not talk: the
    // Light panel went on reporting the LED as it had last read it while this
    // button had already changed it. Two renderings of one fact — PANELS.md
    // rule 1, and reported from the rig.
    //
    // Nothing here remembers the LED any more; the panel reads it from the
    // device and this asks the panel. Programmatic close still lives here
    // because pane exit and end-of-acquisition are operate.js's business.
    async function forceLedOff() {
        try { await postJSON('/api/devices/led/set', { state: 'Closed' }); } catch (_) {}
        if (typeof LightPanel !== 'undefined') { try { await LightPanel.refresh(); } catch (_) {} }
        renderSubnavMeta();
    }

    // ── calibration settings ────────────────────────────────────────────────
    // calibrate_embryo takes these; the pane used to send none of them, so a
    // rig whose galvo range is already known still paid for a Claude-vision
    // edge hunt, and the two numbers that place the calibration points inside
    // that range could not be touched at all. Defaults here MUST match the
    // tool's, so an untouched pane behaves exactly as before.
    const CAL_KEY = 'gently.calibrate.settings';
    const CAL_DEFAULTS = {
        method: 'legacy',   // which routine: legacy sweep or hardware-timed scan
        edges: true,        // skip_edge_detection = !edges
        zbuf: 25,           // z_buffer_um
        estep: 0.05,        // edge_step (deg)
        erange: 0.5,        // edge_max_range (deg)
        etol: 0.2,          // edge_tolerance_deg
        inset: 0.4,         // inset_fraction
        gtop: null,         // galvo_top, only with edge detection off
        gbot: null,         // galvo_bottom
    };
    let _cal = Object.assign({}, CAL_DEFAULTS);
    try {
        const saved = JSON.parse(localStorage.getItem(CAL_KEY) || '{}');
        if (saved && typeof saved === 'object') _cal = Object.assign({}, CAL_DEFAULTS, saved);
    } catch (e) { /* defaults */ }

    function saveCal() {
        try { localStorage.setItem(CAL_KEY, JSON.stringify(_cal)); } catch (e) { /* not fatal */ }
    }

    const calNum = (id, fallback) => {
        const el = $(id);
        if (!el) return fallback;
        const v = parseFloat(el.value);
        return Number.isFinite(v) ? v : fallback;
    };

    function readCalForm() {
        _cal = {
            method: $('cal-method') ? $('cal-method').value : _cal.method,
            edges: $('cal-edges') ? !!$('cal-edges').checked : _cal.edges,
            zbuf: calNum('cal-zbuf', CAL_DEFAULTS.zbuf),
            estep: calNum('cal-estep', CAL_DEFAULTS.estep),
            erange: calNum('cal-erange', CAL_DEFAULTS.erange),
            etol: calNum('cal-etol', CAL_DEFAULTS.etol),
            inset: calNum('cal-inset', CAL_DEFAULTS.inset),
            gtop: $('cal-gtop') && $('cal-gtop').value !== '' ? calNum('cal-gtop', null) : null,
            gbot: $('cal-gbot') && $('cal-gbot').value !== '' ? calNum('cal-gbot', null) : null,
        };
        saveCal();
        renderCalForm();
    }

    function renderCalForm() {
        const set = (id, v) => { const el = $(id); if (el && el.value !== String(v)) el.value = v; };
        if ($('cal-edges')) $('cal-edges').checked = !!_cal.edges;
        set('cal-method', _cal.method || 'legacy');
        const say = $('op-cal-method');
        if (say) say.textContent = _cal.method === 'scan'
            ? 'Scan — one slice-only volume for the extent, then piezo-only volumes at three '
              + 'galvo positions, a line through every point. Seconds, hardware-timed. Needs the laser.'
            : 'Legacy sweep — a galvo sweep read by the light-sheet camera, then a piezo focus '
              + 'sweep. Needs the laser: the LED alone gives a DIC-like image with no nuclei to find.';
        // The sweep's own knobs mean nothing to the scan.
        ['cal-edges', 'cal-more'].forEach(id => { const el = $(id); if (el) el.closest('label, button').hidden = _cal.method === 'scan'; });
        if (_cal.method === 'scan' && $('cal-adv')) $('cal-adv').hidden = true;
        set('cal-zbuf', _cal.zbuf); set('cal-estep', _cal.estep);
        set('cal-erange', _cal.erange); set('cal-etol', _cal.etol); set('cal-inset', _cal.inset);
        if ($('cal-gtop')) $('cal-gtop').value = _cal.gtop == null ? '' : _cal.gtop;
        if ($('cal-gbot')) $('cal-gbot').value = _cal.gbot == null ? '' : _cal.gbot;
        // Explicit bounds only mean anything when nothing is hunting for them.
        const bounds = $('cal-adv-bounds');
        if (bounds) bounds.hidden = !!_cal.edges;
    }

    // What the pane will actually send. Only what differs from the tool's own
    // defaults travels, so the request says what the operator changed.
    function calibrationSettings() {
        const body = {};
        if (_cal.method && _cal.method !== CAL_DEFAULTS.method) body.method = _cal.method;
        if (_cal.method === 'scan') {
            if (Number.isFinite(_cal.zbuf) && _cal.zbuf !== CAL_DEFAULTS.zbuf) body.z_buffer_um = _cal.zbuf;
            return body;
        }
        if (!_cal.edges) {
            body.skip_edge_detection = true;
            if (_cal.gtop != null) body.galvo_top = _cal.gtop;
            if (_cal.gbot != null) body.galvo_bottom = _cal.gbot;
        }
        const pairs = [
            ['z_buffer_um', _cal.zbuf, CAL_DEFAULTS.zbuf],
            ['edge_step', _cal.estep, CAL_DEFAULTS.estep],
            ['edge_max_range', _cal.erange, CAL_DEFAULTS.erange],
            ['edge_tolerance_deg', _cal.etol, CAL_DEFAULTS.etol],
            ['inset_fraction', _cal.inset, CAL_DEFAULTS.inset],
        ];
        pairs.forEach(([key, val, def]) => { if (Number.isFinite(val) && val !== def) body[key] = val; });
        return body;
    }

    function wireCalForm() {
        const from = $('op-cal-borrow-from');
        if (from) from.addEventListener('change', () => renderBorrow(_embryos.find(e => e.id === _selected)));
        ['cal-method', 'cal-edges', 'cal-zbuf', 'cal-estep', 'cal-erange', 'cal-etol', 'cal-inset',
            'cal-gtop', 'cal-gbot'].forEach(id => {
            const el = $(id);
            if (el) el.addEventListener('change', readCalForm);
        });
        const more = $('cal-more'), adv = $('cal-adv');
        if (more && adv) {
            more.addEventListener('click', () => {
                const open = adv.hidden;
                adv.hidden = !open;
                more.setAttribute('aria-expanded', String(open));
                more.textContent = open ? 'Less' : 'More…';
            });
        }
        const reset = $('cal-reset');
        if (reset) reset.addEventListener('click', () => {
            _cal = Object.assign({}, CAL_DEFAULTS);
            saveCal();
            renderCalForm();
            toast('Calibration settings back to defaults');
        });
        renderCalForm();
    }

    async function calibrateSelected(opts) {
        if (!_selected) { toastFail('Select an embryo first'); return; }
        if (!mayTakeFromRun('A calibration')) return;
        // The button is in the Sheet panel, on screen with any camera. The run
        // takes the light-sheet camera for itself, so whichever view was live
        // is stopped (its surface's onLeave) and Fit comes up to show the run.
        if (_pane !== 'cal') showPane('cal');
        hideRefusal();
        const b = $('op-calibrate'), out = $('op-cal-result');
        // A routine that runs for tens of seconds behind a disabled button is
        // indistinguishable from one that has hung. Count out loud.
        const t0 = Date.now();
        const tick = setInterval(() => {
            if (b) b.textContent = `Calibrating… ${Math.round((Date.now() - t0) / 1000)}s`;
        }, 1000);
        if (b) { b.disabled = true; b.textContent = 'Calibrating… 0s'; }
        const ab = $('op-cal-abort');
        if (ab) { ab.hidden = false; ab.disabled = false; ab.textContent = 'Abort'; }
        if (out) out.textContent = 'sweeping…';
        // The frames this run is about to take are already broadcast; the
        // progress panel shows them as they land.
        if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.begin(_selected);
        try {
            const body = calibrationSettings();
            // Only ever false, and only when the operator has just been shown
            // the refusal and the frames behind it. Absent means "check".
            if (opts && opts.anyway) body.require_object = false;
            const d = await postJSON(`/api/devices/embryos/${_selected}/calibrate`, body);
            const cal = d.calibration || {};
            // Onto the local copy first: the render in `finally` recomputes
            // from `_embryos`, so without this a calibration the server has
            // just confirmed redraws as "not calibrated" until the
            // EMBRYOS_UPDATE broadcast catches up.
            const mine = _embryos.find(e => e.id === _selected);
            if (mine && cal.slope_um_per_deg != null) mine.calibration = cal;
            const slope = cal.slope_um_per_deg, r2 = cal.r_squared;
            if (out) {
                out.textContent = (slope != null)
                    ? `${Number(slope).toFixed(1)} µm/deg${r2 != null ? ` · R² ${Number(r2).toFixed(2)}` : ''}`
                    : 'done';
            }
            if (typeof CalProgressPanel !== 'undefined') {
                CalProgressPanel.finish(true, out ? out.textContent : '');
            }
        } catch (e) {
            // 409 is the pre-flight check declining, not a crash: nothing was
            // spent past one frame and the operator can say "anyway". Anything
            // else is a failure and reads as one.
            const detail = String((e && e.data && e.data.detail) || '');
            if (e && e.status === 409 && /aborted/i.test(detail)) {
                // The operator's own doing: not a failure, not a refusal.
                if (out) out.textContent = 'aborted';
                if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.finish(false, 'aborted by operator');
                toast('Calibration aborted');
            } else if (e && e.status === 409) {
                if (out) out.textContent = 'nothing there';
                _refusedFor = _selected;
                showRefusal(e);
                if (typeof CalProgressPanel !== 'undefined') {
                    CalProgressPanel.finish(false, 'nothing visible at the expected focus');
                }
            } else {
                if (out) out.textContent = 'failed';
                // The frames stay up on a failure — they are the evidence of WHERE
                // it went wrong, which is exactly what a bare 'failed' withholds.
                if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.finish(false, why(e));
                toastFail(`Calibrate failed (${why(e)})`);
            }
        } finally {
            clearInterval(tick);
            if (b) b.disabled = false;
            if (ab) ab.hidden = true;
            renderCalTarget();   // restores the verb: Calibrate / Recalibrate
        }
    }

    /** Stop the running calibration. The calibrate request then answers 409 "aborted". */
    async function abortCalibration() {
        const ab = $('op-cal-abort');
        if (ab) { ab.disabled = true; ab.textContent = 'Aborting…'; }
        try {
            const d = await postJSON('/api/devices/calibrate/abort', {});
            if (!d.aborted) toast('Nothing to abort — the calibration had already finished');
        } catch (e) {
            toastFail(`Abort failed (${why(e)})`);
            if (ab) { ab.disabled = false; ab.textContent = 'Abort'; }
        }
    }

    // The calibration pane names its subject and reports the fit it has, if any
    // — the same field the server-side gate checks, so the pane shows what a run
    // would refuse rather than leaving it to be discovered at Start.
    const hasFit = emb => {
        const slope = Number(((emb && emb.calibration) || {}).slope_um_per_deg);
        return Number.isFinite(slope) && slope !== 0;
    };

    let _refusedFor = null;

    function renderCalTarget() {
        const t = $('op-cal-target');
        const emb = _embryos.find(e => e.id === _selected);
        // A refusal is about ONE embryo. Carrying it to the next selection
        // would offer "calibrate anyway" over an embryo nobody has checked.
        if (_refusedFor && _refusedFor !== _selected) { _refusedFor = null; hideRefusal(); }
        if (t) t.textContent = emb ? `embryo ${labelFor(emb)}` : 'no embryo selected';
        renderBorrow(emb);
        renderCalibrateAll();
        renderClearFit(emb);
        renderFitRow();
        if (emb) renderCalKept(emb);
    }

    // The Sheet panel's Fit row: whose fit, what it is, and the verb. It is
    // on screen with any camera, so it is drawn with the instrument
    // (renderScope) and reads nothing from the server.
    function renderFitRow() {
        const emb = _embryos.find(e => e.id === _selected);
        // The verb says which of the two things it does. Running it again over
        // a fit that already exists is a different decision from calibrating
        // something that has none, and the button used to read the same.
        const b = $('op-calibrate');
        if (b && !b.disabled) b.textContent = hasFit(emb) ? 'Recalibrate' : 'Calibrate';
        const out = $('op-cal-result');
        if (!out) return;
        // While a run goes the line is the run's ("sweeping…"); it is put
        // back when the run ends and the button with it.
        if (b && b.disabled) return;
        let says = 'no embryo selected';
        if (emb && hasFit(emb)) {
            // A fit records an R² for each end of the sheet; the weaker one
            // decides, as it does when a fit is borrowed (fitScore).
            const c = emb.calibration || {};
            const known = [c.r_squared_top, c.r_squared_bottom, c.r_squared].some(v => v != null);
            says = `embryo ${labelFor(emb)} · ${Number(c.slope_um_per_deg).toFixed(1)} µm/deg`
                + (known ? ` · R² ${fitScore(emb).toFixed(2)}` : '');
        } else if (emb) {
            says = `embryo ${labelFor(emb)} · not calibrated`;
        }
        out.textContent = says;
        out.title = says;
    }

    // ── what the calibration looked at ──────────────────────────────────────
    // The exposures and plots of each run are kept with the embryo. The latest
    // run's plots are shown here; every image of it opens behind a click.
    let _calKept = null;     // {embryoId, run, images} as last shown

    async function renderCalKept(emb) {
        const host = $('op-cal-kept');
        if (!host) return;
        if (!emb) { host.hidden = true; return; }
        const id = emb.id;
        let runs = [];
        try {
            const d = await getJSON(`/api/calibration/records?embryo_id=${encodeURIComponent(id)}`);
            runs = (d && d.records) || [];
        } catch (_) { runs = []; }
        if (_selected !== id) return;            // the selection moved on while we asked
        if (!runs.length) { host.hidden = true; _calKept = null; return; }
        const last = runs[runs.length - 1];
        let images = [];
        try {
            const d = await getJSON(`/api/calibration/records/${encodeURIComponent(id)}/${encodeURIComponent(last.run)}`);
            images = (d && d.images) || [];
        } catch (_) { images = []; }
        if (_selected !== id) return;
        _calKept = { embryoId: id, run: last.run, images };
        const when = last.started_at ? new Date(last.started_at) : null;
        const t = when && !isNaN(when) ? when.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' }) : last.run;
        const say = $('op-cal-kept-say');
        if (say) {
            say.textContent = `${runs.length} run${runs.length === 1 ? '' : 's'} kept · latest ${t}, ` +
                `${last.outcome || 'unknown'}: ${last.frames || 0} exposure${last.frames === 1 ? '' : 's'}, ` +
                `${last.plots || 0} plot${last.plots === 1 ? '' : 's'}`;
        }
        const strip = $('op-cal-kept-strip');
        if (strip) {
            const plots = images.filter(i => (i.file || '').startsWith('plots/'));
            const shown = plots.length ? plots : images.slice(-6);
            strip.innerHTML = shown.map(i =>
                `<button type="button" class="op-cal-kept-img" data-cal-img="${images.indexOf(i)}" title="${escapeHtml(calImageTitle(i))}">` +
                `<img loading="lazy" src="${escapeHtml(i.url)}?max=720" alt="${escapeHtml(calImageTitle(i))}"></button>`).join('');
        }
        host.hidden = false;
    }

    function calImageTitle(i) {
        const bits = [String(i.kind || 'image').replace(/_/g, ' ')];
        if (i.galvo_name) bits.push(i.galvo_name);
        if (typeof i.piezo === 'number') bits.push(`piezo ${i.piezo.toFixed(1)} µm`);
        if (typeof i.galvo === 'number') bits.push(`galvo ${i.galvo.toFixed(3)}°`);
        if (typeof i.score === 'number') bits.push(`score ${i.score.toExponential(2)}`);
        if (typeof i.r_squared === 'number') bits.push(`R² ${i.r_squared.toFixed(2)}`);
        return bits.join(' · ');
    }

    function openCalImage(index) {
        if (!_calKept || typeof Lightbox === 'undefined') return;
        Lightbox.open(_calKept.images.map(i => ({
            url: i.url,
            u16: i.u16,                 // an exposure's counts; a plot has none
            data_type: calImageTitle(i),
            metadata: { embryo_id: _calKept.embryoId },
        })), Math.max(0, index), 'calibration');
    }

    async function openCalFolder() {
        if (!_calKept) return;
        if (typeof Reveal !== 'undefined') {
            Reveal.run({ what: 'calibration_run', embryo_id: _calKept.embryoId, run: _calKept.run }, 'show');
            return;
        }
        try {
            const d = await postJSON(`/api/calibration/records/${encodeURIComponent(_calKept.embryoId)}/${encodeURIComponent(_calKept.run)}/open-folder`, {});
            toast(`Opened ${d.path}`);
        } catch (e) { toastFail(`Could not open the folder (${why(e)})`); }
    }

    // ── borrowing a fit ─────────────────────────────────────────────────────
    // Named, not generic: an operator about to copy numbers onto a live embryo
    // should see whose numbers and how good they are before pressing anything.
    // The server's LOW_CONFIDENCE_R2 (gently/app/tools/calibration_tools.py):
    // below this a focus sweep is reported as low confidence.
    const LOW_CONFIDENCE_R2 = 0.5;

    // Same metric as the server: the WORSE of the two ends decides, since an
    // acquisition spans both galvo extremes and the weaker end dominates.
    const fitScore = e => {
        const c = (e || {}).calibration || {};
        const ends = [c.r_squared_top, c.r_squared_bottom].filter(v => v != null);
        return ends.length ? Math.min(...ends) : Number(c.r_squared || 0);
    };

    // Every embryo that could lend this one its slope, best fit first. Not
    // one: the operator may know the slide better than the R² does, and may
    // want the lineaging embryo's line for a neuron embryo whatever the
    // numbers say. Two are never offered: the embryo itself, and any embryo
    // that borrowed FROM it — that is its own line coming back.
    function lenders(forEmbryo) {
        const me = (forEmbryo || {}).id;
        const out = _embryos.filter(e => e.id !== me && !e.should_skip && hasFit(e)
            && (e.calibration || {}).borrowed_from !== me);
        out.sort((a, b) => fitScore(b) - fitScore(a));
        return out.map(e => ({ emb: e, score: fitScore(e) }));
    }
    function bestSource(forEmbryo) { return lenders(forEmbryo)[0] || null; }

    // ── the pre-flight refusal ──────────────────────────────────────────────
    // A calibration that declines to start has to say why in the operator's
    // terms. The detail carries Claude's own words per probe position, and the
    // frames it judged are already in the progress panel above — so the
    // override is offered next to the evidence for it, not instead of it.
    function showRefusal(err) {
        const row = $('op-cal-refused'), why_ = $('op-cal-refused-why');
        if (!row || !why_) return;
        const detail = (err && err.data && err.data.detail) || (err && err.message) || '';
        // First line is the verdict; the rest is per-position detail the
        // filmstrip already shows. Keep the line short and let them look.
        const verdict = String(detail).split(String.fromCharCode(10))[0]
            || 'Nothing visible at the expected focus.';
        // The server cannot tell an unlit sheet from a raised head from a
        // stage that is somewhere else: its advice is to check all three.
        // The page can read all three, and they are on screen beside this.
        const points = pointAtWhatIsWrong();
        const stop = /[.!?]$/.test(verdict) ? '' : '.';
        why_.textContent = points.length ? `${verdict}${stop} ${points.map(p => p.says).join(' ')}` : verdict;
        row.hidden = false;
    }

    const POINTED = { light: 'op-light-host', head: 'op-gauge-fd', stage: 'op-stage-panel' };
    function pointAtWhatIsWrong() {
        if (typeof RunPreflight === 'undefined' || !RunPreflight.calibrationPoints) return [];
        const light = SharedState.get('light');
        const points = RunPreflight.calibrationPoints({
            emitting: typeof LightPanel !== 'undefined' && light ? LightPanel.emitting(light) : null,
            ledOpen: ledIsOpen(),
            head: fd.pos() != null ? { um: fd.pos(), gotoMin: gotoLimits().lo } : null,
            atEmbryo: _xy ? atSelected() : null,
        });
        unpoint();
        points.forEach(p => { const el = $(POINTED[p.panel]); if (el) el.classList.add('is-pointed'); });
        return points;
    }
    function unpoint() {
        Object.values(POINTED).forEach(id => { const el = $(id); if (el) el.classList.remove('is-pointed'); });
    }

    function hideRefusal() {
        const row = $('op-cal-refused');
        if (row) row.hidden = true;
        unpoint();
    }

    // ── clearing a fit ──────────────────────────────────────────────────────
    // Two clicks, not a dialog. The fit being discarded cost sixty to eighty
    // exposures on a live embryo and cannot be recovered except by spending
    // them again, but a modal for every reset would be its own tax — so the
    // button asks once, in place, and forgets after a few seconds.
    let _clearArmed = false;
    let _clearTimer = null;

    function disarmClear() {
        _clearArmed = false;
        if (_clearTimer) { clearTimeout(_clearTimer); _clearTimer = null; }
        const b = $('op-cal-clear');
        if (b) { b.textContent = 'Clear fit'; b.classList.remove('is-armed'); }
    }

    function renderClearFit(emb) {
        const b = $('op-cal-clear');
        if (!b) return;
        const show = hasFit(emb);
        if (b.hidden !== !show) disarmClear();
        b.hidden = !show;
    }

    async function clearFit() {
        if (!_selected) return;
        const b = $('op-cal-clear');
        if (!_clearArmed) {
            _clearArmed = true;
            if (b) { b.textContent = 'Clear it? click again'; b.classList.add('is-armed'); }
            _clearTimer = setTimeout(disarmClear, 5000);
            return;
        }
        disarmClear();
        if (b) b.disabled = true;
        try {
            await deleteJSON(`/api/devices/embryos/${_selected}/calibration`);
            const mine = _embryos.find(e => e.id === _selected);
            if (mine) mine.calibration = {};
            toast('Calibration cleared — this embryo now counts as uncalibrated');
        } catch (e) {
            toastFail(`Could not clear the fit (${why(e)})`);
        } finally {
            if (b) b.disabled = false;
            renderCalTarget();
        }
    }

    // Embryos that would be calibrated by "the rest": no fit, not skipped.
    const uncalibrated = () => _embryos.filter(e => !e.should_skip && !hasFit(e));

    function renderCalibrateAll() {
        const btn = $('op-cal-all');
        if (!btn) return;
        const pending = uncalibrated();
        // One embryo left is just the Calibrate button next to it; a batch
        // verb for a batch of one is noise.
        if (pending.length < 2) { btn.hidden = true; return; }
        btn.hidden = false;
        if (!btn.disabled) btn.textContent = `Calibrate ${pending.length} uncalibrated`;
    }

    async function calibrateAll() {
        const pending = uncalibrated();
        if (!pending.length) return;
        if (!mayTakeFromRun('Calibrating the rest')) return;
        const btn = $('op-cal-all'), out = $('op-cal-result');
        const t0 = Date.now();
        const tick = setInterval(() => {
            if (btn) btn.textContent = `Calibrating ${pending.length}… `
                + `${Math.round((Date.now() - t0) / 1000)}s`;
        }, 1000);
        if (btn) { btn.disabled = true; btn.textContent = `Calibrating ${pending.length}… 0s`; }
        if (out) out.textContent = 'sweeping…';
        // No embryo id: the run walks the slide, so the progress panel should
        // take frames from whichever embryo is under the objective.
        if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.begin(null);
        try {
            const d = await postJSON('/api/devices/calibrate/all',
                Object.assign({ scope: 'uncalibrated' }, calibrationSettings()));
            const ok = (d.calibrated || []).length, bad = (d.failed || []).length;
            if (bad) toastFail(`${ok} calibrated, ${bad} failed: ${(d.failed || []).join(', ')}`);
            else toast(`Calibrated ${ok} embryo${ok === 1 ? '' : 's'}`);
            if (typeof CalProgressPanel !== 'undefined') {
                CalProgressPanel.finish(!bad, bad ? `${bad} failed` : `${ok} calibrated`);
            }
        } catch (e) {
            if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.finish(false, why(e));
            toastFail(`Calibrate all failed (${why(e)})`);
        } finally {
            clearInterval(tick);
            if (btn) btn.disabled = false;
            renderCalTarget();
        }
    }

    function renderBorrow(emb) {
        const btn = $('op-cal-borrow'), note = $('op-cal-borrow-note');
        const row = $('op-cal-borrow-row'), sel = $('op-cal-borrow-from');
        if (!btn || !note || !row || !sel) return;
        const who = emb ? lenders(emb) : [];
        // Nothing to lend, nothing to say, no room taken.
        if (!who.length) { btn.hidden = true; note.hidden = true; row.hidden = true; return; }
        const keep = sel.value;
        sel.innerHTML = '';
        who.forEach(({ emb: e, score }) => {
            const o = document.createElement('option');
            o.value = e.id;
            const how = (e.calibration || {}).method || 'legacy';
            o.textContent = `embryo ${labelFor(e)} — R² ${score.toFixed(2)}, ${how}`;
            sel.appendChild(o);
        });
        sel.value = who.some(w => w.emb.id === keep) ? keep : who[0].emb.id;
        btn.hidden = false; note.hidden = false; row.hidden = false;
        const pick = who.find(w => w.emb.id === sel.value) || who[0];
        btn.textContent = `Borrow embryo ${labelFor(pick.emb)}’s slope`;
        // Calling a bad fit "the best on the slide" is true and misleading at
        // once. Below the module's own low-confidence line the offer stays —
        // an operator may know something the R² does not — but it says what it
        // is rather than recommending it.
        const poor = pick.score < LOW_CONFIDENCE_R2;
        const worse = hasFit(emb) && pick.score <= fitScore(emb);
        note.textContent = poor
            ? `Embryo ${labelFor(pick.emb)}'s fit is poor (R² ${pick.score.toFixed(2)}) — `
              + `below the low-confidence line. Calibrating this embryo is probably `
              + `better than starting from that.`
            : `Starts from embryo ${labelFor(pick.emb)}'s slope (R² ${pick.score.toFixed(2)}) `
              + `and measures this embryo's own extent and focus: a short scan, not a copy.`
              + (worse ? ` This embryo's own fit scores at least as well.` : '');
        note.classList.toggle('op-cap-warn', poor || worse);
    }

    async function borrowCalibration() {
        if (!_selected) { toastFail('Select an embryo first'); return; }
        if (!mayTakeFromRun('Borrowing a fit, which scans this embryo,')) return;
        const b = $('op-cal-borrow'), out = $('op-cal-result');
        const label = b ? b.textContent : '';
        const sel = $('op-cal-borrow-from');
        const source = (sel && sel.value) || 'auto';
        if (b) { b.disabled = true; b.textContent = 'Measuring…'; }
        if (out) out.textContent = 'measuring…';
        if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.begin(_selected);
        try {
            const d = await postJSON(
                `/api/devices/embryos/${_selected}/calibration/borrow`, { source });
            const cal = d.calibration || {};
            toast(`Calibrated from ${d.source_embryo_id}'s slope`);
            if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.finish(true, 'calibrated');
            // Write it onto the local copy rather than waiting for the
            // EMBRYOS_UPDATE broadcast: the render in `finally` would
            // otherwise redraw "not calibrated" over an embryo the server has
            // just confirmed calibrated, for as long as the round trip takes.
            const mine = _embryos.find(e => e.id === _selected);
            if (mine) mine.calibration = cal;
        } catch (e) {
            if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.finish(false, why(e));
            toastFail(`Could not borrow a fit (${why(e)})`);
        } finally {
            if (b) { b.disabled = false; b.textContent = label; }
            renderCalTarget();
        }
    }

    function renderSpimTarget() {
        const el = $('op-spim-target');
        const emb = _embryos.find(e => e.id === _selected);
        const here = atSelected();
        if (el) {
            el.textContent = !emb ? 'No embryo selected'
                : here ? `Selected: embryo ${labelFor(emb)}`
                : `Selected: embryo ${labelFor(emb)} — stage is elsewhere`;
        }
        // Drop the frame here as well as in onSpimFrame: with the stream off, no
        // frame arrives to be refused and the previous embryo's would just sit
        // there. Every path that changes the selection calls this.
        if (!here) clearImg('op-img-spim', 'op-ph-spim', 'Not at this embryo');
    }

    // ══ ACQUISITION PANE ════════════════════════════════════════════════════
    /**
     * Select an embryo, and maintain the selection SET around it.
     *
     * `_selected` is the primary — the one the instrument panes act on, which
     * is what it has always meant. `_targets` is every member. A plain click
     * makes them the same, so single-embryo work is unchanged; the modifiers
     * are the only way to grow the set, and growing it changes nothing until
     * Acquisition is switched to "Selected".
     *
     * Selection is NOT role. Excluding an embryo from tonight's run by marking
     * it a reference also changes expression_monitoring's scope and its
     * photodose budget multiplier in the orchestrator's `_is_eligible` — those
     * are facts about what the embryo is for, not about what is running.
     */
    function selectEmbryo(id, mode) {
        if (!id) return;
        const order = _embryos.map(e => e.id);

        if (mode === 'toggle') {
            const at = _targets.indexOf(id);
            if (at >= 0 && _targets.length > 1) {
                _targets.splice(at, 1);
                // Deselecting the primary hands it to a remaining member rather
                // than leaving the instrument panes pointed at nothing.
                if (_selected === id) _selected = _targets[0];
            } else if (at < 0) {
                _targets.push(id);
                _selected = id;
            }
        } else if (mode === 'range' && _selected && order.includes(_selected)) {
            const a = order.indexOf(_selected), b = order.indexOf(id);
            _targets = order.slice(Math.min(a, b), Math.max(a, b) + 1);
            _selected = id;
        } else {
            _targets = [id];
            _selected = id;
        }

        // Publish AFTER the local assignment: the subscription in wire() sees
        // _selected already equal and no-ops, so our own click renders exactly
        // once, as before. The set() is what makes the other copies of this
        // cursor follow.
        SharedState.set('selectedEmbryoIds', _targets.slice());
        SharedState.set('selectedEmbryoId', _selected);
        publishRoster(); renderSpimTarget(); renderCalTarget(); renderSingle();
        renderTargetScope();
    }

    // Shared embryo list, left of every instrument surface. Reads the canonical
    // _embryos (bootstrapped from /api/embryos/current, kept live by
    // EMBRYOS_UPDATE), so it is the same set on Bottom / SPIM / Acquire and it
    // survives a refresh.
    // The roster is rendered by panels/roster.js, mounted at each host. There
    // used to be publishRoster() and publishRoster() here — the same list,
    // twice, each with its own count element and an arbitrarily different set
    // of buttons. Publishing is all this file does now.
    function publishRoster() {
        // structuredClone, not slice(). SharedState only emits on a real change,
        // and it compares by value — so publishing a shallow copy of an array
        // whose ELEMENTS were mutated in place stores the same objects it is
        // comparing against, and the change is invisible. toggleRole mutates
        // `emb.role` in place, so the role button silently did nothing.
        //
        // Same lesson as #126: never hand out a reference to mutable state.
        SharedState.set('embryos', structuredClone(_embryos));
        const rail = $('op-erail-count'); if (rail) rail.textContent = _embryos.length;
        const ros = $('op-roster-count'); if (ros) ros.textContent = _embryos.length;
    }

    async function deleteEmbryo(id) {
        // An empty id builds `/api/embryos/`, which 307s to a GET-only route
        // and comes back 405 — a confusing failure for a row that should
        // never have had a delete button. Refuse it here, at the funnel.
        if (!id) { toastFail('That row has no id — refresh the roster'); return; }
        // The x is for a false positive, and it sits one row from an embryo
        // imaged all night. One that holds something is asked about first.
        // Nothing is deleted either way: the server moves the folder aside.
        const emb = _embryos.find(e => e.id === id);
        const name = emb ? `embryo ${labelFor(emb)}` : id;
        const holds = heldBy(emb);
        if (holds && !window.confirm(
            `Remove ${name} from the list?\n\nIt has ${holds}. `
            + 'Nothing is deleted: its files are kept in the session, and it can be restored.')) return;
        try {
            const res = await fetch(`/api/embryos/${encodeURIComponent(id)}`, { method: 'DELETE' });
            if (!res.ok) {
                throw Object.assign(new Error('delete failed'),
                    { status: res.status, data: await res.json().catch(() => ({})) });
            }
            const d = await res.json().catch(() => ({}));
            if (d.restorable && typeof showGentlyToast === 'function') {
                showGentlyToast(`Removed ${name}. Nothing was deleted.`, 'Undo',
                    () => restoreEmbryo(id), 12000);
            }
            readRemoved();
            // EMBRYOS_UPDATE will reconcile every view; prune optimistically so
            // the row disappears immediately even before the event lands.
            _embryos = _embryos.filter(e => e.id !== id);
            if (_selected === id) {
                _selected = null;   // the pick is gone; nothing else was picked (#140)
                SharedState.set('selectedEmbryoId', _selected);
            }
            publishRoster(); renderSpimTarget(); renderSingle(); drawMarkers();
        } catch (e) {
            toastFail(`Not removed (${why(e)})`);
        }
    }

    /** What an embryo carries that a slip of the hand would take off the list. */
    function heldBy(emb) {
        if (!emb) return '';
        const parts = [];
        const n = Number(emb.timepoints_acquired) || 0;
        if (n > 0) parts.push(`${n} timepoint${n === 1 ? '' : 's'}`);
        const slope = Number((emb.calibration || {}).slope_um_per_deg);
        if (Number.isFinite(slope) && slope !== 0) parts.push('a calibration');
        return parts.join(' and ');
    }

    async function restoreEmbryo(id) {
        if (!id) return;
        try {
            const res = await fetch(`/api/embryos/${encodeURIComponent(id)}/restore`, { method: 'POST' });
            if (!res.ok) {
                throw Object.assign(new Error('restore failed'),
                    { status: res.status, data: await res.json().catch(() => ({})) });
            }
            toast(`${id.replace(/^embryo_/, 'Embryo ')} is back in the list`);
            // EMBRYOS_UPDATE brings the row back.
            readRemoved();
        } catch (e) {
            toastFail(`Not restored (${why(e)})`);
        }
    }

    /** The embryos removed from this session, for the roster to list. */
    async function readRemoved() {
        let rows = [];
        try {
            const res = await fetch('/api/embryos/removed');
            const d = res.ok ? await res.json() : {};
            rows = Array.isArray(d.removed) ? d.removed : [];
        } catch (e) {
            rows = [];
        }
        SharedState.set('removedEmbryos', rows);
    }

    // Roles are read from the canonical embryo list and written through the
    // endpoint — deliberately NOT mirrored in a local map, which in the old
    // design drifted from _embryos and needed a reconciliation loop.
    async function toggleRole(id) {
        const emb = _embryos.find(e => e.id === id);
        if (!emb) return;
        const cur = (emb.role && emb.role !== 'unassigned') ? emb.role : 'lineaging';
        const next = cur === 'calibration' ? 'lineaging' : 'calibration';
        emb.role = next;
        publishRoster();
        const roles = {};
        _embryos.forEach(e => { roles[e.id] = (e.role && e.role !== 'unassigned') ? e.role : 'lineaging'; });
        try { await postJSON('/api/embryos/roles', { roles }); }
        catch (e) { toastFail(`Roles failed (${why(e)})`); }
    }

    // What `Start` will actually do, per mode. The button used to say "Start"
    // for all four, while `startRun` branched into four different verbs — one
    // of which (single) acquires a volume and finishes, and is not starting an
    // experiment at all. The mode selector sits in a block above, so an
    // operator who chose a mode and then looked away had nothing to read.
    // The form is the run (`adaptive`). A saved tactic that is not a plan
    // cannot fill a form, so it is run as it is (`library`). The other two
    // things this used to offer as peers of those were never kinds of run: a
    // test volume is a button beside the pictures (testVolume), and handing
    // the embryos to the agent is a button under Start (handToAgent).
    const RUN_VERB = {
        adaptive: 'Start timelapse',
        library: 'Run tactic',
    };

    // A run is running or paused: nothing else may start. The button used to
    // go on offering "Run tactic" over a tactic that was running, and pressing
    // it got a refusal from the orchestrator, said as a failure.
    let _runBusy = false;
    let _starting = false;      // a start is in flight: "Working…" is on the button

    function renderRunButton() {
        const b = $('op-run-start');
        if (!b || _starting) return;
        // What would refuse the run is counted onto the button: the verdict
        // is where the hand is, and the reasons are the lines above it.
        const v = _mode === 'adaptive' && !_runBusy ? RunPreflight.verdict(_preflight) : { blocked: 0, says: '' };
        b.disabled = _runBusy || v.blocked > 0;
        b.textContent = _runBusy ? 'A run is going' : (v.says || RUN_VERB[_mode] || 'Start');
        b.classList.toggle('is-blocked', v.blocked > 0);
        b.title = _runBusy ? 'Stop the run before starting another'
            : v.blocked ? 'What stands in the way is listed above' : '';
    }

    /**
     * What Start does: the form's plan (`adaptive`), or a saved tactic as it
     * is (`library`). There is no strip of modes: the form is always there,
     * and a tactic is chosen from the Saved list.
     */
    function setMode(m) {
        _mode = m === 'library' ? 'library' : 'adaptive';
        if (_mode === 'library') showSaved(true);
        if (_mode === 'adaptive') { _selectedLib = null; loadLaserPresets(); renderPlan(); }
        const say = $('op-plan-say');
        if (say) say.classList.toggle('is-aside', _mode !== 'adaptive');
        renderPlanName();
        renderPreflight();
        renderSingle();
    }

    /** The Saved list, open or shut. Load opens it; choosing a plan shuts it. */
    function showSaved(open) {
        const box = $('op-panel-library'), b = $('op-plan-load');
        if (box) box.hidden = !open;
        if (b) b.setAttribute('aria-expanded', String(!!open));
        if (open) loadLibrary();
    }

    // The saved plan the form was filled from: {id, name, edited}. Left as
    // it was loaded, Start runs it as that tactic, so the run is filed as
    // what it was loaded from; once edited it is the form's own.
    let _loaded = null;

    /** The form has been changed by hand: a pending change, and no longer
     *  the saved plan it may have been loaded from. */
    function planTouched() {
        _planDirty = true;
        if (_loaded) _loaded.edited = true;
    }

    function renderPlanName() {
        const el = $('op-plan-name');
        if (!el) return;
        el.textContent = _mode === 'library' ? 'a saved tactic, as it is'
            : _loaded ? (_loaded.edited ? `${_loaded.name}, edited` : _loaded.name)
                : '';
    }

    /**
     * The test volume's button: which embryo, and why not when it cannot.
     *
     * It is the selected embryo's volume with the plan's slices and exposure,
     * kept under the embryo as its next timepoint, and its projection lands
     * on its tile. It used to be a mode with fields of its own, and what it
     * took was shown nowhere on the page that took it.
     */
    function renderSingle() {
        const b = $('op-test-one');
        if (!b || _testing) return;
        const emb = _embryos.find(e => e.id === _selected);
        const volumes = !($('op-plan-spim') && !$('op-plan-spim').checked);
        const why = !emb ? 'Select an embryo first'
            : _runBusy ? 'A run is going'
                : !volumes ? 'This plan takes no volumes'
                    : !hasFit(emb) ? `Embryo ${labelFor(emb)} has no calibration: a volume of it would be refused`
                        : '';
        b.textContent = emb ? `Test embryo ${labelFor(emb)}` : 'Test volume';
        b.disabled = !!why;
        // A fact, not a gate: how far off the stage is. The volume goes to
        // the embryo wherever the stage is now.
        const xy = emb ? resolveXY(emb) : null;
        const away = xy && _xy ? ` The stage is ${Math.round(Math.hypot(xy.x - _xy.x, xy.y - _xy.y))} µm from it.` : '';
        b.title = why || `One volume of embryo ${labelFor(emb)} with this plan's slices and exposure, kept as its next timepoint.${away}`;
    }

    let _testing = false;

    async function testVolume() {
        const b = $('op-test-one');
        const emb = _embryos.find(e => e.id === _selected);
        if (!emb || _testing) return;
        if (_runBusy) { toastFail('A run is going. Stop it before taking a test volume.'); return; }
        const plan = readPlan();
        _testing = true; _acquiring = true; renderSubnavMeta();
        if (b) { b.disabled = true; b.textContent = `Taking embryo ${labelFor(emb)}…`; }
        try {
            const d = await postJSON('/api/devices/acquire/volume', {
                // Say WHICH embryo. The route used to receive no id at
                // all, so it imaged wherever the stage happened to be
                // and could not check whether that embryo had ever been
                // calibrated. Manual-mode snapping still omits it on
                // purpose — a test shot at the current position is a
                // real thing to want.
                embryo_id: emb.id,
                num_slices: plan.spim.slices != null ? plan.spim.slices : (emb.num_slices || 50),
                exposure_ms: plan.spim.exposureMs != null ? plan.spim.exposureMs : (emb.exposure_ms || 10),
            });
            // The first line of what the acquisition said: which embryo,
            // and whether it was kept.
            toast(String((d && d.message) || 'Volume acquired').split(/\r?\n/)[0]);
            // Its picture, on its tile, now: the roster's own update follows.
            try { onEmbryosUpdate(await getJSON('/api/embryos/current')); } catch (_) { /* the broadcast will */ }
        } catch (e) {
            // In the operator's words. The route's own are for a caller that
            // can pass a flag: "…or pass allow_uncalibrated=true to acquire
            // anyway".
            if (e && e.status === 409 && /not calibrated/i.test(String((e.data || {}).detail || ''))) {
                toastFail(`No volume taken: embryo ${labelFor(emb)} has no calibration.`);
            } else {
                toastFail(`No volume taken (${why(e)})`);
            }
        } finally {
            _testing = false; _acquiring = false;
            await forceLedOff(); renderSubnavMeta(); renderSingle(); renderTiles();
        }
    }

    async function loadLibrary() {
        const host = $('op-lib-list');
        if (!host) return;
        try {
            const d = await getJSON('/api/tactic_library');
            const items = (d && d.tactics) || [];
            if (!items.length) { host.innerHTML = '<div class="op-empty">No saved tactics</div>'; return; }
            // A saved plan is listed as its sentence, said for the embryos
            // marked NOW — the template holds the plan, the roster is today's.
            const subjects = planSubjects();
            host.innerHTML = items.map(t => {
                const isPlan = t.kind === 'standing_timelapse' && t.structure;
                const sub = isPlan
                    ? AcquisitionPlan.describe(AcquisitionPlan.fromStructure(t.structure), subjects)
                    : (t.kind || '');
                return `<button class="op-libitem${t.id === _selectedLib ? ' is-sel' : ''}" type="button" ` +
                    `data-lib="${escapeHtml(t.id)}"${isPlan ? ' data-lib-plan="1"' : ''} ` +
                    `title="${isPlan ? 'Fill the form with this plan' : 'Run this tactic as it is'}">${escapeHtml(t.name || t.id)}` +
                    `<small class="${isPlan ? 'op-lib-say' : ''}">${escapeHtml(sub)}</small></button>`;
            }).join('');
            _library = items;
        } catch (_) { host.innerHTML = '<div class="op-empty">Library unavailable</div>'; }
    }

    let _library = [];

    /**
     * One of the Saved list, chosen. A plan fills the form and the list
     * shuts: the form is then that plan, said in the sentence, checked by
     * the lines, started by Start. A tactic that is not a plan has no form
     * to fill, so it stays chosen and Start runs it as it is.
     */
    function chooseSaved(id) {
        const t = _library.find(x => x.id === id);
        if (!t) return;
        if (t.kind === 'standing_timelapse' && t.structure) {
            try { fillPlan(AcquisitionPlan.fromStructure(t.structure)); } catch (e) { toastFail('That plan could not be read'); return; }
            _loaded = { id: t.id, name: t.name || t.id, edited: false };
            // A pending change: the embryos do not hold it yet, and a form
            // that follows the embryos would write theirs back over it.
            _planDirty = true;
            _selectedLib = null;
            showSaved(false);
            setMode('adaptive');
            toast(`“${_loaded.name}” is in the form`);
            return;
        }
        _selectedLib = id;
        setMode('library');
    }

    /** The embryos, handed to the agent with the roster said in words. */
    function handToAgent() {
        const roster = _embryos.map(e => {
            const xy = resolveXY(e);
            const r = e.role === 'calibration' ? 'reference' : 'subject';
            return `${labelFor(e)}${xy ? ` (${xy.x.toFixed(0)},${xy.y.toFixed(0)})` : ''} [${r}]`;
        }).join(', ');
        const prompt = `I marked ${_embryos.length} embryos: ${roster}. ` +
            'Propose and start an Operation Plan to image them.';
        if (typeof AgentChat !== 'undefined' && AgentChat.togglePanel) {
            AgentChat.togglePanel(true);
            if (AgentChat.runCommand) setTimeout(() => AgentChat.runCommand(prompt), 300);
        } else toastFail('Agent chat unavailable');
    }

    /**
     * The embryos a run should image: everything not marked as a reference.
     *
     * There used to be a fallback — `subs.length ? subs : all` — meant to be
     * kind to a roster with no roles assigned. It could never do that. An
     * embryo with no role, or role 'test', or 'unassigned', already passes the
     * filter, so `subs` is empty in exactly ONE case: every embryo is marked
     * `calibration`. The fallback therefore fired only when the operator had
     * said "these are all references", and answered by imaging all of them as
     * subjects — the precise opposite of the instruction.
     *
     * Empty now, and the caller says so.
     */
    function allSubjectIds() {
        return _embryos.filter(e => e.role !== 'calibration').map(e => e.id);
    }

    /** The embryos a run will image, per the declared scope. */
    function subjectIds() {
        if (_targetScope !== 'selected') return allSubjectIds();
        // Never a reference, whatever is selected: role still decides what an
        // embryo is for.
        const refs = new Set(_embryos.filter(e => e.role === 'calibration').map(e => e.id));
        return _targets.filter(id => !refs.has(id));
    }

    // The pane says which set it will use, and how big it is. The modifier keys
    // that grow the set do not have to be discovered for this to be readable.
    function renderTargetScope() {
        const el = $('op-target-scope');
        if (!el) return;
        const all = allSubjectIds().length;
        const sel = subjectIds().length;
        el.querySelectorAll('[data-scope]').forEach(b => {
            const on = b.dataset.scope === _targetScope;
            b.classList.toggle('is-on', on);
            b.setAttribute('aria-pressed', String(on));
        });
        const inrun = $('op-roster-inrun');
        if (inrun) inrun.textContent = _embryos.length ? `· ${subjectIds().length} in the run` : '';
        const a = el.querySelector('[data-scope="all"]');
        const s2 = el.querySelector('[data-scope="selected"]');
        if (a) a.textContent = `All subjects (${all})`;
        if (s2) {
            s2.textContent = `Selected (${_targetScope === 'selected' ? sel : _targets.length})`;
            s2.disabled = !_targets.length;
        }
    }

    function setTargetScope(scope) {
        _targetScope = scope === 'selected' ? 'selected' : 'all';
        renderTargetScope();
        renderSingle();
        // Which embryos is part of the plan: its sentence, its lines, the
        // table's dimming and the pictures all follow.
        if (_pane === 'acquire') renderPlan();
    }

    // Every embryo marked as a reference means there is nothing to image. Say
    // so once, here, rather than at each mode — and say which state it is in,
    // because "no embryos" and "no subjects among your embryos" need
    // different fixes.
    function haveSubjects() {
        if (!_embryos.length) { toastFail('No embryos registered yet'); return false; }
        if (!subjectIds().length) {
            toastFail('Every embryo is marked as a reference — assign at least one subject');
            return false;
        }
        return true;
    }

    async function startRun() {
        const b = $('op-run-start');
        if (_runBusy) { toastFail('A run is already going. Stop it before starting another.'); return; }
        const done = () => { _starting = false; renderRunButton(); renderRun(); };
        _starting = true;
        if (b) { b.disabled = true; b.textContent = 'Working…'; }
        try {
            if (_mode === 'adaptive') {
                const plan = readPlan();
                // A brightfield frame is of the field. It is taken with no
                // embryo registered, so the run is not refused for having none.
                if (plan.spim.enabled && !haveSubjects()) return;
                const ids = subjectIds();
                const problems = AcquisitionPlan.validate(plan, ids, _laserLimits);
                if (problems.length) { toastFail(problems[0]); return; }
                // One object: the sentence the operator just read is exactly
                // what goes on the wire, and what the run view says back.
                // A saved plan, loaded and left as it was, is run as that
                // tactic: the run is then filed as what it was loaded from.
                if (_loaded && !_loaded.edited && !(_setupItem && _setupItem.id)) {
                    const d = await postJSON('/api/operate/run-tactic',
                        { library_id: _loaded.id, embryo_ids: ids, scope: _targetScope });
                    if (!d.success) { toastFail(`Run failed: ${(d.result && d.result.message) || '?'}`); return; }
                    toast(`“${_loaded.name}” started`);
                    landOnRun(AcquisitionPlan.describe(plan, planSubjects()));
                    return;
                }
                const payload = AcquisitionPlan.toPayload(plan, ids);
                payload.scope = _targetScope;   // "what to run", kept with the plan
                if (_setupItem && _setupItem.id) payload.plan_item_id = _setupItem.id;
                await postJSON('/api/devices/timelapse/start', payload);
                if (_setupItem) { _setupItem = null; renderSetupBanner(); }
                // What was typed has been applied: the form follows the
                // embryos again until the operator types something new.
                _planDirty = false;
                toast(plan.spim.enabled ? 'Timelapse started' : 'Brightfield timelapse started');
                landOnRun(AcquisitionPlan.describe(plan, planSubjects()));
                return;
            }
            if (_mode === 'library') {
                if (!_selectedLib) { toastFail('Pick a saved tactic'); return; }
                if (!haveSubjects()) return;
                const d = await postJSON('/api/operate/run-tactic',
                    { library_id: _selectedLib, embryo_ids: subjectIds(), scope: _targetScope });
                if (d.success) { toast('Tactic started'); renderRun(); }
                else toastFail(`Run failed: ${(d.result && d.result.message) || '?'}`);
                return;
            }
        } catch (e) {
            toastFail(`Start failed (${why(e)})`);
        } finally { done(); }
    }

    // Run presence is DERIVED from the server, not from a client flag. The old
    // design kept it in memory, so F5 during a running timelapse lost the whole
    // panel — and left a client state machine that could re-grow into steps.
    // ══ THE ACQUISITION PLAN ══════════════════════════════════════════════
    // The Adaptive pane is a form for one object (acquisition-plan.js). Every
    // input re-reads it and re-says it; Start sends exactly what was said.
    // The fields of view the overview is taken from, [{x, y}] in stage µm:
    // one, or several when the embryos do not all fit in one frame. Built in
    // the rail on Scope (panels/fields.js), kept in the session
    // (/api/brightfield/fields), read by the plan as "taken from the fields".
    let _bfPins = [];
    let _laserPresetsLoaded = false;
    // Per-line power bounds, from the device layer ({488: {min, max}}). Null
    // until read: the fields are then unbounded on the pane, and the start
    // route is what refuses a power the hardware would.
    let _laserLimits = null;

    // ══ THE OVERVIEW FIELDS ═══════════════════════════════════════════════
    // The list is the session's, not the form's: a field is a place on the
    // dish the operator chose while looking at it, and it has to be there
    // after a reload and on the other pane. So every change is published
    // (the two Fields panels redraw), persisted (best effort — the page
    // keeps the list if the write fails), and said back in the plan.
    let _fieldsLoaded = false;
    let _fieldsSaveTimer = null;

    function publishFields() {
        SharedState.set('overviewFields', structuredClone(_bfPins));
        ['op-frail-count', 'op-fields-count'].forEach(id => {
            const el = $(id); if (el) el.textContent = _bfPins.length;
        });
    }

    function persistFields() {
        clearTimeout(_fieldsSaveTimer);
        _fieldsSaveTimer = setTimeout(() => {
            fetch('/api/brightfield/fields', {
                method: 'PUT', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ fields: _bfPins.map(p => ({ x: p.x, y: p.y })) }),
            }).then(r => { if (!r.ok) console.warn(`[gently] fields not kept: ${r.status}`); })
                .catch(() => { /* the list lives on in the page */ });
        }, 200);
    }

    /** The session's fields, once. A list already built here outranks them. */
    async function loadFields() {
        if (_fieldsLoaded) return;
        _fieldsLoaded = true;
        try {
            const d = await getJSON('/api/brightfield/fields');
            const got = (d && Array.isArray(d.fields) ? d.fields : [])
                .filter(p => p && Number.isFinite(p.x) && Number.isFinite(p.y))
                .map(p => ({ x: p.x, y: p.y }));
            if (got.length && !_bfPins.length) {
                // A session with fields is a session that wants the overview
                // from them: the select and the channel follow, as they do
                // when a field is added. The last run's plan, restored after
                // this, may still say otherwise — and then it is believed.
                _bfPins = got;
                const pos = $('op-plan-bf-pos'); if (pos) pos.value = 'here';
                const bf = $('op-plan-bf'); if (bf && !bf.disabled) bf.checked = true;
            }
        } catch (_) { /* no session, or the rig is away: an empty list */ }
        publishFields();
        renderPlan();
    }

    /** The field the stage is at, within the Fields panel's tolerance, or -1. */
    function fieldIndexAt(xy) {
        const tol = (typeof FieldsPanel !== 'undefined' && FieldsPanel.HERE_UM) || 50;
        return _bfPins.findIndex(p => M ? M.atPosition(xy, p, tol)
            : (xy && Math.hypot(p.x - xy.x, p.y - xy.y) <= tol));
    }

    /**
     * A field from where the stage is, now. The one way a field is made —
     * from the rail, from Acquisition, or from the "taken from" select
     * choosing the list while it is empty.
     */
    function addFieldHere() {
        if (!_xy || !Number.isFinite(_xy.x) || !Number.isFinite(_xy.y)) {
            toastFail('No stage position known yet');
            return false;
        }
        const dup = fieldIndexAt(_xy);
        if (dup >= 0) { toast(`The stage is at field ${dup + 1} already`); return false; }
        _bfPins.push({ x: _xy.x, y: _xy.y });
        fieldsChanged();
        const n = _bfPins.length;
        toast(n === 1 ? 'Field 1 added — the overview will be taken from it'
            : `Field ${n} added — the overview will take a frame from each of the ${n} fields`);
        return true;
    }

    function removeField(i) {
        if (!(i >= 0 && i < _bfPins.length)) return;
        _bfPins.splice(i, 1);
        fieldsChanged();
        toast(_bfPins.length ? `Field dropped — ${_bfPins.length} left` : 'Last field dropped — the overview goes back to the centroid');
    }

    /** Through the XY chokepoint, so the interlock holds here too. */
    async function goToField(i) {
        const p = _bfPins[i];
        if (!p) return;
        await moveStageTo(p.x, p.y, `Stage sent to field ${i + 1}`);
    }

    /**
     * The list is the plan's "taken from". A field added is a field wanted:
     * the select follows the list, and the overview channel is switched on
     * (it cannot be, while a brightfield run already is the overview). The
     * last one dropped means the centroid again.
     */
    function fieldsChanged() {
        const pos = $('op-plan-bf-pos');
        if (pos) pos.value = _bfPins.length ? 'here' : 'centroid';
        const bf = $('op-plan-bf');
        if (bf && _bfPins.length && !bf.disabled) bf.checked = true;
        _planDirty = true;
        publishFields();
        persistFields();
        renderPlan();
    }

    /**
     * The overview frames as the live view has them: the LED's brightness
     * if it is open (else the room light), and the camera's exposure. What
     * the operator is looking at is what they usually want the run to take.
     */
    async function useLiveSettings() {
        const b = $('op-ov-match');
        if (b) b.disabled = true;
        try {
            const light = SharedState.get('light') || {};
            const ledOpen = light.led === 'Open';
            const pct = ledOpen && light.ledPct != null && Number.isFinite(Number(light.ledPct))
                ? Math.max(1, Math.min(100, Math.round(Number(light.ledPct)))) : null;
            let ms = null;
            try {
                const d = await getJSON('/api/devices/camera/exposure');
                if (d && d.success !== false && d.exposure_ms != null) ms = Number(d.exposure_ms);
            } catch (_) { /* unread stays as it was */ }
            const sel = $('op-plan-bf-light');
            if (sel) sel.value = ledOpen ? 'led' : 'room';
            const led = $('op-plan-bf-led');
            if (led && pct != null) led.value = pct;
            const exp = $('op-plan-bf-exposure');
            if (exp && Number.isFinite(ms) && ms > 0) exp.value = ms;
            _planDirty = true;
            renderPlan();
            if (typeof BrightfieldRefs !== 'undefined') BrightfieldRefs.refresh();
            const lit = ledOpen ? `LED${pct != null ? ` ${pct} %` : ''}` : 'room light';
            toast(`Overview frames: ${lit}${Number.isFinite(ms) && ms > 0 ? ` · ${ms} ms` : ' · exposure not read'}`);
        } finally {
            if (b) b.disabled = false;
        }
    }

    /** The embryos this run will image, with the labels the sentence uses. */
    function planSubjects() {
        const ids = new Set(subjectIds());
        return _embryos.filter(e => ids.has(e.id)).map(e => ({ id: e.id, label: labelFor(e) }));
    }

    // The plan as the session last ran it. Filled once per page life, and
    // never over something the operator has already typed.
    let _planRestored = false;
    let _planDirty = false;

    /**
     * The SPIM fields follow the embryos the run targets.
     *
     * The form is what Start will apply; the embryos hold what the next
     * acquisition will use. Those are one thing only while nobody else is
     * changing them, and the agent does — `modify_parameters` used to set
     * an embryo to 30 slices while this field went on saying 50. So on
     * every EMBRYOS_UPDATE the fields are read back from the targets: one
     * value when they agree, blank with "varies 30–50" when they do not,
     * and a line naming who set what when it is not what the field says.
     *
     * Not over something the operator has typed and not yet started
     * (`_planDirty`): that is a pending change, and the line says how it
     * differs from what the embryos hold.
     */
    const PLAN_FIELDS = [
        { key: 'num_slices', id: 'op-plan-slices', unit: 'slices' },
        { key: 'exposure_ms', id: 'op-plan-exposure', unit: 'ms' },
        { key: 'laser_power_488_pct', id: 'op-plan-power-488', unit: '% 488' },
        { key: 'laser_power_561_pct', id: 'op-plan-power-561', unit: '% 561' },
        { key: 'laser_power_405_pct', id: 'op-plan-power-405', unit: '% 405' },
        { key: 'laser_power_637_pct', id: 'op-plan-power-637', unit: '% 637' },
    ];

    /** {value, min, max, by} of one parameter across the targets. */
    function heldAcross(targets, key) {
        const vals = targets.map(e => e[key]).filter(v => v != null);
        if (!vals.length) return null;
        const min = Math.min(...vals), max = Math.max(...vals);
        const who = new Set();
        targets.forEach(e => {
            const by = e.param_provenance && e.param_provenance[key] && e.param_provenance[key].by;
            if (by) who.add(by);
        });
        return { value: min === max ? min : null, min, max, by: [...who] };
    }

    function syncPlanFromEmbryos() {
        const ids = new Set(subjectIds());
        const targets = _embryos.filter(e => ids.has(e.id));
        const now = $('op-plan-spim-now');
        if (!targets.length || !$('op-plan-slices')) { if (now) now.hidden = true; return; }
        const notes = [];
        // What the operator has typed that the embryos do not hold — what an
        // Apply would write. Only a number: a blank field asks for nothing.
        const pending = {};
        PLAN_FIELDS.forEach(f => {
            const held = heldAcross(targets, f.key);
            const el = $(f.id);
            if (!el) return;
            if (held === null) { el.placeholder = f.id === 'op-plan-slices' || f.id === 'op-plan-exposure' ? '' : 'as it is'; return; }
            if (!_planDirty) {
                // Derived, not remembered: the field shows what the embryos
                // hold, and says "varies" rather than pick one of them.
                el.value = held.value != null ? held.value : '';
                el.placeholder = held.value != null ? '' : `varies ${held.min}–${held.max}`;
            }
            const typed = el.value === '' ? null : Number(el.value);
            const differs = typed == null ? held.value == null : typed !== held.value;
            if (differs) {
                const have = held.value != null ? `${held.value}` : `${held.min}–${held.max}`;
                const by = held.by.length ? ` (set by ${held.by.join(', ')})` : '';
                notes.push(`${have} ${f.unit}${by}`);
                if (typed != null && Number.isFinite(typed)) pending[f.key] = typed;
            }
        });
        if (!now) return;
        now.hidden = !notes.length;
        if (!notes.length) { now.textContent = ''; return; }
        // The button exists in one scenario: a run is going, and the field
        // holds something the embryos do not. Then "at Start" is not an
        // answer — a restart is not what the operator wants — and applying
        // now, to the next acquisition, is what the agent can already do.
        // Otherwise there is no button: the form is vanilla, and Start is
        // the apply.
        const applicable = _runBusy && Object.keys(pending).length > 0;
        const held = `Embryos now hold ${notes.join('; ')}`;
        now.textContent = applicable ? `${held}. ` : `${held} — the field applies at Start.`;
        if (applicable) {
            const n = targets.length;
            const what = Object.entries(pending)
                .map(([k, v]) => `${v} ${(PLAN_FIELDS.find(f => f.key === k) || {}).unit}`).join(', ');
            const b = document.createElement('button');
            b.type = 'button';
            b.className = 'op-btn op-btn-quiet op-plan-apply';
            b.dataset.planApply = '1';
            b.textContent = `Apply ${what} to ${n === 1 ? 'the embryo' : `${n} embryos`} now`;
            b.title = 'Takes effect at their next acquisition, like a change made by the agent';
            b.onclick = () => applyPendingToEmbryos(pending, targets.map(e => e.id));
            now.appendChild(b);
        }
    }

    /**
     * The operator's mid-run change, through the same door as the agent's:
     * recorded as the operator's, announced, in effect at the next
     * acquisition. The broadcast that follows re-syncs the form, so the
     * button goes with the difference it was for.
     */
    async function applyPendingToEmbryos(pending, ids) {
        const b = document.querySelector('[data-plan-apply]');
        if (b) { b.disabled = true; b.textContent = 'Applying…'; }
        try {
            await postJSON('/api/embryos/params', { embryo_ids: ids, changes: pending });
            _planDirty = false;
            toast(`Applied to ${ids.length} embryo${ids.length === 1 ? '' : 's'}`);
        } catch (e) {
            toastFail(`Apply failed (${why(e)})`);
        }
        renderPlan();
    }

    /** Put a plan into the form. The inverse of readPlan(). */
    function fillPlan(plan) {
        const set = (id, v) => { const el = $(id); if (el && v != null) el.value = v; };
        const secs = plan.intervalSeconds;
        if (secs % 60 === 0 && secs >= 60) { set('op-tl-interval', secs / 60); set('op-plan-unit', 'min'); }
        else { set('op-tl-interval', secs); set('op-plan-unit', 's'); }
        const spim = $('op-plan-spim');
        if (spim) spim.checked = plan.spim.enabled !== false;
        set('op-plan-slices', plan.spim.slices);
        set('op-plan-exposure', plan.spim.exposureMs);
        const laser = $('op-plan-laser');
        if (laser) {
            const want = plan.spim.laserConfig || '';
            if (want && ![...laser.options].some(o => o.value === want)) {
                laser.insertAdjacentHTML('beforeend', `<option value="${escapeHtml(want)}">${escapeHtml(want)}</option>`);
            }
            laser.value = want;
        }
        // After the select: which rows exist follows the preset. Every row is
        // written, so a line the plan leaves alone is cleared of the last
        // plan's number.
        renderPowerRows();
        document.querySelectorAll('#op-plan-powers [data-plan-power]').forEach(inp => {
            const pct = (plan.spim.laserPowers || {})[inp.dataset.planPower];
            inp.value = pct != null ? pct : '';
        });
        const bf = $('op-plan-bf');
        if (bf) bf.checked = !!plan.bf.enabled;
        set('op-plan-bf-every', plan.bf.everyRounds);
        // The fields are the session's (loadFields), and a list already
        // built outranks the last run's positions. A session that has none
        // takes the plan's, and keeps them from now on.
        if (!_bfPins.length) {
            _bfPins = plan.bf.position === 'here' ? (plan.bf.pins || []).map(p => ({ x: p.x, y: p.y })) : [];
            if (_bfPins.length) persistFields();
        }
        set('op-plan-bf-pos', _bfPins.length && plan.bf.position === 'here' ? 'here' : 'centroid');
        publishFields();
        set('op-plan-bf-exposure', plan.bf.exposureMs);
        set('op-plan-bf-light', plan.bf.light);
        // Not through set(): an absent brightness has to CLEAR the field, or
        // the last plan's 40 % is sent with this one.
        const led = $('op-plan-bf-led');
        if (led) led.value = plan.bf.ledPct != null ? plan.bf.ledPct : '';
        set('op-tl-stop', plan.stop.kind);
        set('op-tl-condval', plan.stop.value);
        set('op-tl-monitor', plan.monitoringMode || 'idle');
        // Every ending is written: an embryo the plan leaves alone is cleared
        // of the last plan's.
        _endings = {};
        plan.overrides.forEach(o => { _endings[o.embryoId] = { kind: o.kind, value: o.value }; });
        renderEndings();
    }

    /**
     * The session's last plan, back in the form. A resumed session used to
     * come back with the pane's defaults — five minutes, fifty slices, no
     * brightfield, manual — whatever it had been running.
     */
    async function restorePlan() {
        if (_planRestored) return;
        _planRestored = true;
        let d = null;
        try { d = await getJSON('/api/devices/timelapse/plan'); } catch (_) { return; }
        if (!d || !d.plan || _planDirty) return;
        await loadLaserPresets();
        fillPlan(AcquisitionPlan.fromStructure(d.plan));
        restoreWhatToRun(d.plan);
        const from = $('op-plan-from');
        if (from) {
            from.textContent = d.source === 'saved'
                ? 'The plan as this session last started it.'
                : 'The plan as read from this session\u2019s last run.';
            from.hidden = false;
        }
        renderPlan();
    }

    /**
     * "What to run" as the session last ran it: the set and the mode. The
     * pane used to come back on Single volume / All subjects whatever the
     * session had been doing — "not the ones i had selected for that session".
     */
    function restoreWhatToRun(plan) {
        const known = new Set(_embryos.map(e => e.id));
        const ids = (plan.embryo_ids || []).filter(id => known.has(id));
        if (plan.scope === 'selected' && ids.length) {
            _targets = ids.slice();
            _selected = ids[0];
            SharedState.set('selectedEmbryoIds', _targets.slice());
            SharedState.set('selectedEmbryoId', _selected);
            publishRoster(); renderSpimTarget(); renderCalTarget();
            setTargetScope('selected');
        } else {
            setTargetScope('all');
        }
        if (plan.mode === 'library' && plan.library_id) {
            _selectedLib = plan.library_id;
            setMode('library');
        } else {
            setMode('adaptive');
        }
    }

    function readPlan() {
        const v = id => { const el = $(id); return el ? el.value : undefined; };
        // Only of the embryos this run images: an ending set on one that is
        // then left out is kept on its row, and is not sent.
        const inRun = new Set(subjectIds());
        const overrides = Object.keys(_endings).filter(id => inRun.has(id))
            .map(id => ({ embryoId: id, kind: _endings[id].kind, value: _endings[id].value }));
        const laserPowers = {};
        document.querySelectorAll('#op-plan-powers [data-plan-power]').forEach(inp => {
            laserPowers[inp.dataset.planPower] = inp.value;
        });
        return AcquisitionPlan.fromForm({
            laserPowers,
            interval: v('op-tl-interval'),
            intervalUnit: v('op-plan-unit'),
            // Absent from the page (an older template) is a volume run.
            volumes: !($('op-plan-spim') && !$('op-plan-spim').checked),
            bfLedPct: v('op-plan-bf-led'),
            slices: v('op-plan-slices'),
            exposureMs: v('op-plan-exposure'),
            laserConfig: v('op-plan-laser'),
            bf: !!($('op-plan-bf') && $('op-plan-bf').checked),
            bfEveryRounds: v('op-plan-bf-every'),
            bfPosition: v('op-plan-bf-pos'),
            bfPins: _bfPins,
            bfExposureMs: v('op-plan-bf-exposure'),
            bfLight: v('op-plan-bf-light'),
            stopKind: v('op-tl-stop'),
            stopValue: v('op-tl-condval'),
            overrides,
            monitoringMode: v('op-tl-monitor'),
        });
    }

    function stopOptions(selected, withDefault) {
        const kinds = AcquisitionPlan.STOP_KINDS;
        const opts = withDefault ? [`<option value="default"${selected === 'default' ? ' selected' : ''}>as the run</option>`] : [];
        Object.keys(kinds).forEach(k => {
            opts.push(`<option value="${k}"${selected === k ? ' selected' : ''}>${escapeHtml(kinds[k].label)}</option>`);
        });
        return opts.join('');
    }

    // How each embryo ends, where it is not as the run does: {id: {kind,
    // value}}. It was a row an embryo in the plan's form, so the form grew
    // with the roster, which is what pushed Start off the screen. It is a
    // cell on the embryo's own row in the table now (panels/roster.js draws
    // the row and asks here for the cell), and the form does not grow.
    let _endings = {};

    /** The ending cell of one embryo's row in the Acquisition table. */
    function endingCell(emb) {
        if (!emb || emb.role === 'calibration') return '';
        const c = _endings[emb.id] || { kind: 'default', value: '' };
        const needs = (AcquisitionPlan.STOP_KINDS[c.kind] || {}).needs;
        // An embryo's own ending is the ending of its volumes.
        const volumes = !($('op-plan-spim') && !$('op-plan-spim').checked);
        const who = `embryo ${labelFor(emb)}`;
        return `<select class="op-sel rp-end" data-ending="kind" aria-label="How ${escapeHtml(who)} ends"${volumes ? '' : ' disabled'}>` +
            `${stopOptions(c.kind, true)}</select>` +
            (needs ? `<input class="op-numbox rp-end-n" type="number" min="1" data-ending="value" ` +
                `value="${escapeHtml(c.value == null ? '' : c.value)}" ` +
                `aria-label="${needs === 'count' ? 'After how many timepoints' : 'After how many hours'}, ${escapeHtml(who)}">` : '');
    }

    /** A change in an ending cell: the select, or the number beside it. */
    function setEnding(id, control) {
        if (!id || !control) return;
        const cur = _endings[id] || { kind: 'default', value: '' };
        if (control.dataset.ending === 'kind') cur.kind = control.value;
        else cur.value = control.value;
        if (cur.kind === 'default') delete _endings[id];
        else _endings[id] = cur;
        planTouched();
        // The number box comes and goes with the kind; a typed number must
        // not redraw the box it is being typed in.
        if (control.dataset.ending === 'kind') renderEndings();
        renderPlan();
    }

    /** The table's ending cells, and what the plan says of them. */
    function renderEndings() {
        if (typeof RosterPanel !== 'undefined' && RosterPanel.render) RosterPanel.render();
        // How many the run images, beside how many there are: it follows a
        // role and the scope alike, so it is said where both redraw.
        const inrun = $('op-roster-inrun');
        if (inrun) inrun.textContent = _embryos.length ? `· ${subjectIds().length} in the run` : '';
        const say = $('op-plan-ends-say');
        if (!say) return;
        const ids = new Set(subjectIds());
        const own = _embryos.filter(e => ids.has(e.id) && _endings[e.id]);
        const volumes = !($('op-plan-spim') && !$('op-plan-spim').checked);
        say.hidden = !volumes;
        say.textContent = !own.length
            ? 'Every embryo ends with the run. One embryo\'s own ending is on its row, on the left.'
            : `${own.length} embryo${own.length === 1 ? ' ends' : 's end'} on ${own.length === 1 ? 'its' : 'their'} own: ` +
                own.map(e => `${labelFor(e)} ${AcquisitionPlan.stopWords(_endings[e.id].kind, _endings[e.id].value)}`).join(', ') +
                '. Set on the row, on the left.';
    }

    /** Is this embryo imaged by the run as it stands? For the table's dimming. */
    function inRun(emb) {
        return !!emb && subjectIds().includes(emb.id);
    }

    function renderPlan() {
        const say = $('op-plan-say');
        if (!say) return;
        renderPowerRows();
        syncPlanFromEmbryos();
        let plan = readPlan();
        const volumes = plan.spim.enabled !== false;
        renderChannels(volumes);
        // The endings on offer follow the channels, so re-read: an ending
        // the run can no longer have has just been taken off the select.
        plan = readPlan();
        const condval = $('op-tl-condval');
        if (condval) condval.hidden = !(AcquisitionPlan.STOP_KINDS[plan.stop.kind] || {}).needs;
        const bfBody = $('op-plan-bf-body');
        if (bfBody) bfBody.hidden = !plan.bf.enabled;
        const ledField = $('op-plan-bf-led-field');
        if (ledField) ledField.hidden = plan.bf.light !== 'led';
        // The "here" option carries the list's size, so the select reads as
        // a fact: "the 2 fields in the list", not a promise.
        const posSel = $('op-plan-bf-pos');
        if (posSel) {
            const n = _bfPins.length;
            const opt = [...posSel.options].find(o => o.value === 'here');
            if (opt) opt.textContent = n ? `the ${n} field${n === 1 ? '' : 's'} in the list` : 'the fields list (none yet — adds where the stage is)';
        }
        const pin = $('op-plan-bf-pin');
        if (pin) {
            const here = plan.bf.position === 'here';
            pin.hidden = !here;
            const n = _bfPins.length;
            // A list changed under a run is the NEXT run's: the orchestrator
            // read its positions at Start, and says so rather than implying
            // the frames move tonight.
            const later = _runBusy ? ' A change here applies at the next Start, not to the run going now.' : '';
            pin.textContent = !here ? ''
                : n === 0 ? 'No fields yet — add them on Scope, beside the picture, or from the list on the left.'
                    : (n === 1 ? 'One frame each round, from field 1.' : `${n} frames each round, one from each field.`)
                        + ' Add or drop fields in the list on the left, or on Scope.' + later;
        }
        // How the frame is lit and exposed, and whether its dark and flat
        // exist, are set on Scope (the rail's Overview frames box, beside
        // the bottom camera's picture); said back here with the way there.
        const setup = $('op-plan-bf-setup');
        const ovSummary = $('op-ov-summary');
        if (setup || ovSummary) {
            const lit = plan.bf.light === 'led' ? `LED${plan.bf.ledPct != null ? ` ${plan.bf.ledPct} %` : ''}`
                : plan.bf.light === 'room' ? 'room light' : 'light as it is';
            const exp = plan.bf.exposureMs != null ? `${plan.bf.exposureMs} ms` : "the camera's exposure";
            const refs = typeof BrightfieldRefs !== 'undefined' && BrightfieldRefs.status ? BrightfieldRefs.status() : null;
            const refTxt = !refs ? '' : refs.have ? ' · dark and flat taken'
                : ' · <span class="op-cap-warn">no dark and flat yet</span>';
            const said = `${escapeHtml(lit)} · ${escapeHtml(exp)}${refTxt}`;
            // The same fact in both places: the Overview frames box's
            // closed state, and the Acquisition pane's line with the way there.
            if (ovSummary) ovSummary.innerHTML = said;
            if (setup) {
                setup.innerHTML = `<span>${said}</span>`
                    + '<button type="button" class="op-btn op-btn-quiet" data-goto-pane="bottom" '
                    + 'title="The light, exposure, dark and flat are set beside the live view">Change on Scope →</button>';
            }
        }
        say.textContent = AcquisitionPlan.describe(plan, planSubjects());
        // What is wrong with the plan is a line under the sentence now, with
        // its fix, not a tooltip on a sentence turned amber. The sentence
        // stays the plan and nothing more.
        say.dataset.bad = '0';
        say.title = '';
        renderEndings();
        renderPlanName();
        renderPreflight(plan);
        renderSingle();
        renderTiles();
    }

    // ══ BEFORE IT STARTS ══════════════════════════════════════════════════
    // What stands in the way of the run, between the sentence and Start
    // (run-preflight.js). The page knew every embryo was uncalibrated and
    // said so only as a 409 after the press; it knew the cadence and the
    // slices and never said that a night at the form's default is 576 GB.
    // Derived on every renderPlan from what has already been read. The one
    // thing asked of the server for it is the disk's free room.
    let _room = null;           // {free_bytes} as last read; null is unread
    let _preflight = [];        // the lines as last drawn, for Start to count

    async function readRoom() {
        try { _room = await getJSON('/api/devices/timelapse/room'); } catch (_) { _room = null; }
        if (_pane === 'acquire') renderPreflight();
    }

    /** Everything the lines are derived from, gathered from what the page holds. */
    function preflightContext(plan) {
        const ids = new Set(subjectIds());
        const targets = _embryos.filter(e => ids.has(e.id));
        const volumes = plan.spim.enabled !== false;
        const held = key => { const h = heldAcross(targets, key); return h ? h.max : null; };
        const light = SharedState.get('light') || {};
        const powers = {};
        Object.entries(light.power || {}).forEach(([wl, pct]) => { if (pct != null) powers[wl] = pct; });
        // An unread preset is not a dark one: no line is claimed either way.
        const routed = light.config && typeof LightPanel !== 'undefined' && LightPanel.wavelengthsOf
            ? LightPanel.wavelengthsOf(light.config) : null;
        const refs = typeof BrightfieldRefs !== 'undefined' && BrightfieldRefs.status ? BrightfieldRefs.status() : null;
        // "No embryos to image" has two causes with two fixes; say which.
        let problems = AcquisitionPlan.validate(plan, [...ids], _laserLimits);
        if (volumes && !ids.size) {
            problems = problems.filter(q => !/^No embryos/.test(q));
            problems.unshift(!_embryos.length ? 'No embryos yet: detect on the bottom camera, then register.'
                : _targetScope === 'selected' ? 'No subject is selected.'
                    : 'Every embryo is marked as a reference: make at least one a subject.');
        }
        return {
            plan,
            est: RunPreflight.estimate(plan, targets.length,
                { slices: held('num_slices'), exposureMs: held('exposure_ms') }),
            subjects: targets.map(e => ({
                id: e.id, label: labelFor(e), calibrated: hasFit(e), r2: hasFit(e) ? fitScore(e) : null })),
            references: _embryos.filter(e => e.role === 'calibration').length,
            notSelected: _targetScope === 'selected' ? Math.max(0, allSubjectIds().length - ids.size) : 0,
            problems,
            routed, powers, limits: _laserLimits,
            head: fd.pos() != null ? { um: fd.pos(), gotoMin: gotoLimits().lo } : null,
            freeBytes: _room && _room.free_bytes != null ? Number(_room.free_bytes) : null,
            refs,
            lowR2: LOW_CONFIDENCE_R2,
        };
    }

    /**
     * Redraw a list a line at a time, leaving alone the lines that still say
     * what they said.
     *
     * A press on a line's button starts on one node and has to end on the
     * same one. Typing a cadence and then pressing "Calibrate the 3" blurs
     * the field; the blur is a change; the change re-says the plan; and a
     * list replaced whole between the press and the release swallows the
     * press. Found in the browser: the button did nothing, every time, when
     * it was the first thing pressed after typing. It also keeps the focus
     * of someone who tabbed onto a fix while the light was being re-read.
     */
    function patchLines(host, html, opts) {
        const had = host._lines || [];
        const held = opts && opts.keepFocused ? document.activeElement : null;
        html.forEach((h, i) => {
            if (had[i] === h && host.children[i]) return;
            // A select being chosen from, or a number being typed: the line
            // waits for the next redraw rather than close under the hand.
            if (held && host.children[i] && host.children[i].contains(held)
                && /^(SELECT|INPUT)$/.test(held.tagName)) { html[i] = had[i]; return; }
            const t = document.createElement('template');
            t.innerHTML = h;
            const el = t.content.firstElementChild;
            if (host.children[i]) host.replaceChild(el, host.children[i]);
            else host.appendChild(el);
        });
        while (host.children.length > html.length) host.lastElementChild.remove();
        host._lines = html.slice();
    }

    const PREFLIGHT_MARK = { ok: '✓', warn: '!', no: '✕' };
    const PREFLIGHT_SAID = { ok: '', warn: 'Worth knowing: ', no: 'In the way: ' };

    /**
     * The lines, drawn. `plan` is passed by renderPlan, which has just read
     * the form; anything else that changes what the lines are derived from
     * (the light, the head, the disk) calls with none and the form is read.
     */
    function renderPreflight(plan) {
        const host = $('op-preflight');
        if (!host) return;
        if (_mode !== 'adaptive') {
            // A tactic runs as it was saved: this form, and so its lines,
            // do not apply to it.
            _preflight = [];
            host.hidden = false;
            patchLines(host, ['<div class="op-pf-line is-ok" role="listitem"><span class="op-pf-mark" aria-hidden="true">·</span>' +
                '<span class="op-pf-says">A saved tactic runs as it was saved. The form on the left is not what Start will run; ' +
                'shut the Saved list to go back to it.</span></div>']);
            const keptEl = $('op-plan-kept');
            if (keptEl) keptEl.textContent = '';
            renderRunButton();
            return;
        }
        const ctx = preflightContext(plan || readPlan());
        _preflight = RunPreflight.lines(ctx);
        host.hidden = false;
        // The mark is decoration; what kind of line it is, is said in words
        // for a reader that does not see it.
        patchLines(host, _preflight.map(l =>
            `<div class="op-pf-line is-${l.kind}" role="listitem">` +
            `<span class="op-pf-mark" aria-hidden="true">${PREFLIGHT_MARK[l.kind]}</span>` +
            `<span class="op-pf-says"><span class="op-pf-kind">${PREFLIGHT_SAID[l.kind]}</span>${escapeHtml(l.text)}` +
            (l.fix || []).map(f => ` <button type="button" class="op-btn op-btn-quiet op-pf-fix" ` +
                `data-preflight-fix="${escapeHtml(f.action)}">${escapeHtml(f.label)}</button>`).join('') +
            '</span></div>'));
        const kept = $('op-plan-kept');
        if (kept) kept.textContent = RunPreflight.keptWords(ctx.est);
        renderRunButton();
    }

    /** The way past a line: each fix is one press, and says what it did. */
    function preflightFix(action) {
        const ids = new Set(subjectIds());
        const subs = _embryos.filter(e => ids.has(e.id));
        if (action === 'calibrate') {
            // The instrument is pointed at the first embryo with no fit. The
            // set a run images is left as it is: this is not a narrowing.
            const first = subs.find(e => !hasFit(e));
            if (first && _targets.includes(first.id)) {
                _selected = first.id;
                SharedState.set('selectedEmbryoId', _selected);
                publishRoster(); renderSpimTarget(); renderCalTarget(); renderSingle();
            } else if (first) {
                selectEmbryo(first.id);
            }
            showPane('cal');
        } else if (action === 'without') {
            const keep = subs.filter(hasFit).map(e => e.id);
            if (!keep.length) return;
            _targets = keep.slice();
            if (!keep.includes(_selected)) _selected = keep[0];
            SharedState.set('selectedEmbryoIds', _targets.slice());
            SharedState.set('selectedEmbryoId', _selected);
            publishRoster(); renderSpimTarget(); renderCalTarget();
            setTargetScope('selected');
            renderPlan();
            toast(`The run is the ${keep.length} calibrated embryo${keep.length === 1 ? '' : 's'}`);
        } else if (action === 'head') {
            const lo = gotoLimits().lo;
            if (lo != null) headTo(lo);
        } else if (action === 'overview') {
            showPane('bottom');
        }
    }

    /**
     * A power field for each line the chosen preset routes.
     *
     * Redrawn only when the set of lines changes, so typing in one is never
     * interrupted, and a value typed for a line survives a change of preset
     * that still routes it. The bounds are the device layer's; the field is
     * not clamped to them, because a number silently changed under the
     * operator's hand is worse than one the plan refuses by name.
     */
    function renderPowerRows() {
        const host = $('op-plan-powers');
        if (!host) return;
        const lines = AcquisitionPlan.linesOf(($('op-plan-laser') || {}).value);
        const key = lines.join(',') + '|' + (_laserLimits ? 'l' : '');
        if (host.dataset.lines === key) return;
        const typed = {};
        host.querySelectorAll('[data-plan-power]').forEach(inp => {
            typed[inp.dataset.planPower] = inp.value;
        });
        host.dataset.lines = key;
        host.innerHTML = lines.map(wl => {
            const lim = (_laserLimits && _laserLimits[wl]) || null;
            const range = lim ? `${lim.min}–${lim.max}` : '';
            // The label is the line's number alone: a label is uppercased,
            // and "405 nm" came out "405 NM".
            return `<div class="op-row op-plan-line"><label class="op-label" for="op-plan-power-${wl}" ` +
                `title="The ${wl} nm line">${wl}</label>` +
                `<input class="op-numbox op-numbox-wide" id="op-plan-power-${wl}" data-plan-power="${wl}" ` +
                `type="number" step="0.1"${lim ? ` min="${lim.min}" max="${lim.max}"` : ''} ` +
                `value="${escapeHtml(typed[wl] || '')}" placeholder="as it is" ` +
                `aria-label="${wl} nm power, percent"><span class="op-unit">%</span>` +
                `<span class="op-ext" title="The limits this line's power is held to on this rig">${range}</span></div>`;
        }).join('');
    }

    /**
     * What the form offers, given whether the run takes volumes.
     *
     * Without them the overview is the run: its box is ticked and cannot be
     * unticked, "every N rounds" goes (a round is a frame), and so does
     * everything that is about volumes — per-embryo endings, stage-watching,
     * and the endings read from a stage.
     */
    let _planWasVolumes = true;
    function renderChannels(volumes) {
        const show = (id, on) => { const el = $(id); if (el) el.hidden = !on; };
        show('op-plan-spim-body', volumes);
        show('op-plan-bf-every-field', volumes);
        show('op-plan-watch-sec', volumes);
        show('op-plan-watch-field', volumes);
        const cap = $('op-plan-spim-cap');
        if (cap) cap.textContent = volumes ? 'every embryo, every round' : 'off — a brightfield run';
        const name = $('op-plan-bf-name');
        if (name) name.textContent = volumes ? 'Brightfield overview' : 'Brightfield';
        const bf = $('op-plan-bf');
        if (bf) {
            if (!volumes) bf.checked = true;
            bf.disabled = !volumes;
        }
        // On the way INTO a brightfield run, once: the LED is what it is lit
        // by. Afterwards the select is the operator's, room light included.
        if (!volumes && _planWasVolumes) {
            const light = $('op-plan-bf-light');
            if (light && light.value === 'room') light.value = 'led';
        }
        _planWasVolumes = volumes;
        const stop = $('op-tl-stop');
        if (stop) {
            const ok = k => volumes || AcquisitionPlan.BRIGHTFIELD_STOPS.includes(k);
            [...stop.options].forEach(o => { o.hidden = !ok(o.value); o.disabled = !ok(o.value); });
            if (!ok(stop.value)) stop.value = 'manual';
        }
    }

    async function loadLaserPresets() {
        if (_laserPresetsLoaded) return;
        const sel = $('op-plan-laser');
        if (!sel) return;
        try {
            const d = await getJSON('/api/devices/laser/configs');
            const configs = (d && d.configs) || [];
            const current = d && d.current && d.current !== 'unknown' ? d.current : '';
            sel.innerHTML = `<option value="">current preset${current ? ` (${escapeHtml(current)})` : ''}</option>` +
                configs.map(c => `<option value="${escapeHtml(c)}">${escapeHtml(c)}</option>`).join('');
            _laserPresetsLoaded = true;
        } catch (_) { /* offline: "current preset" stands */ }
        // Class constants on the server, so this answers with the device
        // layer down. Separate from the presets: either can fail alone.
        try {
            const d = await getJSON('/api/devices/laser/limits');
            if (d && d.limits) { _laserLimits = d.limits; renderPlan(); }
        } catch (_) { /* the start route still refuses what the hardware would */ }
    }

    /** The plan as a template, under a name the operator gives it. */
    async function savePlan() {
        const plan = readPlan();
        const problems = AcquisitionPlan.validate(plan, subjectIds().length ? subjectIds() : ['_']);
        const real = problems.filter(p => !/No embryos/.test(p));
        if (real.length) { toastFail(real[0]); return; }
        const name = window.prompt('Save this plan as…', '');
        if (!name || !name.trim()) return;
        try {
            const d = await postJSON('/api/tactic_library', {
                name: name.trim(),
                kind: 'standing_timelapse',
                structure: AcquisitionPlan.toStructure(plan),
                scope: { mode: 'global' },
                rationale: AcquisitionPlan.describe(plan, planSubjects()),
                source: 'operate',
            });
            toast(`Saved “${d.name || name.trim()}”. Load brings it back.`);
            const box = $('op-panel-library');
            if (box && !box.hidden) loadLibrary();
        } catch (e) { toastFail(`Save failed (${why(e)})`); }
    }

    /**
     * Start lands on the run. The sentence the operator pressed Start on
     * heads the Running column, and the column is brought into view; the
     * run rows underneath it come from the timelapse status (next PR).
     */
    function landOnRun(sentence) {
        const head = $('op-run-plan');
        if (head) { head.textContent = sentence; head.hidden = false; }
        setAcqView('watch');
        renderRun();
    }

    // ══ TWO STATES ════════════════════════════════════════════════════════
    // Designing a run and watching one never happen at once, so the surface
    // is one or the other, each with the whole page (`data-acq` on the pane;
    // the template says which parts belong to which). The state follows the
    // run. With none going the operator may look back at the last one, or
    // plan another, and that is the only time it is theirs to choose.
    let _acqView = 'design';
    let _runGoing = false;      // running, paused, or there to be carried on

    function setAcqView(view) {
        _acqView = view === 'watch' ? 'watch' : 'design';
        const pane = $('op-pane-acquire');
        if (pane) pane.dataset.acq = _acqView;
        renderTiles();
    }

    // ══ THE PICTURES ══════════════════════════════════════════════════════
    // Each embryo's latest volume, as its saved projection: one tile each,
    // as large as the room allows. Before a run they are what a test volume
    // took; during one they are what the run is seeing. The Embryos tab is
    // the deep monitor (every timepoint, the film, the stage calls); this is
    // the shallow one, beside the controls.
    let _runRows = {};          // the run's rows as last read, by embryo id
    let _runBrightfield = false;    // the run takes no volumes
    let _runOverview = false;       // the run takes overview frames
    let _tilesKind = 'volumes';     // which pictures, where there are both
    let _bfFrames = [];             // the session's overview frames, as last listed
    let _bfFramesAt = 0;

    /** Which pictures the zone shows, and whether there is a choice. */
    function picturesKind() {
        const watching = _acqView === 'watch';
        const plan = watching ? null : readPlan();
        const volumes = watching ? !_runBrightfield : plan.spim.enabled !== false;
        const overview = watching ? _runOverview : !!plan.bf.enabled;
        return { volumes, overview, kind: !volumes ? 'overview' : !overview ? 'volumes' : _tilesKind };
    }

    /** The overview's frames, listed at most every few seconds. */
    async function readOverviewFrames() {
        if (Date.now() - _bfFramesAt < 4000) return;
        _bfFramesAt = Date.now();
        try {
            const d = await getJSON('/api/bf/frames');
            _bfFrames = (d && Array.isArray(d.frames)) ? d.frames : [];
        } catch (_) { /* the frames already listed stand */ }
        if (_pane === 'acquire') renderTiles();
    }

    /** The newest round of overview frames: one a field. */
    function overviewTiles() {
        if (!_bfFrames.length) return [];
        const last = _bfFrames[_bfFrames.length - 1];
        const perRound = Math.max(1, Number(last.fields) || 1);
        return _bfFrames.slice(-perRound).map((f, i) => {
            const at = f.captured_at ? new Date(f.captured_at) : null;
            const when = at && !isNaN(at) ? at.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : '';
            const field = perRound > 1 ? `field ${Number(f.field) > 0 ? f.field : i + 1}` : 'overview';
            return {
                id: `bf:${f.stem}`, label: field,
                src: `${f.url}?max=1200`,
                said: [`frame ${f.frame != null ? f.frame : _bfFrames.length - perRound + i + 1}`, when].filter(Boolean).join(' · '),
            };
        });
    }

    function tilesModel() {
        const sid = SharedState.get('sessionId');
        const watching = _acqView === 'watch';
        const ids = watching && Object.keys(_runRows).length ? Object.keys(_runRows) : subjectIds();
        return ids.map(id => {
            const emb = _embryos.find(e => e.id === id);
            const row = _runRows[id] || {};
            const t = Math.max(Number(row.timepoints) || 0, Number(emb && emb.timepoints_acquired) || 0);
            const due = row.next_due_at ? (new Date(row.next_due_at) - Date.now()) / 1000 : null;
            return {
                id, label: emb ? labelFor(emb) : id, t,
                src: sid && t > 0 ? `/api/sessions/${encodeURIComponent(sid)}/projection?embryo=${encodeURIComponent(id)}&t=${t}` : null,
                fit: !!emb && hasFit(emb),
                // Due and not done: it is being imaged, or is next.
                now: watching && _runBusy && !row.is_complete && due != null && due <= 0,
                done: !!row.is_complete,
                said: row.is_complete ? (row.completion_reason || 'done') : '',
            };
        });
    }

    function renderTiles() {
        const host = $('op-tiles');
        if (!host) return;
        const watching = _acqView === 'watch';
        const pics = picturesKind();
        const kindSeg = $('op-tiles-kind');
        if (kindSeg) {
            kindSeg.hidden = !(pics.volumes && pics.overview);
            kindSeg.querySelectorAll('[data-kind]').forEach(b => {
                const on = b.dataset.kind === pics.kind;
                b.classList.toggle('is-on', on);
                b.setAttribute('aria-pressed', String(on));
            });
        }
        const say = $('op-tiles-say');
        if (pics.kind === 'overview') {
            readOverviewFrames();
            const frames = overviewTiles();
            if (say) { say.textContent = 'The overview\'s latest frames'; say.title = ''; }
            host.dataset.kind = 'overview';
            patchLines(host, frames.length ? frames.map(t =>
                `<button type="button" class="op-tile op-tile-bf" data-tile-frame="${escapeHtml(t.id)}" title="${escapeHtml(t.label)}, ${escapeHtml(t.said)}">` +
                `<img loading="lazy" decoding="async" src="${escapeHtml(t.src)}" alt="The overview, ${escapeHtml(t.label)}, ${escapeHtml(t.said)}">` +
                `<span class="op-tile-id">${escapeHtml(t.label)}</span><span class="op-tile-say">${escapeHtml(t.said)}</span></button>`)
                : ['<div class="op-empty op-tiles-empty">No overview frame yet. The first is taken when the run starts.</div>']);
            fitTiles();
            return;
        }
        host.dataset.kind = 'volumes';
        const tiles = tilesModel();
        if (say) {
            say.textContent = !tiles.length ? ''
                : watching ? 'Each embryo\'s latest volume, as it lands'
                    : 'Each embryo\'s latest volume';
            say.title = watching ? '' : 'A test volume is taken with this plan\'s slices and exposure, and kept as the embryo\'s next timepoint.';
        }
        if (!tiles.length) {
            patchLines(host, ['<div class="op-empty op-tiles-empty">No embryos in the run.</div>']);
            return;
        }
        patchLines(host, tiles.map(t => {
            const cls = (t.id === _selected ? ' is-sel' : '') + (t.now ? ' is-now' : '') + (t.src ? '' : ' is-none') + (t.done ? ' is-done' : '');
            const said = t.now ? `imaging t${t.t + 1}…`
                : t.src ? `t${t.t}${t.said ? ` · ${t.said}` : ''}`
                    : t.fit || watching ? 'no volume yet' : 'needs a fit first';
            return `<button type="button" class="op-tile${cls}" data-tile="${escapeHtml(t.id)}" ` +
                `title="Embryo ${escapeHtml(t.label)}${t.src ? `, timepoint ${t.t}` : ''}">` +
                (t.src ? `<img loading="lazy" decoding="async" src="${escapeHtml(t.src)}" alt="Embryo ${escapeHtml(t.label)}, timepoint ${t.t}">` : '') +
                `<span class="op-tile-id">${escapeHtml(t.label)}</span><span class="op-tile-say">${escapeHtml(said)}</span></button>`;
        }));
        fitTiles();
    }

    /**
     * As many tiles across as makes them largest in the room there is,
     * without scrolling where that is possible. A projection is 1024 × 630.
     */
    function fitTiles() {
        const host = $('op-tiles');
        if (!host) return;
        const n = host.querySelectorAll('.op-tile').length;
        // The box, not what is left of it beside a scrollbar: asking the
        // room inside a scrollbar for the size that needs no scrollbar goes
        // round in a circle, and ends with a scrollbar and nothing to scroll.
        const W = host.offsetWidth, H = host.offsetHeight;
        if (!n || !W || !H) return;
        // A projection is 1024 × 630; a frame of the bottom camera is square.
        const gap = 8, ar = host.dataset.kind === 'overview' ? 1 : 1024 / 630, smallest = 132;
        let best = 1, bestW = 0;
        for (let across = 1; across <= n; across++) {
            const rows = Math.ceil(n / across);
            // As wide as the row allows, and no taller than the rows allow.
            const w = Math.min((W - (across - 1) * gap) / across, ar * (H - (rows - 1) * gap) / rows);
            if (w > bestW) { best = across; bestW = w; }
        }
        if (bestW >= smallest) {
            host.style.setProperty('--across', String(best));
            host.style.setProperty('--tile-w', `${Math.floor(bestW)}px`);
            host.style.overflowY = 'hidden';
        } else {
            // Too many for the room at a size worth looking at: they scroll.
            host.style.setProperty('--across', String(Math.max(1, Math.floor((W - 10 + gap) / (smallest + gap)))));
            host.style.setProperty('--tile-w', '1fr');
            host.style.overflowY = 'auto';
        }
    }

    /** A tile pressed: the instrument is pointed at that embryo. The set a
     *  run images is left as it is. */
    function pointAt(id) {
        if (!id || !_embryos.some(e => e.id === id)) return;
        if (_targets.includes(id)) {
            _selected = id;
            SharedState.set('selectedEmbryoId', _selected);
            publishRoster(); renderSpimTarget(); renderCalTarget(); renderSingle(); renderTiles();
        } else {
            selectEmbryo(id);
        }
    }

    // ══ THE RUN ═══════════════════════════════════════════════════════════════
    // Start lands here, and this is where the run is watched and steered:
    // embryo by embryo, because the acquisition is — each embryo has its own
    // clock, its own ending, and can be stopped on its own.
    let _runPoll = null;
    let _runRenderTimer = null;

    function scheduleRenderRun() {
        clearTimeout(_runRenderTimer);
        _runRenderTimer = setTimeout(renderRun, 250);
    }

    function fmtWhen(seconds) {
        if (seconds == null || !Number.isFinite(seconds)) return '—';
        if (seconds < 1) return 'now';
        if (seconds < 90) return `${Math.round(seconds)} s`;
        const m = Math.round(seconds / 60);
        return m < 90 ? `${m} min` : `${(seconds / 3600).toFixed(1)} h`;
    }

    function runRow(id, r, live) {
        const emb = _embryos.find(e => e.id === id);
        const label = emb ? labelFor(emb) : id;
        const due = r.next_due_at ? (new Date(r.next_due_at) - Date.now()) / 1000 : null;
        // A restored run is not running: its rows used to say "running ·
        // next now" with a Stop each, over a loop that no longer existed.
        const state = r.is_complete ? (r.completion_reason || 'done')
            : r.should_skip ? 'skipped'
            : !live ? 'waiting'
            : r.cadence_phase === 'paused' ? 'paused'
            : r.last_error ? 'error' : 'running';
        const cls = r.is_complete ? 'is-done' : r.last_error ? 'is-error' : live ? 'is-live' : 'is-waiting';
        const ending = r.stop_condition || 'manual';
        // The table's row, with the run's columns: who, its timepoint, when
        // it is next due, its ending, Stop. Under them, what its next
        // acquisition uses (the agent changes these per embryo, and this is
        // where that shows against the embryo it was made on).
        const next = r.is_complete || !live ? state
            : state !== 'running' ? state : `next ${fmtWhen(due)}`;
        const every = r.interval_seconds != null ? `every ${AcquisitionPlan.intervalWords(r.interval_seconds)}` : '';
        const more = [every, paramsWords(r)].filter(Boolean).join(' · ');
        return `<div class="op-runrow ${cls}" data-run-id="${escapeHtml(id)}">` +
            `<span class="op-runrow-who" title="Embryo ${escapeHtml(label)}">${escapeHtml(label)}</span>` +
            `<span class="op-runrow-n">t${r.timepoints}</span>` +
            `<span class="op-runrow-next">${escapeHtml(next)}</span>` +
            (r.is_complete || !live ? '<span></span><span></span>' :
                `<select class="op-sel op-runrow-stop" data-run-stop="${escapeHtml(id)}" title="How this embryo ends" ` +
                    `aria-label="How embryo ${escapeHtml(label)} ends">` + runStopOptions(ending) + '</select>' +
                `<button class="op-nbtn op-runrow-halt" type="button" data-run-halt="${escapeHtml(id)}" ` +
                    `title="Stop this embryo; the rest carry on" aria-label="Stop embryo ${escapeHtml(label)}">Stop</button>`) +
            `<span class="op-runrow-params" title="${escapeHtml(paramsTitle(r))}">${escapeHtml(more)}</span>` +
            '</div>';
    }

    /**
     * What this embryo's next acquisition uses, from the status row. The
     * agent changes these per embryo (`modify_parameters`), so this is the
     * one place its change is shown against the embryo it was made on.
     */
    function paramsWords(r) {
        if (r.acquisition_mode === 'snap') return `snap · ${r.exposure_ms} ms`;
        const bits = [];
        if (r.num_slices != null) bits.push(`${r.num_slices} sl`);
        if (r.exposure_ms != null) bits.push(`${r.exposure_ms} ms`);
        Object.entries(r.laser_powers || {}).forEach(([wl, pct]) => bits.push(`${wl}@${pct}%`));
        return bits.join(' · ');
    }

    /** Who set what — the provenance, for the hover. */
    function paramsTitle(r) {
        const by = r.set_by || {};
        const said = Object.keys(by).map(k => `${k}: set by ${by[k]}`);
        return said.length ? said.join('\n') : 'as registered';
    }

    /** The ending select for a running embryo, preselecting what it has. */
    function runStopOptions(spec) {
        const kinds = AcquisitionPlan.STOP_KINDS;
        const kind = String(spec).split(':')[0].replace(/\+\d+$/, '');
        return Object.keys(kinds).map(k =>
            `<option value="${k}"${k === kind ? ' selected' : ''}>${escapeHtml(kinds[k].label)}</option>`).join('') +
            (kinds[kind] ? '' : `<option value="${escapeHtml(spec)}" selected>${escapeHtml(spec)}</option>`);
    }

    async function renderRun() {
        const host = $('op-runspine'), actions = $('op-run-actions');
        if (!host) return;
        let st = null;
        try { st = await getJSON('/api/devices/timelapse/status'); } catch (_) { st = null; }
        let tactics = [];
        try {
            const d = await getJSON('/api/operation_plan');
            tactics = (d && d.plan && d.plan.tactics) || [];
        } catch (_) { /* leave empty */ }

        const running = st && (st.status === 'running' || st.status === 'paused');
        const wasBusy = _runBusy;
        _runBusy = !!running;
        renderRunButton();
        // Whether a run is going decides whether a draft in the SPIM fields
        // gets an Apply button; the plan line has to hear when that changes.
        if (wasBusy !== _runBusy && _pane === 'acquire') renderPlan();
        const rows = (st && st.embryos) || {};
        const ids = Object.keys(rows);
        _runRows = rows;
        const live = tactics.filter(t => t.state === 'active' || t.state === 'paused');
        // A run restored from its checkpoint after a restart: idle, embryos
        // still going. The one button it needs is Resume — the same route a
        // paused run resumes through, which carries this one on instead.
        const resumable = !!(st && st.resumable) && !running;
        if (actions) actions.hidden = !running && live.length === 0 && !resumable;
        _runPaused = running ? st.status === 'paused' : (resumable || live.some(t => t.state === 'paused'));
        const p = $('op-run-pause');
        if (p) p.textContent = _runPaused ? (resumable ? 'Resume run' : 'Resume') : 'Pause';
        const stopb = $('op-run-stop');
        if (stopb) stopb.hidden = !running && live.length === 0;

        // The surface follows the run: going, it watches; ended, the form is
        // back. Only the change moves it, so with no run going the operator's
        // own choice (look back, or plan another) is left alone.
        // A run somebody stopped is one they are done with, so the form is
        // back, with the way to look at it (and carry it on) under Start. One
        // that was interrupted is still the business in hand.
        const going = !!running || live.length > 0 || (resumable && st.ended !== 'stopped');
        if (going !== _runGoing) { _runGoing = going; setAcqView(going ? 'watch' : 'design'); }
        const anything = ids.length > 0 || tactics.length > 0;
        _runBrightfield = !!(st && st.volumes === false && st.bf);
        _runOverview = !!(st && st.bf);
        const fresh = $('op-acq-new');
        if (fresh) fresh.hidden = !!running;
        const back = $('op-acq-show-run');
        if (back) {
            back.hidden = going || !anything;
            back.textContent = st && st.ended ? `The last run (${st.ended}) →` : 'The last run →';
        }
        const stateEl = $('op-run-state');
        if (stateEl) {
            stateEl.textContent = running ? st.status
                : resumable ? (st.ended === 'stopped' ? 'stopped' : 'interrupted')
                    : (st && st.ended) || '';
        }

        const parts = [];
        // A brightfield run has no embryo rows to be seen by.
        const brightfield = !!(st && st.volumes === false && st.bf);
        if (running || ids.length || (brightfield && (resumable || st.bf.frames))) {
            // Idle with embryos still going is one of two things. A run
            // somebody stopped is not one that was interrupted.
            const idle = st.ended === 'stopped'
                ? 'stopped — Resume run carries it on'
                : 'interrupted — press Resume run to carry on';
            const bits = [resumable ? idle : (st.ended && !running ? st.ended : st.status)];
            if (brightfield) {
                const n = st.bf.frames || 0;
                bits.push('brightfield, no SPIM volumes');
                bits.push(`${n} frame${n === 1 ? '' : 's'}`);
            } else if (st.current_round != null && st.current_round >= 0) {
                bits.push(`${st.total_timepoints || 0} volumes`);
            }
            if (st.seconds_until_next_round != null) bits.push(`next ${fmtWhen(st.seconds_until_next_round)}`);
            if (st.duration_minutes) bits.push(`${Math.round(st.duration_minutes)} min in`);
            if (st.bf && !brightfield) {
                bits.push(`brightfield ${st.bf.frames || 0} frame${st.bf.frames === 1 ? '' : 's'}` +
                    (st.bf.seconds_until_next != null && running ? `, next ${fmtWhen(st.bf.seconds_until_next)}` : ''));
            }
            // The clock: what there is to wait for, large, then the rest.
            const clock = running && st.status === 'running' && st.seconds_until_next_round != null
                ? `<span class="op-run-clock">${escapeHtml(fmtWhen(st.seconds_until_next_round))}</span>` +
                  '<span class="op-run-clock-say">to the next round</span>'
                : '';
            parts.push(`<div class="op-run-clockrow">${clock}</div>` +
                `<div class="op-run-bits">${escapeHtml(bits.join(' · '))}</div>`);
        }
        const status = $('op-run-status');
        if (status) status.innerHTML = parts.join('');
        // The rows, one at a time: a row whose ending is being chosen is not
        // redrawn under the hand by the next poll.
        patchLines(host, ids.length ? ids.map(id => runRow(id, rows[id], running))
            : [`<div class="op-empty">${brightfield ? 'A brightfield run images no embryo.' : 'Nothing running.'}</div>`],
        { keepFocused: true });
        const tact = $('op-run-tactics');
        if (tact) tact.innerHTML = tactics.map(tacticCard).join('');
        const head = $('op-run-plan');
        if (head && !going) head.hidden = true;
        // Reloaded over a run: the sentence Start was pressed on is gone
        // with the page, but the form was filled from the session's own
        // plan and nobody has typed over it, so it says the same thing.
        if (head && going && head.hidden && _planRestored && !_planDirty && $('op-plan-say')) {
            head.textContent = AcquisitionPlan.describe(readPlan(), planSubjects());
            head.hidden = false;
        }
        const headBox = head && head.closest('.op-panel');
        if (headBox) headBox.hidden = head.hidden;
        if (_pane === 'acquire') renderTiles();
    }

    async function stopEmbryo(id) {
        const emb = _embryos.find(e => e.id === id);
        if (!window.confirm(`Stop imaging embryo ${emb ? labelFor(emb) : id}? The rest carry on.`)) return;
        try {
            await postJSON(`/api/devices/timelapse/embryo/${encodeURIComponent(id)}/stop`, { reason: 'operator' });
            toast(`Stopped embryo ${emb ? labelFor(emb) : id}`);
        } catch (e) { toastFail(`Stop failed (${why(e)})`); }
        renderRun();
    }

    async function changeEmbryoEnding(id, kind) {
        // A kind that needs a number asks for it here; the row is too small
        // to hold a second field for something set once in a night.
        const needs = (AcquisitionPlan.STOP_KINDS[kind] || {}).needs;
        let value = null;
        if (needs) {
            const ask = window.prompt(needs === 'count' ? 'Stop after how many timepoints?' : 'Stop after how many hours?');
            if (ask == null) { renderRun(); return; }
            value = Number(ask);
            if (!(value > 0)) { toastFail('That is not a number'); renderRun(); return; }
        }
        try {
            await postJSON(`/api/devices/timelapse/embryo/${encodeURIComponent(id)}/modify`,
                { stop_condition: AcquisitionPlan.stopSpec(kind, value) });
            toast('Ending changed');
        } catch (e) { toastFail(`Change failed (${why(e)})`); }
        renderRun();
    }
    function tacticCard(t) {
        const state = t.state || 'planned';
        const struct = t.structure || {};
        const meta = [];
        // One cadence, in words: "30s · 30s" was the same number from two
        // fields of the structure.
        const cadence = struct.cadence_s != null ? struct.cadence_s : struct.interval;
        if (cadence != null && Number.isFinite(Number(cadence))) meta.push(`every ${AcquisitionPlan.intervalWords(Number(cadence))}`);
        if (struct.status) meta.push(struct.status);
        if (struct.laser_config) meta.push(struct.laser_config);
        if (struct.volumes === false) meta.push('brightfield');
        if (t.live && t.live.signal != null) meta.push(`signal ${t.live.signal}`);
        // What the run was: two cards both saying "done" are two runs, and
        // these are what tell a 20-second false start from the eight-hour one.
        const live = t.live || {};
        const when = [];
        if (live.started) when.push(`started ${live.started}`);
        if (live.ended) when.push(live.ended);
        if (live.acquired) when.push(live.acquired);
        // The code's names for things are not the operator's: a plan started
        // from this pane is `standing_timelapse`, "Started from the Operate
        // Run step." The first is said by the card's own name and the second
        // says nothing the card does not.
        const kind = t.kind === 'standing_timelapse' ? '' : String(t.kind || '').replace(/_/g, ' ');
        const why = /^Started from the Operate Run step\.?$/.test(String(t.rationale || '').trim()) ? '' : (t.rationale || '');
        return `<div class="op-tcard st-${escapeHtml(state)}">` +
            `<div class="op-tcard-head"><span class="op-tcard-name">${escapeHtml(t.name || t.id)}</span>` +
            `<span class="op-tcard-state">${escapeHtml(state)}</span></div>` +
            (kind ? `<div class="op-tcard-kind">${escapeHtml(kind)}</div>` : '') +
            (meta.length ? `<div class="op-tcard-meta">${escapeHtml(meta.join(' · '))}</div>` : '') +
            (when.length ? `<div class="op-tcard-meta op-tcard-when">${escapeHtml(when.join(' · '))}</div>` : '') +
            (why ? `<div class="op-tcard-meta">${escapeHtml(why)}</div>` : '') +
            '</div>';
    }
    async function pauseRun() {
        try {
            const d = await postJSON(_runPaused ? '/api/devices/timelapse/resume' : '/api/devices/timelapse/pause', {});
            toast(_runPaused ? (d && d.continued ? 'Run carried on from its checkpoint' : 'Resumed') : 'Paused');
        } catch (e) { toastFail(`Pause/resume failed (${why(e)})`); }
        renderRun();
    }
    async function stopRun() {
        if (!window.confirm('Stop the run?')) return;
        try { await postJSON('/api/devices/timelapse/stop', { reason: 'operator' }); toast('Run stopped'); }
        catch (e) { toastFail(`Stop failed (${why(e)})`); }
        renderRun();
    }

    // ══ PANES ═══════════════════════════════════════════════════════════════
    // Camera ownership is keyed on VISIBILITY, not on a step. Both cameras
    // contend for MMCore, and the client swaps .src per frame with no throttle,
    // so two live decoders is the condition that risks a Video-TDR freeze. "The
    // camera is live while you are looking at it" guarantees at most one.
    // Workflow order, and the single list: each surface, and the section of
    // the page it is drawn in. The two camera surfaces and calibration are
    // one section, Scope, and which of them its picture shows is `[data-src]`
    // (paintPane). Calibration was a section of its own; what it needs (the
    // sheet, the embryo list, the light-sheet camera, the laser) is on Scope
    // and none of it was on that page.
    // The list used to be spelled out in showPane and again in
    // showPaneInitial, so adding a pane meant remembering both.
    const PANE_SECTION = { bottom: 'scope', spim: 'scope', cal: 'scope', acquire: 'acquire' };
    const SECTIONS = [...new Set(Object.values(PANE_SECTION))];
    const inScope = name => PANE_SECTION[name] === 'scope';
    // The instrument panels are on screen with either camera, so either
    // camera's surface draws all of them.
    function renderScope() {
        renderMarkCount(); drawMarkers(); renderSpimTarget();
        bz.render(); fd.render(); renderGoto(); renderFitRow();
    }

    const PANES = {
        bottom: {
            // Leaving turns the camera off; coming back does not turn it on.
            onEnter() { drawMarkers(); },
            onLeave() { if (_bottomOn) stopBottom(); },
            render() { renderScope(); },
        },
        spim: {
            onEnter() { adoptLsParams(); },
            // To the bottom camera the LED stays as it is: it lights that
            // camera too, and the Light panel beside the frame goes on
            // saying what it is. Leaving Scope closes it, as leaving the
            // SPIM head always has.
            // Fit is in Scope too, and going to it closes the LED as going
            // to the Calibration page did: under the LED alone a calibration
            // has no nuclei to find (#106).
            onLeave(to) { if (_spimOn) stopSpim(); if (!inScope(to) || to === 'cal') forceLedOff(); },
            render() { renderScope(); },
        },
        cal: {
            // Calibration takes its own frames; it never read the live view,
            // and Fit has no image to show one on. Entering used to
            // restart the stream anyway, unseen. Leaving closes the LED — the
            // calibrate path never did (#106).
            onEnter() { renderCalTarget(); },
            onLeave() { if (_spimOn) stopSpim(); forceLedOff(); },
            render() { renderScope(); renderCalTarget(); },
        },
        acquire: {
            // The run is watched while this pane is open: a poll for the
            // clocks, and the events for the moments. Nothing polls when it
            // is not.
            onEnter() { restorePlan(); readRoom(); renderRun(); clearInterval(_runPoll); _runPoll = setInterval(renderRun, 5000); },
            onLeave() { clearInterval(_runPoll); _runPoll = null; },
            render() { publishRoster(); renderSingle(); renderTargetScope(); renderPlan(); },
        },
    };
    function stopBottom() {
        fetch('/api/devices/bottom_camera/stream/stop', { method: 'POST' }).catch(() => {});
        applyBottomCam(false);
    }
    function stopSpim() {
        fetch('/api/devices/lightsheet/live/stop', { method: 'POST' }).catch(() => {});
        applySpim(false);
    }

    // Zoom/pan on the camera surfaces. Attached once each; the transform is
    // view state, not instrument state, so it stays local rather than going
    // into SharedState — two people looking at one scope still want their own
    // magnification.
    function attachImageViews() {
        if (typeof ImageView === 'undefined') return;
        ImageView.attach('op-cam-bottom', { controlsHost: 'op-display-bottom', display: 'stacked' });
        ImageView.attach('op-cam-spim', { controlsHost: 'op-display-spim', display: 'stacked' });
    }

    // The Light panel is shared, so Operate only says where to draw it — see
    // docs/architecture/PANELS.md. Mounted once, with the other panels;
    // SharedState keeps it current. The whole panel beside either camera: the
    // bottom camera used to get a card showing the LED alone, mounted apart.
    let _lightMounted = false;
    function mountLightPanel() {
        if (_lightMounted || typeof LightPanel === 'undefined') return;
        if (!$('op-light-host')) return;
        _lightMounted = true;
        LightPanel.mount('op-light-host');
    }

    // The dark/flat references for the overview frames sit under the plan's
    // light, LED and exposure fields in the rail's Overview frames box, and
    // read them (panels/brightfield-refs.js). When a reference
    // lands, the Acquisition pane's summary line says so.
    let _bfRefsMounted = false;
    function mountBrightfieldRefs() {
        if (_bfRefsMounted || typeof BrightfieldRefs === 'undefined') return;
        if (!$('op-bfref-host')) return;
        _bfRefsMounted = true;
        BrightfieldRefs.mount('op-bfref-host', { onChange: () => renderPlan() });
    }

    // The fields list, in the rail beside every instrument surface and in
    // the Acquisition pane's left column — the same two places the embryo
    // roster is, because it is the same kind of list (panels/fields.js).
    let _fieldsMounted = false;
    function mountFieldsPanels() {
        if (_fieldsMounted || typeof FieldsPanel === 'undefined') return;
        _fieldsMounted = true;
        if ($('op-frail-list')) FieldsPanel.mount('op-frail-list', { compact: true });
        if ($('op-fields')) FieldsPanel.mount('op-fields', {});
    }

    let _stagePadMounted = false;
    function mountStagePad() {
        if (_stagePadMounted || typeof StagePad === 'undefined') return;
        if (!$('op-stage-host')) return;
        _stagePadMounted = true;
        StagePad.mount('op-stage-host');
        // The pad sends its own jogs, so it is told when to ask first.
        StagePad.setGuard(() => mayTakeFromRun('Moving the stage'));
    }

    let _panelsMounted = false;
    function mountPanels() {
        if (_panelsMounted) return;
        mountBrightfieldRefs();
        mountStagePad();
        _panelsMounted = true;
        if (typeof MarkingPanel !== 'undefined' && $('op-marking-host')) {
            MarkingPanel.mount('op-marking-host');
        }
        if (typeof RosterPanel !== 'undefined') {
            // Actions declared per mount. The narrow rail sits beside the frame,
            // so removing a false positive belongs there; the Acquisition list
            // is the pre-run review surface and gets everything. Previously the
            // difference was an accident of where each button was added.
            if ($('op-erail-list')) {
                // showFit: the rail is beside every pane, so calibration state is
                // visible wherever you are — including before you reach the run
                // and discover the gate refusing it.
                //
                // centre: likewise. The rail is the embryo list on EVERY pane,
                // and the SPIM head is where "go to that embryo" is actually
                // wanted — it already says "stage is elsewhere" and blanks the
                // frame, but the only ways to act on that were to leave for the
                // bottom camera and click the dish, or for Acquisition and press
                // Centre there. The pane that reports the gap can now close it.
                RosterPanel.mount('op-erail-list',
                    { actions: ['centre', 'remove'], showFit: true, compact: true });
            }
            if ($('op-roster')) {
                // The fit is shown here too: this is the list a run is
                // started from, and a run refuses an embryo without one.
                // As a table: its role, its fit, how it ends. Centring and
                // removing are Scope's, beside the picture they are judged on.
                RosterPanel.mount('op-roster', {
                    actions: [],
                    table: true, emptyAction: 'bottom', showFit: true,
                    cell: emb => endingCell(emb),
                    out: emb => !inRun(emb),
                });
            }
        }
        mountFieldsPanels();
        mountLightPanel();
        if (typeof CameraPanel !== 'undefined') {
            if ($('op-cam-panel-bottom')) {
                CameraPanel.mount('op-cam-panel-bottom', { camera: 'bottom', titled: false });
            }
            if ($('op-cam-panel-spim')) {
                CameraPanel.mount('op-cam-panel-spim', { camera: 'spim', titled: false });
            }
        }
    }

    // ══ THE FOLDING CARDS ══════════════════════════════════════════════════
    // A card that folds to its head row. One rule for all of them:
    // `data-disclose` names the card, the head row and anything marked
    // `.op-disc-keep` stay, the other direct children fold.
    //
    // On the old Bottom cam rail every card folded, because the rail was a
    // 260 px strip that scrolled and folding was how it was made to fit. In
    // the workspace the instrument panels have fixed places and do not fold;
    // what still does is what is set once a night (the overview frames).
    //
    // The choice is the RIG's, not this browser's, and it is kept as it is
    // pressed: read from
    // /api/ui/rail-cards when the pane wakes, written through on every
    // press, and every browser on the rig hears UI_RAIL_CARDS and follows.
    // Until the rig has said, what is used every minute opens and what is
    // set once a night starts closed.
    const DISCLOSE_DEFAULT = { camera: true, stage: true, led: true, focus: true, overview: false, advanced: false };
    let _railCards = null;     // the rig's answer, once read

    function discloseState(key) {
        if (_railCards && typeof _railCards[key] === 'boolean') return _railCards[key];
        return DISCLOSE_DEFAULT[key] !== false;
    }

    function applyAllDisclosures() {
        document.querySelectorAll('#devices-view-operate [data-disclose]').forEach(block => {
            applyDisclosure(block, discloseState(block.dataset.disclose));
        });
    }

    async function loadRailCards() {
        try {
            const d = await getJSON('/api/ui/rail-cards');
            _railCards = d && d.cards && typeof d.cards === 'object' ? d.cards : {};
        } catch (_) { _railCards = _railCards || {}; }
        applyAllDisclosures();
    }

    function saveRailCard(key, open) {
        _railCards = Object.assign({}, _railCards || {}, { [key]: open });
        fetch('/api/ui/rail-cards', {
            method: 'PUT', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ cards: { [key]: open } }),
        }).then(r => { if (!r.ok) console.warn(`[gently] rail card not kept: ${r.status}`); })
            .catch(() => { /* the card stays as pressed on this page */ });
    }

    function applyDisclosure(block, open) {
        const head = block.querySelector(':scope > .op-disc-head, :scope > .op-gauge-head');
        [...block.children].forEach(ch => {
            if (ch === head || ch.classList.contains('op-disc-keep')) return;
            ch.hidden = !open;
        });
        const btn = head && head.querySelector('[data-disclose-toggle]');
        if (btn) {
            btn.textContent = open ? 'Hide' : 'Show';
            btn.setAttribute('aria-expanded', String(open));
        }
        block.dataset.open = open ? '1' : '0';
    }

    function wireDisclosures() {
        document.querySelectorAll('#devices-view-operate [data-disclose]').forEach(block => {
            const key = block.dataset.disclose;
            applyDisclosure(block, discloseState(key));
            const btn = block.querySelector('[data-disclose-toggle]');
            if (!btn) return;
            btn.addEventListener('click', () => {
                const open = block.dataset.open !== '1';
                applyDisclosure(block, open);
                saveRailCard(key, open);
            });
        });
        // Another browser pressed, or this one did and is hearing it back.
        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('UI_RAIL_CARDS', d => {
                if (!d || !d.cards || typeof d.cards !== 'object') return;
                _railCards = Object.assign({}, _railCards || {}, d.cards);
                applyAllDisclosures();
            });
        }
    }

    function showPane(name) {
        // "Scope" is the workspace; the camera it shows is the one it last did.
        if (name === 'scope') name = _scope;
        if (!PANES[name] || name === _pane) return;
        const prev = _pane;
        _pane = name;
        if (inScope(name)) _scope = name;
        if (PANES[prev]) PANES[prev].onLeave(name);
        paintPane();
        PANES[name].onEnter();
        PANES[name].render();
        publishRoster();
    }

    // What is on screen for the surface `_pane` names: its section of the
    // page, and inside Scope the chosen camera's frame, caption, verbs and
    // display panel (`[data-src]`). Render dispatch, in one place for
    // showPane and showPaneInitial both.
    function paintPane() {
        const section = PANE_SECTION[_pane];
        SECTIONS.forEach(s => {
            const el = $(`op-pane-${s}`);
            if (el) el.hidden = s !== section;
        });
        if (inScope(_pane)) {
            document.querySelectorAll('#op-pane-scope [data-src]').forEach(el => {
                el.hidden = el.dataset.src !== _pane;
            });
        }
        // Drives the CSS that hides the shared rail on Acquisition (its own
        // roster is richer) and, on Calibration, the rail's two panels that
        // are about the bottom camera's picture.
        const body = $('op-body'); if (body) body.dataset.pane = _pane;
        if (typeof updateViewButtons === 'function') updateViewButtons('operate-subtab-switcher', section);
        renderSource();
        renderViewMeta();
    }

    function renderSubnavMeta() {
        const el = $('op-subnav-meta');
        if (!el) return;
        const bits = [];
        if (_bottomOn) bits.push('BOTTOM ● LIVE');
        if (_spimOn) bits.push('SPIM ● LIVE');
        if (ledIsOpen()) bits.push('LED EMITTING');
        // Derived by the Light panel from what the hardware says (a beam
        // armed, a line routed, its power above zero), so it is true with
        // the live view as well as during a run. It used to be said only
        // while this page had itself started an acquisition.
        const light = SharedState.get('light');
        const lasing = typeof LightPanel !== 'undefined' && light ? LightPanel.emitting(light) === true : false;
        // The laser's word alone wears the hazard's colour: "the camera is
        // live" beside it is not a hazard and must not look like one.
        const key = bits.join('|') + (lasing || _acquiring ? '|LASER' : '');
        if (el.dataset.says === key) return;
        el.dataset.says = key;
        el.textContent = bits.join('  ·  ');
        if (lasing || _acquiring) {
            if (bits.length) el.append('  ·  ');
            const hot = document.createElement('span');
            hot.className = 'is-emitting';
            hot.textContent = 'LASER EMITTING';
            el.append(hot);
        }
    }

    /**
     * The agent is asking the operator to mark embryos on an image it captured.
     *
     * Adapts the pushed image into the same payload shape a live bottom-camera
     * frame has, so `frameOf`/`stageOf`/`drawMarkers`/`onCanvasClick` and the
     * corrected hit-test all work on it with no special cases. The one thing
     * that differs is the scale: the session declares its own `pixel_size_um`,
     * which `pxBase()` threads into the geometry.
     */
    function onMarkingImage(d) {
        if (!d || !d.image_b64) return;

        // The session's scale is µm per image pixel at the sample (0.65 here).
        // A camera pixel (6.5) once came through this field and every mark
        // landed ten times too far out; the pane's own scale is used instead
        // of anything no objective could give.
        const scale = Number(d.pixel_size_um);
        const sane = Number.isFinite(scale) && scale >= 0.01 && scale <= 5;
        if (d.pixel_size_um != null && !sane) console.error('marking session pixel_size_um is not a sample-plane pixel:', d.pixel_size_um);
        _markSession = {
            sessionId: d.session_id,
            defaultRole: d.default_role || 'lineaging',
            pixelSizeUm: sane ? scale : undefined,
        };

        // A pushed still, in the shape a live frame arrives in. `mime` matters:
        // start_marking_session sends PNG, the camera stream sends JPEG.
        _lastBottom = {
            t: Date.now(),
            shape: [d.height, d.width],
            downsample: 1,
            stage_position: [d.stage_x_um != null ? d.stage_x_um : 0,
                             d.stage_y_um != null ? d.stage_y_um : 0],
            mime: 'image/png',
            jpeg_b64: d.image_b64,
        };

        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        // Initial markers arrive in PIXEL coordinates; this pane keeps markers
        // in stage µm so they stay attached to the sample under zoom and stage
        // motion. Convert once, here, at the boundary.
        _markers = (d.initial_markers || []).map(m => {
            const st = (f && cap && M) ? M.frameToStage(m.pixelX, m.pixelY, f, cap, pxBase()) : null;
            return st ? {
                stageX: st[0], stageY: st[1],
                source: m.source || 'sam',
                role: m.role || _markSession.defaultRole,
                embryo_id: m.embryo_id || null,
                confidence: m.confidence != null ? m.confidence : null,
            } : null;
        }).filter(Boolean);

        // Bring the operator to the surface rather than expecting them to find
        // it. The old implementation did this too, and it is right: the agent
        // is blocked waiting on an answer.
        if (typeof switchTab === 'function') switchTab('devices');
        showPane('bottom');
        // A still the agent pushed: its own bytes, which the device layer's last
        // grab need not be, so it is shown as sent.
        showFrame('bottom', _lastBottom, false);
        drawMarkers();
        renderMarkCount();
        setDetectNote(_markers.length
            ? `${_markers.length} detected — the agent is waiting. Adjust them, set roles, then Done.`
            : 'The agent is waiting for you to mark the embryos. Click each one, then Done.');
    }

    /** Answer the agent. Markers go back in pixel coordinates, with roles. */
    function finishMarkingSession() {
        if (!_markSession) return;
        const f = frameOf(_lastBottom), cap = stageOf(_lastBottom);
        const markers = _markers.map((m, i) => {
            const px = (f && cap && M) ? M.stageToFrame(m.stageX, m.stageY, f, cap, pxBase()) : null;
            return px ? {
                number: i + 1,
                pixelX: Math.round(px[0]),
                pixelY: Math.round(px[1]),
                role: m.role || _markSession.defaultRole,
                source: m.source || 'manual',
                embryo_id: m.embryo_id || null,
                confidence: m.confidence != null ? m.confidence : null,
                timestamp: new Date().toISOString(),
            } : null;
        }).filter(Boolean);

        const sent = sendWs({ type: 'marking_done', session_id: _markSession.sessionId, markers });
        if (!sent) {
            toastFail('Not connected — the agent did not get your marks');
            return;
        }
        const n = markers.length;
        _markSession = null;
        _markers = [];
        drawMarkers();
        renderMarkCount();
        setDetectNote(`Marking complete — ${n} embryo${n === 1 ? '' : 's'} sent to the agent.`);
        publishMarking();
    }

    /** Ask the agent to recapture and re-detect. */
    function redetectMarkingSession() {
        if (!_markSession) return;
        if (!sendWs({ type: 'marking_redetect', session_id: _markSession.sessionId })) {
            toastFail('Not connected — could not ask for a re-detect');
            return;
        }
        setDetectNote('Asked the agent to recapture and re-detect…');
    }

    /** Cycle one pending marker between subject and reference. */
    function cycleMarkerRole(index) {
        const m = _markers[index];
        if (!m || !_markSession) return;
        m.role = m.role === 'calibration' ? 'lineaging' : 'calibration';
        drawMarkers();
        publishMarking();
    }

    // The marking contract is a websocket request/response keyed on
    // session_id, not an HTTP call — the agent is blocked on `complete`.
    function sendWs(payload) {
        const ws = (typeof state !== 'undefined' && state) ? state.ws : null;
        if (!ws || ws.readyState !== WebSocket.OPEN) return false;
        ws.send(JSON.stringify(payload));
        return true;
    }

    // ══ EVENTS ══════════════════════════════════════════════════════════════
    function onBottomFrame(p) {
        // Bail when hidden, or a hidden Operate keeps base64-decoding every
        // frame behind whatever is on screen and races for stream ownership.
        if (!_active || _pane !== 'bottom' || !p || !p.jpeg_b64) return;
        _lastBottom = p;
        noteFrame('bottom');
        showFrame('bottom', p);
        drawMarkers();
    }
    function onSpimFrame(p) {
        if (!_active || _pane !== 'spim' || !p || !p.jpeg_b64) return;
        if (p.side && p.side !== _side) {
            // Inside the switch window the frame is the old side's, grabbed
            // before the switch: dropped. Outside it the device layer is on a
            // side this pane never chose, and the pane follows it.
            if (Date.now() - _sideChangedAt > SIDE_SWITCH_MS) adoptLsParams();
            return;
        }
        noteFrame('spim');
        // The frame is of wherever the stage is, which is not necessarily the
        // embryo the caption names. Showing it there would be a false claim.
        if (!atSelected()) { clearImg('op-img-spim', 'op-ph-spim', 'Not at this embryo'); return; }
        // Multi is two cameras composed in colour, a rendering: it comes as its
        // JPEG. A or B is one camera's frame, drawn from its counts.
        showFrame('spim', p, p.side !== 'Multi');
    }
    function onEmbryosUpdate(p) {
        const hadAny = _embryos.length > 0;
        _embryos = (p && Array.isArray(p.embryos)) ? p.embryos.slice() : [];
        if (_selected && !_embryos.some(e => e.id === _selected)) _selected = null;
        // Drop members that no longer exist, or the set silently targets ghosts
        // — the same class of bug as the phantom roster row in #126.
        const known = new Set(_embryos.map(e => e.id));
        _targets = _targets.filter(id => known.has(id));
        // The embryo list is shared across all three panes; on first population
        // pick a live selection so SPIM/Acquire aren't a dead-end ("No embryo
        // selected") right after registering. After that the selection is the
        // operator's: an embryo the server drops from under it falls to none,
        // it does not hop to embryo 1 with nobody touching the list (#140).
        if (!_selected && !hadAny && _embryos.length) _selected = _embryos[0].id;
        if (!_targets.length && _selected) _targets = [_selected];
        SharedState.set('selectedEmbryoIds', _targets.slice());
        SharedState.set('selectedEmbryoId', _selected);
        // Render the shared rail even when the Operate view isn't the active tab,
        // so switching to it (or refreshing) shows the list immediately rather
        // than waiting for the next mutation event.
        publishRoster();
        publishMarking();
        if (!_active) return;
        // renderCalTarget was missing here: the Calibration pane kept whatever
        // it last drew, so an embryo calibrated by the agent (or by the pane's
        // own borrow) still read "not calibrated" until something else forced
        // a redraw. Every pane that shows per-embryo state redraws here.
        publishRoster(); renderSpimTarget(); renderSingle(); renderCalTarget();
        // The Acquisition pane shows per-embryo parameters twice: the plan's
        // fields (derived from the targets) and the run rows (each its own).
        // Both follow the change the moment it is announced.
        if (_pane === 'acquire') { renderPlan(); renderRun(); }
    }

    function wire() {
        if (_wired) return;
        _wired = true;

        if (typeof initViewSwitcher === 'function') {
            // Click delegation only — deliberately NO `views` option.
            //
            // initViewSwitcher's `views` binds BARE number keys on document, and
            // 1-6 are already global main-tab navigation (KeyboardShortcuts in
            // app.js), with system/calibration/plan switchers claiming 1-3 too.
            // Binding them here either steals a main-tab key or, with a guard
            // tight enough to be safe, never fires at all — verified in-browser:
            // app.js handles the keypress first and moves state.tab, so the
            // guard then correctly refuses. Three peer surfaces are fine to
            // click between; a shortcut would need a modifier to be honest.
            initViewSwitcher('operate-subtab-switcher', name => {
                // The surfaces share the Devices toolbar with Map, Details,
                // 3D and Manual. Pressed from one of those, the press comes
                // back to Operate first, then goes to the surface.
                if (!_active && typeof DevicesManager !== 'undefined') DevicesManager.switchView('operate');
                showPane(name);
            });
        }

        bz.wire(); fd.wire();

        const cam = $('op-cam-toggle'); if (cam) cam.addEventListener('click', toggleBottomCam);
        const det = $('op-detect'); if (det) det.addEventListener('click', runDetect);
        const ok = $('op-confirm'); if (ok) ok.addEventListener('click', confirmMarks);
        const cl = $('op-clear');
        if (cl) cl.addEventListener('click', clearMarks);
        const canvas = $('op-mark-canvas');
        if (canvas) {
            canvas.addEventListener('click', onCanvasClick);
            canvas.addEventListener('mousemove', readUnderCursor);
            canvas.addEventListener('mouseleave', () => { const fit = fitOf('bottom'); if (fit && fit._u16) fit._u16.readOff(); });
        }

        // Row clicks and keys are the Roster panel's business now — it owns
        // the markup, so it owns the handlers. Two listeners on one host, one
        // of them looking for buttons the panel no longer emits, is how a
        // select fires twice.
        //
        // Everything below was collateral of that deletion in the roster
        // refactor: the slice that removed the roster's own listeners ran past
        // them. Eight controls went dead, including the interlock banner's
        // back-off button. Restored, and pinned by a test that counts them.
        const sp = $('op-spim-toggle'); if (sp) sp.addEventListener('click', toggleSpim);
        const cal = $('op-calibrate'); if (cal) cal.addEventListener('click', calibrateSelected);
        const abort = $('op-cal-abort'); if (abort) abort.addEventListener('click', abortCalibration);
        const borrow = $('op-cal-borrow');
        if (borrow) borrow.addEventListener('click', borrowCalibration);
        const all = $('op-cal-all');
        if (all) all.addEventListener('click', calibrateAll);
        const clear = $('op-cal-clear');
        if (clear) clear.addEventListener('click', clearFit);
        wireDisclosures();
        const alignSet = $('op-align-set');
        if (alignSet) alignSet.addEventListener('click', setSpimCentre);
        const alignHist = $('op-align-history');
        if (alignHist) alignHist.addEventListener('click', e => {
            const b = e.target.closest('.al-restore');
            if (b) restoreAlignment(b.dataset.at);
        });
        const alignMore = $('op-align-more');
        if (alignMore) alignMore.addEventListener('click', async () => {
            const host = $('op-align-history');
            if (host && !host.hidden) { host.hidden = true; return; }
            try { renderAlignHistory(await getJSON('/api/devices/spim/alignment')); }
            catch (e) { toastFail(`Could not read the alignment history (${why(e)})`); }
        });
        loadAlignment();

        const anyway = $('op-cal-anyway');
        if (anyway) anyway.addEventListener('click', () => calibrateSelected({ anyway: true }));
        wireCalForm();
        if (typeof CalProgressPanel !== 'undefined') CalProgressPanel.mount('op-cal-progress');
        // The sheet's two axes: a line to drag and the same number to type.
        // The line moves the sheet as it is dragged (the view is how the
        // pose is judged); a typed number moves it on Enter.
        const bindAxis = (key, line, box, decimals) => {
            if (!line) return;
            if (box && typeof NumRow !== 'undefined') {
                _axisRow[key] = NumRow.bind(line, box, {
                    decimals, onInput: v => setAxis(key, v), onCommit: v => setAxis(key, v),
                });
            } else {
                line.addEventListener('input', () => setAxis(key, Number(line.value)));
            }
        };
        bindAxis('galvo', $('op-gv-in'), $('op-gv'), 2);
        bindAxis('piezo', $('op-pz-in'), $('op-pz'), 1);
        adoptLsParams();
        document.querySelectorAll('#op-source [data-source]').forEach(b =>
            b.addEventListener('click', () => chooseSource(b.dataset.source)));
        const halt = $('op-halt');
        if (halt) halt.addEventListener('click', haltMotion);
        const keptStrip = $('op-cal-kept-strip');
        if (keptStrip) keptStrip.addEventListener('click', e => {
            const b = e.target.closest('[data-cal-img]');
            if (b) openCalImage(Number(b.dataset.calImg));
        });
        const keptOpen = $('op-cal-kept-open');
        if (keptOpen) keptOpen.addEventListener('click', openCalFolder);
        // From what the last run kept to every run and every raw exposure.
        const keptAll = $('op-cal-kept-all');
        if (keptAll) keptAll.addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab('calibration');
            if (typeof CalibrationManager !== 'undefined') CalibrationManager.switchView('runs');
        });
        const to = $('op-fd-to');
        if (to) to.addEventListener('click', () => headTo(Number(to.dataset.fdTo), to));
        const go = $('op-fd-go');
        if (go) go.addEventListener('click', goHeadTyped);
        const goBox = $('op-fd-goto');
        if (goBox) goBox.addEventListener('keydown', e => {
            if (e.key === 'Enter') { e.preventDefault(); goHeadTyped(); }
        });
        renderGoto();
        const raise = $('op-fd-raise');
        if (raise) raise.addEventListener('click', raiseHead);

        const test = $('op-test-one'); if (test) test.addEventListener('click', testVolume);
        const agentBtn = $('op-run-agent'); if (agentBtn) agentBtn.addEventListener('click', handToAgent);
        const loadBtn = $('op-plan-load');
        if (loadBtn) loadBtn.addEventListener('click', () => {
            const box = $('op-panel-library');
            const open = !box || box.hidden;
            // Shutting the list lets go of a tactic chosen in it: the form is
            // the run again.
            if (!open && _mode === 'library') setMode('adaptive');
            showSaved(open);
        });
        const tiles = $('op-tiles');
        if (tiles) {
            tiles.addEventListener('click', e => {
                const t = e.target.closest('[data-tile]');
                if (t) pointAt(t.dataset.tile);
            });
            if (typeof ResizeObserver !== 'undefined') new ResizeObserver(() => fitTiles()).observe(tiles);
        }
        const monitor = $('op-acq-monitor');
        if (monitor) monitor.addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab('embryos');
        });
        const kindSeg = $('op-tiles-kind');
        if (kindSeg) kindSeg.addEventListener('click', e => {
            const b = e.target.closest('[data-kind]');
            if (b) { _tilesKind = b.dataset.kind === 'overview' ? 'overview' : 'volumes'; renderTiles(); }
        });
        const fresh = $('op-acq-new'); if (fresh) fresh.addEventListener('click', () => setAcqView('design'));
        const lastRun = $('op-acq-show-run'); if (lastRun) lastRun.addEventListener('click', () => setAcqView('watch'));
        // The acquisition plan. One listener on the pane re-says the plan for
        // every input, including the per-embryo rows that come and go with
        // the roster; the run's own stop select is populated here, once.
        const stopSel = $('op-tl-stop');
        // A run ends after 16 hours unless told otherwise (2026-10-09):
        // the night, with the morning to look at it.
        if (stopSel && !stopSel.options.length) stopSel.innerHTML = stopOptions('duration', false);
        const planPanel = $('op-panel-adaptive');
        if (planPanel) {
            planPanel.addEventListener('input', () => { planTouched(); renderPlan(); });
            // (An embryo's own ending is on its row in the table, which is
            // the roster's: it comes here through roster.cellChange.)
            planPanel.addEventListener('change', e => {
                planTouched();
                // "Taken from the fields" with none in the list yet makes one
                // from where the stage is, the way the rail's button does —
                // the operator drove there and said so. Choosing the centroid
                // leaves the list alone: it is the session's, just not used.
                const pos = e.target.closest('#op-plan-bf-pos');
                if (pos && pos.value === 'here' && !_bfPins.length && !addFieldHere()) {
                    pos.value = 'centroid';
                }
                renderPlan();
            });
            // The way to where the light, exposure, dark and flat are set.
            planPanel.addEventListener('click', e => {
                const go = e.target.closest('[data-goto-pane]');
                if (go) { e.preventDefault(); showPane(go.dataset.gotoPane); }
            });
            renderPlan();
        }
        // The plan's overview fields live in the rail on Scope, beside the
        // live view; a change there re-says the plan like one on Acquisition.
        const ov = $('op-overview-host');
        if (ov) {
            ov.addEventListener('input', () => { _planDirty = true; renderPlan(); });
            ov.addEventListener('change', () => { _planDirty = true; renderPlan(); });
        }
        const match = $('op-ov-match');
        if (match) match.addEventListener('click', useLiveSettings);
        const lib = $('op-lib-list');
        if (lib) {
            lib.addEventListener('click', e => {
                const b = e.target.closest('[data-lib]');
                if (b) chooseSaved(b.dataset.lib);
            });
        }
        const scope = $('op-target-scope');
        if (scope) scope.addEventListener('click', e => {
            const b = e.target.closest('[data-scope]');
            if (b && !b.disabled) setTargetScope(b.dataset.scope);
        });
        const start = $('op-run-start'); if (start) start.addEventListener('click', startRun);
        const pf = $('op-preflight');
        if (pf) pf.addEventListener('click', e => {
            const b = e.target.closest('[data-preflight-fix]');
            if (b) preflightFix(b.dataset.preflightFix);
        });
        // The light is one of the lines: what it is read as changes them.
        SharedState.on('light', () => { if (_pane === 'acquire') renderPreflight(); });
        const pause = $('op-run-pause'); if (pause) pause.addEventListener('click', pauseRun);
        const stopb = $('op-run-stop'); if (stopb) stopb.addEventListener('click', stopRun);
        const saveBtn = $('op-plan-save');
        if (saveBtn) saveBtn.addEventListener('click', savePlan);
        // Per-embryo steering lives on rows the run renders, so it is bound
        // on the spine once and delegated.
        const spine = $('op-runspine');
        if (spine) {
            spine.addEventListener('click', e => {
                const b = e.target.closest('[data-run-halt]');
                if (b) stopEmbryo(b.dataset.runHalt);
            });
            spine.addEventListener('change', e => {
                const sel = e.target.closest('[data-run-stop]');
                if (sel) changeEmbryoEnding(sel.dataset.runStop, sel.value);
            });
        }

        window.addEventListener('resize', () => { if (_active && _pane === 'bottom') drawMarkers(); });
        // The viewport also changes size without a window resize — revealing the
        // pane, the agent panel opening, the first frame arriving. Without this
        // the overlay keeps whatever size it was first drawn at and every marker
        // sits in the wrong place until the next frame happens to redraw it.
        const camBox = $('op-cam-bottom');
        if (camBox && typeof ResizeObserver !== 'undefined') {
            new ResizeObserver(() => { if (_active && _pane === 'bottom') drawMarkers(); }).observe(camBox);
        }

        // ── shared state: follow the values this file used to keep privately ──
        // Both are sticky and synchronous, so a set() from our own handler has
        // applied the local before the handler's next line runs. Assignment
        // only: the renders stay where they already were, so nothing here can
        // change what is drawn today. What it buys is fan-IN — when another
        // surface moves the stage or the cursor, these locals follow instead of
        // going stale.
        SharedState.on('stageXY', v => {
            if (!v) return;
            _xy = v;
            // Arrival is a stage event, not a selection event: without this the
            // caption would still read "stage is elsewhere" after the move landed.
            renderSpimTarget();
        });
        // What the Light panel reads back is what the toolbar says of it.
        SharedState.on('light', () => renderSubnavMeta());
        SharedState.on('selectedEmbryoId', id => {
            if (id === _selected) return;      // our own publish, already applied
            _selected = id;
            publishRoster(); renderSpimTarget(); renderCalTarget(); renderSingle();
        });

        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('BOTTOM_CAMERA_FRAME', onBottomFrame);
            ClientEventBus.on('LIGHTSHEET_FRAME', onSpimFrame);
            ClientEventBus.on('EMBRYOS_UPDATE', onEmbryosUpdate);
            // The moments of a run, on top of the poll.
            ['ACQUISITION_STARTED', 'ACQUISITION_COMPLETED', 'ACQUISITION_STOPPED',
             'ACQUISITION_FAILED', 'TIMELAPSE_STATE', 'VOLUME_ACQUIRED', 'IMAGE_ACQUIRED',
             'EMBRYO_TERMINATED'].forEach(ev => ClientEventBus.on(ev, () => { if (_pane === 'acquire') scheduleRenderRun(); }));
            // Server-pushed stills (focus montages today). websocket.js emits
            // this for every image; onPushedImage takes the kinds this pane owns.
            ClientEventBus.on('IMAGE_RECEIVED', onPushedImage);
            // The agent asking for marks. One surface, two invocations.
            ClientEventBus.on('MARKING_IMAGE', onMarkingImage);
            ClientEventBus.on('DEVICE_STATE_UPDATE', p => {
                const pos = p && p.positions;
                if (!pos) return;
                if (Array.isArray(pos.xy_stage)) {
                    SharedState.set('stageXY', { x: pos.xy_stage[0], y: pos.xy_stage[1] });
                }
                if (!_active) return;
                for (const v of Object.values(pos)) {
                    if (!v || typeof v !== 'object' || v.Position == null) continue;
                    const val = Number(v.Position);
                    if (!Number.isFinite(val)) continue;
                    if (v.kind === 'fdrive') fd.absorbTelemetry(val);
                    else if (v.kind === 'bottom_z') bz.absorbTelemetry(val);
                }
                if (_pane === 'acquire') renderSingle();
            });
        }
    }

    async function activate() {
        wire();
        // Here rather than in showPane: showPane early-returns when the pane has
        // not changed, and 'bottom' is the pane we start on, so the initial
        // surface would never get its zoom.
        attachImageViews();
        mountPanels();
        renderRunButton();
        if (_active) return;
        _active = true;
        showPaneInitial();
        try { onEmbryosUpdate(await getJSON('/api/embryos/current')); } catch (_) {}
        // The session's fields, then the session's last plan — in that
        // order, so a list the session holds outranks the run's positions.
        // The plan is restored HERE, not only on entering Acquisition: the
        // plan's light, exposure and fields are on Scope now,
        // and the first thing typed there must not be what stops the rest
        // of the plan (cadence, ending) coming back.
        await loadFields();
        await restorePlan();
        // The rig's choice of which rail cards are open.
        await loadRailCards();
        await Promise.all([bz.refresh(), fd.refresh()]);
        renderSubnavMeta();
    }
    // ---- a plan item, set up here ----------------------------------------
    // The Projects tab hands an item over (sessionStorage + an event): its
    // acquisition fills the Acquisition pane, the banner says where it came
    // from, and Start files the run under it.
    let _setupItem = null;

    function takeSetupItem() {
        try {
            const raw = sessionStorage.getItem('gently-setup-item');
            if (!raw) return null;
            sessionStorage.removeItem('gently-setup-item');
            return JSON.parse(raw);
        } catch (_) { return null; }
    }

    function renderSetupBanner() {
        // In the run's column, over the sentence: as the pane's first child
        // it was a row above three zones, and pushed every one of them down.
        const pane = $('op-setup-host') || $('op-pane-acquire');
        if (!pane) return;
        let el = document.getElementById('op-setup-banner');
        if (!_setupItem) { if (el) el.remove(); return; }
        if (!el) {
            el = document.createElement('div');
            el.id = 'op-setup-banner';
            el.className = 'op-setup-banner';
            pane.insertBefore(el, pane.firstChild);
        }
        const where = _setupItem.project && _setupItem.project.name ? ` · in ${escapeHtml(_setupItem.project.name)}` : '';
        el.innerHTML = `<span class="op-setup-chip">plan item</span> <b>${escapeHtml(_setupItem.title || '')}</b>${where}`
            + ' <span class="op-setup-hint">Start files this run under it</span>'
            + ' <button type="button" class="op-setup-clear" id="op-setup-clear">clear</button>';
        const btn = document.getElementById('op-setup-clear');
        if (btn) btn.addEventListener('click', () => { _setupItem = null; renderSetupBanner(); });
    }

    function applySetupItem(item) {
        if (!item || typeof AcquisitionPlan === 'undefined') return;
        _setupItem = item;
        showPane('acquire');
        if (typeof setMode === 'function') setMode('adaptive');
        try { fillPlan(AcquisitionPlan.fromStructure(item.structure || {})); } catch (e) { console.warn('plan item did not fill the pane', e); }
        _planDirty = true;
        renderSetupBanner();
        if (typeof renderPlan === 'function') renderPlan();
    }

    window.addEventListener('gently:setup-item', e => applySetupItem(e.detail));

    function showPaneInitial() {
        paintPane();
        if (PANES[_pane]) { PANES[_pane].onEnter(); PANES[_pane].render(); }
        const handed = takeSetupItem();
        if (handed) applySetupItem(handed);
    }
    function deactivate() {
        if (!_active) return;
        _active = false;
        // Leave nothing running behind a hidden view, and nothing to come
        // back on by itself.
        if (_bottomOn) stopBottom();
        if (_spimOn) stopSpim();
        forceLedOff();
        // The surfaces' buttons sit in the Devices toolbar beside Map and the
        // rest: with another of those up, none of these is the one on screen.
        if (typeof updateViewButtons === 'function') updateViewButtons('operate-subtab-switcher', '');
    }

    // redraw: a CSS transform on an ancestor fires neither `resize` nor
    // ResizeObserver, so the bench has to say when it has zoomed. Cheap and
    // idempotent — it no-ops off the bottom pane.
    // The Marking panel renders SharedState and calls these. The logic stays
    // here, with the canvas and the frame geometry it depends on — the panel
    // owns the readout and the verbs, not the marking itself.
    return {
        activate, deactivate, redraw: drawMarkers,
        // panels/roster.js renders SharedState.embryos and calls these. The
        // list, the selection and the endpoints stay here.
        roster: {
            select: (id, mode) => selectEmbryo(id, mode),
            remove: id => deleteEmbryo(id),
            restore: id => restoreEmbryo(id),
            readRemoved: () => readRemoved(),
            centre: id => {
                const emb = _embryos.find(e => e.id === id);
                if (emb) centerOnEmbryo(emb);
            },
            toggleRole: id => toggleRole(id),
            goTo: pane => showPane(pane),
            // A change in a row's own cell (the Acquisition table's ending).
            cellChange: (id, control) => setEnding(id, control),
        },
        // panels/fields.js renders SharedState.overviewFields and calls
        // these. The list, the stage position and the plan stay here.
        fields: {
            addHere: () => addFieldHere(),
            remove: i => removeField(Number(i)),
            goTo: i => goToField(Number(i)),
        },
        marking: {
            detect: opts => runDetect(opts),
            register: () => confirmMarks(),
            clear: () => clearMarks(),
            // Session verbs — only meaningful while the agent is waiting.
            done: () => finishMarkingSession(),
            redetect: () => redetectMarkingSession(),
            cycleRole: i => cycleMarkerRole(Number(i)),
        },
    };
})();
