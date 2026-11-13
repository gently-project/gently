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

    const pure = { isPlot, exposures, plots, rSquared, hasFit, cameTo, took, startedAt, describe, fileName, scoreHeights, facts, newestFirst };
    if (typeof document === 'undefined') return pure;

    // ── the page ────────────────────────────────────────────────────────────
    const $ = id => document.getElementById(id);
    const esc = s => (typeof escapeHtml === 'function' ? escapeHtml(s) : String(s == null ? '' : s));
    const enc = encodeURIComponent;

    let _runs = [];          // newest first
    let _rec = null;         // the run shown, with its images
    let _frames = [];        // its exposures, in the order taken
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
        _frames = exposures(_rec.images);
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
        const ph = $('cal-arc-plots');
        if (ph) {
            const ps = plots(_rec.images);
            ph.innerHTML = ps.length
                ? ps.map(p => `<button type="button" class="cal-arc-plot" data-arc-plot="${_rec.images.indexOf(p)}" title="${esc(describe(p))}"><img loading="lazy" src="${esc(p.url)}?max=640" alt="${esc(describe(p))}"></button>`).join('')
                : '<p class="cal-arc-msg">This run drew no plots: it ended before a sweep was fitted.</p>';
        }
        const film = $('cal-arc-film');
        if (film) {
            const h = scoreHeights(_frames);
            film.innerHTML = _frames.map((f, k) =>
                `<button type="button" class="cal-arc-cell" data-arc-frame="${k}" title="${esc(describe(f))}">` +
                `<img loading="lazy" src="${esc(f.url)}?max=160" alt="">` +
                `<span class="cal-arc-score">${h[k] == null ? '' : `<i style="height:${Math.max(4, Math.round(h[k] * 100))}%"></i>`}</span>` +
                `<span class="cal-arc-n">${f.n}</span></button>`).join('');
        }
        showFrame(_at);
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
        const f = _frames[_at];
        if (img) { img.src = `${f.url}?max=1400`; img.alt = describe(f); }
        if (cap) cap.textContent = `${_at + 1} of ${_frames.length} · ${describe(f)}`;
        if (file) file.textContent = fileName(f);
        document.querySelectorAll('#cal-arc-film .cal-arc-cell').forEach((c, n) => {
            c.classList.toggle('is-on', n === _at);
            if (n === _at) c.scrollIntoView({ block: 'nearest', inline: 'nearest' });
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
        // ← → step through the run's exposures; ↑ ↓ through the runs.
        root.addEventListener('keydown', e => {
            if (/INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
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
