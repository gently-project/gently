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

    // A run is shown as cards, one a step: where the embryo is, each focus
    // sweep, the fit. A card is the step's finding, its graph and one
    // picture. The graph is how the step is looked through: the exposure
    // under the pointer is the picture, and at rest the picture is the one
    // the step picked. A run that was kept is shown with the same cards
    // (show), so what was watched and what is looked back at are one thing.
    //
    // Exposures whose pictures a card holds, and cards a run holds. A base64
    // PNG is real memory; past this the oldest gives its picture up and
    // keeps its point on the graph.
    const MAX_FRAMES = 240;
    const MAX_CARDS = 60;
    // A run is over when the frames stop. The agent's calibration has no
    // "finished" signal on this path, so quiet for this long ends it.
    const IDLE_MS = 20000;

    const TYPES = new Set([
        'presence_check',
        'edge_detection', 'focus_sweep', 'focus_plot', 'focus_montage', 'calibration_summary',
    ]);

    let _host = null;
    let _cards = [];      // the steps, in order; the last is the one going on
    let _count = 0;       // exposures seen this run
    let _live = new Set();   // embryos whose run this page watched and still shows
    let _onOpen = null;      // a kept run's picture, pressed
    let _sel = null;         // the step pressed open; null follows the newest
    let _phase = null;       // the heading, when it is not the step going on
    let _tone = '';
    let _detail = null;      // the one open body
    let _endedAt = 0;        // when the run begun here was answered
    const TAIL_MS = 90000;   // how long after that its last frames may still arrive: 20 s, on the rig
    let _running = false;
    let _begun = false;   // begun by this page's Calibrate, not seen arriving
    let _embryo = null;
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

    // ── the steps, named as the Calibration tab names them ─────────────────
    // "Where the embryo is", "Focus at 0.160° wide", "The fit": the same
    // headings a kept run is browsed by afterwards, so what is watched and
    // what is looked back at are organised the one way.
    const MIN_POINTS = 3;   // fewer is not a curve
    const SWEEP_WORD = { sparse: 'coarse', dense: 'dense', fine: 'fine', wide: 'wide' };
    const ok = v => typeof v === 'number' && isFinite(v);
    const signed = (v, d) => `${v > 0 ? '+' : v < 0 ? '−' : ''}${Math.abs(v).toFixed(d)}`;

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

    // Whose step, and on which side: a walk visits several embryos and "A
    // then B" fits each one twice.
    const ownerOf = img => {
        const m = img.metadata || {};
        return `${m.embryo_id || ''}|${m.side === 'A' || m.side === 'B' ? m.side : ''}`;
    };
    function cardKey(img) { return `${ownerOf(img)}|${stepOf(img).key}`; }

    // A frame's point on its step's graph: sharpness against piezo for a
    // sweep, signal against galvo for the edges. None when it has no numbers.
    function pointOf(img) {
        const m = img.metadata || {};
        if (img.data_type === 'focus_sweep' && ok(m.piezo) && ok(m.score)) return { x: m.piezo, y: m.score };
        if (img.data_type === 'edge_detection' && ok(m.galvo)) {
            const y = ok(m.signal) ? m.signal : ok(m.feature_score) ? m.feature_score : null;
            if (y !== null) return { x: m.galvo, y, seen: m.visible === true };
        }
        return null;
    }

    // What the step has found so far, in the words the Calibration tab uses.
    function saysOf(card) {
        if (card.fit) {
            const f = card.fit;
            return [`${f.slope.toFixed(1)} µm/°`, `offset ${signed(f.offset, 1)} µm`, ok(f.r2) ? `R² ${f.r2.toFixed(2)}` : '']
                .filter(Boolean).join(' · ');
        }
        if (card.kind === 'edges' && card.pts.length) {
            const seen = card.pts.filter(p => p.seen).map(p => p.x);
            return seen.length ? `seen from ${signed(Math.min(...seen), 2)}° to ${signed(Math.max(...seen), 2)}°` : 'not seen at any angle';
        }
        if (ok(card.best)) {
            return [`sharpest at ${signed(card.best, 1)} µm`, ok(card.r2) ? `R² ${card.r2.toFixed(2)}` : ''].filter(Boolean).join(' · ');
        }
        return card.note || '';
    }

    // The frame the step settled on: the exposure nearest the sharpest piezo
    // of a sweep, the brightest angle the embryo was seen at. -1 before the
    // step has concluded, or when it has nothing to pick.
    function pickedOf(card) {
        let at = -1;
        if (card.kind === 'edges') {
            card.pts.forEach(p => { if (p.seen && (at < 0 || p.y > card.pts[at].y)) at = card.pts.indexOf(p); });
        } else if (ok(card.best)) {
            card.pts.forEach((p, k) => { if (at < 0 || Math.abs(p.x - card.best) < Math.abs(card.pts[at].x - card.best)) at = k; });
        }
        return at < 0 ? -1 : card.pts[at].frame;
    }

    // Put a frame on the run's cards; true when it began a new card. Pure, so
    // the grouping can be tested without a page.
    function intoCards(cards, img) {
        const m = img.metadata || {};
        let owner = ownerOf(img);
        // Not every frame says its side. The same embryo, with one of the two
        // not saying, is the same fit going on.
        const prev = cards[cards.length - 1];
        if (prev && prev.owner !== owner && prev.who === (m.embryo_id || null)
            && (!prev.side || !owner.split('|')[1])) owner = prev.owner;
        const step = stepOf(img);
        const key = `${owner}|${step.key}`;
        let card = cards[cards.length - 1];
        const joinsTo = `${owner}|focus|${step.focus}|`;
        if (step.joins) {
            // The newest card of this owner's sweep at this angle, if any.
            for (let i = cards.length - 1; i >= 0; i--) {
                if (cards[i].key.startsWith(joinsTo)) { card = cards[i]; break; }
            }
        }
        const fits = card && (card.key === key || (step.joins && card.key.startsWith(joinsTo)));
        const fresh = !fits;
        if (fresh) {
            card = {
                key, owner, title: step.title, who: m.embryo_id || null, side: owner.split('|')[1] || null,
                kind: step.key.split('|')[0], named: step.key.startsWith('focus|') ? !!step.focus : true,
                frames: [], pts: [], extras: [], note: '', best: null, r2: null, galvo: null, fit: null,
                pin: -1, hover: -1, el: null,
            };
            // The same angle swept again in the one fit: the first was the
            // wide look and this is the fine one, as the Calibration tab
            // names them. A fit ends at its edges card, the next one's start.
            if (step.focus && !SWEEP_WORD[m.sweep]) {
                for (let i = cards.length - 1; i >= 0; i--) {
                    const c = cards[i];
                    if (c.owner !== owner || c.kind === 'edges') break;
                    if (c.title === step.title) { c.title += ' wide'; c.dirty = true; card.title += ' fine'; break; }
                }
            }
            cards.push(card);
        }
        card.dirty = true;
        if (img.data_type === 'focus_plot') {
            if (ok(m.best_piezo)) card.best = m.best_piezo;
            if (ok(m.r_squared)) card.r2 = m.r_squared;
            if (ok(m.galvo)) card.galvo = m.galvo;
        }
        if (img.data_type === 'focus_montage') {
            card.note = [m.pick != null ? `picked ${m.pick}` : '', m.method ? `by ${m.method}` : ''].filter(Boolean).join(' ');
            card.why = m.reasoning ? String(m.reasoning) : '';
        }
        if (img.data_type === 'calibration_summary' && ok(m.slope)) {
            // The line, and the points it went through. The summary's own are
            // the fit's; without them, the sharpest piezo each of this
            // owner's sweeps came to, the newest sweep at an angle counting.
            const at = new Map();
            cards.forEach(c => { if (c.owner === owner && ok(c.galvo) && ok(c.best)) at.set(c.galvo, c.best); });
            let points = [...at].map(([x, y]) => ({ x, y }));
            const own = (Array.isArray(m.points) ? m.points : []).filter(q => q && ok(q.galvo) && ok(q.piezo));
            if (own.length >= 2) points = own.map(q => ({ x: q.galvo, y: q.piezo }));
            card.fit = { slope: m.slope, offset: ok(m.offset) ? m.offset : 0, r2: ok(m.r_squared) ? m.r_squared : null, points };
        }
        const pt = pointOf(img);
        if (pt) {
            // An exposure: a point on the graph and the picture behind it.
            pt.frame = card.frames.length;
            card.pts.push(pt);
            card.frames.push(img);
            // The pictures are the memory; the oldest gives its up, and keeps
            // its point.
            const over = card.frames.length - MAX_FRAMES;
            if (over > 0 && card.frames[over - 1]) card.frames[over - 1] = { ...card.frames[over - 1], base64_png: null };
            return fresh;
        }
        // A picture with no point of its own. The picture of a graph is not
        // kept where the graph is drawn from the numbers: the sweep's curve,
        // the fit's line.
        const drawn = (img.data_type === 'focus_plot' && card.pts.length >= MIN_POINTS)
            || (img.data_type === 'calibration_summary' && card.fit && card.fit.points.length >= 2);
        if (!drawn) card.extras.push(img);
        return fresh;
    }

    // ── the run, drawn ──────────────────────────────────────────────────────
    // The steps are a list, one open at a time. The step going on is open:
    // its graph, the exposure looked at, and a row of its exposures with the
    // one it picked marked. When the next step starts it folds to one line,
    // its name and what it found, and can be opened again by pressing it.
    // Nothing here scrolls: a fit is eight lines and one open step, and a
    // walk shows one embryo's one side at a time.
    const hasGraph = card => card.kind === 'edges' || card.kind === 'fit' || (card.kind === 'focus' && card.named);
    const srcOf = img => (!img ? '' : img.base64_png ? `data:image/png;base64,${img.base64_png}` : (img.src || ''));

    // The step's graph so far, drawn as the Calibration tab draws a kept
    // run's (CalibrationArchive.chart): a point an exposure, as they come.
    function graphOf(card, on) {
        const arc = typeof CalibrationArchive !== 'undefined' ? CalibrationArchive : null;
        if (!arc || !arc.chart) return '';
        try {
            if (card.fit && card.fit.points.length >= 2) {
                const f = card.fit, gs = f.points.map(p => p.x);
                const pad = (Math.max(...gs) - Math.min(...gs)) * 0.15 || 0.05;
                const y = g => f.slope * g + f.offset;
                return arc.chart({ title: 'Sharpest piezo against galvo, and the line through it', xLabel: 'galvo °',
                    line: [[Math.min(...gs) - pad, y(Math.min(...gs) - pad)], [Math.max(...gs) + pad, y(Math.max(...gs) + pad)]],
                    pts: f.points.map(q => ({ x: q.x, y: q.y, tip: `galvo ${signed(q.x, 3)}° · sharpest at piezo ${signed(q.y, 1)} µm` })) });
            }
            if (card.pts.length < MIN_POINTS) return '';
            if (card.kind === 'edges') {
                const seen = card.pts.filter(p => p.seen).map(p => p.x);
                return arc.chart({ title: 'Signal at each galvo angle', xLabel: 'galvo °', zero: true, on,
                    band: seen.length ? [Math.min(...seen), Math.max(...seen)] : null,
                    pts: card.pts.map(p => ({ x: p.x, y: p.y, frame: p.frame, tip: `galvo ${signed(p.x, 3)}° · ${p.seen ? 'embryo seen' : 'nothing seen'}` })) });
            }
            const top = Math.max(...card.pts.map(p => p.y), 1e-9);
            const pts = card.pts.map(p => ({ x: p.x, y: p.y / top, frame: p.frame, tip: `piezo ${signed(p.x, 1)} µm · sharpness ${(100 * p.y / top).toFixed(0)}% of this sweep’s best` }));
            return arc.chart({ title: `Sharpness against piezo, ${card.title}`, xLabel: 'piezo µm', zero: true, yTop: 'best', on,
                vline: card.best, pts, line: pts.slice().sort((a, b) => a.x - b.x).map(p => [p.x, p.y]) });
        } catch (_) { return ''; }
    }

    // Which exposure of a step is shown: the one under the pointer, else the
    // one pinned, else the one the step picked, else the newest.
    function shownOf(card) {
        const n = card.frames.length;
        if (card.hover >= 0 && card.hover < n) return card.hover;
        if (card.pin >= 0 && card.pin < n) return card.pin;
        const picked = pickedOf(card);
        return picked >= 0 ? picked : n - 1;
    }

    // The exposures on the open step's row: at most `max`, spread evenly
    // along the graph's axis, with the one picked and the one shown always
    // among them. A sweep is eighty exposures; a row holds a dozen.
    function thumbsOf(card, max, shown) {
        const order = card.pts.slice().sort((a, b) => a.x - b.x).map(p => p.frame);
        if (order.length <= max) return order;
        const keep = new Set();
        for (let k = 0; k < max; k++) keep.add(order[Math.round(k * (order.length - 1) / (max - 1))]);
        [pickedOf(card), shown].forEach(must => {
            if (must < 0 || keep.has(must) || !order.includes(must)) return;
            // It takes the place of the sampled exposure nearest it.
            const at = order.indexOf(must);
            let near = null;
            keep.forEach(f => { if (near === null || Math.abs(order.indexOf(f) - at) < Math.abs(order.indexOf(near) - at)) near = f; });
            keep.delete(near);
            keep.add(must);
        });
        return order.filter(f => keep.has(f));
    }
    const THUMBS = 12;

    const wrapOf = () => (_host ? _host.querySelector('.cp') : null);
    const ownerWords = card => [card.who ? String(card.who).replace(/^embryo_/, 'embryo ') : '', card.side ? `side ${card.side}` : ''].filter(Boolean).join(' · ');
    // The step looked at: the one pressed, else the newest.
    const current = () => (_sel && _cards.includes(_sel) ? _sel : _cards[_cards.length - 1]) || null;

    function renderHead(phase, tone) {
        const wrap = wrapOf();
        if (!wrap) return;
        if (phase != null) { _phase = phase; _tone = tone || ''; }
        const last = _cards[_cards.length - 1];
        const head = wrap.querySelector('.cp-head');
        head.classList.toggle('is-ok', _tone === 'ok');
        head.classList.toggle('is-bad', _tone === 'bad');
        wrap.querySelector('.cp-phase').textContent = _phase != null ? _phase : (last ? last.title : '');
        wrap.querySelector('.cp-count').textContent = _count
            ? `${_count} exposure${_count === 1 ? '' : 's'} · ${_cards.length} step${_cards.length === 1 ? '' : 's'}`
            : '';
        wrap.querySelector('.cp-dot').hidden = !_running;
    }

    // Whose steps are on the tiles: one embryo's one side. With one owner
    // there is nothing to choose and no row.
    function renderOwners() {
        const wrap = wrapOf();
        if (!wrap) return;
        const row = wrap.querySelector('.cp-secs');
        const owners = [];
        _cards.forEach(c => { if (!owners.some(o => o.owner === c.owner)) owners.push(c); });
        const cur = current();
        row.hidden = owners.length < 2;
        row.innerHTML = owners.length < 2 ? '' : owners.map(c =>
            `<button type="button" class="cp-sec${cur && cur.owner === c.owner ? ' is-on' : ''}" role="tab" aria-selected="${cur && cur.owner === c.owner}" data-owner="${esc(c.owner)}">${esc(ownerWords(c) || 'run')}</button>`).join('');
        const one = wrap.querySelector('.cp-owner');
        one.textContent = owners.length === 1 ? ownerWords(owners[0]) : '';
    }

    function stepHead(card) {
        const says = saysOf(card);
        const n = card.frames.length;
        return `<b class="cp-step-title">${esc(card.title)}</b>`
            + `<span class="cp-step-says${says ? ' is-found' : ''}">${esc(says || (_running && card === _cards[_cards.length - 1] ? 'measuring…' : '—'))}</span>`
            + `<span class="cp-step-n">${n > 1 ? `${n} exposures` : ''}</span>`;
    }

    // The steps of the owner looked at, in order. A step's line is made once
    // and refilled, and the one open body is moved under the step it is of,
    // so a step arriving does not redraw the ones before it.
    function renderSteps() {
        const wrap = wrapOf();
        if (!wrap) return;
        const list = wrap.querySelector('.cp-steps');
        const cur = current();
        const mine = _cards.filter(c => cur && c.owner === cur.owner);
        const have = [...list.children];
        if (have.length !== mine.length || have.some((el, i) => el !== mine[i].el)) {
            list.innerHTML = '';
            mine.forEach(card => {
                if (!card.el) {
                    card.el = document.createElement('section');
                    card.el.className = 'cp-step';
                    card.el.setAttribute('role', 'listitem');
                    card.el.innerHTML = '<button type="button" class="cp-step-head"></button>';
                    card.el.firstChild.addEventListener('click', () => look(card));
                    card.dirty = true;
                }
                list.appendChild(card.el);
            });
        }
        const newest = _cards[_cards.length - 1];
        mine.forEach(card => {
            const head = card.el.firstChild;
            if (card.dirty) head.innerHTML = stepHead(card);
            card.el.classList.toggle('is-open', card === cur);
            card.el.classList.toggle('is-live', _running && card === newest);
            head.setAttribute('aria-expanded', card === cur ? 'true' : 'false');
        });
        if (cur && cur.el && _detail.parentNode !== cur.el) cur.el.appendChild(_detail);
    }

    // The picture, its caption and the marks on the graph: everything that
    // changes when only the exposure looked at does. The graph is not redrawn
    // here, so a pointer moving along it is not chasing new elements.
    function renderShown() {
        const wrap = _detail, card = current();
        if (!wrap || !card) return;
        const at = shownOf(card), picked = pickedOf(card);
        const cur = at >= 0 ? card.frames[at] : card.extras[card.extras.length - 1];
        const stage = wrap.querySelector('.cp-stage'), img = wrap.querySelector('.cp-img');
        const src = srcOf(cur);
        if (src) { if (img.getAttribute('src') !== src) img.src = src; img.hidden = false; }
        else img.hidden = true;
        stage.classList.toggle('is-gone', !!cur && !src);
        stage.classList.toggle('can-open', !!(cur && cur.src && _onOpen));
        // The fit has no exposure of its own: its points, said.
        const said = wrap.querySelector('.cp-said');
        said.hidden = !!cur;
        said.textContent = cur ? '' : card.fit
            ? card.fit.points.map(q => `galvo ${signed(q.x, 3)}°  →  piezo ${signed(q.y, 1)} µm`).join('\n')
            : (_running ? 'waiting for the first exposure' : '');
        const word = card.kind === 'edges' ? 'brightest' : 'sharpest';
        wrap.querySelector('.cp-cap').textContent = !cur ? '' : at >= 0
            ? `${captionOf(cur)}${at === picked ? ` · the ${word}` : ''}${card.pin === at ? ' · pinned' : ''}`
            : (card.why || captionOf(cur));
        // The row of exposures: the one shown and the one picked are among
        // them and marked. Redrawn only when which exposures it holds changes.
        const strip = wrap.querySelector('.cp-thumbs');
        const row = thumbsOf(card, THUMBS, at);
        strip.hidden = row.length < 2;
        const sig = `${_cards.indexOf(card)}:${row.join(',')}:${picked}`;
        if (strip.dataset.sig !== sig) {
            strip.dataset.sig = sig;
            strip.innerHTML = row.map(f => {
                const img = card.frames[f], label = `${captionOf(img)}${f === picked ? ` · the ${word}` : ''}`;
                const pic = srcOf(img) ? `<img loading="lazy" src="${esc(img.thumb || srcOf(img))}" alt="">` : '';
                return `<button type="button" class="cp-thumb${f === picked ? ' is-pick' : ''}" data-f="${f}" title="${esc(label)}" aria-label="${esc(label)}">${pic}${f === picked ? `<i>${word}</i>` : ''}</button>`;
            }).join('');
        }
        strip.querySelectorAll('.cp-thumb').forEach(b => b.classList.toggle('is-on', Number(b.dataset.f) === at));
        wrap.querySelectorAll('.cp-graph .pt').forEach(g => {
            const n = Number(g.dataset.arcFrame);
            g.classList.toggle('is-on', n === at);
            g.classList.toggle('is-pick', n === picked);
        });
    }

    function renderDetail() {
        const wrap = _detail, card = current();
        if (!wrap) return;
        wrap.hidden = !card;
        if (!card) return;
        const graph = wrap.querySelector('.cp-graph');
        const svg = hasGraph(card) ? graphOf(card, shownOf(card)) : '';
        // A step with no curve says why it chose, where the curve would be.
        graph.innerHTML = svg || `<p class="cp-why">${esc(card.why || (hasGraph(card) ? 'the curve is drawn from the third exposure on' : ''))}</p>`;
        graph.setAttribute('aria-label', `${card.title}: the graph. Left and right arrows step through its exposures.`);
        renderShown();
    }

    function renderAll() {
        const wrap = wrapOf();
        if (!wrap) return;
        if (!_cards.length && !_running) { wrap.hidden = true; return; }
        wrap.hidden = false;
        renderHead();
        renderOwners();
        renderSteps();
        renderDetail();
        _cards.forEach(c => { c.dirty = false; });
    }

    // A step's line pressed opens it; the newest one pressed goes back to
    // following the run.
    function look(card) {
        _sel = card === _cards[_cards.length - 1] ? null : card;
        renderAll();
    }

    // The exposure looked at changes by pointer, by press and by key: the
    // graph is how a step is walked through. Wired once, on the one graph.
    function wire(wrap) {
        const graph = _detail.querySelector('.cp-graph');
        const frameAt = e => { const g = e.target.closest && e.target.closest('[data-arc-frame]'); return g ? Number(g.dataset.arcFrame) : -1; };
        graph.addEventListener('mouseover', e => { const c = current(), n = frameAt(e); if (c && n >= 0 && n !== c.hover) { c.hover = n; renderShown(); } });
        graph.addEventListener('mouseleave', () => { const c = current(); if (c && c.hover >= 0) { c.hover = -1; renderShown(); } });
        graph.addEventListener('click', e => { const c = current(), n = frameAt(e); if (c && n >= 0) { c.pin = c.pin === n ? -1 : n; renderShown(); } });
        // Left and right step through the exposures in the graph's order.
        graph.addEventListener('keydown', e => {
            const c = current();
            if (!c || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight' && e.key !== 'Escape')) return;
            e.preventDefault();
            if (e.key === 'Escape') { c.pin = -1; renderShown(); return; }
            const order = c.pts.slice().sort((a, b) => a.x - b.x).map(p => p.frame);
            if (!order.length) return;
            const k = order.indexOf(shownOf(c)) + (e.key === 'ArrowRight' ? 1 : -1);
            c.pin = order[Math.max(0, Math.min(order.length - 1, k))];
            renderShown();
        });
        _detail.querySelector('.cp-thumbs').addEventListener('click', e => {
            const c = current(), b = e.target.closest('.cp-thumb');
            if (!c || !b) return;
            const n = Number(b.dataset.f);
            c.pin = c.pin === n ? -1 : n;
            renderShown();
        });
        _detail.querySelector('.cp-stage').addEventListener('click', () => {
            const c = current();
            if (!c) return;
            const at = shownOf(c), cur = at >= 0 ? c.frames[at] : c.extras[c.extras.length - 1];
            if (cur && cur.src && _onOpen) _onOpen(cur);
        });
        wrap.querySelector('.cp-secs').addEventListener('click', e => {
            const b = e.target.closest('[data-owner]');
            if (!b) return;
            const mine = _cards.filter(c => c.owner === b.dataset.owner);
            if (mine.length) look(mine[mine.length - 1]);
        });
    }

    function armIdle() {
        if (_idle) clearTimeout(_idle);
        // A run begun here ends when its request does (finish), however long
        // a step is quiet: timed out, its next frame started the steps afresh
        // and the ones already shown were gone.
        if (_begun) return;
        _idle = setTimeout(() => { _running = false; _cards.forEach(c => { c.dirty = true; }); renderAll(); }, IDLE_MS);
    }

    function clearCards() {
        _cards = [];
        _count = 0;
        _sel = null;
        _phase = null;
        _tone = '';
        _live = new Set();
        _endedAt = 0;
        _onOpen = null;
        const wrap = wrapOf();
        if (wrap) { _detail.remove(); wrap.querySelector('.cp-steps').innerHTML = ''; }
    }

    function onImage(data) {
        if (!data || !TYPES.has(data.data_type)) return;
        const emb = (data.metadata || {}).embryo_id;
        // A frame for a different embryo belongs to a different run.
        if (_running && _embryo && emb && emb !== _embryo) return;
        // The request answers before its last frames have come down the
        // socket. For a while after a run ends, a frame of an embryo that run
        // was on is the end of that run: taken as a new one, it wiped the
        // steps and left the last sweep's tail standing alone.
        const tail = !_running && _endedAt && Date.now() - _endedAt < TAIL_MS && (!emb || _live.has(emb));
        if (tail) {
            if (pointOf(data)) _count += 1;
            intoCards(_cards, data);
            renderAll();
            return;
        }
        if (!_running) {
            // Nobody pressed Calibrate here — the agent is calibrating. Show it,
            // and do not pin it to one embryo: the agent may be walking the
            // slide too, and dropping the other embryos' frames would make a
            // batch look like it stalled after the first one.
            clearCards();
            _running = true;
            _embryo = null;
        }
        if (emb) _live.add(emb);
        if (pointOf(data)) _count += 1;
        const before = _cards[_cards.length - 1];
        if (intoCards(_cards, data)) {
            // The step before is over: its tile stops saying it is measuring.
            if (before) before.dirty = true;
            while (_cards.length > MAX_CARDS) _cards.shift();
        }
        _phase = null;
        armIdle();
        renderAll();
    }

    function begin(embryoId) {
        clearCards();
        _running = true;
        _embryo = embryoId || null;
        _begun = true;
        armIdle();
        const wrap = wrapOf();
        if (!wrap) return;
        // Nothing has arrived yet, but the run HAS started: say so rather than
        // leaving the pane blank until the first exposure comes back.
        wrap.hidden = false;
        renderHead('Starting the calibration');
        renderOwners();
        renderSteps();
        renderDetail();
    }

    // How it ended is said where the run was narrated: the heading. The
    // steps stay as they stood; they are the run.
    function finish(good, text) {
        _running = false;
        _begun = false;
        _endedAt = Date.now();
        if (_idle) { clearTimeout(_idle); _idle = null; }
        const wrap = wrapOf();
        if (!wrap) return;
        if (!_cards.length) {
            // A run that produced no frames has nothing to show; the pane's
            // own result line already says what happened.
            wrap.hidden = true;
            return;
        }
        _cards.forEach(c => { c.dirty = true; });
        _phase = `${good ? 'Calibrated' : 'Calibration failed'}${text ? ` · ${text}` : ''}`;
        _tone = good ? 'ok' : 'bad';
        renderAll();
    }

    // A run that was kept, shown as it was watched: the same steps, from the
    // record's images ({data_type, src, metadata}). It opens on the fit, the
    // run's answer. `onOpen` is told the image whose picture is pressed.
    function show(images, opts) {
        if (_running) return;
        clearCards();
        const o = opts || {};
        _onOpen = typeof o.onOpen === 'function' ? o.onOpen : null;
        (images || []).forEach(img => {
            if (!img || !TYPES.has(img.data_type)) return;
            if (pointOf(img)) _count += 1;
            intoCards(_cards, img);
        });
        _phase = o.title || '';
        _tone = o.tone || '';
        renderAll();
    }

    // A run is going; or the steps on show are a run this page watched, of
    // this embryo, and are not to be swapped for the record of the same run.
    const busy = () => _running;
    const watched = embryoId => _live.has(embryoId);

    function mount(hostId) {
        _host = $(hostId);
        if (!_host) return;
        _host.innerHTML = `
          <div class="cp" hidden>
            <div class="cp-head" role="status">
              <span class="cp-dot" aria-hidden="true" hidden></span>
              <span class="cp-phase"></span>
              <span class="cp-owner"></span>
              <span class="cp-count"></span>
            </div>
            <div class="cp-secs" role="tablist" aria-label="Whose steps are shown" hidden></div>
            <div class="cp-steps" role="list" aria-label="The steps of this calibration"></div>
          </div>`;
        // The one open body, moved under whichever step is open.
        _detail = document.createElement('div');
        _detail.className = 'cp-detail';
        _detail.hidden = true;
        _detail.innerHTML = `
              <div class="cp-graph" tabindex="0" role="group"></div>
              <div class="cp-stage"><img class="cp-img" alt="The exposure looked at" hidden><pre class="cp-said" hidden></pre></div>
              <div class="cp-thumbs" hidden></div>
              <div class="cp-cap"></div>`;
        wire(_host.querySelector('.cp'));
        if (!_bound && typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('IMAGE_RECEIVED', onImage);
            _bound = true;
        }
        renderAll();
    }

    return { mount, begin, finish, show, busy, watched, phaseOf, captionOf, stepOf, cardKey, intoCards, pickedOf, saysOf, thumbsOf, MAX_FRAMES, _onImage: onImage };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CalProgressPanel;
