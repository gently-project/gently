/**
 * A slider and its number: one control, two ways in.
 *
 *     const row = NumRow.bind(rangeInput, textInput, {
 *         decimals: 1,
 *         onInput:  v => { ... },     // optional: every movement of the line
 *         onCommit: v => { ... },     // the value is meant: released, Enter, blur, ↑ ↓
 *     });
 *     row.show(3.1);                  // what the hardware says; ignored mid-edit
 *
 * WHY
 *
 * "The adjustable parameters like laser power can also have a way to enter
 * numbers into a text box, as sometimes biologists love that" (2026-11-13).
 * A slider finds a value by looking at the picture; a number is how a value
 * is written in a notebook, said across the room and put back the next day.
 * Every adjustable value in Operate was a slider with a read-only number
 * beside it, so 3.1 % had to be found by dragging.
 *
 * THE RULES, the same wherever this is bound
 *
 *   The limits are the slider's min and max, which the panel sets from what
 *   the server says (PANELS.md rule 4). This holds no limits of its own.
 *
 *   A typed value is a DRAFT until Enter or leaving the box: it is drawn as
 *   one (`is-draft`) and nothing is sent. Typing "12" on the way to "120"
 *   must not send 12 to a laser.
 *
 *   A value outside the limits is pulled inside and the box flashes
 *   (`is-clamped`), so the number on screen is the number sent, and the
 *   operator sees that it is not the one they typed.
 *
 *   Something that is not a number puts back what was there. Esc does too.
 *
 *   ↑ and ↓ step by the slider's step, Shift by ten of them, and commit.
 *
 *   show() is the read-back. It does not overwrite a draft or a drag in
 *   progress: the hardware's number must not arrive under the cursor.
 *
 * The arithmetic is pure and tested (tests/js/numrow.test.mjs); bind() is the
 * DOM around it.
 */
const NumRow = (() => {
    'use strict';

    /** A typed string as a number, or null. Takes a typeset minus and a decimal comma. */
    function parse(text) {
        if (text == null) return null;
        const t = String(text).trim().replace(/[−–]/g, '-').replace(',', '.');
        if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) return null;
        const v = Number(t);
        return Number.isFinite(v) ? v : null;
    }

    const clamp = (v, min, max) => Math.min(max, Math.max(min, v));

    /** Rounded to the decimals shown, so what is sent is what is read. */
    function round(v, decimals) {
        const k = Math.pow(10, Math.max(0, decimals | 0));
        return Math.round(v * k) / k;
    }

    const format = (v, decimals) => Number(v).toFixed(Math.max(0, decimals | 0));

    /**
     * What a typed string settles to: {value, clamped}, or null when it is not
     * a number (the caller puts back what was there).
     */
    function settle(text, min, max, decimals) {
        const v = parse(text);
        if (v == null) return null;
        const inside = round(clamp(v, min, max), decimals);
        return { value: inside, clamped: inside !== round(v, decimals) };
    }

    /** One press of ↑ (dir 1) or ↓ (dir -1); `big` is Shift, ten steps. */
    function stepped(v, step, dir, big, min, max, decimals) {
        const s = (Number(step) > 0 ? Number(step) : 1) * (big ? 10 : 1);
        return round(clamp(Number(v) + dir * s, min, max), decimals);
    }

    function bind(range, box, opts) {
        const o = opts || {};
        const decimals = o.decimals != null ? o.decimals : Number(box.dataset.decimals || 0);
        const lo = () => Number(range.min), hi = () => Number(range.max);
        let dragging = false;
        // What the box goes back to: the last value shown or committed.
        let held = Number(range.value);

        const editing = () => dragging || box.classList.contains('is-draft');

        function paint(v) {
            box.value = format(v, decimals);
            box.classList.remove('is-draft');
        }

        function show(v) {
            if (v == null || !Number.isFinite(Number(v))) return;
            held = Number(v);
            if (editing()) return;
            range.value = held;
            paint(held);
        }

        function commit(v, clamped) {
            held = v;
            range.value = v;
            paint(v);
            if (clamped) {
                box.classList.remove('is-clamped');
                void box.offsetWidth;            // restart the flash
                box.classList.add('is-clamped');
            }
            if (o.onCommit) o.onCommit(v);
        }

        range.addEventListener('input', () => {
            dragging = true;
            const v = round(Number(range.value), decimals);
            box.value = format(v, decimals);
            if (o.onInput) o.onInput(v);
        });
        range.addEventListener('change', () => {
            dragging = false;
            commit(round(Number(range.value), decimals), false);
        });

        box.addEventListener('input', () => box.classList.add('is-draft'));
        box.addEventListener('focus', () => box.select());
        box.addEventListener('blur', () => {
            if (!box.classList.contains('is-draft')) return;
            const s = settle(box.value, lo(), hi(), decimals);
            if (s) commit(s.value, s.clamped); else paint(held);
        });
        box.addEventListener('keydown', e => {
            if (e.key === 'Enter') {
                e.preventDefault();
                const s = settle(box.value, lo(), hi(), decimals);
                if (s) commit(s.value, s.clamped); else paint(held);
                box.select();
            } else if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                paint(held);
                box.blur();
            } else if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                e.preventDefault();
                const from = settle(box.value, lo(), hi(), decimals);
                const base = from ? from.value : held;
                commit(stepped(base, range.step, e.key === 'ArrowUp' ? 1 : -1, e.shiftKey, lo(), hi(), decimals), false);
                box.select();
            }
        });

        paint(held);
        return { show, editing };
    }

    return { parse, clamp, round, format, settle, stepped, bind };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = NumRow;
