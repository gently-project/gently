/**
 * Calibration progress — what the calibration is looking at, while it looks.
 *
 *     CalProgressPanel.mount('op-cal-progress');
 *     CalProgressPanel.begin('embryo_1');      // the pane pressed Calibrate
 *     CalProgressPanel.finish(true, '101.2 um/deg');
 *
 * WHY
 *
 * Calibration is the longest thing the Devices tab can start: sixty to eighty
 * exposures, a minute or more, every one of them a frame Claude is being asked
 * to judge. The pane showed a disabled button for the whole of it. Kesavan, on
 * the walkthrough: "we have the calibration button, but it shows no in place
 * update on what is going on... not even images preview of calibration or
 * whatever." A run that shows nothing is indistinguishable from a run that has
 * hung, and when it ends badly there is no way to see WHICH frames were bad.
 *
 * Nothing new had to be measured. Every one of those frames is already pushed
 * to the viz server (`agent.push_viz`) and already broadcast to every client as
 * a `type: 'image'` message — the v1 gallery renders them after the fact. The
 * Operate pane simply never listened. This panel listens, and the metadata
 * riding along with each frame (galvo, piezo, visible, feature_score, sweep,
 * galvo_name, r_squared) is enough to narrate the run without the backend
 * emitting a single extra byte.
 *
 * WHAT IT DOES NOT OWN
 *
 * The run. operate.js starts the calibration and reports its result; this
 * panel only watches the frames go by. It therefore also narrates a
 * calibration the AGENT started from chat, which the pane never knew about —
 * a frame arriving with no run in progress opens one.
 */
const CalProgressPanel = (() => {
    'use strict';

    // A run is shown as cards that append, one a step: checking something is
    // there, finding the edges, each focus sweep, each fit, the summary. A card
    // holds its step's frames; the newest is the one shown, the rest are a
    // row under it. It was one picture and one row of forty thumbnails for
    // the whole run, where a step could not be told from the one before.
    //
    // Frames kept in a card, and cards kept in a run. Every base64 PNG in the
    // DOM is real memory; the newest of a step is what tells you where it is.
    const MAX_FRAMES = 16;
    const MAX_CARDS = 60;
    // A run is over when the frames stop. The agent's calibration has no
    // "finished" signal on this path, so quiet for this long ends it.
    const IDLE_MS = 20000;

    const TYPES = new Set([
        'presence_check',
        'edge_detection', 'focus_sweep', 'focus_plot', 'focus_montage', 'calibration_summary',
    ]);

    let _host = null;
    let _cards = [];      // {key, title, who, frames, shown, el}; the last is the step going on
    let _count = 0;       // frames seen this run, kept or not
    let _running = false;
    let _begun = false;   // begun by this page's Calibrate, not seen arriving
    let _embryo = null;
    // A batch walks the slide, so its frames come from several embryos and
    // each card has to say which one it is of.
    let _walk = false;
    let _idle = null;
    let _bound = false;

    const $ = id => document.getElementById(id);
    const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g,
        c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
    const num = (v, digits) => (typeof v === 'number' && isFinite(v) ? v.toFixed(digits) : null);

    // ── what a frame is, in words ──────────────────────────────────────────
    // Each phase names itself from the frame's own metadata, so the line reads
    // as the run's commentary rather than a progress bar with no content.
    function phaseOf(img) {
        const m = img.metadata || {};
        switch (img.data_type) {
            case 'presence_check': return 'Checking there is something there';
            case 'edge_detection': return 'Finding the embryo edges';
            case 'focus_sweep': {
                const side = m.galvo_name ? `${m.galvo_name} ` : '';
                const kind = { sparse: 'coarse', dense: 'dense', fine: 'fine' }[m.sweep] || '';
                return `Focus sweep · ${side}${kind}`.trim();
            }
            case 'focus_plot': return `Fitting the ${m.galvo_name || ''} focus curve`.trim();
            case 'focus_montage': return 'Choosing the focus slice';
            case 'calibration_summary': return 'Calibrated';
            default: return 'Calibrating';
        }
    }

    function captionOf(img) {
        const m = img.metadata || {};
        const bits = [];
        switch (img.data_type) {
            // The probe frame carries Claude's own words, which are the whole
            // point of it: "empty field" and "out of focus" get different fixes.
            case 'presence_check': {
                const g = num(m.galvo, 3);
                if (g !== null) bits.push(`galvo ${g}°`);
                bits.push(m.visible ? 'something here' : 'nothing here');
                if (m.description) bits.push(String(m.description).slice(0, 80));
                break;
            }
            case 'edge_detection': {
                const g = num(m.galvo, 3);
                if (g !== null) bits.push(`galvo ${g}°`);
                if (m.visible === true) bits.push('embryo visible');
                else if (m.visible === false) bits.push('nothing there');
                if (typeof m.feature_score === 'number') bits.push(`features ${m.feature_score}/10`);
                break;
            }
            case 'focus_sweep': {
                const p = num(m.piezo, 1), s = num(m.score, 2);
                if (m.galvo_name) bits.push(m.galvo_name);
                if (p !== null) bits.push(`piezo ${p} µm`);
                if (s !== null) bits.push(`sharpness ${s}`);
                if (m.peak_detected) bits.push('peak found');
                break;
            }
            case 'focus_plot': {
                const b = num(m.best_piezo, 1), r = num(m.r_squared, 3);
                if (m.galvo_name) bits.push(m.galvo_name);
                if (b !== null) bits.push(`best piezo ${b} µm`);
                if (r !== null) bits.push(`R² ${r}`);
                break;
            }
            case 'focus_montage': {
                if (m.pick != null) bits.push(`picked ${m.pick}`);
                if (m.method) bits.push(String(m.method));
                if (m.reasoning) bits.push(String(m.reasoning));
                break;
            }
            case 'calibration_summary': {
                const s = num(m.slope, 1);
                if (s !== null) bits.push(`${s} µm/deg`);
                const rt = num(m.r_squared_top, 3), rb = num(m.r_squared_bottom, 3);
                if (rt !== null && rb !== null) bits.push(`R² ${rt} top / ${rb} bottom`);
                break;
            }
            default: break;
        }
        return bits.join(' · ');
    }

    // A frame worth keeping when the strip overflows. The plots, the montage
    // and the summary are conclusions, not exposures — they are what you want
    // to still be looking at when the run ends.
    const isConclusion = img =>
        img.data_type === 'focus_plot' || img.data_type === 'calibration_summary' ||
        img.data_type === 'focus_montage';

    // ── the steps, named as the Calibration tab names them ─────────────────
    // "Where the embryo is", "Focus at 0.160° wide", "The fit": the same
    // headings a kept run is browsed by afterwards, so what is watched and
    // what is looked back at are organised the one way.
    const MIN_POINTS = 3;   // fewer is not a curve
    const SWEEP_WORD = { sparse: 'coarse', dense: 'dense', fine: 'fine', wide: 'wide' };
    function stepOf(img) {
        const m = img.metadata || {};
        switch (img.data_type) {
            case 'presence_check': return { key: 'presence', title: 'Checking there is something there' };
            case 'edge_detection': return { key: 'edges', title: 'Where the embryo is' };
            case 'focus_sweep': {
                const name = String(m.galvo_name || '');
                const word = SWEEP_WORD[m.sweep] || '';
                return { key: `focus|${name}|${m.sweep || ''}`, focus: name, title: name ? `Focus at ${name}${word ? ` ${word}` : ''}` : 'Finding the focus' };
            }
            // A sweep's plot and its montage are that sweep's conclusions:
            // they go on its card, not on one of their own.
            case 'focus_plot':
            case 'focus_montage': {
                const name = String(m.galvo_name || '');
                return { key: `focus|${name}|`, focus: name, joins: true, title: name ? `Focus at ${name}` : 'Finding the focus' };
            }
            case 'calibration_summary': return { key: 'fit', title: 'The fit' };
            default: return { key: String(img.data_type), title: phaseOf(img) };
        }
    }

    function cardKey(img) {
        const who = (img.metadata || {}).embryo_id || '';
        return `${who}|${stepOf(img).key}`;
    }

    // What a step found, in the words the Calibration tab's graphs use.
    function saysOf(img) {
        const m = img.metadata || {};
        if (img.data_type === 'focus_plot') {
            const b = num(m.best_piezo, 1), r = num(m.r_squared, 2);
            return [b !== null ? `sharpest at ${Number(m.best_piezo) > 0 ? '+' : ''}${b} µm` : '', r !== null ? `R² ${r}` : '']
                .filter(Boolean).join(' · ');
        }
        if (img.data_type === 'calibration_summary') {
            const sl = num(m.slope, 1), off = num(m.offset, 1), r = num(m.r_squared, 2);
            return [sl !== null ? `${sl} µm/°` : '', off !== null ? `offset ${Number(m.offset) > 0 ? '+' : ''}${off} µm` : '', r !== null ? `R² ${r}` : '']
                .filter(Boolean).join(' · ') || captionOf(img);
        }
        return '';
    }

    // A frame's point on its step's graph: sharpness against piezo for a
    // sweep, signal against galvo for the edges. None when it has no numbers.
    function pointOf(img) {
        const m = img.metadata || {};
        const ok = v => typeof v === 'number' && isFinite(v);
        if (img.data_type === 'focus_sweep' && ok(m.piezo) && ok(m.score)) return { x: m.piezo, y: m.score };
        if (img.data_type === 'edge_detection' && ok(m.galvo)) {
            const y = ok(m.signal) ? m.signal : ok(m.feature_score) ? m.feature_score : null;
            if (y !== null) return { x: m.galvo, y, seen: m.visible === true };
        }
        return null;
    }

    // Put a frame on the run's cards; true when it began a new card. Pure, so
    // the grouping can be tested without a page.
    function intoCards(cards, img) {
        const who = (img.metadata || {}).embryo_id || '';
        const step = stepOf(img);
        const key = `${who}|${step.key}`;
        let card = cards[cards.length - 1];
        if (step.joins) {
            // The newest card of this embryo's sweep at this angle, if any.
            const prefix = `${who}|focus|${step.focus}|`;
            for (let i = cards.length - 1; i >= 0; i--) {
                if (cards[i].key.startsWith(prefix)) { card = cards[i]; break; }
            }
        }
        const fits = card && (card.key === key || (step.joins && card.key.startsWith(`${who}|focus|${step.focus}|`)));
        const fresh = !fits;
        if (fresh) {
            card = { key, title: step.title, who: who || null, frames: [], pts: [], says: '', best: null, shown: -1, el: null };
            // The same angle swept again in the one fit: the first was the
            // wide look and this is the fine one, as the Calibration tab
            // names them. A fit ends at its edges card, the next one's start.
            if (step.focus && !SWEEP_WORD[(img.metadata || {}).sweep]) {
                for (let i = cards.length - 1; i >= 0; i--) {
                    const c = cards[i];
                    if (c.who !== card.who || c.key.endsWith('|edges')) break;
                    if (c.title === step.title) { c.title += ' wide'; c.dirty = true; card.title += ' fine'; break; }
                }
            }
            cards.push(card);
        }
        const m = img.metadata || {};
        const ok = v => typeof v === 'number' && isFinite(v);
        card.dirty = true;
        const pt = pointOf(img);
        if (pt) card.pts.push(pt);
        const says = saysOf(img);
        if (says) card.says = says;
        if (img.data_type === 'focus_plot' && ok(m.best_piezo)) {
            card.best = m.best_piezo;
            if (ok(m.galvo)) card.galvo = m.galvo;
        }
        if (img.data_type === 'calibration_summary' && ok(m.slope)) {
            // The line, and the sharpest piezo each of this embryo's sweeps
            // came to: the newest sweep at an angle is the one that counts.
            const at = new Map();
            cards.forEach(c => { if (c.who === card.who && ok(c.galvo) && ok(c.best)) at.set(c.galvo, c.best); });
            // The summary's own points are the fit's; the cards' are the
            // next best, for a summary that came without them.
            const own = (Array.isArray(m.points) ? m.points : []).filter(q => q && ok(q.galvo) && ok(q.piezo));
            if (own.length >= 2) { at.clear(); own.forEach(q => at.set(q.galvo, q.piezo)); }
            card.fit = { slope: m.slope, offset: ok(m.offset) ? m.offset : 0, points: [...at].map(([x, y]) => ({ x, y })) };
        }
        // The picture of a graph is not kept where the graph itself is drawn
        // from the numbers (graphOf): the sweep's curve, the fit's line.
        const drawn = (img.data_type === 'focus_plot' && card.pts.length >= MIN_POINTS)
            || (img.data_type === 'calibration_summary' && card.fit && card.fit.points.length >= 2);
        if (drawn) return fresh;
        card.frames.push(img);
        if (card.frames.length > MAX_FRAMES) {
            // Drop the oldest EXPOSURE, never a conclusion: the findings are
            // the part of the step you still want when it ends. Its point
            // stays on the graph.
            const drop = card.frames.findIndex(f => !isConclusion(f));
            card.frames.splice(drop < 0 ? 0 : drop, 1);
            if (card.shown > 0) card.shown -= 1;
        }
        return fresh;
    }

    // The step's graph so far, drawn as the Calibration tab draws a kept
    // run's (CalibrationArchive.chart): a point a frame, as the frames come.
    function graphOf(card) {
        const arc = typeof CalibrationArchive !== 'undefined' ? CalibrationArchive : null;
        if (!arc || !arc.chart) return '';
        if (card.fit && card.fit.points.length >= 2) {
            const f = card.fit, gs = f.points.map(p => p.x);
            const pad = (Math.max(...gs) - Math.min(...gs)) * 0.15 || 0.05;
            const y = g => f.slope * g + f.offset;
            try {
                return arc.chart({ title: 'Sharpest piezo against galvo, and the line through it', xLabel: 'galvo °', h: 132,
                    line: [[Math.min(...gs) - pad, y(Math.min(...gs) - pad)], [Math.max(...gs) + pad, y(Math.max(...gs) + pad)]],
                    pts: f.points.map(q => ({ x: q.x, y: q.y, tip: `galvo ${q.x.toFixed(3)}° · sharpest at piezo ${q.y.toFixed(1)} µm` })) });
            } catch (_) { return ''; }
        }
        if (card.pts.length < MIN_POINTS) return '';
        const focus = card.key.includes('|focus|');
        const top = Math.max(...card.pts.map(p => p.y), 1e-9);
        const pts = card.pts.map(p => ({ x: p.x, y: focus ? p.y / top : p.y, tip: focus ? `piezo ${p.x.toFixed(1)} µm · sharpness ${(100 * p.y / top).toFixed(0)}%` : `galvo ${p.x.toFixed(3)}° · ${p.seen ? 'embryo seen' : 'nothing seen'}` }));
        const seen = card.pts.filter(p => p.seen).map(p => p.x);
        try {
            return arc.chart(focus
                ? { title: `Sharpness against piezo, ${card.title}`, xLabel: 'piezo µm', zero: true, yTop: 'best', vline: card.best, pts, line: pts.slice().sort((a, b) => a.x - b.x).map(p => [p.x, p.y]) }
                : { title: 'Signal at each galvo angle', xLabel: 'galvo °', zero: true, band: seen.length ? [Math.min(...seen), Math.max(...seen)] : null, pts });
        } catch (_) { return ''; }
    }

    const wrapOf = () => (_host ? _host.querySelector('.cp') : null);

    function renderHead(phase) {
        const wrap = wrapOf();
        if (!wrap) return;
        const last = _cards[_cards.length - 1];
        wrap.querySelector('.cp-phase').textContent = phase || (last ? last.title : '');
        wrap.querySelector('.cp-count').textContent = _count
            ? `${_count} frame${_count === 1 ? '' : 's'} · ${_cards.length} step${_cards.length === 1 ? '' : 's'}`
            : 'no frames yet';
        wrap.querySelector('.cp-dot').hidden = !_running;
    }

    function renderCard(card) {
        const el = card.el;
        if (!el) return;
        const n = card.frames.length;
        const idx = card.shown >= 0 && card.shown < n ? card.shown : n - 1;
        const cur = card.frames[idx];
        el.querySelector('.cp-card-n').textContent = n > 1 ? `${n} frames` : '';
        el.querySelector('.cp-card-title').textContent = card.title;
        el.querySelector('.cp-stage').hidden = !n;
        el.querySelector('.cp-card-says').textContent = card.says || '';
        const graph = el.querySelector('.cp-card-graph');
        const svg = graphOf(card);
        graph.hidden = !svg;
        if (svg) graph.innerHTML = svg;
        const img = el.querySelector('.cp-img');
        if (cur && cur.base64_png) { img.src = `data:image/png;base64,${cur.base64_png}`; img.hidden = false; }
        else img.hidden = true;
        el.querySelector('.cp-cap').textContent = cur ? captionOf(cur) : '';
        const strip = el.querySelector('.cp-strip');
        strip.hidden = n < 2;
        if (n < 2) { strip.innerHTML = ''; return; }
        strip.innerHTML = card.frames.map((f, i) => {
            const label = esc(captionOf(f) || phaseOf(f));
            const cls = `cp-thumb${i === idx ? ' is-on' : ''}${isConclusion(f) ? ' is-key' : ''}`;
            const pic = f.base64_png ? `<img src="data:image/png;base64,${f.base64_png}" alt="">` : '';
            return `<button class="${cls}" type="button" data-i="${i}" title="${label}" aria-label="${label}">${pic}</button>`;
        }).join('');
        if (card.shown < 0) strip.scrollLeft = strip.scrollWidth;
    }

    // A new card goes on the end. The one before it is finished: it stops
    // being the live one, and is left as it stood.
    function appendCard(card) {
        const wrap = wrapOf();
        if (!wrap) return;
        const list = wrap.querySelector('.cp-cards');
        list.querySelectorAll('.cp-card.is-live').forEach(c => c.classList.remove('is-live'));
        const el = document.createElement('article');
        el.className = 'cp-card is-live';
        el.setAttribute('role', 'listitem');
        el.innerHTML = `
            <header class="cp-card-head">
              <b class="cp-card-title">${esc(card.title)}</b>
              ${_walk && card.who ? `<span class="cp-card-who">${esc(String(card.who).replace(/^embryo_/, 'embryo '))}</span>` : ''}
              <span class="cp-card-n"></span>
            </header>
            <div class="cp-card-says"></div>
            <div class="cp-card-graph cal-arc-chart" hidden></div>
            <div class="cp-stage"><img class="cp-img" alt="${esc(card.title)}" hidden></div>
            <div class="cp-cap"></div>
            <div class="cp-strip" hidden></div>`;
        el.querySelector('.cp-strip').addEventListener('click', e => {
            const b = e.target.closest('.cp-thumb');
            if (!b) return;
            const i = parseInt(b.dataset.i, 10);
            // The newest frame of a card goes back to following its step.
            card.shown = (i === card.frames.length - 1) ? -1 : i;
            renderCard(card);
        });
        card.el = el;
        // Following the run means the newest card is in view; somebody who
        // has scrolled back to look at an earlier step is left where they are.
        const scroller = list.closest('.op-calfit-body') || list;
        const following = scroller.scrollHeight - scroller.scrollTop - scroller.clientHeight < 160;
        list.appendChild(el);
        while (_cards.length > MAX_CARDS) {
            const gone = _cards.shift();
            if (gone.el) gone.el.remove();
        }
        if (following && el.scrollIntoView) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    function render() {
        const wrap = wrapOf();
        if (!wrap) return;
        if (!_cards.length && !_running) { wrap.hidden = true; return; }
        wrap.hidden = false;
        renderHead();
    }

    function armIdle() {
        if (_idle) clearTimeout(_idle);
        // A run begun here ends when its request does (finish), however long
        // a step is quiet: timed out, its next frame started the cards afresh
        // and the steps already shown were gone.
        if (_begun) return;
        _idle = setTimeout(() => { _running = false; render(); }, IDLE_MS);
    }

    function clearCards() {
        _cards = [];
        _count = 0;
        const wrap = wrapOf();
        if (wrap) wrap.querySelector('.cp-cards').innerHTML = '';
    }

    function onImage(data) {
        if (!data || !TYPES.has(data.data_type)) return;
        const emb = (data.metadata || {}).embryo_id;
        // A frame for a different embryo belongs to a different run.
        if (_running && _embryo && emb && emb !== _embryo) return;
        if (!_running) {
            // Nobody pressed Calibrate here — the agent is calibrating. Show it,
            // and do not pin it to one embryo: the agent may be walking the
            // slide too, and dropping the other embryos' frames would make a
            // batch look like it stalled after the first one.
            clearCards();
            _running = true;
            _embryo = null;
            _walk = true;
        }
        _count += 1;
        const fresh = intoCards(_cards, data);
        if (fresh) appendCard(_cards[_cards.length - 1]);
        // A sweep's conclusion lands on its own card, which need not be the last.
        _cards.forEach(c => { if (c.dirty) { c.dirty = false; renderCard(c); } });
        armIdle();
        render();
    }

    function begin(embryoId) {
        clearCards();
        _running = true;
        _embryo = embryoId || null;
        _begun = true;
        // No id means "whatever the run visits" — a batch, not one embryo.
        _walk = !embryoId;
        armIdle();
        const wrap = wrapOf();
        if (!wrap) return;
        // Nothing has arrived yet, but the run HAS started: say so rather than
        // leaving the pane blank until the first exposure comes back.
        wrap.hidden = false;
        renderHead('Starting the calibration');
    }

    function finish(ok, text) {
        _running = false;
        _begun = false;
        if (_idle) { clearTimeout(_idle); _idle = null; }
        const wrap = wrapOf();
        if (!wrap) return;
        if (!_cards.length) {
            // A run that produced no frames has nothing to show; the pane's
            // own result line already says what happened.
            wrap.hidden = true;
            return;
        }
        // How it ended is the last card: one line, and no picture.
        const list = wrap.querySelector('.cp-cards');
        list.querySelectorAll('.cp-card.is-live').forEach(c => c.classList.remove('is-live'));
        const el = document.createElement('article');
        el.className = `cp-card cp-card-end ${ok ? 'is-ok' : 'is-bad'}`;
        el.setAttribute('role', 'listitem');
        el.innerHTML = `<header class="cp-card-head"><b class="cp-card-title">${ok ? 'Calibrated' : 'Calibration failed'}</b></header>`
            + (text ? `<div class="cp-cap">${esc(text)}</div>` : '');
        list.appendChild(el);
        if (el.scrollIntoView) el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        renderHead(ok ? 'Calibrated' : 'Calibration failed');
    }

    function mount(hostId) {
        _host = $(hostId);
        if (!_host) return;
        _host.innerHTML = `
          <div class="cp" hidden>
            <div class="cp-head">
              <span class="cp-dot" aria-hidden="true" hidden></span>
              <span class="cp-phase"></span>
              <span class="cp-count"></span>
            </div>
            <div class="cp-cards" role="list" aria-label="The steps of this calibration, as they happen"></div>
          </div>`;
        if (!_bound && typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('IMAGE_RECEIVED', onImage);
            _bound = true;
        }
        render();
    }

    return { mount, begin, finish, phaseOf, captionOf, stepOf, cardKey, intoCards, MAX_FRAMES, _onImage: onImage };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CalProgressPanel;
