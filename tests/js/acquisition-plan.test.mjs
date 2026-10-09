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
    assert.equal(plan.intervalSeconds, 30);
    assert.equal(plan.spim.slices, 50);
    assert.equal(plan.bf.enabled, false);
    assert.deepEqual(P.validate(plan, IDS), []);
    assert.deepEqual(plan.stop, { kind: 'duration', value: 16 });
    assert.match(P.describe(plan, SUBJECTS), /^Every 30 s: SPIM volumes \(50 slices · 10 ms\) of 4 embryos · after 16 h\.$/);
});

test('minutes are the unit the biologist thinks in; seconds are what is sent', () => {
    const plan = P.fromForm({ interval: 5, intervalUnit: 'min' });
    assert.equal(plan.intervalSeconds, 300);
    assert.equal(P.toPayload(plan, IDS).interval_seconds, 300);
    assert.match(P.describe(plan, SUBJECTS), /^Every 5 min/);
    assert.match(P.describe(P.fromForm({ interval: 90, intervalUnit: 's' }), SUBJECTS), /^Every 90 s/);
    assert.match(P.describe(P.fromForm({ interval: 2, intervalUnit: 'min' }), SUBJECTS), /^Every 2 min/);
});

test('the brightfield channel rides on its own clock, in rounds', () => {
    const plan = P.fromForm({ interval: 5, intervalUnit: 'min', bf: true, bfEveryRounds: 3, bfExposureMs: 8 });
    const body = P.toPayload(plan, IDS);
    assert.deepEqual(body.bf, { enabled: true, every_seconds: 900, position: null, exposure_ms: 8, light: 'led' });
    assert.match(P.describe(plan, SUBJECTS), /\+ one brightfield overview every 3 rounds from the centroid/);
    assert.match(P.describe(P.fromForm({ bf: true }), SUBJECTS), /one brightfield overview per round from the centroid/);
});

test('a plan without the brightfield channel sends no bf at all', () => {
    // The orchestrator treats an absent bf as off, and the existing exact-kwargs
    // route tests pin that a plain run calls start() exactly as before.
    assert.equal('bf' in P.toPayload(P.fromForm({}), IDS), false);
});

test('"taken from here" is the position captured when it was chosen', () => {
    const plan = P.fromForm({ bf: true, bfPosition: 'here', bfPin: { x: -512.4, y: -388.9 } });
    assert.deepEqual(P.toPayload(plan, IDS).bf.position, { x: -512.4, y: -388.9 });
    assert.match(P.describe(plan, SUBJECTS), /from -512, -389/);
    // and without a captured position it is not a plan yet
    const none = P.fromForm({ bf: true, bfPosition: 'here', bfPin: null });
    assert.match(P.validate(none, IDS).join(' '), /no field captured/i);
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

// ── a plan ⇄ a saved tactic's structure ──────────────────────────────────

test('a plan survives being saved and reloaded', () => {
    const plan = P.fromForm({
        interval: 5, intervalUnit: 'min', slices: 80, exposureMs: 12, laserConfig: '488 and 561',
        bf: true, bfEveryRounds: 2, bfPosition: 'here', bfPin: { x: -500, y: -400 }, bfExposureMs: 8,
        stopKind: 'duration', stopValue: 12,
        overrides: [{ embryoId: 'embryo_2', kind: 'hatching' }, { embryoId: 'embryo_3', kind: 'timepoints', value: 3 }],
        monitoringMode: 'expression_monitoring',
    });
    const st = P.toStructure(plan);
    assert.equal(st.cadence_s, 300);
    assert.equal(st.stop_condition, 'duration:12h');
    assert.deepEqual(st.bf, { enabled: true, every_seconds: 600, position: { x: -500, y: -400 }, exposure_ms: 8, light: 'led' });
    assert.deepEqual(st.stop_conditions, { embryo_2: 'hatching', embryo_3: 'timepoints:3' });

    const back = P.fromStructure(st);
    assert.deepEqual(back, plan, 'what was saved is what comes back');
    assert.equal(P.describe(back, SUBJECTS), P.describe(plan, SUBJECTS), 'and says the same sentence');
});

test('a structure the start route seeded, before any of this, still reads as a plan', () => {
    // The Adaptive start has always seeded {cadence_s, interval, stop_condition,
    // condition_value, monitoring_mode}. Nothing else — so nothing else is required.
    const plan = P.fromStructure({ cadence_s: 120, interval: 120, stop_condition: 'manual',
                                   condition_value: null, monitoring_mode: 'idle' });
    assert.equal(plan.intervalSeconds, 120);
    assert.equal(plan.bf.enabled, false);
    assert.deepEqual(plan.overrides, []);
    assert.match(P.describe(plan, SUBJECTS), /^Every 2 min: SPIM volumes \(50 slices · 10 ms\) of 4 embryos · until stopped\.$/);
});

test('the stop spec parses back to what the pane offers', () => {
    assert.deepEqual(P.parseStopSpec('timepoints:12'), { kind: 'timepoints', value: 12 });
    assert.deepEqual(P.parseStopSpec('duration:6h'), { kind: 'duration', value: 6 });
    assert.deepEqual(P.parseStopSpec('hatching+3'), { kind: 'hatching', value: null });
    assert.deepEqual(P.parseStopSpec('something_else'), { kind: 'manual', value: null });
    assert.deepEqual(P.parseStopSpec(undefined), { kind: 'manual', value: null });
});

test('a brightfield interval that is not a whole number of rounds rounds to one', () => {
    const plan = P.fromStructure({ cadence_s: 300, bf: { enabled: true, every_seconds: 700 } });
    assert.equal(plan.bf.everyRounds, 2);
});

test('the agent’s stage-based ending reads back as the pane’s own', () => {
    // A resumed session written by the agent ends at "stages(hatched,hatching)";
    // the pane has that ending, by name. It used to read back as "until stopped".
    assert.deepEqual(P.parseStopSpec('stages(hatched,hatching)'), { kind: 'hatching', value: null });
    assert.deepEqual(P.parseStopSpec('stages(comma)'), { kind: 'comma', value: null });
    assert.deepEqual(P.parseStopSpec('stages(twofold)'), { kind: 'manual', value: null });
    assert.equal(P.fromStructure({ stop_condition: 'stages(hatched,hatching)' }).stop.kind, 'hatching');
});

test('the plan says which light the overview is taken under', () => {
    // The bottom camera drives no light of its own. A night of overview
    // frames came out dark because nothing said which light to use. The
    // default is the LED (Ryan, 2026-10-09: "light should be default to LED
    // for BF imaging. at 1 percent").
    const dflt = P.fromForm({ bf: true });
    assert.equal(dflt.bf.light, 'led', 'the LED is what this rig uses for brightfield');
    assert.match(P.describe(dflt, SUBJECTS), /from the centroid, under the LED/);
    const room = P.fromForm({ bf: true, bfLight: 'room' });
    assert.equal(P.toPayload(room, IDS).bf.light, 'room');
    assert.match(P.describe(room, SUBJECTS), /under the room light/);
    const asIs = P.fromForm({ bf: true, bfLight: 'none' });
    assert.match(P.describe(asIs, SUBJECTS), /in the light as it is/);
    assert.equal(P.fromForm({ bf: true, bfLight: 'sunlight' }).bf.light, 'led');
    // saved and reloaded, the light comes back
    assert.equal(P.fromStructure(P.toStructure(room)).bf.light, 'room');
    // a plan saved before the light existed takes the default
    assert.equal(P.fromStructure({ bf: { enabled: true, use_led: true } }).bf.light, 'led');
    assert.deepEqual(Object.keys(P.BF_LIGHTS), ['led', 'room', 'none']);
});

test('the embryos do not all fit in one field: a frame from each pinned position', () => {
    const two = P.fromForm({ bf: true, bfPosition: 'here', bfPins: [{ x: -500, y: -400 }, { x: 900, y: -380 }] });
    const bf = P.toPayload(two, IDS).bf;
    assert.deepEqual(bf.position, { x: -500, y: -400 }, 'the first is the position older code reads');
    assert.deepEqual(bf.positions, [{ x: -500, y: -400 }, { x: 900, y: -380 }]);
    assert.match(P.describe(two, SUBJECTS), /from 2 positions/);
    // and it survives being saved and reloaded
    const back = P.fromStructure(P.toStructure(two));
    assert.deepEqual(back.bf.pins, two.bf.pins);
    // one pin says nothing new, so the payload is the old payload
    const one = P.fromForm({ bf: true, bfPosition: 'here', bfPins: [{ x: -500, y: -400 }] });
    assert.equal('positions' in P.toPayload(one, IDS).bf, false);
    assert.deepEqual(P.toPayload(one, IDS).bf.position, { x: -500, y: -400 });
});
