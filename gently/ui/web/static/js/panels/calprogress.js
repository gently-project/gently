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

    // Which card a frame belongs on: its step, and in a walk its embryo.
    function cardKey(img) {
        const who = (img.metadata || {}).embryo_id || '';
        return `${who}|${phaseOf(img)}`;
    }

    // Put a frame on the run's cards; true when it began a new card. Pure, so
    // the grouping can be tested without a page.
    function intoCards(cards, img) {
        const key = cardKey(img);
        let card = cards[cards.length - 1];
        const fresh = !card || card.key !== key;
        if (fresh) {
            card = { key, title: phaseOf(img), who: (img.metadata || {}).embryo_id || null, frames: [], shown: -1, el: null };
            cards.push(card);
        }
        card.frames.push(img);
        if (card.frames.length > MAX_FRAMES) {
            // Drop the oldest EXPOSURE, never a conclusion: the findings are
            // the part of the step you still want when it ends.
            const drop = card.frames.findIndex(f => !isConclusion(f));
            card.frames.splice(drop < 0 ? 0 : drop, 1);
            if (card.shown > 0) card.shown -= 1;
        }
        return fresh;
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
        const card = _cards[_cards.length - 1];
        if (fresh) appendCard(card);
        renderCard(card);
        armIdle();
        render();
    }

    function begin(embryoId) {
        clearCards();
        _running = true;
        _embryo = embryoId || null;
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

    return { mount, begin, finish, phaseOf, captionOf, cardKey, intoCards, MAX_FRAMES, _onImage: onImage };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = CalProgressPanel;
