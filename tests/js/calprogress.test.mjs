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
    // What each step found, in the graphs' own words.
    assert.equal(P.saysOf(cards[1]), 'seen from −0.10° to −0.10°');
    assert.equal(P.saysOf(cards[2]), 'sharpest at +10.0 µm · R² 0.67');
    assert.equal(P.saysOf(cards[3]), '');
    // A point an exposure, for the graph, each knowing its picture.
    assert.deepEqual(cards[2].pts, [{ x: -31, y: 0.2, frame: 0 }, { x: 10, y: 0.9, frame: 1 }]);
    assert.deepEqual(cards[1].pts.map(p => [p.x, p.y, p.seen]), [[-0.2, 3, false], [-0.1, 40, true]]);
});

test('the picture at rest is the exposure the step picked', () => {
    const cards = [];
    [-4, 0, 4, 8, 12].forEach((z, i) => P.intoCards(cards, frame('focus_sweep', { galvo_name: '0.1°', piezo: z, score: i })));
    // Nothing is picked while the sweep is still coming in.
    assert.equal(P.pickedOf(cards[0]), -1);
    P.intoCards(cards, frame('focus_plot', { galvo_name: '0.1°', best_piezo: 3.1, r_squared: 0.9 }));
    assert.equal(P.pickedOf(cards[0]), 2);          // the exposure at piezo 4, nearest 3.1

    // Where the embryo is: the brightest angle it was seen at, not the brightest of all.
    const edges = [];
    [[-0.2, 90, false], [0.0, 40, true], [0.1, 70, true], [0.3, 5, false]]
        .forEach(([galvo, signal, visible]) => P.intoCards(edges, frame('edge_detection', { galvo, signal, visible })));
    assert.equal(P.pickedOf(edges[0]), 2);
    const none = [];
    P.intoCards(none, frame('edge_detection', { galvo: 0, signal: 3, visible: false }));
    assert.equal(P.pickedOf(none[0]), -1);
    assert.equal(P.saysOf(none[0]), 'not seen at any angle');
});

test('in a walk, each embryo and each side has its own cards', () => {
    const cards = [];
    const edge = (embryo_id, side) => P.intoCards(cards, frame('edge_detection', { embryo_id, side, galvo: 0, signal: 1 }));
    edge('embryo_1', 'A'); edge('embryo_1', 'A');
    assert.equal(edge('embryo_1', 'B'), true);
    assert.equal(edge('embryo_2', 'A'), true);
    assert.deepEqual(cards.map(c => [c.who, c.side]), [['embryo_1', 'A'], ['embryo_1', 'B'], ['embryo_2', 'A']]);
    // A plot joins its own embryo's sweep, not the other's.
    P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_1', galvo_name: 'top', sweep: 'dense', piezo: 1, score: 1 }));
    P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_2', galvo_name: 'top', sweep: 'dense', piezo: 1, score: 1 }));
    assert.equal(P.intoCards(cards, frame('focus_plot', { embryo_id: 'embryo_1', galvo_name: 'top', best_piezo: 2 })), false);
    assert.equal(cards.find(c => c.who === 'embryo_1' && c.title === 'Focus at top dense').best, 2);
    assert.equal(cards.find(c => c.who === 'embryo_2' && c.title === 'Focus at top dense').best, null);
});

test('a frame that does not say its side belongs with the ones that do', () => {
    // A kept run's exposures did not record the side; its summary did.
    const cards = [];
    for (let i = 0; i < 4; i++) P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_2', galvo_name: '0.1°', piezo: i, score: i }));
    P.intoCards(cards, frame('focus_plot', { embryo_id: 'embryo_2', galvo_name: '0.1°', galvo: 0.1, best_piezo: 2 }));
    for (let i = 0; i < 4; i++) P.intoCards(cards, frame('focus_sweep', { embryo_id: 'embryo_2', galvo_name: '0.2°', piezo: i, score: i }));
    P.intoCards(cards, frame('focus_plot', { embryo_id: 'embryo_2', galvo_name: '0.2°', galvo: 0.2, best_piezo: 12 }));
    P.intoCards(cards, frame('calibration_summary', { embryo_id: 'embryo_2', side: 'B', slope: 100, offset: -8 }));
    assert.equal(new Set(cards.map(c => c.owner)).size, 1);
    assert.deepEqual(cards[2].fit.points, [{ x: 0.1, y: 2 }, { x: 0.2, y: 12 }]);
});

test('a long step keeps every point, and lets the oldest pictures go', () => {
    const cards = [];
    const n = P.MAX_FRAMES + 20;
    for (let i = 0; i < n; i++) P.intoCards(cards, frame('focus_sweep', { galvo_name: 'top', sweep: 'dense', piezo: i, score: 0.5 }));
    P.intoCards(cards, frame('focus_plot', { galvo_name: 'top', best_piezo: 30 }));
    assert.equal(cards.length, 1);
    const sweep = cards[0];
    assert.equal(sweep.pts.length, n);
    assert.equal(sweep.frames.length, n);
    assert.equal(sweep.frames.filter(f => f.base64_png).length, P.MAX_FRAMES);
    assert.equal(sweep.frames[0].base64_png, null);
    assert.equal(sweep.frames[n - 1].base64_png, 'x');
    // The plot's picture is not kept: the curve is drawn from the points.
    assert.equal(sweep.extras.length, 0);
    assert.equal(sweep.best, 30);
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
    assert.equal(P.saysOf(fit), '100.0 µm/° · offset −6.0 µm · R² 0.99');
    assert.deepEqual(fit.fit.points, [{ x: 0.1, y: 4.0 }, { x: 0.22, y: 16.0 }]);
    assert.ok(cards.every(c => c.extras.length === 0));

    // No numbers to draw from: the picture is what there is, so it stays.
    const bare = [];
    P.intoCards(bare, frame('focus_plot', { galvo_name: 'top', best_piezo: 3 }));
    P.intoCards(bare, frame('calibration_summary', { slope: 97 }));
    assert.deepEqual(bare.map(c => c.extras.length), [1, 1]);
});

test('an angle swept twice in one fit is the wide look and then the fine one', () => {
    const cards = [];
    const sweep = name => P.intoCards(cards, frame('focus_sweep', { galvo_name: name, sweep: 'stack', piezo: 1, score: 1 }));
    P.intoCards(cards, frame('focus_montage', { pick: 'D', method: 'vision', reasoning: 'D is the sharpest.' }));
    sweep('0.100°'); sweep('0.034°'); sweep('0.100°'); sweep('0.166°');
    // The other side's fit starts at its own edges, and is named afresh.
    P.intoCards(cards, frame('edge_detection', { galvo: 0, signal: 1 }));
    sweep('0.100°');
    assert.deepEqual(cards.map(c => c.title), [
        'Finding the focus', 'Focus at 0.100° wide', 'Focus at 0.034°', 'Focus at 0.100° fine', 'Focus at 0.166°',
        'Where the embryo is', 'Focus at 0.100°',
    ]);
    // The montage is the first card's picture, and what was picked its finding.
    assert.equal(P.saysOf(cards[0]), 'picked D by vision');
    assert.equal(cards[0].extras.length, 1);
});

test('the fit is drawn from the points its summary carries', () => {
    const cards = [];
    P.intoCards(cards, frame('calibration_summary', { slope: 97, offset: -6, points: [{ galvo: 0.03, piezo: -3 }, { galvo: 0.1, piezo: 4 }, { galvo: 0.17, piezo: 10.5 }] }));
    assert.equal(cards[0].fit.points.length, 3);
    assert.equal(cards[0].extras.length, 0);
});

test('the row of exposures is a dozen along the sweep, the picked one among them', () => {
    const cards = [];
    for (let i = 0; i < 61; i++) P.intoCards(cards, frame('focus_sweep', { galvo_name: '0.1°', piezo: i, score: i }));
    P.intoCards(cards, frame('focus_plot', { galvo_name: '0.1°', best_piezo: 23.2 }));
    const row = P.thumbsOf(cards[0], 12, -1);
    assert.equal(row.length, 12);
    assert.equal(row[0], 0);
    assert.equal(row[11], 60);
    assert.ok(row.includes(23), 'the exposure the sweep picked is not on its row');
    // One being looked at is put on the row too, and the row stays in order.
    const looking = P.thumbsOf(cards[0], 12, 41);
    assert.ok(looking.includes(41) && looking.includes(23));
    assert.deepEqual(looking, looking.slice().sort((a, b) => a - b));
    // A short step shows every exposure.
    const few = [];
    for (let i = 0; i < 5; i++) P.intoCards(few, frame('edge_detection', { galvo: i, signal: i }));
    assert.deepEqual(P.thumbsOf(few[0], 12, -1), [0, 1, 2, 3, 4]);
});
