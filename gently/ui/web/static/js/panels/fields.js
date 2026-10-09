/**
 * Fields — the bottom camera's fields of view for the brightfield overview.
 *
 *     FieldsPanel.mount('op-frail-list', { compact: true });   // the rail
 *     FieldsPanel.mount('op-fields');                          // Acquisition
 *
 * WHY
 *
 * A timelapse has two kinds of place it goes back to. The embryos are where
 * the SPIM volumes are taken, and they have always had a list. The fields
 * are where the bottom camera's overview frame is taken — one, or several
 * when the embryos do not all fit in one frame — and they had no list at
 * all: they were captured one at a time from a select on the Acquisition
 * pane, two panes away from the stage pad and the picture that show what a
 * field holds. Setting up three fields meant walking between the panes six
 * times.
 *
 * This is the fields' list, the same shape as the embryos' and mounted in
 * the same places: the rail beside every instrument surface, and the
 * Acquisition pane's left column. A field is added from where the stage is,
 * while the operator is looking at it. The list is the plan's "taken from".
 *
 * WHAT IT DOES NOT OWN
 *
 * The list. `_bfPins`, the stage position, the plan and the endpoints stay
 * in operate.js. This renders `SharedState.overviewFields` against
 * `SharedState.stageXY` and calls `OperateManager.fields.*` — the same split
 * as the Roster panel (docs/architecture/PANELS.md).
 */
const FieldsPanel = (() => {
    'use strict';

    const mounts = new Map();   // hostId -> opts

    // The stage is "at" a field within this. A frame is on the order of a
    // millimetre across, so fifty microns is the same picture; it is also
    // OperateMath.AT_TOL_UM, the tolerance the SPIM caption uses.
    const HERE_UM = 50;

    const CROSSHAIR = '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor"'
        + ' stroke-width="1.9" stroke-linecap="round" aria-hidden="true">'
        + '<circle cx="12" cy="12" r="6.5"></circle><circle cx="12" cy="12" r="1.6" fill="currentColor"></circle>'
        + '<path d="M12 2v3"></path><path d="M12 19v3"></path><path d="M2 12h3"></path><path d="M19 12h3"></path></svg>';

    function mount(hostId, opts) {
        mounts.set(hostId, {
            compact: !!(opts && opts.compact),
        });
        if (mounts.size === 1) {
            SharedState.on('overviewFields', render);
            SharedState.on('stageXY', render);
            SharedState.on('embryos', render);
        }
        render();
    }

    function unmount(hostId) { mounts.delete(hostId); }

    const verbs = () =>
        (typeof OperateManager !== 'undefined' && OperateManager.fields) || null;

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }

    /** Is the stage at this field? Unknown is not a yes. */
    function at(xy, f) {
        if (typeof OperateMath !== 'undefined' && OperateMath.atPosition) return OperateMath.atPosition(xy, f, HERE_UM);
        if (!xy || !f || !Number.isFinite(xy.x) || !Number.isFinite(xy.y)) return false;
        return Math.hypot(f.x - xy.x, f.y - xy.y) <= HERE_UM;
    }

    /** The index of the field the stage is at, or -1. */
    function hereIndex(fields, xy) {
        return fields.findIndex(f => at(xy, f));
    }

    function render() {
        const fields = SharedState.get('overviewFields') || [];
        const xy = SharedState.get('stageXY');
        const embryos = SharedState.get('embryos') || [];
        const here = hereIndex(fields, xy);
        mounts.forEach((opts, hostId) => {
            const host = document.getElementById(hostId);
            if (!host) return;
            host.innerHTML = (fields.length
                ? fields.map((f, i) => row(f, i, i === here, opts)).join('') + note(fields, opts)
                : empty(embryos, opts)) + add(fields, xy, here, opts);
            wire(host);
        });
    }

    function row(f, i, isHere, opts) {
        const x = Number.isFinite(f.x) ? f.x.toFixed(0) : '—';
        const y = Number.isFinite(f.y) ? f.y.toFixed(0) : '—';
        const mark = isHere
            ? `<span class="fp-here" title="The stage is at this field now">${opts.compact ? '◎' : 'stage here'}</span>`
            : '';
        return `<div class="rp-row fp-row${isHere ? ' is-here' : ''}" data-field="${i}">
                  <span class="rp-main">
                    <span class="rp-label">Field ${i + 1}${mark}</span>
                    <span class="rp-xy">${esc(x)}, ${esc(y)}</span>
                  </span>
                  <span class="rp-acts">
                    <button class="rp-btn rp-centre${opts.compact ? ' is-compact' : ''}" type="button"
                      title="Send the stage to field ${i + 1}" aria-label="Send the stage to field ${i + 1}"
                      data-verb="goTo" data-index="${i}">${opts.compact ? CROSSHAIR : 'Go'}</button>
                    <button class="rp-btn rp-del${opts.compact ? ' is-compact' : ''}" type="button"
                      title="Drop field ${i + 1} from the overview" aria-label="Drop field ${i + 1} from the overview"
                      data-verb="remove" data-index="${i}">×</button>
                  </span>
                </div>`;
    }

    /** What the list means for the run, under it. */
    function note(fields, opts) {
        if (opts.compact) return '';
        const n = fields.length;
        return `<div class="fp-note">The overview takes ${n === 1 ? 'one frame, from this field' : `${n} frames each round, one from each field`}.</div>`;
    }

    function empty(embryos, opts) {
        const fallback = embryos.length
            ? 'the overview is taken from the embryos’ centroid'
            : 'the overview is taken from wherever the stage is';
        return `<div class="rp-empty fp-empty">No fields yet — ${fallback}.${
    opts.compact ? ' Drive to a view and add it.' : ' Add them on Bottom cam, beside the picture, or from where the stage is now.'}</div>`;
    }

    /** The one verb that makes a field: from where the stage is, now. */
    function add(fields, xy, here, opts) {
        const known = !!(xy && Number.isFinite(xy.x) && Number.isFinite(xy.y));
        const dup = here >= 0;
        const title = !known ? 'No stage position known yet'
            : dup ? `The stage is at field ${here + 1} already`
                : `Add the view at ${xy.x.toFixed(0)}, ${xy.y.toFixed(0)} as field ${fields.length + 1}`;
        return `<button class="rp-cta fp-add" type="button" data-add ${known && !dup ? '' : 'disabled'} title="${esc(title)}">
                  + Add this view${opts.compact ? '' : ' as a field'}
                </button>`;
    }

    function wire(host) {
        host.onclick = e => {
            const v = verbs();
            if (!v) return;
            const act = e.target.closest('[data-verb]');
            if (act) {
                e.stopPropagation();
                const fn = v[act.dataset.verb];
                if (typeof fn === 'function') fn(Number(act.dataset.index));
                return;
            }
            const addBtn = e.target.closest('[data-add]');
            if (addBtn && !addBtn.disabled && typeof v.addHere === 'function') v.addHere();
        };
    }

    return { mount, unmount, render, hereIndex, HERE_UM };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = FieldsPanel;
