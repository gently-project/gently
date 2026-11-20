/**
 * Unit tests for the hardware timeline's arithmetic.
 *
 *   node --test tests/js/hardware-timeline-math.test.mjs
 *
 * The timeline is one zoomable object: the whole session at one end, a single
 * round down to its slices at the other. What it draws is decided here — which
 * row a volume's light goes in, where each slice fell, which marks make up a
 * round, what the axis says — so it can be checked without a browser.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const M = require('../../gently/ui/web/static/js/hardware-timeline-math.js');

const r6 = x => Math.round(x * 1e6) / 1e6;
const pairs = list => list.map(([a, b]) => [r6(a), r6(b)]);

test('sliceTimes: a recorded stack slices at its measured period from the scan start', () => {
    // Five frames arrived 0.1 s apart; each exposure is 20 ms.
    const v = { scan_started: 100, first_frame: 100.05, last_frame: 100.45, slices: 5, exposure_ms: 20 };
    assert.deepEqual(pairs(M.sliceTimes(v)), [
        [100, 100.02], [100.1, 100.12], [100.2, 100.22], [100.3, 100.32], [100.4, 100.42],
    ]);
});

test('sliceTimes: an unrecorded stack is its light time, one exposure after another', () => {
    const v = { scan_started: 100, first_frame: null, last_frame: 100.1, slices: 5, exposure_ms: 20 };
    assert.deepEqual(pairs(M.sliceTimes(v)), [
        [100, 100.02], [100.02, 100.04], [100.04, 100.06], [100.06, 100.08], [100.08, 100.1],
    ]);
});

test('sliceTimes: a one-slice stack is one exposure at the scan start', () => {
    const v = { scan_started: 5, first_frame: 5.1, last_frame: 5.1, slices: 1, exposure_ms: 10 };
    assert.deepEqual(pairs(M.sliceTimes(v)), [[5, 5.01]]);
});

test('sliceTimes: a stack with no exposure or start has no slices to draw', () => {
    assert.deepEqual(M.sliceTimes({ scan_started: 5, slices: 3, exposure_ms: null }), []);
    assert.deepEqual(M.sliceTimes({ scan_started: null, slices: 3, exposure_ms: 10 }), []);
});

const SEQ = {
    t0: 0, t1: 20,
    lines: [488, 561],
    embryos: [{ id: 'e1', label: 'A' }, { id: 'e2', label: 'B' }],
    volumes: [
        {
            embryo: 'e1', t: 1, side: 'A', recorded: true, slices: 3, exposure_ms: 20,
            lasers: { 488: 2.5, 561: 7.5 }, settings: { 488: 2.5, 561: 8 },
            lasers_on: 1.0, scan_started: 1.25, first_frame: 1.3, last_frame: 2.1, lasers_off: 2.2,
        },
        {
            embryo: 'e2', t: 1, side: 'A', recorded: false, slices: 20, exposure_ms: 10,
            lasers: null, settings: { 488: 3 },
            lasers_on: null, scan_started: 5, first_frame: null, last_frame: 5.2, lasers_off: null,
        },
    ],
    bf: [
        { recorded: true, light: 'led', led_pct: 30, exposure_ms: 10, light_on: 0, light_off: 0.9, exposed: 0.8, filed: 0.95 },
        { recorded: false, light: 'led', led_pct: 30, exposure_ms: 10, light_on: null, light_off: null, exposed: null, filed: 10 },
        // Recorded, but the light was on already: no window this frame can claim.
        { recorded: true, light: 'room', led_pct: null, exposure_ms: 10, light_on: null, light_off: null, exposed: 12, filed: 12.1 },
    ],
    temperature: [[0, 20.0, 20.0], [10, 20.1, 20.0]],
};

test('marks: a recorded volume lights each routed line for its laser window, at its power', () => {
    const rows = M.marks(SEQ);
    const l488 = rows['488'].find(m => m.embryo === 'e1');
    assert.deepEqual([l488.kind, l488.a, l488.b, l488.value], ['laser', 1.0, 2.2, 2.5]);
    // The scan inside the window, where the slices are.
    assert.deepEqual([l488.scanA, l488.scanB], [1.25, 2.1]);
    assert.equal(rows['561'].length, 1);
    assert.equal(rows['561'][0].value, 7.5);
});

test('marks: an unrecorded volume is drawn from its settings, and says so', () => {
    const rows = M.marks(SEQ);
    const set = rows['488'].find(m => m.embryo === 'e2');
    assert.deepEqual([set.kind, set.a, set.b, set.value], ['setting', 5, 5.2, 3]);
    assert.ok(!rows['561'].some(m => m.embryo === 'e2'), 'no 561 setting, no 561 mark');
});

test('marks: brightfield light belongs to no embryo; a window only when the frame switched it', () => {
    const rows = M.marks(SEQ);
    assert.deepEqual(rows.bf.map(m => [m.kind, m.a, m.b]), [['light', 0, 0.9], ['filed', 10, 10]]);
    assert.ok(rows.bf.every(m => m.embryo === undefined));
});

test('marks: the exposure row holds every stack and every frame the camera took', () => {
    const rows = M.marks(SEQ);
    assert.deepEqual(rows.exposure.map(m => [m.kind, r6(m.a), r6(m.b), m.value]), [
        ['frame', 0.79, 0.8, 10],
        ['stack', 1.25, 2.1, 20],
        ['stack', 5, 5.2, 10],
        ['frame-filed', 9.99, 10, 10],
        ['frame', 11.99, 12, 10],
    ]);
});

test('rows: one per laser line the session shows; brightfield and temperature only when there', () => {
    assert.deepEqual(M.rows(SEQ).map(r => r.key), ['bf', '488', '561', 'exposure', 'temp']);
    const bare = { lines: [488], volumes: [{}], bf: [], temperature: [] };
    assert.deepEqual(M.rows(bare).map(r => r.key), ['488', 'exposure']);
});

test('rounds: marks closer than the gap are one round', () => {
    const items = [{ a: 0, b: 1 }, { a: 2, b: 3 }, { a: 600, b: 601 }, { a: 603, b: 604 }];
    assert.deepEqual(M.rounds(items, 20).map(r => [r.a, r.b, r.items.length]), [[0, 3, 2], [600, 604, 2]]);
    assert.deepEqual(M.rounds([], 20), []);
});

test('roundPause: half the cadence, and never under twenty seconds', () => {
    const every = s => [0, 1, 2].map(i => ({ embryo: 'e1', side: 'A', scan_started: i * s }));
    assert.equal(M.roundPause(every(600)), 300);
    assert.equal(M.roundPause(every(40)), 20);
    assert.equal(M.roundPause(every(2)), 20);
    assert.equal(M.roundPause([]), 20);
});

test('zoomAt keeps the moment under the pointer where it was', () => {
    assert.deepEqual(M.zoomAt({ a: 0, b: 100 }, 25, 0.5, { a: 0, b: 100 }, 0.001), { a: 12.5, b: 62.5 });
});

test('zoomAt goes no wider than the session and no closer than the floor', () => {
    assert.deepEqual(M.zoomAt({ a: 0, b: 100 }, 50, 4, { a: 0, b: 100 }, 0.001), { a: 0, b: 100 });
    const z = M.zoomAt({ a: 10, b: 10.002 }, 10.001, 0.1, { a: 0, b: 100 }, 0.001);
    assert.deepEqual([r6(z.a), r6(z.b)], [10.0005, 10.0015]);
});

test('pan stops at the session edges', () => {
    assert.deepEqual(M.pan({ a: 10, b: 20 }, -15, { a: 0, b: 100 }), { a: 0, b: 10 });
    assert.deepEqual(M.pan({ a: 10, b: 20 }, 95, { a: 0, b: 100 }), { a: 90, b: 100 });
});

test('ticks: a long view counts the clock from the first acquisition', () => {
    const t = M.ticks({ a: 0, b: 3600 }, 0, 6);
    assert.deepEqual(t.ticks.map(x => x.label), ['0:00', '10:00', '20:00', '30:00', '40:00', '50:00', '1:00:00']);
    assert.equal(t.caption, 'Time since the first acquisition');
});

test('ticks: a view of seconds counts seconds from a round mark', () => {
    const t = M.ticks({ a: 1203.2, b: 1214.9 }, 0, 6);
    assert.deepEqual(t.ticks.map(x => x.label), ['4', '6', '8', '10', '12', '14']);
    assert.deepEqual(t.ticks.map(x => x.t), [1204, 1206, 1208, 1210, 1212, 1214]);
    assert.equal(t.caption, 'Seconds after 20:00');
});

test('ticks: a round counts from its own ten-second mark, never from before the session', () => {
    // Round 1 opens just before the first acquisition; round 2 a little before 2:00.
    const first = M.ticks({ a: -0.8, b: 12.6 }, 0, 6);
    assert.equal(first.caption, 'Seconds after 0:00');
    assert.deepEqual(first.ticks.map(x => x.label), ['0', '5', '10']);
    // A wider round opening just before the session (the sim rig's round 1).
    const wide = M.ticks({ a: -2.4, b: 28.1 }, 0, 6);
    assert.equal(wide.caption, 'Seconds after 0:00');
    assert.deepEqual(wide.ticks.map(x => x.label), ['0', '10', '20']);
    const second = M.ticks({ a: 119.8, b: 133.4 }, 0, 6);
    assert.equal(second.caption, 'Seconds after 2:00');
    assert.deepEqual(second.ticks.map(x => x.label), ['0', '5', '10']);
});

test('ticks: down at the slices the labels carry the decimals the step needs', () => {
    const t = M.ticks({ a: 1201.21, b: 1201.33 }, 0, 6);
    assert.deepEqual(t.ticks.map(x => x.label), ['1.22', '1.24', '1.26', '1.28', '1.30', '1.32']);
});

test('fmtDuration speaks in the unit that fits', () => {
    assert.equal(M.fmtDuration(0.0413), '41.3 ms');
    assert.equal(M.fmtDuration(1.6634), '1.66 s');
    assert.equal(M.fmtDuration(125), '2:05');
    assert.equal(M.fmtDuration(3725), '1:02:05');
});

test('fmtClock: minutes and seconds, hours when there are any', () => {
    assert.equal(M.fmtClock(65), '1:05');
    assert.equal(M.fmtClock(3600), '1:00:00');
    assert.equal(M.fmtClock(12.345, 3), '0:12.345');
    // A hair before the start is the start, not "-0:00".
    assert.equal(M.fmtClock(-0.01), '0:00');
    assert.equal(M.fmtClock(-65), '-1:05');
});

test('hit: the mark under the pointer wins, else the nearest within reach', () => {
    const marks = [{ a: 0, b: 1, id: 'x' }, { a: 5, b: 6, id: 'y' }, { a: 5.5, b: 5.6, id: 'z' }];
    assert.equal(M.hit(marks, 0.5, 0.2).id, 'x');
    assert.equal(M.hit(marks, 4.9, 0.2).id, 'y');
    assert.equal(M.hit(marks, 3, 0.2), null);
    // Two marks under the pointer: the narrower one is the one aimed at.
    assert.equal(M.hit(marks, 5.55, 0.2).id, 'z');
});

test('slots: colour follows the embryo; the first eight take a slot each, the rest share Other', () => {
    const embryos = Array.from({ length: 10 }, (_, i) => ({ id: `e${i}` }));
    const s = M.slots(embryos);
    assert.equal(s.e0, 0);
    assert.equal(s.e7, 7);
    assert.equal(s.e8, null);
    assert.equal(s.e9, null);
});

test('niceCeil rounds a row up to a clean top', () => {
    assert.equal(M.niceCeil(7.5), 10);
    assert.equal(M.niceCeil(20), 20);
    assert.equal(M.niceCeil(2.4), 2.5);
    assert.equal(M.niceCeil(0), 1);
});

test('tempRange: centred on the setpoint and never tighter than a degree', () => {
    assert.deepEqual(M.tempRange([[0, 20.02, 20], [1, 19.98, 20]]), { lo: 19.5, hi: 20.5 });
    const wide = M.tempRange([[0, 22.0, 20], [1, 19.9, 20]]);
    assert.deepEqual([r6(wide.lo), r6(wide.hi)], [17.7, 22.3]);
    assert.equal(M.tempRange([]), null);
});

// Ten pixels to the second, from t = 0: marks 0.1 s wide are one pixel.
const px = t => t * 10;
const h = m => m.value;

test('bins: where marks are denser than pixels, a column keeps its one embryo or says "several"', () => {
    const marks = [
        { a: 0.0, b: 0.1, embryo: 'e1', value: 3 },
        { a: 0.05, b: 0.12, embryo: 'e2', value: 5 },      // same pixels as e1's
        { a: 1.0, b: 1.1, embryo: 'e2', value: 4 },        // a pixel of its own
        { a: 2.0, b: 2.6, value: 2 },                      // the dish's light: no embryo
    ];
    assert.deepEqual(M.bins(marks, px, 40, h), [
        { x0: 0, x1: 2, h: 5, who: '__several', recorded: true },
        { x0: 10, x1: 12, h: 4, who: 'e2', recorded: true },
        { x0: 20, x1: 26, h: 2, who: '__bf', recorded: true },
    ]);
});

test('bins: a column of marks that were not recorded is drawn as not recorded', () => {
    const marks = [
        { a: 0.0, b: 0.1, embryo: 'e1', value: 3, kind: 'setting' },
        { a: 1.0, b: 1.1, embryo: 'e1', value: 3, kind: 'laser' },
    ];
    assert.deepEqual(M.bins(marks, px, 40, h).map(r => r.recorded), [false, true]);
});

test('bins: marks off either edge are cut to the plot', () => {
    const marks = [{ a: -1, b: 0.3, embryo: 'e1', value: 1 }, { a: 3.8, b: 9, embryo: 'e1', value: 1 }];
    assert.deepEqual(M.bins(marks, px, 40, h).map(r => [r.x0, r.x1]), [[0, 3], [38, 40]]);
});

test('two sides in one scan: side B is drawn from its own start, not the shared trigger', () => {
    const b = {
        embryo: 'e1', t: 1, side: 'B', recorded: true, slices: 3, exposure_ms: 20,
        lasers: { 488: 3 }, settings: {},
        lasers_on: 99.9, scan_started: 100, side_began: 102.0, first_frame: 102.1, last_frame: 102.5, lasers_off: 102.7,
    };
    assert.deepEqual(pairs(M.sliceTimes(b)), [[102, 102.02], [102.2, 102.22], [102.4, 102.42]]);
    const rows = M.marks({ lines: [488], volumes: [b], bf: [] });
    assert.deepEqual([rows['488'][0].a, rows['488'][0].scanA, rows['488'][0].b], [99.9, 102.0, 102.7]);
    assert.deepEqual([rows.exposure[0].a, rows.exposure[0].b], [102.0, 102.5]);
});

test('marks: a light that was not seen to go off runs to when its frame was filed', () => {
    const rows = M.marks({ lines: [], volumes: [], bf: [{ recorded: true, light_on: 5, light_off: null, exposed: 6, filed: 8 }] });
    assert.deepEqual(rows.bf.map(m => [m.a, m.b]), [[5, 8]]);
});

test('roundView: a round with its margins; one with no length gets a second to be seen in', () => {
    const bounds = { a: 0, b: 1000 };
    const v = M.roundView({ a: 100, b: 110 }, bounds);
    assert.deepEqual([r6(v.a), r6(v.b)], [99.2, 110.8]);
    assert.deepEqual(M.roundView({ a: 500, b: 500 }, bounds), { a: 499.5, b: 500.5 });
    // Still inside the session.
    assert.deepEqual(M.roundView({ a: 0, b: 0 }, bounds), { a: 0, b: 1 });
});

test('fmtWall: the rig\'s own clock, with its offset said', () => {
    const t = 1794700000;            // 2026-11-14T23:46:40Z
    assert.equal(M.fmtWall(t, -5 * 3600), '18:46:40 UTC−5');
    assert.equal(M.fmtWall(t, 3600), '00:46:40 UTC+1');
    assert.equal(M.fmtWall(t, 5.5 * 3600), '05:16:40 UTC+5:30');
    assert.equal(M.fmtWall(t, 0), '23:46:40 UTC');
});

// A volume for round grouping: [a, b] its laser window.
const vol = (embryo, side, a, b) => ({ embryo, side, recorded: true, lasers_on: a, scan_started: a, last_frame: b, lasers_off: b });
const frame = (a, b) => ({ recorded: true, light_on: a, light_off: b, exposed: b, exposure_ms: 10 });

test('roundsOf: a run behind its schedule has no pauses; a round is each embryo once', () => {
    const vols = [];
    for (let r = 0; r < 3; r++) {
        const t = r * 10;   // back to back: ten seconds a round, not a gap between
        vols.push(vol('A', 'A', t, t + 2), vol('B', 'A', t + 2.5, t + 4.5), vol('C', 'A', t + 5, t + 7), vol('C', 'B', t + 7.2, t + 9.5));
    }
    const r = M.roundsOf({ volumes: vols, bf: [] }, 20);
    assert.deepEqual(r.map(x => [x.a, x.b, x.items.length]), [[0, 9.5, 4], [10, 19.5, 4], [20, 29.5, 4]]);
});

test('roundsOf: embryos on different cadences make rounds of whoever was due', () => {
    const vols = [vol('A', 'A', 0, 2), vol('B', 'A', 5, 7), vol('A', 'A', 60, 62), vol('A', 'A', 120, 122), vol('B', 'A', 125, 127)];
    assert.deepEqual(M.roundsOf({ volumes: vols, bf: [] }, 20).map(x => x.items.length), [2, 1, 2]);
});

test('roundsOf: the overview just before a round is that round\'s', () => {
    const r = M.roundsOf({ volumes: [vol('A', 'A', 0, 2), vol('A', 'A', 100, 102)], bf: [frame(-3, -2.5), frame(-2, -1.5), frame(97, 97.5)] }, 20);
    assert.deepEqual(r.map(x => [x.a, x.b, x.items.length]), [[-3, 2, 3], [97, 102, 2]]);
});

test('roundsOf: brightfield alone groups by its pauses', () => {
    const r = M.roundsOf({ volumes: [], bf: [frame(0, 0.5), frame(1, 1.5), frame(60, 60.5)] }, 20);
    assert.deepEqual(r.map(x => [x.a, x.b, x.items.length]), [[0, 1.5, 2], [60, 60.5, 1]]);
});

test('roundsOf: brightfield mid-round and slow moves keep a round whole (a run on the sim rig)', () => {
    // Seconds from the start, as the simulated rig took them: each round is
    // embryo 1, 2, 3 (both sides); a three-field overview every 30 s lands
    // before a round or in the middle of one; the stage takes 6-13 s between.
    const sweep = a => [frame(a, a + 2.4), frame(a + 2.8, a + 5.1), frame(a + 5.5, a + 7.8)];
    const r = M.roundsOf({
        volumes: [
            vol('1', 'A', 9, 10.1), vol('2', 'A', 16.7, 17.8), vol('3', 'A', 24.2, 25.3), vol('3', 'B', 30.1, 31.2),
            vol('1', 'A', 48.1, 49.2), vol('2', 'A', 56, 57), vol('3', 'A', 72.3, 73.3), vol('3', 'B', 78.6, 79.7),
            vol('1', 'A', 87.5, 88.6), vol('2', 'A', 103.8, 104.9), vol('3', 'A', 117.5, 118.6), vol('3', 'B', 123.9, 125),
        ],
        bf: [...sweep(0), ...sweep(38.1), ...sweep(63), ...sweep(94.6)],
    }, 23);
    assert.deepEqual(r.map(x => [x.a, x.items.length]), [[0, 7], [38.1, 10], [87.5, 7]]);
});
