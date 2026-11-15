/**
 * The Calibration tab's archive: every calibration run this session kept,
 * read from disk, with its raw exposures.
 *
 * The tab used to show only the copies pushed to the page while a
 * calibration ran, so it was empty after a restart, and a run that was
 * refused or aborted (the one somebody wants to look at) never had a place.
 * The runs themselves are on disk with every exposure they took
 * (embryos/{id}/calibration/{run}/, gently.core.calibration_record). This
 * reads them through /api/calibration/records.
 *
 * Three zones, as Scope has them: the runs, one exposure large over the run's
 * strip, and the run's record.
 *
 * The words for a run and an exposure are pure, above the line, and are
 * tested in node (tests/js/calibration-archive.test.mjs). CI drives no
 * browser.
 */
const CalibrationArchive = (() => {
    const isNum = v => typeof v === 'number' && isFinite(v);
    const signed = (v, d) => (v < 0 ? '−' : '+') + Math.abs(v).toFixed(d);

    /** A plot is a picture the run drew; anything else is an exposure. */
    const isPlot = i => String((i && i.file) || '').toLowerCase().endsWith('.png');
    const exposures = images => (images || []).filter(i => !isPlot(i));
    const plots = images => (images || []).filter(isPlot);

    /** The weaker end decides, as it does when a fit is borrowed. */
    function rSquared(c) {
        if (!c) return null;
        const ends = [c.r_squared_top, c.r_squared_bottom].filter(isNum);
        if (ends.length) return Math.min(...ends);
        return isNum(c.r_squared) ? c.r_squared : null;
    }

    /** Whether a run left a fit. */
    const hasFit = rec => !!(rec && rec.calibration && isNum(rec.calibration.slope_um_per_deg));

    /** What a run came to, in a few words: its fit, or how it ended. */
    function cameTo(rec) {
        if (hasFit(rec)) {
            const r2 = rSquared(rec.calibration);
            return `${rec.calibration.slope_um_per_deg.toFixed(1)} µm/°` + (r2 != null ? ` · R² ${r2.toFixed(2)}` : '');
        }
        return String((rec && rec.outcome) || 'unknown').replace(/_/g, ' ');
    }

    /** How long a run took, from its two timestamps. */
    function took(rec) {
        const a = Date.parse(rec && rec.started_at), b = Date.parse(rec && rec.finished_at);
        if (!isFinite(a) || !isFinite(b) || b < a) return '';
        const s = Math.round((b - a) / 1000);
        return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${s % 60} s`;
    }

    /** The clock time a run started, and its date when that is not today. */
    function startedAt(rec, now) {
        const d = new Date(rec && rec.started_at);
        if (isNaN(d)) return String((rec && rec.run) || '');
        const n = now || new Date();
        const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
        const same = d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
        return same ? hm : `${d.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${hm}`;
    }

    /** An exposure in words: what it was for and where the sheet stood. */
    function describe(i) {
        if (!i) return '';
        const bits = [String(i.kind || 'image').replace(/_/g, ' ')];
        if (i.sweep) bits.push(String(i.sweep));
        if (i.galvo_name) bits.push(String(i.galvo_name));
        if (isNum(i.galvo)) bits.push(`galvo ${signed(i.galvo, 3)}°`);
        if (isNum(i.piezo)) bits.push(`piezo ${signed(i.piezo, 1)} µm`);
        if (isNum(i.score)) bits.push(`score ${i.score.toExponential(2)}`);
        return bits.join(' · ');
    }

    /** The file's own name, as it is on disk. */
    const fileName = i => String((i && i.file) || '').split('/').pop();

    /**
     * Each exposure's score as a height from 0 to 1, against the best of its
     * own sweep (the same kind at the same galvo end): a focus score means
     * nothing beside one taken somewhere else. No score, no bar.
     */
    function scoreHeights(frames) {
        const best = new Map();
        const key = i => `${i.kind}|${i.galvo_name || ''}`;
        (frames || []).forEach(i => { if (isNum(i.score)) best.set(key(i), Math.max(best.get(key(i)) || 0, i.score)); });
        return (frames || []).map(i => (isNum(i.score) && best.get(key(i)) > 0 ? i.score / best.get(key(i)) : null));
    }

    /** The run's record as label and value pairs, only the ones it has. */
    function facts(rec) {
        if (!rec) return [];
        const out = [['Embryo', String(rec.embryo_id || '').replace(/^embryo_/, '')]];
        const t = took(rec);
        out.push(['Started', startedAt(rec) + (t ? ` · took ${t}` : '')]);
        out.push(['Came to', String(rec.outcome || 'unknown').replace(/_/g, ' ')]);
        const c = rec.calibration;
        if (hasFit(rec)) {
            out.push(['Slope', `${c.slope_um_per_deg.toFixed(2)} µm/°`]);
            if (isNum(c.offset_um)) out.push(['Offset', `${signed(c.offset_um, 2)} µm`]);
            if (isNum(c.r_squared_top) || isNum(c.r_squared_bottom)) {
                out.push(['R²', [['top', c.r_squared_top], ['bottom', c.r_squared_bottom]]
                    .filter(e => isNum(e[1])).map(e => `${e[0]} ${e[1].toFixed(2)}`).join(' · ')]);
            }
            if (isNum(c.galvo_top_deg) && isNum(c.galvo_bottom_deg)) {
                out.push(['Extent', `galvo ${signed(c.galvo_top_deg, 3)}° to ${signed(c.galvo_bottom_deg, 3)}°`]);
            }
        }
        const q = rec.requested || {};
        if (q.method) out.push(['Method', String(q.method)]);
        if (isNum(q.z_buffer_um)) out.push(['Z buffer', `±${q.z_buffer_um} µm`]);
        out.push(['Kept', `${rec.frames || 0} exposure${rec.frames === 1 ? '' : 's'} · ${rec.plots || 0} plot${rec.plots === 1 ? '' : 's'}`]);
        return out;
    }

    /** Newest first: the run just made is the one being looked for. */
    const newestFirst = records => (records || []).slice().sort((a, b) =>
        String(b.started_at || b.run || '').localeCompare(String(a.started_at || a.run || '')));

    // ── the run as the steps it took ────────────────────────────────────────
    // A run is not one strip of 264 exposures: it finds the embryo's edges,
    // then sweeps the focus at a few galvo angles. Each of those is a step,
    // and a step is what is browsed. A sweep is put in piezo order, so it
    // reads as a focus series, and carries the best focus its plot recorded.
    function steps(images) {
        const out = [];
        let cur = null;
        (images || []).forEach(i => {
            if (isPlot(i)) {
                // A sweep's plot closes it, and says what the sweep found.
                if (i.kind === 'focus_plot' && cur && cur.kind === 'focus_sweep') {
                    cur.best = isNum(i.best_piezo) ? i.best_piezo : null;
                    cur.r2 = isNum(i.r_squared) ? i.r_squared : null;
                    cur = null;
                }
                return;
            }
            const key = i.kind === 'focus_sweep' ? `focus_sweep|${i.galvo_name || ''}` : String(i.kind);
            if (!cur || cur.key !== key) {
                cur = { key, kind: String(i.kind), name: String(i.galvo_name || ''), frames: [], best: null, r2: null };
                out.push(cur);
            }
            cur.frames.push(i);
        });
        const span = s => { const p = s.frames.map(f => f.piezo).filter(isNum); return p.length ? Math.max(...p) - Math.min(...p) : 0; };
        out.forEach(s => {
            if (s.kind !== 'focus_sweep') { s.label = s.kind.replace(/_/g, ' ').replace('edge detection', 'edges'); return; }
            s.frames.sort((a, b) => (a.piezo || 0) - (b.piezo || 0));
            // The scan looks wide at one angle first, then finely at each.
            const twin = out.find(o => o !== s && o.key === s.key);
            s.label = `${s.name || 'sweep'}${twin ? (span(s) > span(twin) ? ' wide' : ' fine') : ''}`;
        });
        let start = 0;
        out.forEach(s => { s.start = start; start += s.frames.length; });
        return out;
    }

    // ── a graph, drawn on the page from the run's own numbers ───────────────
    // The run's plots are pictures of graphs. These are the graphs: every
    // point is the exposure it came from, says its values, and shows that
    // exposure when pressed. One series each, so no legend: the title names it.
    //   pts   [{x, y, frame?, tip}]   frame is the exposure's place in the run
    //   line  [[x, y], ...] drawn through, or null     vline  an x to mark, or null
    //   band  [x0, x1] shaded, or null                 on     the frame shown large
    function chart(o) {
        const W = o.w || 292, H = o.h || 118, L = 34, Rm = 8, T = 8, B = 20;
        const xs = o.pts.map(p => p.x).concat(o.line ? o.line.map(p => p[0]) : []);
        const ys = o.pts.map(p => p.y).concat(o.line ? o.line.map(p => p[1]) : []);
        if (!xs.length) return '';
        let x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = o.zero ? 0 : Math.min(...ys), y1 = Math.max(...ys);
        if (x1 === x0) { x0 -= 1; x1 += 1; }
        if (y1 === y0) { y0 -= 1; y1 += 1; }
        const px = x => L + (x - x0) / (x1 - x0) * (W - L - Rm), py = y => H - B - (y - y0) / (y1 - y0) * (H - T - B);
        const n = v => (Math.abs(v) >= 100 ? v.toFixed(0) : Math.abs(v) >= 10 ? v.toFixed(1) : v.toFixed(2));
        const path = pp => pp.map((p, k) => `${k ? 'L' : 'M'}${px(p[0]).toFixed(1)} ${py(p[1]).toFixed(1)}`).join(' ');
        // Many points are a curve: the dots step back so the line reads.
        const dense = o.pts.length > 25 ? ' is-dense' : '';
        return `<svg class="cal-arc-chart${dense}" viewBox="0 0 ${W} ${H}" role="img" aria-label="${o.title || ''}">`
            + (o.band ? `<rect class="band" x="${px(o.band[0]).toFixed(1)}" y="${T}" width="${Math.max(1, px(o.band[1]) - px(o.band[0])).toFixed(1)}" height="${H - T - B}"/>` : '')
            + `<path class="axis" d="M${L} ${T}V${H - B}H${W - Rm}"/>`
            + `<text class="tick" x="${L}" y="${H - 6}">${n(x0)}</text><text class="tick end" x="${W - Rm}" y="${H - 6}">${n(x1)}</text>`
            + `<text class="tick mid" x="${(L + W - Rm) / 2}" y="${H - 6}">${o.xLabel || ''}</text>`
            + `<text class="tick end" x="${L - 4}" y="${T + 8}">${o.yTop != null ? o.yTop : n(y1)}</text><text class="tick end" x="${L - 4}" y="${H - B}">${o.zero ? '0' : n(y0)}</text>`
            + (o.vline != null && o.vline >= x0 && o.vline <= x1 ? `<path class="best" d="M${px(o.vline).toFixed(1)} ${T}V${H - B}"/>` : '')
            + (o.line ? `<path class="ln" d="${path(o.line)}"/>` : '')
            + o.pts.map(p => `<g class="pt${p.frame != null && p.frame === o.on ? ' is-on' : ''}"${p.frame != null ? ` data-arc-frame="${p.frame}"` : ''}>`
                + `<title>${p.tip || ''}</title><circle class="hit" cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="9"/>`
                + `<circle class="dot" cx="${px(p.x).toFixed(1)}" cy="${py(p.y).toFixed(1)}" r="4"/></g>`).join('')
            + '</svg>';
    }

    const pure = { isPlot, exposures, plots, rSquared, hasFit, cameTo, took, startedAt, describe, fileName, scoreHeights, facts, newestFirst, steps, chart };
    if (typeof document === 'undefined') return pure;

    // ── the page ────────────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);
    const esc = s => (typeof escapeHtml === 'function' ? escapeHtml(s) : String(s == null ? '' : s));
    const enc = encodeURIComponent;

    let _runs = [];          // newest first
    let _rec = null;         // the run shown, with its images
    let _frames = [];        // its exposures, step by step (a sweep in piezo order)
    let _steps = [];         // the run as steps; each knows where it starts in _frames
    let _at = 0;             // which exposure is large
    let _asked = 0;          // only the newest answer draws
    let _wired = false;

    async function getJSON(url) {
        const r = await fetch(url);
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
    }

    const sameRun = (a, b) => !!a && !!b && a.embryo_id === b.embryo_id && a.run === b.run;

    async function refresh() {
        const ask = ++_asked;
        let records = [];
        try { records = ((await getJSON('/api/calibration/records')) || {}).records || []; } catch (_) { records = []; }
        if (ask !== _asked) return;
        _runs = newestFirst(records);
        const root = $('cal-archive');
        if (!root) return;
        root.dataset.runs = _runs.length ? 'some' : 'none';
        const count = $('cal-arc-count');
        if (count) count.textContent = _runs.length ? `${_runs.length} kept this session` : '';
        renderList();
        if (!_runs.length) { _rec = null; _frames = []; return; }
        const keep = _rec && _runs.find(r => sameRun(r, _rec));
        await select(keep || _runs[0]);
    }

    function renderList() {
        const host = $('cal-arc-list');
        if (!host) return;
        host.innerHTML = _runs.map((r, k) => {
            const on = sameRun(r, _rec);
            return `<button type="button" class="cal-arc-run${on ? ' is-on' : ''}" role="option" aria-selected="${on}" data-arc-run="${k}" title="${esc(String(r.message || '').split('\n')[0])}">` +
                `<span class="cal-arc-id">${esc(String(r.embryo_id || '').replace(/^embryo_/, ''))}</span>` +
                `<span class="cal-arc-at">${esc(startedAt(r))}</span>` +
                `<span class="cal-arc-out ${hasFit(r) ? 'is-fit' : 'is-no'}">${esc(cameTo(r))}</span></button>`;
        }).join('');
    }

    async function select(run) {
        const ask = ++_asked;
        let rec = null;
        try { rec = await getJSON(`/api/calibration/records/${enc(run.embryo_id)}/${enc(run.run)}`); } catch (_) { rec = null; }
        if (ask !== _asked) return;
        _rec = { ...run, ...(rec || {}), images: (rec && rec.images) || [] };
        _steps = steps(_rec.images);
        _frames = _steps.flatMap(s => s.frames);
        // Open on the sharpest exposure the run found, when it scored any.
        const h = scoreHeights(_frames);
        const best = h.reduce((b, v, k) => (v != null && (b < 0 || v > h[b]) ? k : b), -1);
        _at = best >= 0 ? best : 0;
        renderList();
        renderRun();
    }

    function renderRun() {
        const kv = $('cal-arc-kv');
        if (kv) {
            kv.innerHTML = facts(_rec).map(f =>
                `<div class="op-row"><span class="op-label">${esc(f[0])}</span><span class="cal-arc-v">${esc(f[1])}</span></div>`).join('') +
                // A run with no fit says why in its own words; a fit's are the lines above.
                (!hasFit(_rec) && _rec.message ? `<p class="cal-arc-msg">${esc(String(_rec.message))}</p>` : '');
        }
        renderGraphs();
        renderFilm();
    }

    const stepOf = k => _steps.findIndex(s => k >= s.start && k < s.start + s.frames.length);

    // The run's graphs, from its numbers: where the embryo was found, each
    // focus sweep, and the line fitted through them.
    function renderGraphs() {
        const host = $('cal-arc-plots');
        if (!host) return;
        const out = [];
        const block = (title, says, svg) => { if (svg) out.push(`<figure class="cal-arc-graph"><figcaption><b>${esc(title)}</b>${says ? ` <span>${esc(says)}</span>` : ''}</figcaption>${svg}</figure>`); };
        _steps.forEach(s => {
            const at = f => s.start + s.frames.indexOf(f);
            if (s.kind === 'edge_detection') {
                const fr = s.frames.filter(f => isNum(f.galvo) && isNum(f.signal));
                const seen = fr.filter(f => f.visible).map(f => f.galvo);
                block('Where the embryo is', seen.length ? `seen from ${signed(Math.min(...seen), 2)}° to ${signed(Math.max(...seen), 2)}°` : 'not seen at any angle',
                    chart({ title: 'Signal at each galvo angle', xLabel: 'galvo °', zero: true, on: _at,
                        band: seen.length ? [Math.min(...seen), Math.max(...seen)] : null,
                        pts: fr.map(f => ({ x: f.galvo, y: f.signal, frame: at(f), tip: `galvo ${signed(f.galvo, 3)}° · signal ${f.signal} · ${f.visible ? 'embryo seen' : 'nothing'}` })) }));
            } else if (s.kind === 'focus_sweep') {
                const fr = s.frames.filter(f => isNum(f.piezo) && isNum(f.score));
                if (!fr.length) return;
                const top = Math.max(...fr.map(f => f.score), 1e-9);
                const pts = fr.map(f => ({ x: f.piezo, y: f.score / top, frame: at(f), tip: `piezo ${signed(f.piezo, 1)} µm · sharpness ${(100 * f.score / top).toFixed(0)}% of this sweep’s best` }));
                block(`Focus at ${s.label}`, [s.best != null ? `sharpest at ${signed(s.best, 1)} µm` : '', s.r2 != null ? `R² ${s.r2.toFixed(2)}` : ''].filter(Boolean).join(' · '),
                    chart({ title: `Sharpness against piezo at ${s.label}`, xLabel: 'piezo µm', zero: true, yTop: 'best', on: _at, vline: s.best, pts, line: pts.map(p => [p.x, p.y]) }));
            }
        });
        const c = _rec && _rec.calibration;
        const points = ((c && c.points) || []).filter(p => isNum(p.galvo) && isNum(p.piezo));
        if (hasFit(_rec) && points.length) {
            const gs = points.map(p => p.galvo), pad = (Math.max(...gs) - Math.min(...gs)) * 0.15 || 0.05;
            const f = g => c.slope_um_per_deg * g + (c.offset_um || 0);
            block('The fit', `${c.slope_um_per_deg.toFixed(1)} µm/° · offset ${signed(c.offset_um || 0, 1)} µm${isNum(c.r_squared) ? ` · R² ${c.r_squared.toFixed(2)}` : ''}`,
                chart({ title: 'Sharpest piezo against galvo, and the line through it', xLabel: 'galvo °', h: 132,
                    line: [[Math.min(...gs) - pad, f(Math.min(...gs) - pad)], [Math.max(...gs) + pad, f(Math.max(...gs) + pad)]],
                    pts: points.map(p => ({ x: p.galvo, y: p.piezo, tip: `galvo ${signed(p.galvo, 3)}° · sharpest at piezo ${signed(p.piezo, 1)} µm${isNum(p.r_squared) ? ` · R² ${p.r_squared.toFixed(2)}` : ''}` })) }));
        }
        host.innerHTML = out.join('') || '<p class="cal-arc-msg">This run has nothing to graph: it ended before it measured anything.</p>';
    }

    // The film is one step at a time, chosen from the steps above it: 264
    // exposures in one strip was a long way to scroll to find a sweep.
    function renderFilm() {
        const film = $('cal-arc-film'), tabs = $('cal-arc-steps');
        const now = Math.max(0, stepOf(_at));
        if (tabs) {
            tabs.innerHTML = _steps.map((s, k) => `<button type="button" class="cal-arc-step${k === now ? ' is-on' : ''}" role="tab" aria-selected="${k === now}" data-arc-step="${k}">${esc(s.label)}<small>${s.frames.length}</small></button>`).join('');
        }
        const s = _steps[now];
        if (film) {
            const h = s ? scoreHeights(s.frames) : [];
            film.dataset.step = String(now);
            film.innerHTML = !s ? '' : s.frames.map((f, k) =>
                `<button type="button" class="cal-arc-cell" data-arc-frame="${s.start + k}" title="${esc(describe(f))}">` +
                `<img loading="lazy" src="${esc(f.url)}?max=160" alt="">` +
                `<span class="cal-arc-score">${h[k] == null ? '' : `<i style="height:${Math.max(4, Math.round(h[k] * 100))}%"></i>`}</span>` +
                `<span class="cal-arc-n">${isNum(f.piezo) && s.kind === 'focus_sweep' ? signed(f.piezo, 1) : f.n}</span></button>`).join('');
        }
        showFrame(_at);
    }

    /** Another step: on its sharpest exposure, or its first. */
    function showStep(k) {
        const s = _steps[Math.max(0, Math.min(_steps.length - 1, k))];
        if (!s) return;
        const h = scoreHeights(s.frames);
        const best = h.reduce((b, v, i) => (v != null && (b < 0 || v > h[b]) ? i : b), -1);
        _at = s.start + Math.max(0, best);
        renderFilm();
    }

    function showFrame(k) {
        const none = !_frames.length;
        const raw = $('cal-arc-raw'), img = $('cal-arc-img'), cap = $('cal-arc-cap'), file = $('cal-arc-file');
        if (raw) raw.hidden = none;
        ['cal-arc-show', 'cal-arc-fiji'].forEach(id => { const b = $(id); if (b) b.disabled = none; });
        if (none) {
            if (cap) cap.textContent = 'This run kept no exposures.';
            if (file) file.textContent = '';
            return;
        }
        _at = Math.max(0, Math.min(_frames.length - 1, k));
        // A point pressed on a graph may be in another step than the film's.
        const film = $('cal-arc-film');
        if (film && film.dataset.step !== String(stepOf(_at))) { renderFilm(); return; }
        const f = _frames[_at];
        if (img) { img.src = `${f.url}?max=1400`; img.alt = describe(f); }
        if (cap) cap.textContent = `${_at + 1} of ${_frames.length} · ${describe(f)}`;
        if (file) file.textContent = fileName(f);
        document.querySelectorAll('#cal-arc-film .cal-arc-cell').forEach(c => {
            const on = Number(c.dataset.arcFrame) === _at;
            c.classList.toggle('is-on', on);
            if (on) c.scrollIntoView({ block: 'nearest', inline: 'nearest' });
        });
        // The exposure shown is ringed on the graph it is a point of.
        document.querySelectorAll('#cal-arc-plots .pt').forEach(p => {
            const on = Number(p.dataset.arcFrame) === _at;
            p.classList.toggle('is-on', on);
            // Its graph comes into view with it; the graphs are a column that scrolls.
            if (on) { const fig = p.closest('.cal-arc-graph'); if (fig) fig.scrollIntoView({ block: 'nearest' }); }
        });
    }

    /** The viewer that draws its own contrast and reads values, on the counts. */
    function openLarge(index) {
        if (!_rec || typeof Lightbox === 'undefined') return;
        Lightbox.open(_rec.images.map(i => ({
            url: i.url, u16: i.u16, data_type: describe(i), metadata: { embryo_id: _rec.embryo_id },
        })), Math.max(0, index), 'calibration');
    }

    function reveal(action, image) {
        if (!_rec || typeof Reveal === 'undefined') return;
        const what = image
            ? { what: 'calibration_image', embryo_id: _rec.embryo_id, run: _rec.run, n: image.n }
            : { what: 'calibration_run', embryo_id: _rec.embryo_id, run: _rec.run };
        Reveal.run(what, action);
    }

    /** Back to the instrument, on this embryo, where a calibration is pressed. */
    function recalibrate() {
        if (!_rec) return;
        if (typeof switchTab === 'function') switchTab('devices');
        if (typeof DevicesManager !== 'undefined' && DevicesManager.switchView) DevicesManager.switchView('operate');
        if (typeof OperateManager !== 'undefined' && OperateManager.roster) {
            OperateManager.roster.select(_rec.embryo_id);
            OperateManager.roster.goTo('cal');
        }
    }

    function wire() {
        if (_wired) return;
        const root = $('cal-archive');
        if (!root) return;
        _wired = true;
        root.addEventListener('click', e => {
            // Names of their own: the page's body carries a data-run (the run's
            // state), and closest() climbs past this root to find it.
            const run = e.target.closest('[data-arc-run]');
            if (run) { select(_runs[Number(run.dataset.arcRun)]); return; }
            const step = e.target.closest('[data-arc-step]');
            if (step) { showStep(Number(step.dataset.arcStep)); return; }
            const cell = e.target.closest('[data-arc-frame]');
            if (cell) { showFrame(Number(cell.dataset.arcFrame)); return; }
            const plot = e.target.closest('[data-arc-plot]');
            if (plot) { openLarge(Number(plot.dataset.arcPlot)); return; }
            const b = e.target.closest('button');
            if (!b) return;
            if (b.id === 'cal-arc-raw') openLarge(_rec.images.indexOf(_frames[_at]));
            else if (b.id === 'cal-arc-show') reveal('show', _frames[_at]);
            else if (b.id === 'cal-arc-fiji') reveal('fiji', _frames[_at]);
            else if (b.id === 'cal-arc-folder') reveal('show', null);
            else if (b.id === 'cal-arc-recal') recalibrate();
            else if (b.id === 'cal-arc-refresh') refresh();
        });
        // Over a point on a graph: the exposure it is, small, beside the
        // pointer, with its values. Pressing the point shows it large.
        const peek = document.createElement('div');
        peek.className = 'cal-arc-peek';
        peek.hidden = true;
        root.appendChild(peek);
        root.addEventListener('mouseover', e => {
            const pt = e.target.closest && e.target.closest('.cal-arc-chart .pt[data-arc-frame]');
            if (!pt) { peek.hidden = true; return; }
            const f = _frames[Number(pt.dataset.arcFrame)];
            if (!f) return;
            peek.innerHTML = `<img src="${esc(f.url)}?max=160" alt=""><span>${esc(describe(f))}</span>`;
            const box = root.getBoundingClientRect(), at = pt.getBoundingClientRect();
            // To the left of the graphs' column, level with the point, kept on the page.
            peek.style.right = `${Math.round(box.right - at.left + 14)}px`;
            peek.style.top = `${Math.round(Math.max(0, Math.min(box.height - 150, at.top - box.top - 60)))}px`;
            peek.hidden = false;
        });
        root.addEventListener('mouseleave', () => { peek.hidden = true; });
        // ← → step through the run's exposures; ↑ ↓ through the runs.
        root.addEventListener('keydown', e => {
            if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
            if (e.key === '[' || e.key === ']') {
                e.preventDefault();
                showStep(stepOf(_at) + (e.key === ']' ? 1 : -1));
            } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                if (!_frames.length) return;
                e.preventDefault();
                showFrame(_at + (e.key === 'ArrowRight' ? 1 : -1));
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                const k = _runs.findIndex(r => sameRun(r, _rec));
                const next = _runs[k + (e.key === 'ArrowDown' ? 1 : -1)];
                if (!next) return;
                e.preventDefault();
                select(next).then(() => { const on = document.querySelector('#cal-arc-list .is-on'); if (on) on.focus(); });
            }
        });
    }

    /** The tab, or this view of it, has come up: read what is on disk now. */
    function show() {
        wire();
        return refresh();
    }

    return { ...pure, show, refresh };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CalibrationArchive;
