/**
 * Unit tests for the slider-and-number row's arithmetic.
 *
 *   node --test tests/js/numrow.test.mjs
 *
 * "The adjustable parameters like laser power can also have a way to enter
 * numbers into a text box, as sometimes biologists love that." A typed number
 * is a hardware setpoint on its way to a laser, a galvo or a piezo, so what a
 * string settles to is worth pinning: what counts as a number, what happens
 * outside the limits, and that what is sent is what is shown.
 *
 * bind() is the DOM around this and is exercised in the browser.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const N = require('../../gently/ui/web/static/js/panels/numrow.js');

test('parse: plain numbers', () => {
    assert.equal(N.parse('3.1'), 3.1);
    assert.equal(N.parse(' 12 '), 12);
    assert.equal(N.parse('.5'), 0.5);
    assert.equal(N.parse('5.'), 5);
    assert.equal(N.parse('+4'), 4);
    assert.equal(N.parse('-0.75'), -0.75);
});

test('parse: the minus the page itself prints, and a decimal comma', () => {
    // The limits beside the sheet's lines are typeset with U+2212; a value
    // copied from there must come back as a number.
    assert.equal(N.parse('−0.75'), -0.75);
    assert.equal(N.parse('3,1'), 3.1);
});

test('parse: anything else is not a number, rather than part of one', () => {
    for (const bad of ['', '  ', 'abc', '3.1.2', '12abc', '1e3', '--4', '0x10', '—', null, undefined, '3 1']) {
        assert.equal(N.parse(bad), null, String(bad));
    }
});

test('settle: inside the limits a number is itself, at the decimals shown', () => {
    assert.deepEqual(N.settle('3.14159', 0, 100, 1), { value: 3.1, clamped: false });
    assert.deepEqual(N.settle('35', 1, 100, 0), { value: 35, clamped: false });
    assert.deepEqual(N.settle('12.6', 1, 100, 0), { value: 13, clamped: false });
});

test('settle: outside the limits it is pulled inside, and says so', () => {
    // 488 nm is held to 2-6 % on this rig.
    assert.deepEqual(N.settle('12', 2, 6, 1), { value: 6, clamped: true });
    assert.deepEqual(N.settle('0', 2, 6, 1), { value: 2, clamped: true });
    assert.deepEqual(N.settle('-99', -4, 4, 2), { value: -4, clamped: true });
});

test('settle: the limits themselves are inside', () => {
    assert.deepEqual(N.settle('6', 2, 6, 1), { value: 6, clamped: false });
    assert.deepEqual(N.settle('2.0', 2, 6, 1), { value: 2, clamped: false });
});

test('settle: not a number settles to nothing, so the caller puts back what was there', () => {
    assert.equal(N.settle('', 0, 100, 1), null);
    assert.equal(N.settle('five', 0, 100, 1), null);
});

test('stepped: one step, ten with Shift, never past a limit', () => {
    assert.equal(N.stepped(3.1, 0.1, 1, false, 2, 6, 1), 3.2);
    assert.equal(N.stepped(3.1, 0.1, -1, false, 2, 6, 1), 3);
    assert.equal(N.stepped(3.1, 0.1, 1, true, 2, 6, 1), 4.1);
    assert.equal(N.stepped(5.95, 0.1, 1, true, 2, 6, 1), 6);
    assert.equal(N.stepped(2, 0.1, -1, false, 2, 6, 1), 2);
});

test('stepped: floating point does not leak into the value sent', () => {
    // 0.1 + 0.2 is the classic; a power of 0.30000000000000004 % must not be
    // what reaches the device layer, or what is read back never matches.
    assert.equal(N.stepped(0.2, 0.1, 1, false, 0, 100, 1), 0.3);
    assert.equal(N.stepped(0.07, 0.01, 1, false, -4, 4, 2), 0.08);
});

test('stepped: a missing step is one', () => {
    assert.equal(N.stepped(10, '', 1, false, 1, 100, 0), 11);
    assert.equal(N.stepped(10, undefined, -1, true, 1, 100, 0), 1);
});

test('format: the decimals the row shows', () => {
    assert.equal(N.format(3, 1), '3.0');
    assert.equal(N.format(0.75, 2), '0.75');
    assert.equal(N.format(35, 0), '35');
});
