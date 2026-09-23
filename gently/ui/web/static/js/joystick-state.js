/**
 * The physical XY joystick's state, in one place.
 *
 * WHY A STORE AND NOT A THIRD COPY
 *
 * The lock is one hardware flag with three surfaces that want it: Settings,
 * the Devices map, and the rig menu in the header. Each rendering its own
 * fetch would mean three answers to one question — and the failure would be
 * quiet, because the one you are looking at would still look right. This is
 * PANELS.md rule 2: state comes from a shared store, so two mounted copies
 * cannot disagree.
 *
 * WHAT IT DOES NOT DO
 *
 * Decide anything. `enabled` is whatever the controller reported when it was
 * last asked — never what we asked it to be (rule 3). A write re-reads, and a
 * failed write re-reads too, so the stored value is always something the
 * hardware said.
 *
 * `enabled: null` means "not known": no device layer, or nobody has asked
 * yet. Renderers must show that as unknown rather than picking a side — a
 * control that guesses "enabled" while the stage is locked sends someone to
 * wiggle a dead joystick.
 */
const JoystickState = (() => {
    'use strict';

    const ENDPOINT = '/api/devices/stage/joystick';

    let _enabled = null;     // null = unknown; true/false = read back
    let _reason = '';        // why it is unknown, when it is
    let _busy = false;
    const _subs = new Set();

    const snapshot = () => ({ enabled: _enabled, reason: _reason, busy: _busy });

    function notify() {
        const s = snapshot();
        _subs.forEach(fn => {
            try { fn(s); } catch (e) { console.debug('joystick subscriber failed', e); }
        });
    }

    function set(enabled, reason) {
        _enabled = enabled;
        _reason = reason || '';
        notify();
    }

    /** Ask the controller. Never throws — an unreachable rig is "unknown". */
    async function read() {
        try {
            const r = await fetch(ENDPOINT);
            const d = await r.json().catch(() => ({}));
            if (r.ok && d && d.success !== false) set(!!d.enabled, '');
            else set(null, r.status === 403 ? 'Sign in to see the joystick' : 'Microscope not connected');
        } catch (e) {
            set(null, 'Microscope not connected');
        }
        return snapshot();
    }

    /**
     * Write, then render what came back — never what was sent.
     *
     * A failed write re-reads rather than leaving the stored value at a guess:
     * the operator's next action depends on whether the stage can be nudged by
     * hand, and "probably" is not an answer.
     */
    async function write(enabled) {
        if (_busy) return snapshot();
        _busy = true;
        notify();
        try {
            const r = await fetch(ENDPOINT, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ enabled: !!enabled }),
            });
            const d = await r.json().catch(() => ({}));
            if (r.ok && d && d.success !== false) {
                _busy = false;
                set(!!d.enabled, '');
            } else {
                _busy = false;
                _reason = r.status === 403
                    ? 'Sign in to change the joystick'
                    : (d.detail || `Failed (${r.status})`);
                notify();
                await read();
            }
        } catch (e) {
            _busy = false;
            _reason = `Failed: ${e.message}`;
            notify();
            await read();
        }
        return snapshot();
    }

    /** Render now and on every change. Returns an unsubscribe. */
    function subscribe(fn) {
        _subs.add(fn);
        try { fn(snapshot()); } catch (e) { /* a bad subscriber is not our problem */ }
        return () => _subs.delete(fn);
    }

    // The rig coming or going changes the answer, and both surfaces should
    // learn at once rather than each polling.
    if (typeof ClientEventBus !== 'undefined') {
        ClientEventBus.on('DEVICE_LAYER_STATE', d => {
            if (d && d.ready) read();
            else set(null, 'Microscope not connected');
        });
    }

    return { read, write, subscribe, snapshot };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = JoystickState;
