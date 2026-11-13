/**
 * Unit tests for what the Acquisition page says before a run starts.
 *
 *   node --test tests/js/run-preflight.test.mjs
 *
 * The owner, on the drawing of it: "i love the before it starts idea...
 * really good." What it replaces is a press that answered "Start failed (409 —
 * not calibrated: embryo_2 … or pass allow_uncalibrated=true to acquire
 * anyway...)" from a page that had known all along.
 *
 * The lines are sentences an operator acts on before leaving for the night,
 * so what is pinned is what each says and when it stands in the way: who is
 * in the run, whether each has a fit, whether a round fits the cadence, what
 * the run writes against what is free.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
globalThis.AcquisitionPlan = require('../../gently/ui/web/static/js/acquisition-plan.js');
const P = require('../../gently/ui/web/static/js/run-preflight.js');
const A = globalThis.AcquisitionPlan;

const plan = over => A.fromForm({ interval: 5, intervalUnit: 'min', slices: 50, exposureMs: 10,
    laserConfig: '488 and 561', stopKind: 'duration', stopValue: 16, ...over });
const embryos = (n, uncal = []) => Array.from({ length: n }, (_, i) => ({
    id: `embryo_${i + 1}`, label: String(i + 1), calibrated: !uncal.includes(i + 1), r2: 0.99 }));
const ctx = (p, subjects, over) => ({ plan: p, est: P.estimate(p, subjects.length), subjects, problems: [], ...over });
const kinds = ls => ls.map(l => l.kind);
const find = (ls, re) => ls.find(l => re.test(l.text));

test('estimate: an embryo costs the scan and what surrounds it', () => {
    // 4.0 s a volume at 50 slices and 10 ms: the rig's own median over 6,919.
    const e = P.estimate(plan(), 11);
    assert.equal(e.perEmbryoS, 4.0);
    assert.equal(e.roundS, 44);
});

test('estimate: the cadence kept is the cadence asked plus one acquisition', () => {
    // Measured: 303.1 s kept for 300 asked, 33.5 s for 30.
    assert.equal(P.estimate(plan(), 4).keptS, 304);
    assert.equal(P.estimate(plan({ interval: 30, intervalUnit: 's' }), 4).keptS, 34);
});

test('estimate: a round longer than the interval is the cadence', () => {
    const e = P.estimate(plan({ interval: 30, intervalUnit: 's' }), 11);
    assert.equal(e.roundS, 44);
    assert.equal(e.keptS, 44);
    assert.equal(e.holds, 7);          // every 30 s holds seven embryos and no more
});

test('estimate: a night is counted in rounds of the cadence kept, not the one asked', () => {
    const e = P.estimate(plan(), 11);
    assert.equal(e.rounds, Math.floor(16 * 3600 / 304));          // 189, not 192
    assert.equal(e.count, 189 * 11);
    assert.equal(e.bytes, 189 * 11 * 50 * 512 * 2048 * 2);       // 105 MB a volume
});

test('estimate: a run with no end has a rate and no total', () => {
    const e = P.estimate(plan({ stopKind: 'manual' }), 3);
    assert.equal(e.rounds, null);
    assert.equal(e.bytes, null);
    assert.ok(e.bytesPerHour > 0);
    const h = P.estimate(plan({ stopKind: 'hatching' }), 3);
    assert.equal(h.bytes, null);
});

test('estimate: fields the plan leaves alone are read from the embryos, then the defaults', () => {
    const blank = plan({ slices: '', exposureMs: '' });
    assert.equal(P.estimate(blank, 1, { slices: 30, exposureMs: 5 }).perEmbryoS, 3.5 + 0.15);
    assert.equal(P.estimate(blank, 1).perEmbryoS, 4.0);
});

test('estimate: a brightfield run takes no volumes and writes none', () => {
    const e = P.estimate(plan({ volumes: false }), 3);
    assert.equal(e.roundS, 0);
    assert.equal(e.keptS, 300);
    assert.equal(e.bytes, null);
});

test('span and size say a length and a weight the way a person would', () => {
    assert.equal(P.span(44), '44 s');
    assert.equal(P.span(304), '5 min 4 s');
    assert.equal(P.span(300), '5 min');
    assert.equal(P.span(16 * 3600), '16 h');
    assert.equal(P.span(2 * 3600 + 600), '2 h 10 min');
    assert.equal(P.size(218e9), '218 GB');
    assert.equal(P.size(3.4e12), '3.4 TB');
    assert.equal(P.size(4.2e9), '4.2 GB');
    assert.equal(P.size(105e6), '105 MB');
});

test('keptWords: said only where it differs, and only for a volume run', () => {
    assert.equal(P.keptWords(P.estimate(plan(), 4)), 'kept as about 5 min 4 s');
    assert.equal(P.keptWords(P.estimate(plan({ volumes: false }), 4)), '');
    assert.equal(P.keptWords(P.estimate(plan(), 0)), '');
});

test('lines: every embryo calibrated and the plan sound is nothing in the way', () => {
    const p = plan();
    const ls = P.lines(ctx(p, embryos(11), { references: 1, powers: { 488: 3.1, 561: 4.9 },
        freeBytes: 3.4e12, head: { um: 114.6, gotoMin: 1000 }, refs: { have: true } }));
    assert.deepEqual(P.verdict(ls), { blocked: 0, says: '' });
    assert.ok(kinds(ls).every(k => k === 'ok'), JSON.stringify(ls));
    assert.equal(ls[0].text, '11 embryos in the run; 1 reference left out.');
    assert.ok(find(ls, /^Every embryo in the run has a fit\.$/));
    assert.ok(find(ls, /^488 at 3\.1 %, 561 at 4\.9 %\.$/));
    assert.ok(find(ls, /^A round takes about 44 s of the 5 min between rounds\.$/));
    assert.ok(find(ls, /^About 2,079 volumes, 218 GB; 3\.4 TB free\.$/));
    assert.ok(find(ls, /^The head is at 114\.6 µm\.$/));
});

test('lines: an uncalibrated embryo stands in the way, by name, with both ways past it', () => {
    const p = plan();
    const ls = P.lines(ctx(p, embryos(11, [3, 8, 11])));
    const l = find(ls, /not calibrated/);
    assert.equal(l.kind, 'no');
    assert.equal(l.text, '3 of 11 are not calibrated: 3, 8, 11. A run refuses them.');
    assert.deepEqual(l.fix.map(f => f.action), ['calibrate', 'without']);
    assert.deepEqual(P.verdict(ls), { blocked: 1, says: '1 thing in the way' });
});

test('lines: with none calibrated there is no run to have without them', () => {
    const ls = P.lines(ctx(plan(), embryos(3, [1, 2, 3])));
    const l = find(ls, /not calibrated/);
    assert.equal(l.text, '3 of 3 are not calibrated: 1, 2, 3. A run refuses them.');
    assert.deepEqual(l.fix.map(f => f.action), ['calibrate']);
    const one = find(P.lines(ctx(plan(), embryos(1, [1]))), /not calibrated/);
    assert.equal(one.text, '1 of 1 is not calibrated: 1. A run refuses it.');
});

test('lines: what the plan itself gets wrong is said here, not in a toast', () => {
    const p = plan({ laserPowers: { 488: 9 } });
    const problems = A.validate(p, ['embryo_1'], { 488: { min: 2, max: 6 } });
    const ls = P.lines(ctx(p, embryos(1), { problems }));
    assert.equal(find(ls, /488 nm power/).kind, 'no');
    assert.equal(P.verdict(ls).blocked, 1);
});

test('lines: a round that does not fit is said with how many embryos would', () => {
    const p = plan({ interval: 30, intervalUnit: 's' });
    const l = find(P.lines(ctx(p, embryos(11))), /A round takes/);
    assert.equal(l.kind, 'warn');
    assert.equal(l.text, 'A round takes about 44 s (11 × 4.0 s): every 30 s cannot be kept. Every 30 s holds 7 embryos.');
});

test('lines: a run that would fill the disk is refused before it starts', () => {
    const p = plan({ interval: 30, intervalUnit: 's' });
    const full = find(P.lines(ctx(p, embryos(7), { freeBytes: 200e9 })), /volumes/);
    assert.equal(full.kind, 'no');
    assert.match(full.text, /The disk would fill before the run ends\.$/);
    const half = find(P.lines(ctx(plan(), embryos(11), { freeBytes: 300e9 })), /volumes/);
    assert.equal(half.kind, 'warn');
    // Unread is not a problem, and not a claim either.
    const unread = find(P.lines(ctx(plan(), embryos(11))), /volumes/);
    assert.equal(unread.text, 'About 2,079 volumes, 218 GB.');
});

test('lines: a run with no end says its rate, and the room there is for it', () => {
    const p = plan({ stopKind: 'manual' });
    const l = find(P.lines(ctx(p, embryos(11), { freeBytes: 3.4e12 })), /an hour/);
    assert.equal(l.kind, 'ok');
    assert.match(l.text, /^About 14 GB an hour, with no end set; 3\.4 TB free: room for about \d+ h/);
    const tight = find(P.lines(ctx(p, embryos(11), { freeBytes: 100e9 })), /an hour/);
    assert.equal(tight.kind, 'warn');
});

test('lines: lasers as they are, when none is routed, is a dark run', () => {
    const p = plan({ laserConfig: '' });
    assert.equal(find(P.lines(ctx(p, embryos(2), { routed: [] })), /no line is routed/).kind, 'warn');
    assert.ok(find(P.lines(ctx(p, embryos(2), { routed: [488], powers: { 488: 3.1 } })), /^488 at 3\.1 %, as the rig has them now\.$/));
    // Unread: nothing is claimed about the light.
    assert.equal(find(P.lines(ctx(p, embryos(2), { routed: null })), /routed|as the rig/), undefined);
    const off = plan({ laserConfig: 'ALL OFF' });
    assert.equal(find(P.lines(ctx(off, embryos(2))), /ALL OFF routes no line/).kind, 'warn');
});

test('lines: a power the plan sets is the one said, over the one the line has', () => {
    const p = plan({ laserPowers: { 488: 4 } });
    assert.ok(find(P.lines(ctx(p, embryos(2), { powers: { 488: 3.1, 561: 4.9 } })), /^488 at 4 %, 561 at 4\.9 %\.$/));
});

test('lines: a head parked at the load height is said, with the way down', () => {
    const l = find(P.lines(ctx(plan(), embryos(2), { head: { um: 25000, gotoMin: 1000 } })), /The head/);
    assert.equal(l.kind, 'warn');
    assert.equal(l.text, 'The head is at 25,000 µm, off the sample.');
    assert.deepEqual(l.fix, [{ action: 'head', label: 'To 1,000 µm' }]);
});

test('lines: a poor fit is a warning, not a refusal', () => {
    const subs = embryos(3); subs[1].r2 = 0.41;
    const l = find(P.lines(ctx(plan(), subs, { lowR2: 0.5 })), /poor fit/i);
    assert.equal(l.kind, 'warn');
    assert.equal(l.text, 'A poor fit: 2 (R² 0.41).');
});

test('lines: the overview with no dark and flat is said, for either kind of run', () => {
    const p = plan({ bf: true });
    assert.equal(find(P.lines(ctx(p, embryos(2), { refs: { have: false } })), /^Overview: no dark and flat/).kind, 'warn');
    assert.equal(find(P.lines(ctx(p, embryos(2), { refs: { have: true } })), /dark and flat/), undefined);
    const bf = plan({ volumes: false });
    const ls = P.lines(ctx(bf, embryos(0), { refs: { have: false } }));
    assert.equal(ls[0].text, 'A brightfield run: no embryo is imaged, and no calibration is asked for.');
    assert.ok(find(ls, /^Brightfield: no dark and flat/));
    // Nothing about fits, rounds or volumes for a run that takes none.
    assert.equal(find(ls, /fit|round|volumes,/), undefined);
});
