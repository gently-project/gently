/**
 * The calibration progress panel's reading of a frame.
 *
 *   node --test tests/js/calprogress.test.mjs
 *
 * (Pass the file, not the directory — see operate-math.test.mjs.)
 *
 * The panel's whole claim is that the frames already on the wire say enough to
 * narrate a calibration. That claim lives in two pure functions, so they are
 * what is tested: given the metadata `agent.push_viz` actually attaches, does
 * the panel say something an operator can act on?
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../gently/ui/web/static/js/panels/calprogress.js');

// Exactly the shape gently/app/tools/calibration_tools.py pushes.
const EDGE = {
    data_type: 'edge_detection',
    metadata: { embryo_id: 'embryo_1', galvo: -0.15, piezo: -15.0, visible: false, feature_score: 3 },
};
const SWEEP = {
    data_type: 'focus_sweep',
    metadata: {
        embryo_id: 'embryo_1', sweep: 'dense', galvo_name: 'top',
        galvo: -0.1, piezo: 12.4, score: 0.83, peak_detected: true,
    },
};
const PLOT = {
    data_type: 'focus_plot',
    metadata: { embryo_id: 'embryo_1', galvo_name: 'bottom', best_piezo: 13.44, r_squared: 0.9721 },
};
const SUMMARY = {
    data_type: 'calibration_summary',
    metadata: { embryo_id: 'embryo_1', slope: 101.23, r_squared_top: 0.972, r_squared_bottom: 0.951 },
};

test('each phase names itself from the frame, not from a counter', () => {
    assert.match(P.phaseOf(EDGE), /edges/i);
    assert.equal(P.phaseOf(SWEEP), 'Focus sweep · top dense');
    assert.equal(P.phaseOf(PLOT), 'Fitting the bottom focus curve');
    assert.equal(P.phaseOf(SUMMARY), 'Calibrated');
});

test('an edge frame says where it looked and what was there', () => {
    const cap = P.captionOf(EDGE);
    assert.match(cap, /-0\.150°/);      // where the galvo was
    assert.match(cap, /nothing there/);  // Claude's verdict, the reason the sweep stops
    assert.match(cap, /features 3\/10/);
});

test('a visible edge frame reads differently from an empty one', () => {
    const seen = P.captionOf({ ...EDGE, metadata: { ...EDGE.metadata, visible: true } });
    assert.match(seen, /embryo visible/);
    assert.doesNotMatch(seen, /nothing there/);
});

test('a focus frame carries the number the sweep is maximising', () => {
    const cap = P.captionOf(SWEEP);
    assert.match(cap, /piezo 12\.4 µm/);
    assert.match(cap, /sharpness 0\.83/);
    assert.match(cap, /peak found/);
});

test('the fit reports its R², which is what makes a calibration trustworthy', () => {
    assert.match(P.captionOf(PLOT), /R² 0\.972/);
    assert.match(P.captionOf(SUMMARY), /101\.2 µm\/deg/);
    assert.match(P.captionOf(SUMMARY), /R² 0\.972 top \/ 0\.951 bottom/);
});

test('a frame missing its numbers degrades to silence, never to NaN', () => {
    // Older runs, partial metadata, a phase that pushes an image with nothing
    // attached: a caption of "galvo NaN°" would be worse than no caption.
    for (const t of ['edge_detection', 'focus_sweep', 'focus_plot', 'calibration_summary']) {
        const cap = P.captionOf({ data_type: t, metadata: {} });
        assert.doesNotMatch(cap, /NaN|undefined|null/);
    }
    assert.equal(P.captionOf({ data_type: 'something_else', metadata: { galvo: 1 } }), '');
});

test('an unknown image type is never narrated as a calibration', () => {
    // The panel listens to a broadcast every image on the system rides on, so
    // a snapshot or a volume projection must not be mistaken for a frame.
    assert.equal(P.phaseOf({ data_type: 'snapshot', metadata: {} }), 'Calibrating');
});

// ── cards that append, one a step ──────────────────────────────────────
// The run was one picture and one row of forty thumbnails, where a step
// could not be told from the one before it.

const frame = (data_type, metadata = {}) => ({ data_type, metadata, base64_png: 'x' });

test('the cards are the categories a kept run is browsed by', () => {
    const cards = [];
    const fresh = [
        frame('presence_check', { galvo: 0 }),
        frame('edge_detection', { galvo: -0.2, signal: 3 }),
        frame('edge_detection', { galvo: -0.1, signal: 40, visible: true }),
        frame('focus_sweep', { galvo_name: '0.160°', sweep: 'wide', piezo: -31, score: 0.2 }),
        frame('focus_sweep', { galvo_name: '0.160°', sweep: 'wide', piezo: 10, score: 0.9 }),
        frame('focus_plot', { galvo_name: '0.160°', best_piezo: 10.0, r_squared: 0.67 }),
        frame('focus_sweep', { galvo_name: '0.100°', piezo: 4, score: 0.5 }),
        frame('focus_sweep', { galvo_name: '0.160°', sweep: 'fine', piezo: 9, score: 0.8 }),
        frame('calibration_summary', { slope: 97 }),
    ].map(f => P.intoCards(cards, f));
    // The sweep's plot joins the sweep; everything else that changes step is a new card.
    assert.deepEqual(fresh, [true, true, false, true, false, false, true, true, true]);
    assert.deepEqual(cards.map(c => c.title), [
        'Checking there is something there', 'Where the embryo is',
        'Focus at 0.160° wide', 'Focus at 0.100°', 'Focus at 0.160° fine', 'The fit',
    ]);
    // What the sweep found is on its card, in the graphs' own words.
    assert.equal(cards[2].says, 'sharpest at +10.0 µm · R² 0.67');
    assert.equal(cards[2].best, 10.0);
    // A point a frame, for the graph: sharpness against piezo, signal against galvo.
    assert.deepEqual(cards[2].pts, [{ x: -31, y: 0.2 }, { x: 10, y: 0.9 }]);
    assert.deepEqual(cards[1].pts.map(p => [p.x, p.y, p.seen]), [[-0.2, 3, false], [-0.1, 40, true]]);
});

test('in a walk, the next embryo starts its own cards', () => {
    const cards = [];
    P.intoCards(cards, frame('edge_detection', { embryo_id: 'embryo_1' }));
    P.intoCards(cards, frame('edge_detection', { embryo_id: 'embryo_1' }));
    assert.equal(P.intoCards(cards, frame('edge_detection', { embryo_id: 'embryo_2' })), true);
    assert.deepEqual(cards.map(c => c.who), ['embryo_1', 'embryo_2']);
    // And a plot joins its own embryo's sweep, not the other's.
    P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_1', galvo_name: 'top', sweep: 'dense' }));
    P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_2', galvo_name: 'top', sweep: 'dense' }));
    assert.equal(P.intoCards(cards, frame('focus_plot', { embryo_id: 'embryo_1', galvo_name: 'top', best_piezo: 2 })), false);
    assert.equal(cards.find(c => c.who === 'embryo_1' && c.title === 'Focus at top dense').best, 2);
    assert.equal(cards.find(c => c.who === 'embryo_2' && c.title === 'Focus at top dense').best, null);
});

test('a long step keeps its newest frames, every point, and never drops a conclusion', () => {
    const cards = [];
    for (let i = 0; i < 60; i++) P.intoCards(cards, frame('focus_sweep', { galvo_name: 'top', sweep: 'dense', piezo: i, score: 0.5 }));
    P.intoCards(cards, frame('focus_plot', { galvo_name: 'top', best_piezo: 30 }));
    for (let i = 60; i < 80; i++) P.intoCards(cards, frame('focus_sweep', { galvo_name: 'top', sweep: 'dense', piezo: i, score: 0.5 }));
    assert.equal(cards.length, 1);
    const sweep = cards[0];
    assert.equal(sweep.frames.length, P.MAX_FRAMES);
    // The plot's picture is not kept: the curve is drawn from the points.
    assert.ok(!sweep.frames.some(f => f.data_type === 'focus_plot'));
    assert.equal(sweep.best, 30);
    assert.equal(sweep.frames[sweep.frames.length - 1].metadata.piezo, 79);
    assert.equal(sweep.pts.length, 80);
});

test('a graph is drawn from the numbers, and its picture is kept only when it cannot be', () => {
    const cards = [];
    const sweep = (name, galvo, best) => {
        for (let i = 0; i < 5; i++) P.intoCards(cards, frame('focus_sweep', { galvo_name: name, piezo: i, score: 0.1 * i }));
        P.intoCards(cards, frame('focus_plot', { galvo_name: name, galvo, best_piezo: best, r_squared: 0.9 }));
    };
    sweep('0.100°', 0.1, 4.0);
    sweep('0.220°', 0.22, 16.0);
    P.intoCards(cards, frame('calibration_summary', { slope: 100, offset: -6, r_squared: 0.99 }));
    const fit = cards[cards.length - 1];
    assert.equal(fit.title, 'The fit');
    assert.equal(fit.says, '100.0 µm/° · offset -6.0 µm · R² 0.99');
    assert.deepEqual(fit.fit.points, [{ x: 0.1, y: 4.0 }, { x: 0.22, y: 16.0 }]);
    assert.equal(fit.frames.length, 0);
    assert.ok(cards.every(c => !c.frames.some(f => f.data_type === 'focus_plot')));

    // No numbers to draw from: the picture is what there is, so it stays.
    const bare = [];
    P.intoCards(bare, frame('focus_plot', { galvo_name: 'top', best_piezo: 3 }));
    P.intoCards(bare, frame('calibration_summary', { slope: 97 }));
    assert.deepEqual(bare.map(c => c.frames.length), [1, 1]);
});
