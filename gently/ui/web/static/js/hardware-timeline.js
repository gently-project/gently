/**
 * The hardware timeline — what the instrument did in a session, and when.
 *
 * One zoomable object rather than two plots. The whole session is one end:
 * every brightfield light, every volume's lasers, every exposure, the water
 * temperature. Scroll in on a round and it becomes the other end: the order
 * the embryos were taken in, each volume's laser window around its scan, each
 * slice's exposure at the period its frames came.
 *
 * - **Rows are hardware.** The brightfield light, one row per laser line the
 *   session used, the cameras' exposures, the temperature. Height is the
 *   setting (power %, LED %, exposure ms); colour is the embryo the light was
 *   for. Brightfield light is the dish's, so it wears no embryo's colour.
 * - **What was not recorded says so.** A volume from before the hardware was
 *   recorded is drawn from the embryo's settings, as an outline: which lasers
 *   it was routed and when they went on and off is not known.
 * - **Hover, keyboard and the table read the same thing.** A tooltip names the
 *   mark under the pointer; ←/→ walk the marks in time order; the table lists
 *   every one. Values lead, labels follow.
 *
 * Data: GET /api/sessions/{id}/hardware-sequence (gently/core/hardware_sequence.py).
 * Arithmetic: hardware-timeline-math.js. Classic script, window global.
 */
const HardwareTimeline = (() => {
    const M = (typeof HardwareTimelineMath !== 'undefined') ? HardwareTimelineMath : null;
    // The categorical colours, validated on Gently's chart surfaces in both
    // themes (dataviz validate_palette.js). Light's aqua, yellow and pink sit
    // under 3:1 on white: the legend names them and the table lists every mark.
    const PALETTE = {
        dark: ['#3987e5', '#d95926', '#199e70', '#c98500', '#d55181', '#0ca30c', '#9085e9', '#e66767'],
        light: ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948'],
    };
    const ROW_H = { bf: 34, exposure: 40, temp: 56, laser: 40 };
    const GAP = 12, TOP = 8, AXIS_H = 38, LABEL_W = 96, RIGHT = 14;
    const TOL_C = 0.3;            // the temperature graph's "at setpoint" band
    const MIN_SPAN_S = 0.005;     // close enough to see one slice's exposure
    const CLICK_PX = 4;

    // Each timeline on the page is its own: the Sessions view's, and the
    // Operations tab's, which follows the live session.
    function create() {
        let S = null;                 // this timeline's state

        // ---- helpers -----------------------------------------------------------
        const el = (tag, cls, text) => {
            const n = document.createElement(tag);
            if (cls) n.className = cls;
            if (text != null) n.textContent = text;
            return n;
        };
        const css = (name, fallback) => {
            const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
            return v || fallback;
        };
        const theme = () => (document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark');
        const lightName = l => ({ led: 'LED', room: 'room light', none: 'no light' }[l] || l || 'light');
        // A moment on Gently's clock: the zone the microscope is set to, named.
        const wall = t => `${GentlyTime.clock(t * 1000)} ${GentlyTime.zoneLabel(t * 1000)}`;

        function colours() {
            return {
                text: css('--text', '#c9d1d9'),
                muted: css('--text-muted', '#8b949e'),
                grid: css('--border', '#30363d'),
                surface: css('--bg-card', '#161b22'),
                water: css('--temp-water-color', '#22d3ee'),
                slots: PALETTE[theme()],
            };
        }

        function labelOf(id) {
            const e = (S.seq.embryos || []).find(x => x.id === id);
            return (e && e.label) || id || '';
        }

        function colourOfId(id, c) {
            if (id === undefined || id === '__bf') return c.muted;   // the dish's light, no embryo's
            const slot = S.slots[id];
            return slot == null ? c.muted : c.slots[slot];
        }
        const colourOf = (m, c) => colourOfId(m.embryo, c);

        // Several embryos' marks in one pixel: a 45° hatch, never one embryo's colour.
        function hatch(ctx, c) {
            if (S.hatch && S.hatch.colour === c.muted) return S.hatch.pattern;
            const t = document.createElement('canvas');
            t.width = t.height = 6;
            const g = t.getContext('2d');
            g.strokeStyle = c.muted;
            g.lineWidth = 1.25;
            g.beginPath();
            g.moveTo(0, 6); g.lineTo(6, 0);
            g.moveTo(-1, 1); g.lineTo(1, -1);
            g.moveTo(5, 7); g.lineTo(7, 5);
            g.stroke();
            S.hatch = { colour: c.muted, pattern: ctx.createPattern(t, 'repeat') };
            return S.hatch.pattern;
        }

        const shown = m => m.embryo === undefined || !S.hidden.has(S.slots[m.embryo] == null ? '__other' : m.embryo);

        // ---- data --------------------------------------------------------------
        function prepare(seq) {
            S.seq = seq;
            S.rows = M.rows(seq);
            S.marks = M.marks(seq);
            S.slots = M.slots(seq.embryos || []);
            S.t0 = seq.t0;
            const pad = seq.t1 > seq.t0 ? Math.max(0.5, 0.02 * (seq.t1 - seq.t0)) : 1;
            S.bounds = { a: seq.t0 - pad, b: seq.t1 + pad };
            S.view = { ...S.bounds };
            // One stop per thing the hardware did — a volume, a brightfield frame —
            // in time order: what ←/→ walk. Each stop is its earliest mark (a
            // volume's laser window, a frame's light), which spans the rest of it.
            const seen = new Set();
            S.order = Object.entries(S.marks)
                .flatMap(([row, list]) => list.map(m => Object.assign(m, { row })))
                .sort((p, q) => p.a - q.a)
                .filter(m => !seen.has(m.v || m.f) && seen.add(m.v || m.f));
            S.rounds = M.roundsOf(seq, M.roundPause(seq.volumes || []));
            S.top = {};
            for (const r of S.rows) {
                if (r.key === 'temp') continue;
                const vals = (S.marks[r.key] || []).map(m => m.value).filter(v => typeof v === 'number');
                S.top[r.key] = M.niceCeil(vals.length ? Math.max(...vals) : 100);
            }
            S.tempRange = M.tempRange(seq.temperature || []);
        }

        // ---- geometry ----------------------------------------------------------
        function plotW() { return Math.max(40, S.w - LABEL_W - RIGHT); }
        function x(t) { return LABEL_W + ((t - S.view.a) / (S.view.b - S.view.a)) * plotW(); }
        function tOf(px) { return S.view.a + ((px - LABEL_W) / plotW()) * (S.view.b - S.view.a); }
        function rowH(key) { return ROW_H[key] || ROW_H.laser; }

        function layout() {
            let y = TOP;
            S.layout = {};
            for (const r of S.rows) {
                S.layout[r.key] = { y, h: rowH(r.key) };
                y += rowH(r.key) + GAP;
            }
            S.axisY = y - GAP + 6;
            return y - GAP + AXIS_H;
        }

        function rowAt(py) {
            for (const r of S.rows) {
                const L = S.layout[r.key];
                if (py >= L.y - GAP / 2 && py <= L.y + L.h + GAP / 2) return r.key;
            }
            return null;
        }

        // ---- drawing -----------------------------------------------------------
        // Marks sit on whole pixels: an edge between two is drawn blurred.
        function snap(x0, y0, w, h) {
            const a = Math.round(x0), t = Math.round(y0);
            return [a, t, Math.max(1, Math.round(x0 + w) - a), Math.max(1, Math.round(y0 + h) - t)];
        }

        function bar(ctx, x0, y0, w, h, fill, alpha = 1) {
            [x0, y0, w, h] = snap(x0, y0, w, h);
            const r = Math.min(4, w / 2, h / 2);
            ctx.globalAlpha = alpha;
            ctx.fillStyle = fill;
            ctx.beginPath();
            if (r >= 1 && ctx.roundRect) ctx.roundRect(x0, y0, w, h, [r, r, 0, 0]);
            else ctx.rect(x0, y0, w, h);
            ctx.fill();
            ctx.globalAlpha = 1;
        }

        function outline(ctx, x0, y0, w, h, stroke) {
            [x0, y0, w, h] = snap(x0, y0, w, h);
            ctx.strokeStyle = stroke;
            ctx.lineWidth = 1.5;
            ctx.setLineDash([3, 2]);
            ctx.strokeRect(x0 + 0.75, y0 + 0.75, Math.max(0.5, w - 1.5), Math.max(0.5, h - 1.5));
            ctx.setLineDash([]);
        }

        function heightOf(m, key, h) {
            const room = h - 4;
            if (typeof m.value !== 'number') return room;     // a light with no level: all of it
            return Math.max(2, (m.value / S.top[key]) * room);
        }

        // The pixel box a mark is drawn in: for hover rings and keyboard focus.
        function boxOf(m) {
            const L = S.layout[m.row];
            if (!L) return null;
            const hv = heightOf(m, m.row, L.h);
            const x0 = x(m.a), x1 = x(m.b);
            const w = Math.max(2, x1 - x0);
            return { x: x0 - (w === 2 ? 1 : 0), y: L.y + L.h - hv, w, h: hv };
        }

        function drawStack(ctx, m, c, y0, h, col) {
            const hv = heightOf(m, 'exposure', h);
            const top = y0 + h - hv;
            const slices = M.sliceTimes(m.v);
            const periodPx = slices.length > 1 ? x(slices[1][0]) - x(slices[0][0]) : 0;
            if (periodPx >= 3) {
                for (const [sa, sb] of slices) {
                    if (sb < S.view.a || sa > S.view.b) continue;
                    const w = Math.max(1, x(sb) - x(sa));
                    if (m.v.recorded) bar(ctx, x(sa), top, w, hv, col);
                    else outline(ctx, x(sa), top, Math.max(2, w), hv, col);
                }
                return;
            }
            const w = Math.max(2, x(m.b) - x(m.a));
            if (m.v.recorded) bar(ctx, x(m.a) - (w === 2 ? 1 : 0), top, w, hv, col);
            else outline(ctx, x(m.a) - (w === 2 ? 1 : 0), top, w, hv, col);
        }

        // Denser than one mark per four pixels: merged per pixel column.
        const isDense = (n) => n > plotW() / 4;

        function drawBinned(ctx, key, vis, y0, h, c) {
            for (const r of M.bins(vis, t => x(t) - LABEL_W, plotW(), m => heightOf(m, key, h))) {
                const X = LABEL_W + r.x0, w = r.x1 - r.x0, top = y0 + h - r.h;
                if (r.who === '__several') {
                    bar(ctx, X, top, w, r.h, c.muted, 0.18);
                    ctx.fillStyle = hatch(ctx, c);
                    ctx.fillRect(X, top, w, r.h);
                    S.several = true;
                    continue;
                }
                const col = colourOfId(r.who, c);
                if (r.recorded) bar(ctx, X, top, w, r.h, col);
                else outline(ctx, X, top, Math.max(2, w), r.h, col);
            }
        }

        function drawMarks(ctx, key, y0, h, c) {
            const vis = (S.marks[key] || []).filter(m => m.b >= S.view.a && m.a <= S.view.b && shown(m));
            S.dense[key] = isDense(vis.length);
            if (S.dense[key]) return drawBinned(ctx, key, vis, y0, h, c);
            for (const m of vis) {
                const col = colourOf(m, c);
                if (m.kind === 'stack') { drawStack(ctx, m, c, y0, h, col); continue; }
                const hv = heightOf(m, key, h);
                const top = y0 + h - hv;
                const x0 = x(m.a), w = Math.max(2, x(m.b) - x0), nudge = w === 2 ? 1 : 0;
                if (m.kind === 'laser') {
                    // The laser window as a wash, the scan inside it solid.
                    bar(ctx, x0 - nudge, top, w, hv, col, 0.22);
                    const sw = Math.max(2, x(m.scanB) - x(m.scanA));
                    bar(ctx, x(m.scanA) - (sw === 2 ? 1 : 0), top, sw, hv, col);
                } else if (m.kind === 'light' || m.kind === 'frame') {
                    bar(ctx, x0 - nudge, top, w, hv, col);
                } else {
                    // setting, filed, frame-filed: not recorded, so outlined.
                    outline(ctx, x0 - nudge, top, w, hv, col);
                }
            }
        }

        function drawTemp(ctx, y0, h, c) {
            const temps = S.seq.temperature || [];
            const R = S.tempRange;
            if (!R || !temps.length) return;
            const y = v => y0 + h - ((v - R.lo) / (R.hi - R.lo)) * h;
            const inView = temps.filter((r, i) => {
                const next = temps[i + 1], prev = temps[i - 1];
                return (r[0] >= S.view.a && r[0] <= S.view.b)
                    || (next && next[0] >= S.view.a && r[0] <= S.view.a)
                    || (prev && prev[0] <= S.view.b && r[0] >= S.view.b);
            });
            if (!inView.length) return;
            ctx.save();
            ctx.beginPath();
            ctx.rect(LABEL_W, y0, plotW(), h);
            ctx.clip();
            // The band around the setpoint, as a wash.
            ctx.fillStyle = c.water;
            ctx.globalAlpha = 0.10;
            for (let i = 0; i < inView.length; i++) {
                const r = inView[i], sp = r[2];
                if (sp == null) continue;
                const xa = x(r[0]), xb = i + 1 < inView.length ? x(inView[i + 1][0]) : xa + 1;
                ctx.fillRect(xa, y(sp + TOL_C), Math.max(1, xb - xa), y(sp - TOL_C) - y(sp + TOL_C));
            }
            ctx.globalAlpha = 1;
            // The setpoint: a reference, not a peer — a dashed hairline in ink.
            ctx.strokeStyle = c.muted;
            ctx.lineWidth = 1;
            ctx.setLineDash([4, 3]);
            ctx.beginPath();
            let open = false;
            inView.forEach((r, i) => {
                if (r[2] == null) { open = false; return; }
                const xa = x(r[0]), xb = i + 1 < inView.length ? x(inView[i + 1][0]) : xa;
                if (!open) { ctx.moveTo(xa, y(r[2])); open = true; } else ctx.lineTo(xa, y(r[2]));
                ctx.lineTo(xb, y(r[2]));
            });
            ctx.stroke();
            ctx.setLineDash([]);
            // The water: the data, one 2px line.
            ctx.strokeStyle = c.water;
            ctx.lineWidth = 2;
            ctx.lineJoin = ctx.lineCap = 'round';
            ctx.beginPath();
            inView.forEach((r, i) => (i ? ctx.lineTo(x(r[0]), y(r[1])) : ctx.moveTo(x(r[0]), y(r[1]))));
            ctx.stroke();
            ctx.restore();
        }

        function draw() {
            if (!S || !S.canvas || !S.seq) return;
            const c = colours();
            const ctx = S.ctx;
            const dpr = window.devicePixelRatio || 1;
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
            ctx.clearRect(0, 0, S.w, S.h);
            S.several = false;
            S.dense = {};

            for (const r of S.rows) {
                const L = S.layout[r.key];
                // Its baseline, a recessive hairline. (Its name is HTML: labels().)
                ctx.fillStyle = c.grid;
                ctx.fillRect(LABEL_W, L.y + L.h, plotW(), 1);
                if (r.key === 'temp') drawTemp(ctx, L.y, L.h, c);
                else {
                    ctx.save();
                    ctx.beginPath();
                    ctx.rect(LABEL_W - 2, L.y - 2, plotW() + 4, L.h + 4);
                    ctx.clip();
                    drawMarks(ctx, r.key, L.y, L.h, c);
                    ctx.restore();
                }
            }

            // The axis: its line and ticks here, its words in HTML.
            const T = M.ticks(S.view, S.t0, Math.max(3, Math.floor(plotW() / 110)));
            ctx.fillStyle = c.grid;
            ctx.fillRect(LABEL_W, S.axisY, plotW(), 1);
            const ticks = T.ticks.filter(tk => x(tk.t) >= LABEL_W - 1 && x(tk.t) <= LABEL_W + plotW() + 1);
            for (const tk of ticks) ctx.fillRect(Math.round(x(tk.t)), S.axisY, 1, 4);
            axisWords(ticks, T.caption);

            // What the pointer or the keyboard is on. A focused mark is placed
            // again on every draw: the view may have moved under it.
            if (S.focus) {
                S.focus.box = boxOf(S.focus.m);
                S.cross = S.focus.box ? S.focus.box.x + S.focus.box.w / 2 : null;
            }
            const focus = S.focus || S.hover;
            if (focus && focus.box) {
                const b = focus.box;
                ctx.strokeStyle = c.text;
                ctx.lineWidth = 1.5;
                ctx.strokeRect(b.x - 2.5, b.y - 2.5, b.w + 5, b.h + 5);
            }
            if (S.cross != null) {
                ctx.fillStyle = c.muted;
                ctx.globalAlpha = 0.6;
                ctx.fillRect(Math.round(S.cross), TOP, 1, S.axisY - TOP);
                ctx.globalAlpha = 1;
            }
            if (S.severalKey) S.severalKey.hidden = !S.several;
            S.root.dataset.viewA = String(S.view.a);
            S.root.dataset.viewB = String(S.view.b);
            where();
        }

        function scaleText(r) {
            if (r.key === 'temp') {
                return S.tempRange ? `${S.tempRange.lo.toFixed(1)}–${S.tempRange.hi.toFixed(1)} °C` : '°C';
            }
            return `0–${+S.top[r.key].toPrecision(3)} ${r.unit}`;
        }

        // Each row's name and scale, as HTML beside the canvas: canvas text gets
        // no subpixel smoothing and reads smudged next to the page's own text.
        function labels() {
            S.rowLabels.replaceChildren();
            for (const r of S.rows) {
                const L = S.layout[r.key];
                const box = el('div', 'hwt-row-label');
                box.style.top = `${Math.round(L.y + L.h / 2 - 14)}px`;
                box.style.width = `${LABEL_W - 12}px`;
                box.append(el('strong', null, r.label), el('span', null, scaleText(r)));
                S.rowLabels.appendChild(box);
            }
            S.axisEl.style.top = `${S.axisY + 6}px`;
        }

        function axisWords(ticks, caption) {
            while (S.tickEls.length < ticks.length) {
                const t = el('span', 'hwt-tick');
                S.axisEl.appendChild(t);
                S.tickEls.push(t);
            }
            S.tickEls.forEach((t, i) => {
                const tk = ticks[i];
                t.hidden = !tk;
                if (!tk) return;
                t.textContent = tk.label;
                t.style.left = `${Math.round(x(tk.t)) - 40}px`;  // 80 px wide, centred
            });
            S.captionEl.textContent = caption;
        }

        function resize() {
            if (!S || !S.canvas) return;
            const w = Math.max(240, Math.floor(S.plot.clientWidth));
            S.w = w;
            S.h = layout();
            const dpr = window.devicePixelRatio || 1;
            S.canvas.width = Math.round(w * dpr);
            S.canvas.height = Math.round(S.h * dpr);
            S.canvas.style.width = `${w}px`;
            S.canvas.style.height = `${S.h}px`;
            labels();
            draw();
        }

        // ---- words: the tooltip, the readout, the table --------------------------
        function clock(t) { return M.fmtClock(t - S.t0, S.view.b - S.view.a < 120 ? 2 : 0); }

        function linesOf(m) {
            // [value, label] pairs: values lead, labels follow.
            const out = [];
            if (m.v) {
                const v = m.v;
                const head = `${labelOf(v.embryo)} · volume t${v.t ?? '?'}${v.side && v.side !== 'A' ? ` (side ${v.side})` : ''}`;
                const lit = v.recorded ? (v.lasers || {}) : (v.settings || {});
                for (const [wl, pct] of Object.entries(lit)) {
                    out.push([pct == null ? 'unknown' : `${+pct.toPrecision(4)} %`, `${wl} nm${v.recorded ? '' : ' (setting)'}`]);
                }
                if (v.slices && v.exposure_ms) out.push([`${v.slices} × ${+v.exposure_ms.toPrecision(4)} ms`, 'slices × exposure']);
                if (v.recorded) {
                    if (v.first_frame != null && v.last_frame != null && v.slices > 1) {
                        out.push([M.fmtDuration((v.last_frame - v.first_frame) / (v.slices - 1)), 'between frames, as read out']);
                    }
                    if (v.lasers_on != null && v.lasers_off != null) {
                        out.push([M.fmtDuration(v.lasers_off - v.lasers_on), `lasers on, ${clock(v.lasers_on)} → ${clock(v.lasers_off)}`]);
                    }
                    const began = M.stackStart(v);
                    if (began != null && v.last_frame != null) out.push([M.fmtDuration(v.last_frame - began), 'stack, to its last frame read out']);
                    if (v.side_began != null && v.side !== 'A') out.push([clock(v.scan_started), 'both sides in one scan, from']);
                    if (v.laser_config) out.push([v.laser_config, 'preset']);
                } else {
                    out.push(['not recorded', 'the embryo’s settings, not what the lasers were sent']);
                    if (v.scan_started != null) out.push([clock(v.scan_started), `scan began (${wall(v.scan_started)})`]);
                }
                return { head, rows: out };
            }
            const f = m.f;
            const fieldWord = f.field != null ? ` · field ${f.field + 1}${f.fields ? ` of ${f.fields}` : ''}` : '';
            const head = `Brightfield${fieldWord}${f.frame != null ? ` · frame ${f.frame}` : ''}`;
            const light = lightName(f.light);
            if (f.led_pct != null) out.push([`${f.led_pct} %`, light]);
            else out.push([light, 'light']);
            if (f.light_on != null && f.light_off != null) {
                out.push([M.fmtDuration(f.light_off - f.light_on), `light on, ${clock(f.light_on)} → ${clock(f.light_off)}`]);
            } else if (f.light_on != null) {
                out.push(['not seen off', `on at ${clock(f.light_on)}; it did not answer when put out`]);
            } else if (f.recorded) {
                out.push(['—', f.light === 'none' ? 'no light of its own' : 'light already on; not switched by this frame']);
            }
            if (f.exposure_ms) out.push([`${f.exposure_ms} ms`, 'exposure']);
            if (!f.recorded) out.push(['not recorded', `filed ${f.filed != null ? clock(f.filed) : ''}; when its light was on is not known`]);
            return { head, rows: out };
        }

        function tempLines(t) {
            const temps = S.seq.temperature || [];
            if (!temps.length) return null;
            let lo = 0, hi = temps.length - 1;
            while (hi - lo > 1) {
                const mid = (lo + hi) >> 1;
                if (temps[mid][0] < t) lo = mid; else hi = mid;
            }
            const r = Math.abs(temps[lo][0] - t) <= Math.abs(temps[hi][0] - t) ? temps[lo] : temps[hi];
            const rows = [[`${r[1].toFixed(2)} °C`, 'water']];
            if (r[2] != null) rows.push([`${r[2].toFixed(2)} °C`, 'setpoint']);
            return { head: `Temperature · ${clock(r[0])} (${wall(r[0])})`, rows, t: r[0] };
        }

        function showTip(info, px, py) {
            const tip = S.tip;
            tip.replaceChildren();
            tip.appendChild(el('div', 'hwt-tip-head', info.head));
            for (const [value, label] of info.rows) {
                const row = el('div', 'hwt-tip-row');
                row.appendChild(el('strong', null, value));
                row.appendChild(el('span', null, label));
                tip.appendChild(row);
            }
            tip.hidden = false;
            const pw = S.plot.clientWidth;
            const tw = tip.offsetWidth, th = tip.offsetHeight;
            let left = px + 14;
            if (left + tw > pw - 4) left = Math.max(4, px - tw - 14);
            let top = py + 12;
            if (top + th > S.h) top = Math.max(0, py - th - 12);
            tip.style.left = `${left}px`;
            tip.style.top = `${top}px`;
        }

        function hideTip() { if (S && S.tip) S.tip.hidden = true; }

        function say(info) {
            if (!S.live || !info) return;
            S.live.textContent = `${info.head}. ${info.rows.map(([v, l]) => `${l}: ${v}`).join('; ')}`;
        }

        function roundIndexAt(t) {
            return S.rounds.findIndex(r => t >= r.a - 1e-9 && t <= r.b + 1e-9);
        }

        function where() {
            if (!S.whereEl) return;
            const span = S.view.b - S.view.a, full = S.bounds.b - S.bounds.a;
            let text;
            if (span >= full * 0.999) {
                text = `Whole session · ${M.fmtDuration(S.seq.t1 - S.seq.t0)}`;
            } else {
                const mid = (S.view.a + S.view.b) / 2;
                const i = roundIndexAt(mid);
                const r = S.rounds[i];
                const name = r ? `Round ${i + 1} of ${S.rounds.length}` : '';
                if (r && span <= Math.max(1.2, (r.b - r.a) * 1.6)) {
                    // Closer in than the round itself: say which part of it.
                    text = span < (r.b - r.a) * 0.6
                        ? `${name} · ${clock(S.view.a)} – ${clock(S.view.b)}`
                        : `${name} · ${M.fmtClock(r.a - S.t0)}`;
                } else text = `${clock(S.view.a)} – ${clock(S.view.b)}`;
            }
            S.whereEl.textContent = text;
        }

        function table() {
            const wrap = S.tableWrap;
            const t = el('table', 'hwt-table');
            const head = el('tr');
            for (const h of ['Time', 'What', 'Embryo', 'Light', 'Exposure', 'Duration', 'Recorded']) head.appendChild(el('th', null, h));
            const thead = el('thead');
            thead.appendChild(head);
            t.appendChild(thead);
            const body = el('tbody');
            const items = [
                ...(S.seq.volumes || []).map(v => ({ at: v.lasers_on ?? v.scan_started, v })),
                ...(S.seq.bf || []).map(f => ({ at: f.light_on ?? f.exposed ?? f.filed, f })),
            ].filter(i => i.at != null).sort((p, q) => p.at - q.at);
            for (const i of items) {
                const tr = el('tr');
                const cells = [];
                if (i.v) {
                    const v = i.v;
                    const lit = v.recorded ? (v.lasers || {}) : (v.settings || {});
                    cells.push(
                        M.fmtClock(i.at - S.t0, 2),
                        `Volume t${v.t ?? '?'}${v.side && v.side !== 'A' ? ` side ${v.side}` : ''}`,
                        labelOf(v.embryo),
                        Object.entries(lit).map(([wl, p]) => `${wl} nm ${p == null ? '?' : `${+p.toPrecision(4)} %`}`).join(', ') || '—',
                        v.slices && v.exposure_ms ? `${v.slices} × ${v.exposure_ms} ms` : '—',
                        v.recorded && v.lasers_on != null && v.lasers_off != null
                            ? `lasers ${M.fmtDuration(v.lasers_off - v.lasers_on)}`
                            : (v.scan_started != null && v.last_frame != null ? `light ≥ ${M.fmtDuration(v.last_frame - v.scan_started)}` : '—'),
                        v.recorded ? 'yes' : 'settings only',
                    );
                } else {
                    const f = i.f;
                    cells.push(
                        M.fmtClock(i.at - S.t0, 2),
                        `Brightfield${f.field != null ? ` field ${f.field + 1}` : ''}`,
                        '—',
                        `${lightName(f.light)}${f.led_pct != null ? ` ${f.led_pct} %` : ''}`,
                        f.exposure_ms ? `${f.exposure_ms} ms` : '—',
                        f.light_on != null && f.light_off != null ? `light ${M.fmtDuration(f.light_off - f.light_on)}` : '—',
                        f.recorded ? 'yes' : 'filing time only',
                    );
                }
                for (const cell of cells) tr.appendChild(el('td', null, cell));
                body.appendChild(tr);
            }
            t.appendChild(body);
            wrap.replaceChildren(t);
        }

        // ---- interaction -------------------------------------------------------
        function zoomToRound(i) {
            const r = S.rounds[i];
            if (!r) return;
            S.view = M.roundView(r, S.bounds);
            S.roundIndex = i;
            draw();
        }

        // From the whole session, › opens the first round and ‹ the last; from a
        // round, its neighbour; from anywhere else, the next round either way.
        function stepRound(dir) {
            const n = S.rounds.length;
            if (!n) return;
            if (S.view.b - S.view.a >= (S.bounds.b - S.bounds.a) * 0.999) return zoomToRound(dir > 0 ? 0 : n - 1);
            const mid = (S.view.a + S.view.b) / 2;
            const at = roundIndexAt(mid);
            let i;
            if (at >= 0) i = at + dir;
            else if (dir > 0) i = S.rounds.findIndex(r => r.a > mid);
            else i = S.rounds.map(r => r.b < mid).lastIndexOf(true);
            if (i < 0 || i >= n) i = dir > 0 ? n - 1 : 0;
            zoomToRound(i);
        }

        function whole() {
            S.view = { ...S.bounds };
            draw();
        }

        function pick(px, py) {
            const key = rowAt(py);
            if (!key || px < LABEL_W || px > LABEL_W + plotW()) return null;
            const t = tOf(px);
            if (key === 'temp') {
                const info = tempLines(t);
                return info ? { info, cross: x(info.t) } : null;
            }
            const reach = (6 / plotW()) * (S.view.b - S.view.a);
            const list = (S.marks[key] || []).filter(shown);
            if (S.dense && S.dense[key]) {
                const near = list.filter(m => t >= m.a - reach && t <= m.b + reach);
                const ids = [...new Set(near.map(m => m.embryo))];
                if (ids.length > 1) {
                    const rows = ids.map(id => [`${near.filter(m => m.embryo === id).length}×`, id === undefined ? 'brightfield' : labelOf(id)]);
                    rows.push(['click', 'opens the round; scroll zooms in']);
                    return { m: near[0], info: { head: `${near.length} marks here`, rows }, box: null, cross: px };
                }
            }
            const m = M.hit(list, t, reach);
            if (!m) return null;
            m.row = key;
            return { m, info: linesOf(m), box: boxOf(m), cross: px };
        }

        function onMove(e) {
            const rect = S.plot.getBoundingClientRect();
            const px = e.clientX - rect.left, py = e.clientY - rect.top;
            if (S.drag) {
                const dx = px - S.drag.px;
                if (Math.abs(dx) > CLICK_PX) S.drag.moved = true;
                if (S.drag.moved) {
                    const dt = -(dx / plotW()) * (S.drag.view.b - S.drag.view.a);
                    S.view = M.pan(S.drag.view, dt, S.bounds);
                    hideTip();
                    draw();
                }
                return;
            }
            const hit = pick(px, py);
            S.hover = hit;
            S.focus = null;
            S.cross = hit ? hit.cross : (px >= LABEL_W && px <= LABEL_W + plotW() ? px : null);
            if (hit) showTip(hit.info, px, py); else hideTip();
            draw();
        }

        function onDown(e) {
            if (e.button !== 0) return;
            const rect = S.plot.getBoundingClientRect();
            S.drag = { px: e.clientX - rect.left, py: e.clientY - rect.top, view: { ...S.view }, moved: false };
            S.plot.setPointerCapture?.(e.pointerId);
        }

        function onUp(e) {
            const d = S.drag;
            S.drag = null;
            S.plot.releasePointerCapture?.(e.pointerId);
            if (!d || d.moved) return;
            // A click on a mark opens its round.
            const hit = pick(d.px, d.py);
            if (hit && hit.m) {
                const i = roundIndexAt((hit.m.a + hit.m.b) / 2);
                if (i >= 0) zoomToRound(i);
            }
        }

        function onWheel(e) {
            e.preventDefault();
            const rect = S.plot.getBoundingClientRect();
            const px = e.clientX - rect.left;
            const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
            const dx = e.deltaX * unit, dy = e.deltaY * unit;
            if (e.shiftKey || Math.abs(dx) > Math.abs(dy)) {
                const d = e.shiftKey ? (dy || dx) : dx;
                S.view = M.pan(S.view, (d / plotW()) * (S.view.b - S.view.a), S.bounds);
            } else {
                const t = tOf(Math.min(Math.max(px, LABEL_W), LABEL_W + plotW()));
                S.view = M.zoomAt(S.view, t, Math.exp(dy * 0.0015), S.bounds, MIN_SPAN_S);
            }
            hideTip();
            S.hover = null;
            draw();
        }

        function focusMark(i) {
            if (!S.order.length) return;
            S.focusIndex = Math.max(0, Math.min(S.order.length - 1, i));
            const m = S.order[S.focusIndex];
            const span = S.view.b - S.view.a;
            if (m.a < S.view.a || m.b > S.view.b) {
                S.view = M.pan(S.view, (m.a + m.b) / 2 - (S.view.a + S.view.b) / 2, S.bounds);
                if (m.b - m.a > span) S.view = M.zoomAt(S.view, m.a, (m.b - m.a) * 1.2 / span, S.bounds, MIN_SPAN_S);
            }
            const info = linesOf(m);
            S.focus = { m, info, box: null };
            S.hover = null;
            draw();
            if (S.focus.box) showTip(info, S.focus.box.x + S.focus.box.w, S.focus.box.y);
            say(info);
        }

        // Redraw, with the focused mark's tooltip moved to where the mark now is.
        function redrawFocus() {
            draw();
            if (S.focus && S.focus.box) showTip(S.focus.info, S.focus.box.x + S.focus.box.w, S.focus.box.y);
            else hideTip();
        }

        function onKey(e) {
            const k = e.key;
            const mid = (S.view.a + S.view.b) / 2;
            if (k === 'ArrowRight' || k === 'ArrowLeft') {
                const dir = k === 'ArrowRight' ? 1 : -1;
                let i = S.focusIndex;
                if (i == null || !S.focus) i = Math.max(0, S.order.findIndex(m => m.a >= S.view.a));
                else i += dir;
                // Past marks of embryos the legend has hidden.
                while (i >= 0 && i < S.order.length && !shown(S.order[i])) i += dir;
                if (i >= 0 && i < S.order.length) focusMark(i);
            } else if (k === 'Enter' && S.focus) {
                const i = roundIndexAt((S.focus.m.a + S.focus.m.b) / 2);
                if (i >= 0) zoomToRound(i);
            } else if (k === '+' || k === '=') {
                S.view = M.zoomAt(S.view, S.focus ? S.focus.m.a : mid, 0.5, S.bounds, MIN_SPAN_S);
                redrawFocus();
            } else if (k === '-' || k === '_') {
                S.view = M.zoomAt(S.view, mid, 2, S.bounds, MIN_SPAN_S);
                redrawFocus();
            } else if (k === '0' || k === 'Home') {
                whole();
            } else if (k === '[' || k === ']') {
                stepRound(k === ']' ? 1 : -1);
            } else if (k === 'Escape') {
                S.focus = null;
                S.cross = null;
                hideTip();
                draw();
            } else return;
            e.preventDefault();
        }

        // ---- building it -------------------------------------------------------
        function legend() {
            const box = S.legendEl;
            box.replaceChildren();
            const c = colours();
            const embryos = S.seq.embryos || [];
            const used = new Set((S.seq.volumes || []).map(v => v.embryo));
            const add = (key, text, colour, title) => {
                const b = el('button', 'hwt-key');
                b.type = 'button';
                b.dataset.key = key;
                b.setAttribute('aria-pressed', String(!S.hidden.has(key)));
                b.title = title;
                const sw = el('span', 'hwt-swatch');
                sw.style.background = colour;
                b.append(sw, el('span', null, text));
                b.addEventListener('click', () => {
                    if (S.hidden.has(key)) S.hidden.delete(key); else S.hidden.add(key);
                    b.setAttribute('aria-pressed', String(!S.hidden.has(key)));
                    hideTip();
                    draw();
                });
                box.appendChild(b);
            };
            let others = 0;
            for (const e of embryos) {
                if (!used.has(e.id)) continue;
                const slot = S.slots[e.id];
                if (slot == null) { others++; continue; }
                add(e.id, e.label, c.slots[slot], `Show or hide ${e.label}`);
            }
            if (others) add('__other', `${others} more`, c.muted, 'Embryos past the eighth share one colour');
            // Shown while some pixel holds more than one embryo's marks.
            S.severalKey = el('span', 'hwt-key hwt-key-static hwt-key-several');
            S.severalKey.append(el('span', 'hwt-swatch hwt-swatch-hatch'), el('span', null, 'Several embryos (zoom in)'));
            S.severalKey.hidden = !S.several;
            box.appendChild(S.severalKey);
            if ((S.seq.bf || []).length) {
                const k = el('span', 'hwt-key hwt-key-static');
                const sw = el('span', 'hwt-swatch');
                sw.style.background = c.muted;
                k.append(sw, el('span', null, 'Brightfield (the dish)'));
                box.appendChild(k);
            }
        }

        function destroy() {
            if (!S) return;
            S.ro?.disconnect();
            S.mo?.disconnect();
            S = null;
        }

        async function mount(host, sessionId) {
            destroy();
            if (!M) { host.textContent = 'The hardware timeline did not load.'; return; }
            const root = el('div', 'hwt');
            root.dataset.state = 'loading';
            host.replaceChildren(root);
            S = { root, host, sessionId, hidden: new Set(), hover: null, focus: null, cross: null, dense: {}, several: false };
            const mine = S;
            root.appendChild(el('div', 'empty-tab', 'Reading what the hardware did…'));
            let seq;
            try {
                const r = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}/hardware-sequence`);
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                seq = await r.json();
            } catch (err) {
                if (S !== mine) return;
                root.dataset.state = 'error';
                root.replaceChildren(el('div', 'empty-tab', `Could not read the hardware sequence (${err.message || err}).`));
                return;
            }
            if (S !== mine || !root.isConnected) return;
            if (seq.t0 == null) {
                root.dataset.state = 'empty';
                root.replaceChildren(el('div', 'empty-tab', 'Nothing was acquired in this session yet.'));
                return;
            }
            prepare(seq);
            root.replaceChildren();

            const barEl = el('div', 'hwt-bar');
            S.legendEl = el('div', 'hwt-legend');
            S.legendEl.setAttribute('role', 'group');
            S.legendEl.setAttribute('aria-label', 'Embryos: show or hide');
            const tools = el('div', 'hwt-tools');
            const btn = (act, text, title) => {
                const b = el('button', 'hwt-btn', text);
                b.type = 'button';
                b.dataset.act = act;
                b.title = title;
                return b;
            };
            const prev = btn('prev', '‹', 'Previous round  [');
            prev.setAttribute('aria-label', 'Previous round');
            const next = btn('next', '›', 'Next round  ]');
            next.setAttribute('aria-label', 'Next round');
            S.whereEl = el('span', 'hwt-where');
            const all = btn('all', 'Whole session', 'The whole session  0');
            const tbl = btn('table', 'Table', 'Every mark as a table');
            tbl.setAttribute('aria-pressed', 'false');
            tools.append(prev, S.whereEl, next, all, tbl);
            barEl.append(S.legendEl, tools);

            S.plot = el('div', 'hwt-plot');
            S.plot.tabIndex = 0;
            S.plot.setAttribute('role', 'application');
            S.plot.setAttribute('aria-roledescription', 'hardware timeline');
            const nv = (seq.volumes || []).length, nf = (seq.bf || []).length;
            S.plot.setAttribute('aria-label',
                `What the hardware did: ${nv} volume${nv === 1 ? '' : 's'} and ${nf} brightfield frame${nf === 1 ? '' : 's'} `
                + `over ${M.fmtDuration(seq.t1 - seq.t0)}. Arrow keys step through them, Enter opens a round, 0 shows the whole session.`);
            S.canvas = el('canvas', 'hwt-canvas');
            S.ctx = S.canvas.getContext('2d');
            S.tip = el('div', 'hwt-tip');
            S.tip.hidden = true;
            // The words over the canvas: row names and scales, the axis.
            const overlay = el('div', 'hwt-overlay');
            S.rowLabels = el('div', 'hwt-row-labels');
            S.axisEl = el('div', 'hwt-axis');
            S.captionEl = el('span', 'hwt-caption');
            S.captionEl.style.left = `${LABEL_W}px`;
            S.axisEl.appendChild(S.captionEl);
            S.tickEls = [];
            overlay.append(S.rowLabels, S.axisEl);
            S.plot.append(S.canvas, overlay, S.tip);

            const hint = el('p', 'hwt-hint', 'Scroll to zoom, drag to pan. Click a mark to open its round; double-click for the whole session. Keys: ← → step, Enter opens, [ ] rounds, 0 whole.');
            const unrec = (seq.volumes || []).filter(v => !v.recorded).length + (seq.bf || []).filter(f => !f.recorded).length;
            const note = el('p', 'hwt-note');
            note.hidden = !unrec;
            note.textContent = unrec
                ? `${unrec} mark${unrec === 1 ? ' was' : 's were'} taken before the hardware was recorded and ${unrec === 1 ? 'is' : 'are'} outlined: a volume shows the embryo’s settings, not what the lasers were sent; a brightfield frame shows only when it was filed.`
                : '';
            S.tableWrap = el('div', 'hwt-table-wrap');
            S.tableWrap.hidden = true;
            S.live = el('div', 'hwt-sr');
            S.live.setAttribute('aria-live', 'polite');
            root.append(barEl, S.plot, hint, note, S.tableWrap, S.live);
            root.dataset.state = 'ready';

            legend();
            prev.addEventListener('click', () => stepRound(-1));
            next.addEventListener('click', () => stepRound(1));
            all.addEventListener('click', whole);
            tbl.addEventListener('click', () => {
                const open = S.tableWrap.hidden;
                if (open && !S.tableWrap.firstChild) table();
                S.tableWrap.hidden = !open;
                tbl.setAttribute('aria-pressed', String(open));
            });
            S.plot.addEventListener('pointermove', onMove);
            S.plot.addEventListener('pointerdown', onDown);
            S.plot.addEventListener('pointerup', onUp);
            // A drag the system takes away (a touch gesture) ends the drag too.
            S.plot.addEventListener('pointercancel', () => { S.drag = null; });
            S.plot.addEventListener('pointerleave', () => {
                if (S.drag) return;
                S.hover = null;
                if (!S.focus) { S.cross = null; hideTip(); }
                draw();
            });
            S.plot.addEventListener('wheel', onWheel, { passive: false });
            S.plot.addEventListener('dblclick', whole);
            S.plot.addEventListener('keydown', onKey);

            if (typeof ResizeObserver !== 'undefined') {
                S.ro = new ResizeObserver(() => { if (S === mine && root.isConnected) resize(); else if (S === mine) destroy(); });
                S.ro.observe(S.plot);
            }
            // Colours are each theme's own steps: a theme change redraws.
            S.mo = new MutationObserver(() => { if (S === mine && root.isConnected) { legend(); draw(); } });
            S.mo.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
            resize();
        }

        // What the view shows, for a person reading the console or a browser test.
        function state() {
            if (!S || !S.seq) return { state: S ? S.root.dataset.state : 'none' };
            return {
                state: S.root.dataset.state,
                view: { ...S.view },
                bounds: { ...S.bounds },
                t0: S.t0,
                rows: S.rows.map(r => r.key),
                rounds: S.rounds.map(r => ({ a: r.a, b: r.b, n: r.items.length })),
                where: S.whereEl ? S.whereEl.textContent : '',
                hidden: [...S.hidden],
                focus: S.focus ? S.focus.info.head : null,
                focusBox: S.focus && S.focus.box ? { ...S.focus.box } : null,
            };
        }

        // Where on the page a moment in a row is drawn (client coordinates).
        function pointAt(t, rowKey) {
            if (!S || !S.layout || !S.layout[rowKey]) return null;
            const rect = S.plot.getBoundingClientRect();
            const L = S.layout[rowKey];
            return { x: rect.left + x(t), y: rect.top + L.y + L.h - 3 };
        }


        // A live session's timeline read again: new volumes and frames join,
        // a view zoomed in stays where it is, the whole session grows with it.
        async function refresh() {
            if (!S || !S.root.isConnected) return;
            if (!S.seq) return mount(S.host, S.sessionId);  // nothing acquired until now
            const mine = S;
            let seq;
            try {
                const r = await fetch(`/api/sessions/${encodeURIComponent(S.sessionId)}/hardware-sequence`);
                if (!r.ok) return;
                seq = await r.json();
            } catch (err) {
                return;
            }
            if (S !== mine || seq.t0 == null) return;
            const whole = S.view.b - S.view.a >= (S.bounds.b - S.bounds.a) * 0.999;
            const view = { ...S.view };
            prepare(seq);
            if (!whole) S.view = M.zoomAt(view, view.a, 1, S.bounds, MIN_SPAN_S);
            S.focus = null;
            S.hover = null;
            hideTip();
            legend();
            if (S.tableWrap.hidden) S.tableWrap.replaceChildren(); else table();
            resize();
        }

        // What this timeline read of its session, for the page around it.
        const data = () => (S && S.seq ? S.seq : null);

        return { mount, destroy, state, pointAt, refresh, data };
    }

    const main = create();
    return { create, ...main };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = HardwareTimeline;
