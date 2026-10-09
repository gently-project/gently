/**
 * The Fields panel's one piece of arithmetic: which field the stage is at.
 *
 *   node --test tests/js/fields-panel.test.mjs
 *
 * (Pass the file, not the directory — see operate-math.test.mjs.)
 *
 * The row that says "stage here" and the Add button that refuses a duplicate
 * both turn on this. An unknown stage position is not at any field: the
 * answer has to be "no", never a guess, the same rule as the SPIM caption.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const P = require('../../gently/ui/web/static/js/panels/fields.js');

const FIELDS = [{ x: -500, y: -400 }, { x: 900, y: -380 }];

test('the stage is at the field it is within tolerance of', () => {
    assert.equal(P.hereIndex(FIELDS, { x: -500, y: -400 }), 0);
    assert.equal(P.hereIndex(FIELDS, { x: 900 + P.HERE_UM - 1, y: -380 }), 1);
    assert.equal(P.hereIndex(FIELDS, { x: 0, y: 0 }), -1);
});

test('an unknown position is at no field', () => {
    assert.equal(P.hereIndex(FIELDS, null), -1);
    assert.equal(P.hereIndex(FIELDS, { x: NaN, y: 0 }), -1);
    assert.equal(P.hereIndex([], { x: -500, y: -400 }), -1);
});

test('the tolerance is the one the SPIM caption uses', () => {
    // A frame is on the order of a millimetre: fifty microns is the same picture.
    assert.equal(P.HERE_UM, 50);
});
