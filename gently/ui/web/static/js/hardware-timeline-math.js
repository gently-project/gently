/**
 * The hardware timeline's arithmetic, no DOM: which row each thing the
 * instrument did goes in, where a stack's slices fell, which marks make up a
 * round, how the view zooms and pans, and what its axis says.
 * hardware-timeline.js draws what this works out.
 *
 * Classic script (window global `HardwareTimelineMath`); also CJS-exported
 * for node tests (tests/js/hardware-timeline-math.test.mjs).
 */
const HardwareTimelineMath = (() => {
    // Categorical colours there are; the ninth embryo on shares "Other".
    const SLOTS = 8;
    const STEPS = [
        0.001, 0.002, 0.005, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 15, 30,
        60, 120, 300, 600, 900, 1800, 3600, 7200, 10800, 21600, 43200, 86400,
    ];

    // When a stack's own slices began: its side's start when both sides were
    // taken in one scan (B begins after A), else the scan's.
    const stackStart = v => v.side_began ?? v.scan_started;

    // Where each of a stack's slices fell. A recorded stack's frames arrived
    // at a measured period, counted from the moment its scan began; an
    // unrecorded one is known only as its light time, exposure after exposure.
    function sliceTimes(v) {
        const n = Math.max(0, Math.floor(v.slices || 0));
        const exp = (v.exposure_ms || 0) / 1000;
        const start = stackStart(v);
        if (!n || !exp || start == null) return [];
        const measured = v.first_frame != null && v.last_frame != null && n > 1;
        const period = measured ? (v.last_frame - v.first_frame) / (n - 1) : exp;
        const out = [];
        for (let i = 0; i < n; i++) {
            const a = start + i * period;
            out.push([a, a + exp]);
        }
        return out;
    }

    // Each row's marks, oldest first. A laser line lights for a recorded
    // volume's laser window, at the power it ran at; an unrecorded volume can
    // only show the embryo's setting. Brightfield light is the dish's, no
    // embryo's, and has a window only when its frame switched it.
    function marks(seq) {
        const rows = { bf: [], exposure: [] };
        for (const wl of seq.lines || []) rows[String(wl)] = [];
        for (const v of seq.volumes || []) {
            const a = stackStart(v);
            if (a == null) continue;
            const b = v.last_frame ?? a;
            const lit = v.recorded ? (v.lasers || {}) : (v.settings || {});
            for (const [wl, pct] of Object.entries(lit)) {
                const row = rows[wl] || (rows[wl] = []);
                if (v.recorded) {
                    row.push({ kind: 'laser', a: v.lasers_on ?? a, b: v.lasers_off ?? b, scanA: a, scanB: b, value: pct, embryo: v.embryo, v });
                } else {
                    row.push({ kind: 'setting', a, b, value: pct, embryo: v.embryo, v });
                }
            }
            rows.exposure.push({ kind: 'stack', a, b, value: v.exposure_ms, embryo: v.embryo, v });
        }
        for (const f of seq.bf || []) {
            if (f.light_on != null) {
                // Not seen to go off: it was on at least until its frame was filed.
                rows.bf.push({ kind: 'light', a: f.light_on, b: f.light_off ?? f.filed ?? f.light_on, value: f.led_pct, f });
            } else if (!f.recorded && f.filed != null) {
                rows.bf.push({ kind: 'filed', a: f.filed, b: f.filed, value: f.led_pct, f });
            }
            const exp = (f.exposure_ms || 0) / 1000;
            if (f.exposed != null) {
                rows.exposure.push({ kind: 'frame', a: f.exposed - exp, b: f.exposed, value: f.exposure_ms, f });
            } else if (!f.recorded && f.filed != null) {
                rows.exposure.push({ kind: 'frame-filed', a: f.filed - exp, b: f.filed, value: f.exposure_ms, f });
            }
        }
        for (const k of Object.keys(rows)) rows[k].sort((p, q) => p.a - q.a);
        return rows;
    }

    // The rows there are something to show in, top to bottom.
    function rows(seq) {
        const out = [];
        const bf = (seq.bf || []).length, vols = (seq.volumes || []).length;
        if (bf) out.push({ key: 'bf', label: 'BF light', unit: '%' });
        for (const wl of seq.lines || []) out.push({ key: String(wl), label: `${wl} nm`, unit: '%' });
        if (vols || bf) out.push({ key: 'exposure', label: 'Exposure', unit: 'ms' });
        if ((seq.temperature || []).length) out.push({ key: 'temp', label: 'Temperature', unit: '°C' });
        return out;
    }

    // Marks that follow each other closer than `gap` seconds are one round.
    function rounds(items, gap) {
        const out = [];
        for (const m of [...items].sort((p, q) => p.a - q.a)) {
            const last = out[out.length - 1];
            if (last && m.a <= last.b + gap) {
                last.b = Math.max(last.b, m.b);
                last.items.push(m);
            } else {
                out.push({ a: m.a, b: m.b, items: [m] });
            }
        }
        return out;
    }

    // A volume's and a frame's span on the clock, for grouping into rounds.
    function spanOfVolume(v) {
        const a = v.lasers_on ?? stackStart(v);
        return a == null ? null : [a, v.lasers_off ?? v.last_frame ?? a];
    }
    function spanOfFrame(f) {
        const exp = (f.exposure_ms || 0) / 1000;
        const a = f.light_on ?? (f.exposed != null ? f.exposed - exp : f.filed);
        return a == null ? null : [a, f.light_off ?? f.exposed ?? f.filed ?? a];
    }

    // Rounds as the run made them. The run keeps no round of its own (each
    // embryo has its own cadence), and a run behind its schedule leaves no
    // pause between rounds. So a round is a stretch in which each embryo and
    // side is taken at most once: one coming up again, or a pause of `pause`
    // with nothing at all lit or exposed, begins the next. Brightfield frames
    // after a round's last volume lead the next round if they run into it,
    // else close the one before; with no volume near, they group by pauses.
    function roundsOf(seq, pause) {
        const ev = [
            ...(seq.volumes || []).map(v => ({ v, s: spanOfVolume(v) })),
            ...(seq.bf || []).map(f => ({ f, s: spanOfFrame(f) })),
        ].filter(e => e.s).sort((p, q) => p.s[0] - q.s[0]);
        const out = [], loose = [];
        let cur = null, pending = [], lastEnd = -Infinity;
        const add = (r, e) => {
            r.items.push(e.v || e.f);
            r.a = Math.min(r.a, e.s[0]);
            r.b = Math.max(r.b, e.s[1]);
        };
        // Share out the frames waiting since the last volume: those that run
        // into `next` lead it; the rest close the current round or stand alone.
        const settle = next => {
            let k = pending.length;
            if (next) {
                let edge = next.s[0];
                while (k > 0 && edge - pending[k - 1].s[1] <= pause) edge = pending[--k].s[0];
            }
            for (const e of pending.slice(0, k)) {
                if (cur && e.s[0] - cur.b <= pause) add(cur, e);
                else loose.push({ a: e.s[0], b: e.s[1], f: e.f });
            }
            const lead = pending.slice(k);
            pending = [];
            return lead;
        };
        for (const e of ev) {
            if (e.f) {
                pending.push(e);
                lastEnd = Math.max(lastEnd, e.s[1]);
                continue;
            }
            const key = `${e.v.embryo}/${e.v.side}`;
            if (!cur || cur.keys.has(key) || e.s[0] > lastEnd + pause) {
                const lead = settle(e);
                cur = { a: e.s[0], b: e.s[1], items: [], keys: new Set() };
                out.push(cur);
                for (const l of lead) add(cur, l);
            } else {
                for (const p of pending) add(cur, p);  // taken in the middle of the round
                pending = [];
            }
            cur.keys.add(key);
            add(cur, e);
            lastEnd = Math.max(lastEnd, e.s[1]);
        }
        settle(null);
        const groups = out.map(({ a, b, items }) => ({ a, b, items }));
        for (const g of rounds(loose, pause)) groups.push({ a: g.a, b: g.b, items: g.items.map(x => x.f) });
        return groups.sort((p, q) => p.a - q.a);
    }

    // A pause that ends a round: half the cadence embryos come round at, and
    // never under twenty seconds. Each side of an embryo is its own series.
    function roundPause(volumes) {
        const by = {};
        for (const v of volumes) {
            if (v.scan_started == null) continue;
            (by[`${v.embryo}/${v.side}`] ||= []).push(v.scan_started);
        }
        const gaps = [];
        for (const ts of Object.values(by)) {
            ts.sort((p, q) => p - q);
            for (let i = 1; i < ts.length; i++) gaps.push(ts[i] - ts[i - 1]);
        }
        if (!gaps.length) return 20;
        gaps.sort((p, q) => p - q);
        return Math.max(20, gaps[Math.floor(gaps.length / 2)] / 2);
    }

    function clamp(view, bounds) {
        const span = view.b - view.a;
        const a = Math.max(bounds.a, Math.min(view.a, bounds.b - span));
        return { a, b: a + span };
    }

    // Zoom by `factor` (<1 in, >1 out) keeping the moment `t` where it is on
    // screen; never wider than the session, never closer than `minSpan`.
    function zoomAt(view, t, factor, bounds, minSpan) {
        const span = Math.min(bounds.b - bounds.a, Math.max(minSpan, (view.b - view.a) * factor));
        const k = (t - view.a) / (view.b - view.a);
        const a = t - k * span;
        return clamp({ a, b: a + span }, bounds);
    }

    function pan(view, dt, bounds) {
        return clamp({ a: view.a + dt, b: view.b + dt }, bounds);
    }

    function niceStep(x) {
        return STEPS.find(s => s >= x - 1e-12) || STEPS[STEPS.length - 1];
    }

    function fmtClock(s, dec = 0) {
        const v = Math.abs(s);
        // Negative only if it still is once rounded: a hair before is "0:00".
        const neg = s < 0 && (dec ? +v.toFixed(dec) : Math.floor(v + 1e-9)) > 0;
        const h = Math.floor(v / 3600), m = Math.floor((v % 3600) / 60), sec = v % 60;
        const ss = dec
            ? sec.toFixed(dec).padStart(dec + 3, '0')
            : String(Math.floor(sec + 1e-9)).padStart(2, '0');
        const body = h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`;
        return (neg ? '-' : '') + body;
    }

    // A moment on the rig's own clock, its offset said (the session may be
    // read in another zone). With the offset not known, this browser's clock.
    function fmtWall(t, offsetS) {
        if (offsetS == null) {
            return new Date(t * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false });
        }
        const d = new Date((t + offsetS) * 1000);
        const two = n => String(n).padStart(2, '0');
        const a = Math.abs(offsetS), oh = Math.floor(a / 3600), om = Math.round((a % 3600) / 60);
        const zone = offsetS === 0 ? 'UTC' : `UTC${offsetS < 0 ? '\u2212' : '+'}${oh}${om ? `:${two(om)}` : ''}`;
        return `${two(d.getUTCHours())}:${two(d.getUTCMinutes())}:${two(d.getUTCSeconds())} ${zone}`;
    }

    function fmtDuration(s) {
        if (s < 1) return `${+(s * 1000).toPrecision(3)} ms`;
        if (s < 60) return `${s.toFixed(2)} s`;
        return fmtClock(Math.round(s));
    }

    // The axis. A long view counts the clock from the first acquisition; two
    // minutes and closer, it counts seconds from the ten-second mark just
    // inside the view's left edge (never before the first acquisition), with
    // as many decimals as the step needs.
    function ticks(view, t0, target = 6) {
        const span = view.b - view.a;
        const step = niceStep(span / target);
        const out = [];
        if (span >= 120) {
            const first = Math.ceil((view.a - t0) / step - 1e-9) * step;
            for (let e = first; t0 + e <= view.b + 1e-9; e += step) out.push({ t: t0 + e, label: fmtClock(e) });
            return { ticks: out, step, caption: 'Time since the first acquisition' };
        }
        const anchor = Math.max(0, Math.floor((view.a + 0.1 * span - t0) / 10) * 10);
        const dec = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
        for (let i = Math.ceil((view.a - t0 - anchor) / step - 1e-9); ; i++) {
            const t = t0 + anchor + i * step;
            if (t > view.b + 1e-9) break;
            out.push({ t: +t.toFixed(dec + 3), label: (i * step).toFixed(dec) });
        }
        return { ticks: out, step, caption: `Seconds after ${fmtClock(anchor)}` };
    }

    // The mark at `t`: one under the pointer first, the narrowest of those;
    // else the nearest within `reach` seconds; else none.
    function hit(list, t, reach) {
        let best = null, key = null;
        for (const m of list) {
            const inside = t >= m.a && t <= m.b;
            const dist = inside ? 0 : Math.min(Math.abs(t - m.a), Math.abs(t - m.b));
            if (dist > reach) continue;
            const k = inside ? [0, m.b - m.a] : [1, dist];
            if (!key || k[0] < key[0] || (k[0] === key[0] && k[1] < key[1])) { best = m; key = k; }
        }
        return best;
    }

    // Marks drawn from what was set, not from what the hardware recorded.
    const NOT_RECORDED = new Set(['setting', 'filed', 'frame-filed']);

    // Where marks are denser than pixels, the last one drawn would paint over
    // the rest. Merged per pixel column instead: the column keeps its tallest
    // mark's height and its one embryo, "__several" when marks of more than
    // one fall in it ("__bf" for the dish's light). Recorded unless every mark
    // in it was not. Runs of equal columns, as [x0, x1) plot pixels.
    function bins(list, toPx, width, heightOf) {
        const W = Math.max(0, Math.ceil(width));
        const hgt = new Array(W).fill(0), who = new Array(W).fill(null), rec = new Array(W).fill(false);
        for (const m of list) {
            const x0 = Math.floor(toPx(m.a));
            const x1 = Math.max(Math.ceil(toPx(m.b)), x0 + 2);
            const id = m.embryo === undefined ? '__bf' : m.embryo;
            const hv = heightOf(m);
            const recorded = !NOT_RECORDED.has(m.kind) && !(m.v && m.v.recorded === false);
            for (let i = Math.max(0, x0); i < Math.min(W, x1); i++) {
                if (hv > hgt[i]) hgt[i] = hv;
                who[i] = who[i] === null || who[i] === id ? id : '__several';
                rec[i] = rec[i] || recorded;
            }
        }
        const out = [];
        for (let i = 0; i < W;) {
            if (who[i] === null) { i++; continue; }
            let j = i + 1;
            while (j < W && who[j] === who[i] && hgt[j] === hgt[i] && rec[j] === rec[i]) j++;
            out.push({ x0: i, x1: j, h: hgt[i], who: who[i], recorded: rec[i] });
            i = j;
        }
        return out;
    }

    // The view that opens a round: the round and 8% either side, at least a
    // second wide so a round with no length can be seen; inside the session.
    function roundView(r, bounds) {
        const span = Math.max(1, (r.b - r.a) * 1.16);
        const mid = (r.a + r.b) / 2;
        return clamp({ a: mid - span / 2, b: mid + span / 2 }, bounds);
    }

    // Colour follows the embryo, in the session's order, never its rank.
    function slots(embryos) {
        const out = {};
        embryos.forEach((e, i) => { out[e.id] = i < SLOTS ? i : null; });
        return out;
    }

    function niceCeil(x) {
        if (!(x > 0)) return 1;
        const p = 10 ** Math.floor(Math.log10(x));
        for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= x - 1e-9) return +(m * p).toPrecision(12);
        return 10 * p;
    }

    // The temperature row's scale: centred on the setpoint, at least a degree
    // tall, so sensor jitter reads flat and only a real excursion moves.
    function tempRange(temps) {
        if (!temps.length) return null;
        const sps = temps.map(r => r[2]).filter(x => x != null).sort((p, q) => p - q);
        const waters = temps.map(r => r[1]);
        const center = sps.length
            ? sps[Math.floor(sps.length / 2)]
            : (Math.min(...waters) + Math.max(...waters)) / 2;
        let dev = 0;
        for (const w of waters) dev = Math.max(dev, Math.abs(w - center));
        for (const s of sps) dev = Math.max(dev, Math.abs(s - center));
        const half = Math.max(0.5, dev * 1.15);
        return { lo: center - half, hi: center + half };
    }

    return {
        SLOTS, sliceTimes, marks, rows, rounds, roundsOf, roundPause, zoomAt, pan, niceStep,
        ticks, fmtClock, fmtDuration, fmtWall, hit, bins, slots, niceCeil, tempRange, roundView, stackStart,
    };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = HardwareTimelineMath;
