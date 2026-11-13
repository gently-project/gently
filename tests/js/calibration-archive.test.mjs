// The words the Calibration tab's archive puts on a run and on an exposure
// (gently/ui/web/static/js/calibration-archive.js). The records below are
// shaped like the ones on the rig's disk: a fit, and a run that was refused.

import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const A = require('../../gently/ui/web/static/js/calibration-archive.js');

const FIT = {
    embryo_id: 'embryo_3', run: '20261108_004435', outcome: 'calibrated',
    started_at: '2026-11-08T00:44:35', finished_at: '2026-11-08T00:45:53',
    requested: { method: 'legacy', z_buffer_um: 25.0 },
    calibration: {
        slope_um_per_deg: 35.2713, offset_um: -4.449, galvo_top_deg: -0.35, galvo_bottom_deg: 0.5,
        r_squared_top: 0.99, r_squared_bottom: 0.949,
    },
    frames: 44, plots: 3,
};
const REFUSED = {
    embryo_id: 'embryo_1', run: '20261108_004606', outcome: 'refused', calibration: null,
    started_at: '2026-11-08T00:46:06', finished_at: '2026-11-08T00:46:13',
    requested: { method: 'scan' }, frames: 11, plots: 0,
    message: 'No object visible for embryo_1: nothing lit clears the floor',
};

test('a fit is said as its slope and the weaker end of its two fits', () => {
    assert.equal(A.cameTo(FIT), '35.3 µm/° · R² 0.95');
    assert.equal(A.hasFit(FIT), true);
    assert.equal(A.rSquared(FIT.calibration), 0.949);
});

test('a run with no fit is said as how it ended', () => {
    assert.equal(A.cameTo(REFUSED), 'refused');
    assert.equal(A.hasFit(REFUSED), false);
    assert.equal(A.cameTo({ outcome: 'no_object' }), 'no object');
    assert.equal(A.cameTo({}), 'unknown');
    assert.equal(A.cameTo(null), 'unknown');
});

test('an older record with one R² still says it', () => {
    assert.equal(A.cameTo({ calibration: { slope_um_per_deg: 97.3, r_squared: 0.98 } }), '97.3 µm/° · R² 0.98');
    assert.equal(A.cameTo({ calibration: { slope_um_per_deg: 97.3 } }), '97.3 µm/°');
});

test('how long a run took comes from its two timestamps', () => {
    assert.equal(A.took(FIT), '1 min 18 s');
    assert.equal(A.took(REFUSED), '7 s');
    assert.equal(A.took({ started_at: '2026-11-08T00:46:06' }), '');
    assert.equal(A.took({ started_at: 'x', finished_at: 'y' }), '');
});

test('a run started today is said by the clock, another day with its date', () => {
    assert.equal(A.startedAt(FIT, new Date('2026-11-08T09:00:00')), '00:44');
    assert.match(A.startedAt(FIT, new Date('2026-11-13T09:00:00')), /8.* 00:44$/);
    assert.equal(A.startedAt({ run: '20261108_004435' }), '20261108_004435');
});

test('an exposure is said as what it was for and where the sheet stood', () => {
    const f = { kind: 'focus_sweep', sweep: 'dense', galvo_name: 'top', galvo: -0.05, piezo: -5.9, score: 9.76e11, file: 'frames/031_focus_sweep_dense_top_g-0.050_p-5.9.tif' };
    assert.equal(A.describe(f), 'focus sweep · dense · top · galvo −0.050° · piezo −5.9 µm · score 9.76e+11');
    assert.equal(A.fileName(f), '031_focus_sweep_dense_top_g-0.050_p-5.9.tif');
    assert.equal(A.describe({ kind: 'presence_check', galvo: 0, piezo: 0 }), 'presence check · galvo +0.000° · piezo +0.0 µm');
    assert.equal(A.describe(null), '');
});

test('plots are told from exposures by their file', () => {
    const images = [
        { n: 1, file: 'frames/001_presence_check_g+0.000_p+0.0.tif' },
        { n: 2, file: 'plots/002_focus_plot_top.png' },
        { n: 3, file: 'frames/003_focus_sweep_dense_top_g+0.010_p+3.5.tif' },
    ];
    assert.deepEqual(A.exposures(images).map(i => i.n), [1, 3]);
    assert.deepEqual(A.plots(images).map(i => i.n), [2]);
    assert.deepEqual(A.exposures(undefined), []);
});

test('a score is a height against the best of its own sweep', () => {
    const frames = [
        { kind: 'edge_detection' },                                     // no score, no bar
        { kind: 'focus_sweep', galvo_name: 'top', score: 50 },
        { kind: 'focus_sweep', galvo_name: 'top', score: 100 },
        { kind: 'focus_sweep', galvo_name: 'bottom', score: 4 },      // its own sweep's best
        { kind: 'focus_sweep', galvo_name: 'bottom', score: 1 },
    ];
    assert.deepEqual(A.scoreHeights(frames), [null, 0.5, 1, 1, 0.25]);
    assert.deepEqual(A.scoreHeights([]), []);
});

test('the record lists what the run has, and nothing it has not', () => {
    const fit = Object.fromEntries(A.facts(FIT));
    assert.equal(fit.Embryo, '3');
    assert.equal(fit['Came to'], 'calibrated');
    assert.equal(fit.Slope, '35.27 µm/°');
    assert.equal(fit.Offset, '−4.45 µm');
    assert.equal(fit['R²'], 'top 0.99 · bottom 0.95');
    assert.equal(fit.Extent, 'galvo −0.350° to +0.500°');
    assert.equal(fit['Z buffer'], '±25 µm');
    assert.equal(fit.Kept, '44 exposures · 3 plots');
    const no = Object.fromEntries(A.facts(REFUSED));
    assert.equal(no['Came to'], 'refused');
    assert.equal(no.Kept, '11 exposures · 0 plots');
    for (const k of ['Slope', 'Offset', 'R²', 'Extent', 'Z buffer']) assert.equal(k in no, false, k);
    assert.deepEqual(A.facts(null), []);
});

test('no label carries a unit: a label is drawn in capitals and µ would become M', () => {
    for (const [label] of A.facts(FIT)) assert.doesNotMatch(label, /µ|°/);
});

test('the newest run is first', () => {
    const got = A.newestFirst([FIT, REFUSED, { run: '20261108_004129', started_at: '2026-11-08T00:41:29' }]);
    assert.deepEqual(got.map(r => r.run), ['20261108_004606', '20261108_004435', '20261108_004129']);
    assert.deepEqual(A.newestFirst(undefined), []);
});
