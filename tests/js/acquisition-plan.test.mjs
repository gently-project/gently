/**
 * The acquisition plan, said once.
 *
 *   node --test tests/js/acquisition-plan.test.mjs
 *
 * (Pass the file, not the directory — see operate-math.test.mjs.)
 *
 * The pane reads a form into a plan; this module says it and turns it into
 * the start request. Both directions are what a biologist checks before
 * pressing Start, so both are what is tested: does the sentence say what the
 * form holds, and does the request carry exactly the sentence.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../gently/ui/web/static/js/acquisition-plan.js');

const SUBJECTS = [{ id: 'embryo_1', label: '1' }, { id: 'embryo_2', label: '2' },
                  { id: 'embryo_3', label: '3' }, { id: 'embryo_4', label: '4' }];
const IDS = SUBJECTS.map(s => s.id);

test('an untouched form is still a complete, sayable plan', () => {
    const plan = P.fromForm({});
    assert.equal(plan.intervalSeconds, 120);
    assert.equal(plan.spim.slices, 50);
    assert.equal(plan.dic.enabled, false);
    assert.equal(plan.stop.kind, 'manual');
    assert.deepEqual(P.validate(plan, IDS), []);
    assert.match(P.describe(plan, SUBJECTS), /^Every 2 min: SPIM volumes \(50 slices · 10 ms\) of 4 embryos · until stopped\.$/);
});

test('minutes are the unit the biologist thinks in; seconds are what is sent', () => {
    const plan = P.fromForm({ interval: 5, intervalUnit: 'min' });
    assert.equal(plan.intervalSeconds, 300);
    assert.equal(P.toPayload(plan, IDS).interval_seconds, 300);
    assert.match(P.describe(plan, SUBJECTS), /^Every 5 min/);
    assert.match(P.describe(P.fromForm({ interval: 90, intervalUnit: 's' }), SUBJECTS), /^Every 90 s/);
    assert.match(P.describe(P.fromForm({ interval: 2, intervalUnit: 'min' }), SUBJECTS), /^Every 2 min/);
});

test('the DIC channel rides on its own clock, in rounds', () => {
    const plan = P.fromForm({ interval: 5, intervalUnit: 'min', dic: true, dicEveryRounds: 3, dicExposureMs: 8 });
    const body = P.toPayload(plan, IDS);
    assert.deepEqual(body.dic, { enabled: true, every_seconds: 900, position: null, exposure_ms: 8 });
    assert.match(P.describe(plan, SUBJECTS), /\+ one DIC overview every 3 rounds from the centroid/);
    assert.match(P.describe(P.fromForm({ dic: true }), SUBJECTS), /one DIC overview per round from the centroid/);
});

test('a plan without DIC sends no dic at all', () => {
    // The orchestrator treats an absent dic as off, and the existing exact-kwargs
    // route tests pin that a plain run calls start() exactly as before.
    assert.equal('dic' in P.toPayload(P.fromForm({}), IDS), false);
});

test('"taken from here" is the position captured when it was chosen', () => {
    const plan = P.fromForm({ dic: true, dicPosition: 'here', dicPin: { x: -512.4, y: -388.9 } });
    assert.deepEqual(P.toPayload(plan, IDS).dic.position, { x: -512.4, y: -388.9 });
    assert.match(P.describe(plan, SUBJECTS), /from -512, -389/);
    // and without a captured position it is not a plan yet
    const none = P.fromForm({ dic: true, dicPosition: 'here', dicPin: null });
    assert.match(P.validate(none, IDS).join(' '), /no stage position/i);
});

test('how it ends, for the run and for one embryo', () => {
    const plan = P.fromForm({
        stopKind: 'duration', stopValue: 12,
        overrides: [{ embryoId: 'embryo_2', kind: 'hatching' },
                    { embryoId: 'embryo_3', kind: 'timepoints', value: 3 },
                    { embryoId: 'embryo_4', kind: 'default' }],
    });
    const body = P.toPayload(plan, IDS);
    assert.equal(body.stop_condition, 'duration:12h');
    assert.deepEqual(body.stop_conditions, { embryo_2: 'hatching', embryo_3: 'timepoints:3' },
        '"as the run" is no override, and the run keeps its own');
    assert.match(P.describe(plan, SUBJECTS), /· after 12 h; 2 at hatching, 3 after 3 timepoints\.$/);
});

test('the orchestrator hears the combined spec, never the bare word', () => {
    assert.equal(P.stopSpec('timepoints', 12), 'timepoints:12');
    assert.equal(P.stopSpec('timepoints', '7.6'), 'timepoints:8');
    assert.equal(P.stopSpec('duration', 6), 'duration:6h');
    assert.equal(P.stopSpec('manual'), 'manual');
    assert.equal(P.stopSpec('nonsense'), 'manual');
});

test('a stop that needs a number refuses to start without one', () => {
    assert.match(P.validate(P.fromForm({ stopKind: 'timepoints', stopValue: '' }), IDS)[0], /how many timepoints/);
    assert.match(P.validate(P.fromForm({ stopKind: 'duration', stopValue: 0 }), IDS)[0], /how many hours/);
    assert.deepEqual(P.validate(P.fromForm({ stopKind: 'timepoints', stopValue: 12 }), IDS), []);
});

test('no embryos is the first thing it says', () => {
    assert.match(P.validate(P.fromForm({}), [])[0], /No embryos/);
    assert.match(P.describe(P.fromForm({}), []), /of no embryos/);
});

test('an override for an embryo not in the run is a problem, not a silent drop', () => {
    const plan = P.fromForm({ overrides: [{ embryoId: 'embryo_9', kind: 'hatching' }] });
    assert.match(P.validate(plan, IDS).join(' '), /embryo_9 is not in this run/);
});

test('the SPIM channel carries its settings, and the preset only when chosen', () => {
    const plan = P.fromForm({ slices: 80, exposureMs: 12, laserConfig: '488 and 561' });
    const body = P.toPayload(plan, IDS);
    assert.equal(body.num_slices, 80);
    assert.equal(body.exposure_ms, 12);
    assert.equal(body.laser_config, '488 and 561');
    assert.match(P.describe(plan, SUBJECTS), /\(80 slices · 12 ms · 488 and 561\)/);
    assert.equal('laser_config' in P.toPayload(P.fromForm({}), IDS), false);
});

test('one embryo is named, several are counted', () => {
    assert.match(P.describe(P.fromForm({}), [SUBJECTS[1]]), /of embryo 2 ·/);
    assert.match(P.describe(P.fromForm({}), SUBJECTS), /of 4 embryos ·/);
});
