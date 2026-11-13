/**
 * Unit tests for the Light panel's derived state.
 *
 *   node --test tests/js/light-panel.test.mjs
 *
 * `emitting()` is the reason this panel exists. `LASER: ON` used to mean "an
 * HTTP request returned 200", so the UI reported ON over a dark microscope
 * (#106). The replacement computes emission from three read-back facts, and
 * the rule that matters most is the one about not knowing: an unread value
 * must produce `null`, never `false`. "No" and "I have not looked" are
 * different answers, and only one of them is safe to act on.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../gently/ui/web/static/js/panels/light.js');

const armed = { a: true, b: true };
const dark = { a: false, b: false };

test('wavelengthsOf: reads the lines out of a config name', () => {
    assert.deepEqual(P.wavelengthsOf('488 and 561'), [488, 561]);
    assert.deepEqual(P.wavelengthsOf('488 only'), [488]);
});

test('wavelengthsOf: ALL OFF routes nothing', () => {
    assert.deepEqual(P.wavelengthsOf('ALL OFF'), []);
});

test('wavelengthsOf: an unknown config means every line is in play', () => {
    // Not knowing which lines are routed is not the same as none being routed.
    assert.deepEqual(P.wavelengthsOf(null), [405, 488, 561, 637]);
});

test('wavelengthsOf: ignores wavelengths the hardware cannot address', () => {
    assert.deepEqual(P.wavelengthsOf('488 and 999'), [488]);
});

test('emitting: armed, routed and powered is emitting', () => {
    assert.equal(P.emitting({ beam: armed, config: '488 only', power: { 488: 4.0 } }), true);
});

test('emitting: a disarmed beam is not emitting, whatever else is set', () => {
    assert.equal(P.emitting({ beam: dark, config: '488 only', power: { 488: 6.0 } }), false);
});

test('emitting: armed but routed to nothing is not emitting', () => {
    // The exact state after "ALL OFF" — PLogic gates every line, beam still armed.
    assert.equal(P.emitting({ beam: armed, config: 'ALL OFF', power: { 488: 4.0 } }), false);
});

test('emitting: armed and routed at zero power is not emitting', () => {
    assert.equal(P.emitting({ beam: armed, config: '488 only', power: { 488: 0 } }), false);
});

test('emitting: one armed side is enough', () => {
    assert.equal(P.emitting({ beam: { a: true, b: false }, config: '488 only', power: { 488: 4 } }), true);
});

test('emitting: an unread beam is unknown, not off', () => {
    // The whole point. Returning false here would reproduce #106 with better
    // arithmetic — a confident "not emitting" over a scope nobody has asked.
    assert.equal(P.emitting({ beam: null, config: '488 only', power: { 488: 4 } }), null);
});

test('emitting: an unreadable side is unknown, not off', () => {
    assert.equal(P.emitting({ beam: { a: null, b: false }, config: '488 only', power: { 488: 4 } }), null);
});

test('emitting: unread power under an armed beam is unknown', () => {
    assert.equal(P.emitting({ beam: armed, config: '488 only', power: {} }), null);
    assert.equal(P.emitting({ beam: armed, config: '488 and 561', power: { 488: 4 } }), null);
});

test('emitting: nothing read at all is unknown', () => {
    assert.equal(P.emitting({}), null);
});

/**
 * `mode()` — the root of the panel's decision tree.
 *
 * The one rule with teeth: `both` must be reachable. LED and laser are two
 * independent Micro-Manager config groups, so nothing in the hardware stops
 * both being open, and #106 is that state going unnoticed for weeks — every
 * vision frame LED brightfield with a 50 ms laser gate on top, the detector
 * hunting nuclei in a DIC-like image. A mode selector that collapsed the pair
 * into an either/or would have made its own founding bug unrepresentable.
 */
test('mode: the LED alone is LED mode', () => {
    assert.equal(P.mode({ led: 'Open', config: 'ALL OFF' }), 'led');
});

test('mode: a routed line alone is laser mode', () => {
    assert.equal(P.mode({ led: 'Closed', config: '488 only' }), 'laser');
});

test('mode: neither is off', () => {
    assert.equal(P.mode({ led: 'Closed', config: 'ALL OFF' }), 'off');
});

test('mode: both open is a state, not an impossibility (#106)', () => {
    assert.equal(P.mode({ led: 'Open', config: '488 only' }), 'both');
});

test('mode: an unread source is unknown, never off', () => {
    assert.equal(P.mode({ led: null, config: 'ALL OFF' }), null);
    assert.equal(P.mode({ led: 'Closed', config: null }), null);
    assert.equal(P.mode({}), null);
});

/**
 * "ALL ON" is a preset of the Laser config group, and its name carries no
 * wavelength. The rule used to be "no digits in the name, no lines routed",
 * which is right for "ALL OFF" and made all four lines on, armed and powered
 * read as not emitting. A name that cannot be read for lines, and is not an
 * off, may route any of them.
 */
test('wavelengthsOf: ALL ON is every line, not none', () => {
    assert.deepEqual(P.wavelengthsOf('ALL ON'), [405, 488, 561, 637]);
});

test('wavelengthsOf: a preset name it cannot read is every line, the safe answer', () => {
    assert.deepEqual(P.wavelengthsOf('Imaging'), [405, 488, 561, 637]);
});

test('wavelengthsOf: the rig keeps a trailing space on one of its names', () => {
    assert.deepEqual(P.wavelengthsOf('405 only '), [405]);
});

test('emitting: ALL ON, armed and powered is emitting', () => {
    const power = { 405: 5, 488: 3, 561: 5, 637: 9 };
    assert.equal(P.emitting({ beam: armed, config: 'ALL ON', power }), true);
    assert.equal(P.mode({ led: 'Closed', config: 'ALL ON' }), 'laser');
});

/**
 * `status()` — the panel's one line. Always there, and the same line every
 * time: what is emitting, or what stands in the way of it. The states used
 * to be separate notes that came and went, two of them inside a branch that
 * could be closed.
 */
const POWER = { 405: 5, 488: 3.1, 561: 4.9, 637: 9.1 };
const base = { led: 'Closed', ledPct: 12, config: 'ALL OFF', beam: dark, power: POWER };

test('status: dark is said, not left blank', () => {
    const s = P.status(base);
    assert.equal(s.kind, 'dark');
    assert.match(s.text, /Dark/);
});

test('status: emitting names the lines that are lit and the side that is armed', () => {
    const s = P.status({ ...base, config: '488 and 561', beam: { a: true, b: false } });
    assert.equal(s.kind, 'emit');
    assert.equal(s.text, 'EMITTING · 488 + 561 nm · side A');
});

test('status: a routed line at zero power is not named as lit', () => {
    const s = P.status({ ...base, config: '488 and 561', beam: armed, power: { ...POWER, 561: 0 } });
    assert.equal(s.text, 'EMITTING · 488 nm · side A + B');
});

test('status: emitting over an open LED says both', () => {
    const s = P.status({ ...base, led: 'Open', config: '488 only', beam: armed });
    assert.equal(s.kind, 'emit');
    assert.match(s.text, /LED open too/);
});

test('status: lines routed with the beam off will not emit, and it says why', () => {
    const s = P.status({ ...base, config: '488 only' });
    assert.equal(s.kind, 'warn');
    assert.match(s.text, /beam off/);
    assert.match(s.text, /will not emit/);
    assert.match(s.title, /volume acquisition/);
});

test('status: both sources open without emitting is the #106 state, and a warning', () => {
    const s = P.status({ ...base, led: 'Open', config: '488 only' });
    assert.equal(s.kind, 'warn');
    assert.match(s.text, /LED open and 488 nm routed/);
});

test('status: armed with nothing routed is said, and is not a warning', () => {
    const s = P.status({ ...base, beam: { a: true, b: false } });
    assert.equal(s.kind, 'note');
    assert.match(s.text, /armed, nothing routed/);
});

test('status: lines routed and armed at zero power', () => {
    const s = P.status({ ...base, config: '488 only', beam: armed, power: { ...POWER, 488: 0 } });
    assert.equal(s.kind, 'warn');
    assert.match(s.text, /0 %/);
});

test('status: the LED alone says its brightness', () => {
    const s = P.status({ ...base, led: 'Open' });
    assert.equal(s.kind, 'led');
    assert.equal(s.text, 'LED open at 12 %');
});

test('status: anything unread is unknown, and never dark', () => {
    for (const s of [
        { ...base, beam: null },
        { ...base, beam: { a: null, b: false } },
        { ...base, led: null },
        { ...base, config: null },
        { ...base, config: '488 only', beam: armed, power: {} },
        {},
    ]) {
        assert.equal(P.status(s).kind, 'unknown', JSON.stringify(s));
    }
});

/**
 * The presets, as buttons. The names are Micro-Manager's and are sent back
 * exactly as they came; what is on the button is short enough for seven of
 * them to share a row.
 */
test('presetLabel: a name becomes its lines', () => {
    assert.equal(P.presetLabel('488 only'), '488');
    assert.equal(P.presetLabel('405 only '), '405');
    assert.equal(P.presetLabel('488 and 561'), '488+561');
    assert.equal(P.presetLabel('ALL OFF'), 'Off');
    assert.equal(P.presetLabel('ALL ON'), 'All');
    assert.equal(P.presetLabel(' Imaging '), 'Imaging');
});

test('presetList: off first, then one line, then more, then all', () => {
    P._seed(null, ['637 only', 'ALL OFF', '405 only ', '488 and 561', '561 only', 'ALL ON', '488 only']);
    assert.deepEqual(P.presetList('ALL OFF'),
        ['ALL OFF', '405 only ', '488 only', '561 only', '637 only', '488 and 561', 'ALL ON']);
});

test('presetList: what is set is in the list even when the catalogue is not', () => {
    // The catalogue comes from a route that 503s with the device layer down;
    // the read-back config is a fact either way.
    P._seed(null, []);
    assert.deepEqual(P.presetList('561 only'), ['561 only']);
    assert.deepEqual(P.presetList(null), []);
    P._seed(null, ['ALL OFF', '488 only']);
    assert.deepEqual(P.presetList('405 and 637'), ['ALL OFF', '488 only', '405 and 637']);
});

test('wavelengthsOf: follows the lines the server says the rig has', () => {
    P._seed({ 488: { min: 2, max: 6 }, 561: { min: 0, max: 100 } }, []);
    assert.deepEqual(P.wavelengthsOf(null), [488, 561]);
    assert.deepEqual(P.wavelengthsOf('405 and 561'), [561]);
    P._seed(null, []);
});
