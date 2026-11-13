/**
 * Light — the standard control panel for illumination.
 *
 * The LED, the laser's routed lines and each line's power, the beam on each
 * side, and one line that says what is emitting. Exposure is a camera
 * property, not a light one, and lives in panels/camera.js.
 *
 * The first panel built to docs/architecture/PANELS.md. Mount it anywhere that
 * needs light control; every mount shows the same state because the state
 * lives in SharedState, not in the panel.
 *
 *     LightPanel.mount('op-light-host');
 *
 * WHY THIS EXISTS
 *
 * `LASER: ON` used to mean "an HTTP request returned 200". The operator watched the
 * physical microscope on 2026-08-07 and reported the beam was not firing while
 * the UI said it was (#106). Three independent facts were being collapsed into
 * that one word:
 *
 *   Laser       — the Laser config group ("ALL OFF", "488 only", ...). On this
 *                 rig this IS what an operator means by the laser being on or
 *                 off, so it keeps that name. PLogic gating; it emits nothing
 *                 by itself.
 *   BeamEnabled — the Micro-Manager property on the scanner card, named as
 *                 Micro-Manager names it, because that is where an operator
 *                 has seen it before. Left "No" after every volume
 *                 acquisition with nothing to set it back, which is how a
 *                 correctly configured laser still emits nothing.
 *   power       — per-line setpoint. The calibrate path never touched it.
 *
 * Deliberately not collapsed into one "laser" switch, however much tidier that
 * would read: collapsing them is what produced #106. "Arm" was worse still —
 * it invented a word this instrument does not use.
 *
 * Any of the three can be wrong on its own, so the panel shows all three and
 * computes "emitting" from them rather than believing a flag.
 *
 * THE SHAPE IT HAS NOW (2026-11-13)
 *
 * Every control has one place and is always there:
 *
 *   LED     Closed | Open, and its brightness
 *   Laser   the presets of the Laser config group, as buttons
 *   lines   one row per line the rig has: its power, set by dragging or by
 *           typing, routed or not
 *   Beam    A | B, each side its own switch
 *   status  one line, always present: dark, what is emitting, or what stands
 *           in the way of it
 *
 * Until then the panel opened with a mode (LED | Laser | Off) and disclosed
 * that mode's controls beneath it. That kept a dark panel short, and it cost
 * three things on the rig: the controls moved as the mode changed, so nothing
 * could be found by place; a line's power could not be seen or set until the
 * line was routed, which is the moment it starts to matter; and the facts
 * about emission arrived as separate notes that came and went. "Need to
 * redesign the light panel", and "the adjustable parameters like laser power
 * can also have a way to enter numbers into a text box".
 *
 * ONE SOURCE AT A TIME IS A POLICY
 *
 * LED and Laser are two independent Micro-Manager config groups; nothing in
 * the hardware stops both being open, and #106 is that state going unnoticed.
 * The panel's own presses keep to one: opening the LED gates the lasers
 * first, and routing a line closes the LED first. What the rig is actually in
 * is read back and said, both open included — `mode()` reports `both` rather
 * than the panel making it unrepresentable.
 *
 * Everything rendered here is read back from hardware. A value that was sent is
 * not a value that is true; a value not yet read is an em dash, never a
 * plausible default.
 */
const LightPanel = (() => {
    'use strict';

    const hosts = new Set();
    // The slider-and-number rows of each mount, so a read-back does not redraw
    // the panel under a drag or a half-typed number (panels/numrow.js).
    const rows = new Map();          // hostId -> [NumRow binding]
    const waiting = new Set();       // hostIds whose redraw is held for an edit

    // Bounds and preset names come from the server (PANELS.md rule 4). 488 is
    // limited to 2-6%, so a control hardcoded 0-100 would offer settings the
    // device layer refuses.
    let limits = null;
    let configs = [];

    // RIG-NOTE: polling here is deliberately gentle and only runs while a
    // panel is on screen. Raise it if the readout feels stale, but watch the
    // device-layer log before you do.
    const POLL_MS = 10000;
    let timer = null;

    const state = () => SharedState.get('light') || {};

    /** Every line the rig has, in order. */
    const knownLines = () => (limits
        ? Object.keys(limits).map(Number).sort((a, b) => a - b)
        : [405, 488, 561, 637]);

    /* ── reading ─────────────────────────────────────────────────────────── */

    /** State and brightness come back in the one status read. */
    const ledOf = d => ({
        led: (d && d.current_state) || null,
        ledPct: d && d.intensity_pct != null ? Number(d.intensity_pct) : null,
        ledLim: (d && d.intensity_limits_pct) || null,
    });

    async function readAll() {
        const next = { ...state() };
        const get = async (url, key, pick) => {
            try {
                const r = await fetch(url);
                if (!r.ok) { next[key] = null; return null; }
                const d = await r.json();
                next[key] = pick(d);
                return d;
            } catch (_) { next[key] = null; return null; }
        };

        await Promise.all([
            get('/api/devices/beam', 'beam', d => (d && d.beam) || null),
            // One read answers both questions: the state and the brightness
            // come back together, and a second request would double the
            // traffic on a device layer that is already slow to read.
            get('/api/devices/led/status', 'led', d => (d && d.current_state) || null)
                .then(d => Object.assign(next, ledOf(d))),
            // The config is read, not remembered. It used to be whatever this
            // panel last wrote, which made the whole laser branch an echo.
            // `read()` yields the string "unknown" when the group cannot be
            // queried, and that must stay an em dash rather than become a
            // preset name.
            get('/api/devices/laser/configs', 'config',
                d => (d && d.current && d.current !== 'unknown') ? d.current : null),
        ]);

        // Power is per line, and every line's is read: a line's power is set
        // before the line is routed, so it is shown before then too. One
        // after another, not all at once: four small reads every ten seconds
        // is nothing, four at the same instant is a queue.
        next.power = {};
        for (const wl of knownLines()) {
            try {
                const r = await fetch(`/api/devices/laser/power?wavelength=${wl}`);
                const d = r.ok ? await r.json() : null;
                next.power[wl] = d && d.pct != null ? Number(d.pct) : null;
            } catch (_) { next.power[wl] = null; }
        }

        next.readAt = next.ledReadAt = Date.now();
        SharedState.set('light', next);
    }

    /**
     * Wavelengths a config may route, e.g. "488 and 561" → [488, 561].
     *
     * The safe answer when it cannot be told: an unread config, or a preset
     * whose name carries no wavelength and is not an "off", may route any
     * line, and a line that may be routed is not a line that is dark. "ALL
     * ON" is such a name. It used to come out as nothing routed, because the
     * rule was "no digits, no lines", which made all four lines on, armed and
     * powered read as not emitting.
     */
    function wavelengthsOf(config) {
        const known = knownLines();
        if (!config) return known;
        const name = String(config);
        const found = name.match(/\d{3}/g);
        if (found) return found.map(Number).filter(w => known.includes(w));
        return /\boff\b/i.test(name) ? [] : known;   // "ALL OFF" gates every line
    }

    /**
     * Is light actually coming out? Derived, never commanded (PANELS.md rule 5).
     * Anything unknown makes this unknown — an unread beam is not a dark one.
     */
    function emitting(s) {
        const sides = s.beam ? Object.values(s.beam) : null;
        if (!sides || !sides.length) return null;
        if (!sides.some(v => v === true)) {
            // A side that could not be read might be armed. Only every side
            // definitively false is a safe "not emitting".
            return sides.some(v => v == null) ? null : false;
        }
        const lines = wavelengthsOf(s.config);
        if (!lines.length) return false;
        const powers = lines.map(w => (s.power || {})[w]);
        if (powers.some(p => p == null)) return null;
        return powers.some(p => p > 0);
    }

    /**
     * Which illumination mode the rig is actually in.
     *
     * LED and Laser are two independent Micro-Manager config groups, so
     * "either LED or laser" is a POLICY, not a hardware interlock — nothing
     * stops both being open, and #106 is precisely that: `calibrateSelected`
     * never closed the LED, so every vision frame was LED brightfield with a
     * 50 ms laser gate on top, and the detector was hunting nuclei in a
     * DIC-like image.
     *
     * So `both` is a state this returns, not a state the panel makes
     * unreachable. A panel that could not express the fault would hide the
     * only bug it was built for.
     */
    function mode(s) {
        const ledOn = s.led == null ? null : s.led === 'Open';
        const routed = s.config == null ? null : routedLines(s).length > 0;
        if (ledOn === null || routed === null) return null;
        if (ledOn && routed) return 'both';
        if (ledOn) return 'led';
        if (routed) return 'laser';
        return 'off';
    }

    /**
     * The lines this config actually routes, for DISPLAY.
     *
     * Deliberately not `wavelengthsOf`, which answers "which lines could be
     * involved" and returns all of them for an unknown config — correct for
     * `emitting()`, because an unread config with unread power must come out
     * unknown rather than safe. A row is drawn as routed only when it is
     * KNOWN to be.
     */
    function routedLines(s) {
        return s.config ? wavelengthsOf(s.config) : [];
    }

    /**
     * The panel's one line: what is emitting, or what stands in the way.
     *
     * Always present, and the same line every time, so "is anything on" is
     * answered by looking at one place. The states used to be separate notes
     * (an EMITTING bar, a both-open warning, a routed-but-beam-off warning,
     * an armed-but-nothing-routed note) that appeared and went, and two of
     * them lived inside a branch that could be closed. Hiding the detail
     * must never hide the fact.
     *
     * In order of what matters: emitting; not known; both sources open;
     * routed but will not emit; armed with nothing routed (safe, surprising,
     * and the state the rig is left in); the LED alone; dark.
     */
    function status(s) {
        const em = emitting(s);
        const lines = routedLines(s);
        const sides = s.beam
            ? Object.keys(s.beam).filter(k => s.beam[k] === true).map(k => k.toUpperCase())
            : [];
        const ledOpen = s.led === 'Open';
        const ledSays = `LED open${s.ledPct != null ? ` at ${s.ledPct} %` : ''}`;

        if (em === true) {
            const lit = lines.filter(w => (s.power || {})[w] > 0);
            return {
                kind: 'emit',
                text: `EMITTING · ${lit.join(' + ')} nm · side ${sides.join(' + ')}${ledOpen ? ' · LED open too' : ''}`,
                title: 'A beam is armed, a line is routed and its power is above zero. All three are read from the hardware.',
            };
        }
        if (em === null || mode(s) === null) {
            return {
                kind: 'unknown',
                text: 'Emission state unknown',
                title: 'Not everything in the light path could be read. Unread is not the same as dark.',
            };
        }
        if (lines.length && ledOpen) {
            return {
                kind: 'warn',
                text: `LED open and ${lines.join(', ')} nm routed — choose one`,
                title: 'Both sources are open: fluorescence would sit on top of brightfield. Close the LED, or choose Off.',
            };
        }
        if (lines.length && !sides.length) {
            return {
                kind: 'warn',
                text: 'Lines routed, beam off — will not emit',
                title: 'Every volume acquisition leaves BeamEnabled at No. Arm the beam on the side in view.',
            };
        }
        if (lines.length) {
            return {
                kind: 'warn',
                text: 'Lines routed at 0 % — nothing emits',
                title: 'The beam is armed and lines are routed, but every routed line is at zero power.',
            };
        }
        if (sides.length) {
            return {
                kind: ledOpen ? 'led' : 'note',
                text: `${ledOpen ? `${ledSays} · beam` : 'Beam'} armed, nothing routed — nothing emits`,
                title: 'Safe, and the state the rig is left in: the beam is armed, and the Laser preset routes no line.',
            };
        }
        if (ledOpen) return { kind: 'led', text: ledSays, title: 'Brightfield: the LED is the only source open.' };
        return { kind: 'dark', text: 'Dark — nothing emits', title: 'The LED is closed, no line is routed and no beam is armed.' };
    }

    /* ── the presets, as buttons ─────────────────────────────────────────── */

    /** What a preset is called on its button: "488 and 561" → "488+561". */
    function presetLabel(config) {
        const name = String(config);
        const lines = name.match(/\d{3}/g);
        if (lines) return lines.join('+');
        if (/\boff\b/i.test(name)) return 'Off';
        if (/\ball\b/i.test(name)) return 'All';
        return name.trim();
    }

    /** Off first, then one line, two lines, …, and "all" (or a name unread) last. */
    function presetRank(config) {
        const name = String(config);
        const lines = name.match(/\d{3}/g);
        if (lines) return [lines.length, Number(lines[0])];
        return /\boff\b/i.test(name) ? [0, 0] : [99, 0];
    }

    /**
     * The preset list, always including whatever is actually set.
     *
     * The list comes from `/api/devices/laser/configs`, which 503s with the
     * device layer down. The read-back config is a fact whether or not the
     * catalogue of presets is available, and a row of buttons with none of
     * them lit, over lines drawn as routed, would be the panel contradicting
     * itself.
     */
    function presetList(current) {
        const list = configs.slice();
        if (current && !list.includes(current)) list.push(current);
        return list.sort((a, b) => {
            const [a0, a1] = presetRank(a), [b0, b1] = presetRank(b);
            return a0 - b0 || a1 - b1 || String(a).localeCompare(String(b));
        });
    }

    /* ── writing ─────────────────────────────────────────────────────────── */

    async function send(url, body) {
        const r = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const text = await r.text().catch(() => '');
        let d = {}; try { d = text ? JSON.parse(text) : {}; } catch (_) { /* not JSON */ }
        if (!r.ok) {
            const msg = d.detail || d.error || `${r.status}`;
            if (typeof showGentlyToast === 'function') {
                showGentlyToast(String(msg), null, null, 10000, 'error');
            }
            throw new Error(msg);
        }
        return d;
    }

    // Always re-read after a write. The response is not evidence: that is the
    // assumption that produced #106.
    async function act(fn) {
        try { await fn(); } catch (_) { /* toasted in send() */ }
        await readAll();
    }

    /**
     * The LED's switch. Opening the LED is entering brightfield, so the
     * lasers are gated first — unconditionally, not only when a line is
     * known to be routed: what the laser is doing may be unread, and unknown
     * is not safe (#106). `ALL OFF` gates outputs 5-8 at the PLogic, the
     * documented brightfield-safe state (spec §2.7), and costs nothing when
     * it already holds. Closing touches only the LED.
     *
     * BeamEnabled is left alone throughout. Setting it No here would recreate
     * the #106 state that nothing sets back.
     */
    async function ledSwitch(open) {
        if (open) await send('/api/devices/laser/config', { config: 'ALL OFF' });
        await send('/api/devices/led/set', { state: open ? 'Open' : 'Closed' });
    }

    /**
     * Route a preset of the Laser config group. A preset that routes a line
     * closes the LED first, unless the LED is read as closed already: a line
     * over an open LED is fluorescence on top of brightfield, and an LED not
     * read is not an LED known to be closed. A preset that routes nothing
     * ("ALL OFF") touches only the laser. BeamEnabled is left alone: choosing
     * a line is not arming the beam, and the status line says so.
     */
    async function route(config) {
        if (wavelengthsOf(config).length && state().led !== 'Closed') {
            await send('/api/devices/led/set', { state: 'Closed' });
        }
        await send('/api/devices/laser/config', { config });
    }

    /* ── rendering ───────────────────────────────────────────────────────── */

    const esc = t => String(t).replace(/[&<>"]/g, c =>
        ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

    const ageOf = t => (t ? `${Math.round((Date.now() - t) / 1000)}s ago` : 'never');

    function render() {
        const s = state();
        hosts.forEach(host => {
            const el = document.getElementById(host);
            if (!el) return;
            // A drag in progress, or a number half typed, is the operator's.
            // The read-back waits for it and is drawn when it is done.
            if ((rows.get(host) || []).some(r => r.editing())) { waiting.add(host); return; }
            waiting.delete(host);
            // Whatever had the keyboard keeps it across the redraw, by name.
            const at = el.contains(document.activeElement) ? document.activeElement.dataset.k : null;
            el.innerHTML = markup(s);
            wire(el, host);
            if (at) {
                const again = el.querySelector(`[data-k="${at}"]`);
                if (again && !again.disabled) {
                    again.focus({ preventScroll: true });
                    if (again.select) again.select();
                }
            }
        });
    }

    function markup(s) {
        const st = status(s);
        return `
          <div class="lp lp-light">
            <div class="lp-head">
              <span class="lp-title">Light</span>
              <span class="lp-age" title="Values are read from the hardware, not remembered">read ${ageOf(s.readAt)}</span>
            </div>
            ${ledRow(s)}
            ${presetRow(s)}
            <div class="lp-lines">${lineRows(s)}</div>
            ${beamRow(s)}
            <div class="lp-stat is-${st.kind}" role="status" title="${esc(st.title || '')}">${esc(st.text)}</div>
          </div>`;
    }

    /**
     * The LED: its shutter, and its brightness.
     *
     * The brightness is the ASI Tiger adapter's own `LED Intensity(%)`
     * property. The adapter only sends it to the controller while the LED is
     * open, so on a closed LED the number is what the next open will use —
     * which the unit says ("% when open"), because a slider that moves with
     * no change in the image otherwise reads as broken.
     */
    function ledRow(s) {
        const lim = s.ledLim || { min: 1, max: 100 };
        const val = s.ledPct;
        const seg = ['Closed', 'Open'].map(v => {
            const on = s.led === v;
            const look = on ? (v === 'Open' ? 'is-on' : 'is-rest') : '';
            const tip = v === 'Open' ? 'Gate the lasers off and open the LED' : 'Close the LED shutter';
            return `<button class="lp-mbtn ${look}" type="button" data-led-switch="${v}" data-k="led-${v}"
                            aria-pressed="${on}" title="${tip}">${v}</button>`;
        }).join('');
        return `
            <div class="lp-row lp-led">
              <span class="lp-label" title="The transmitted-light LED: brightfield. Its state and LED Intensity(%) are the ASI Tiger's own.">LED</span>
              <span class="lp-seg" role="group" aria-label="LED shutter">${seg}</span>
              <input class="lp-range" type="range" data-led-pct
                     min="${lim.min}" max="${lim.max}" step="1"
                     value="${val == null ? lim.min : val}"
                     ${val == null ? 'disabled' : ''}
                     title="${lim.min}–${lim.max} %"
                     aria-label="LED intensity percent">
              <input class="op-numbox lp-numbox" type="text" inputmode="numeric" autocomplete="off"
                     data-led-num data-k="led-pct" data-decimals="0"
                     value="${val == null ? '—' : val}"
                     ${val == null ? 'disabled' : ''}
                     aria-label="LED intensity percent, typed">
              <span class="lp-unit" ${s.led === 'Closed' && val != null ? 'title="The LED is closed — this is the brightness it will open at."' : ''}
                >${s.led === 'Closed' && val != null ? '% when open' : '%'}</span>
            </div>`;
    }

    /**
     * Routing: the Laser config group's presets, one button each (the PLogic
     * offers those combinations and no others). The one the device reports is
     * the one lit; a press is a request, and what is lit after it is what the
     * device then says.
     */
    function presetRow(s) {
        const list = presetList(s.config);
        const chips = list.map(c => {
            const on = c === s.config;
            const routes = wavelengthsOf(c).length > 0;
            const look = on ? (routes ? 'is-on' : 'is-rest') : '';
            return `<button class="lp-mbtn lp-chip ${look}" type="button" data-config="${esc(c)}" data-k="cfg-${esc(c)}"
                            aria-pressed="${on}" title="Laser preset “${esc(String(c).trim())}”${routes ? ' — closes the LED first' : ''}">${esc(presetLabel(c))}</button>`;
        }).join('');
        return `
            <div class="lp-row lp-presets">
              <span class="lp-label" title="Which lines the PLogic routes to the sheet — a preset of the Laser config group">Laser</span>
              ${list.length
                ? `<span class="lp-seg lp-chips" role="group" aria-label="Laser lines routed">${chips}</span>`
                : '<span class="lp-val">—</span>'}
            </div>`;
    }

    const LINE_COLOUR = { 405: '#8b5cf6', 488: '#38bdf8', 561: '#a3e635', 637: '#ef4444' };

    /**
     * The laser as its lines: every line the rig has, one row each — a swatch
     * in the line's colour that glows while that line is emitting, the
     * wavelength, its power as a line to drag and a number to type. A line
     * the preset does not route is drawn quieter, and its power can still be
     * set: that is when it should be. The limits are each line's own, from
     * the server.
     */
    function lineRows(s) {
        const lines = routedLines(s);
        const armed = s.beam ? Object.values(s.beam).some(v => v === true) : null;
        return knownLines().map(wl => {
            const routed = lines.includes(wl);
            const lim = (limits && limits[wl]) || { min: 0, max: 100 };
            const val = (s.power || {})[wl];
            const lit = routed && armed === true && val != null && val > 0;
            return `
              <div class="lp-line ${routed ? 'is-routed' : ''} ${lit ? 'is-lit' : ''}" data-line="${wl}">
                <span class="lp-swatch" style="--wl:${LINE_COLOUR[wl] || '#999'}"
                      title="${wl} nm: ${routed ? (lit ? 'emitting' : 'routed, not emitting') : 'not routed'}"></span>
                <span class="lp-wl">${wl}</span>
                <input class="lp-range" type="range" data-power="${wl}"
                       min="${lim.min}" max="${lim.max}" step="0.1"
                       value="${val == null ? lim.min : val}"
                       ${val == null ? 'disabled' : ''}
                       aria-label="${wl} nm power percent">
                <input class="op-numbox lp-numbox" type="text" inputmode="decimal" autocomplete="off"
                       data-power-num="${wl}" data-k="p${wl}" data-decimals="1"
                       value="${val == null ? '—' : Number(val).toFixed(1)}"
                       ${val == null ? 'disabled' : ''}
                       aria-label="${wl} nm power percent, typed">
                <span class="lp-unit">%</span>
                <span class="lp-lim" title="The limits ${wl} nm is held to on this rig">${lim.min}–${lim.max}</span>
              </div>`;
        }).join('');
    }

    /** One switch per side, each the state the hardware reports, never remembered. */
    function beamRow(s) {
        const beam = s.beam;
        const sides = beam && Object.keys(beam).length ? Object.keys(beam) : ['a', 'b'];
        const btns = sides.map(k => {
            const v = beam ? beam[k] : null;
            const on = v === true;
            return `<button class="lp-mbtn ${on ? 'is-on' : ''}" type="button" data-beam-side="${k}" data-beam-on="${on}" data-k="beam-${k}"
                            aria-pressed="${on}" title="Side ${k.toUpperCase()}: ${v == null ? 'not read' : on ? 'armed' : 'off'}">${k.toUpperCase()} ${v == null ? '?' : on ? 'on' : 'off'}</button>`;
        }).join('');
        return `
            <div class="lp-row lp-beam">
              <span class="lp-label" title="BeamEnabled on each side's scanner card: the mirror unparked, so a routed line reaches the sample from that arm.">Beam</span>
              <span class="lp-seg" role="group" aria-label="Beam per side">${btns}</span>
              <span class="lp-hint" title="The live view keeps an armed beam on the side it shows: two sheets on at once light each camera with the other's, edge-on.">follows the view while armed</span>
            </div>`;
    }

    function wire(el, host) {
        // A side's switch arms or disarms that side alone.
        el.querySelectorAll('[data-beam-side]').forEach(b => {
            b.onclick = () => act(() => send('/api/devices/beam',
                { enabled: b.dataset.beamOn !== 'true', side: b.dataset.beamSide }));
        });

        el.querySelectorAll('[data-config]').forEach(b => {
            b.onclick = () => act(() => route(b.dataset.config));
        });

        el.querySelectorAll('[data-led-switch]').forEach(b => {
            b.onclick = () => act(() => ledSwitch(b.dataset.ledSwitch === 'Open'));
        });

        // The numbers. Each is a line to drag and a box to type in, bound as
        // one control; a value is sent when it is meant — on release, on
        // Enter, on leaving the box — never while it is being dragged or
        // typed, since every one of those would be a hardware write.
        const bound = [];
        const settled = () => { if (waiting.has(host)) render(); };
        const pair = (range, box, onCommit) => {
            if (!range || !box || range.disabled || typeof NumRow === 'undefined') {
                // No number box to bind (or nothing read to bind it to): the
                // line alone still writes on release.
                if (range && !range.disabled) range.onchange = () => onCommit(Number(range.value));
                return;
            }
            bound.push(NumRow.bind(range, box, { onCommit }));
            // An edit abandoned (Esc, or a blur with nothing changed) leaves
            // a held read-back to draw.
            box.addEventListener('blur', () => setTimeout(settled, 0));
        };

        const ledPct = el.querySelector('[data-led-pct]');
        pair(ledPct, el.querySelector('[data-led-num]'),
            pct => act(() => send('/api/devices/led/intensity', { pct })));

        el.querySelectorAll('[data-power]').forEach(r => {
            const wl = Number(r.dataset.power);
            pair(r, el.querySelector(`[data-power-num="${wl}"]`),
                pct => act(() => send('/api/devices/laser/power', { wavelength: wl, pct })));
        });
        rows.set(host, bound);
    }

    /* ── lifecycle ───────────────────────────────────────────────────────── */

    async function loadStatics() {
        if (limits && configs.length) return;
        try {
            const r = await fetch('/api/devices/laser/limits');
            if (r.ok) limits = (await r.json()).limits || null;
        } catch (_) { /* the panel still renders, with default bounds */ }
        try {
            const r = await fetch('/api/devices/laser/configs');
            if (r.ok) {
                const d = await r.json();
                configs = d.configs || d.available_configs || [];
            }
        } catch (_) { /* the row shows what is read back, or an em dash */ }
    }

    async function mount(hostId) {
        hosts.add(hostId);
        if (hosts.size === 1) {
            SharedState.on('light', render);
            timer = setInterval(() => { if (visible()) refresh(); }, POLL_MS);
        }
        await loadStatics();
        render();
        await readAll();
    }

    /** Re-read everything; the presets and limits too, if they never arrived. */
    async function refresh() {
        await loadStatics();
        await readAll();
    }

    /** Is a mount on screen? The poll reads nothing for a panel nobody sees. */
    function visible() {
        for (const h of hosts) {
            const el = document.getElementById(h);
            if (el && el.offsetParent !== null) return true;
        }
        return false;
    }

    function unmount(hostId) {
        hosts.delete(hostId);
        rows.delete(hostId);
        waiting.delete(hostId);
        if (!hosts.size && timer) { clearInterval(timer); timer = null; }
    }

    // The device layer coming up is when the first read, and the presets and
    // limits, become possible: a panel mounted before it drew em dashes and a
    // row with no presets until the next visit.
    if (typeof ClientEventBus !== 'undefined') {
        ClientEventBus.on('DEVICE_LAYER_AVAILABILITY', () => { if (hosts.size) refresh(); });
    }

    return {
        mount, unmount, refresh, emitting, mode, status, wavelengthsOf,
        presetLabel, presetList, _state: state,
        // For tests: the server's limits and presets, without a server.
        _seed: (lim, cfgs) => { limits = lim || null; configs = cfgs || []; },
    };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = LightPanel;
