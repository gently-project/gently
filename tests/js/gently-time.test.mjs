/**
 * Gently's clock: times kept in UTC, shown in the zone the microscope is set to.
 *
 *   node --test tests/js/gently-time.test.mjs
 *
 * Two kinds of time reach the page. One written with its zone (UTC's Z, or an
 * offset) is a moment, shown in the set zone. One the rig wrote with no zone
 * is its own wall clock: read in the set zone, so its digits stand wherever
 * the page is opened. A browser in another zone used to show both in its own.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';

const require = createRequire(import.meta.url);
const T = require('../../gently/ui/web/static/js/gently-time.js');
const HM = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };

test('a moment with its zone is shown in the zone the rig is set to', () => {
    const ny = T.make('America/New_York');
    assert.equal(ny.format('2026-11-14T23:46:40Z', HM, 'en-GB'), '18:46');
    assert.equal(ny.format('2026-11-14T23:46:40+00:00', HM, 'en-GB'), '18:46');
    const cph = T.make('Europe/Copenhagen');
    assert.equal(cph.clock(Date.UTC(2026, 10, 14, 23, 46, 40)), '00:46:40');
});

test('a time the rig wrote with no zone is its wall clock: the digits stand', () => {
    const ny = T.make('America/New_York');
    assert.equal(ny.format('2026-11-14T18:46:50', { ...HM, second: '2-digit' }, 'en-GB'), '18:46:50');
    assert.equal(ny.toDate('2026-11-14T18:46:50').toISOString(), '2026-11-14T23:46:50.000Z');
    assert.equal(ny.toDate('2026-11-14T18:46:50.250000').toISOString(), '2026-11-14T23:46:50.250Z');
});

test('a wall clock on either side of a clock change reads at its own offset', () => {
    const cph = T.make('Europe/Copenhagen');
    assert.equal(cph.toDate('2026-03-28T23:00:00').toISOString(), '2026-03-28T22:00:00.000Z');  // CET
    assert.equal(cph.toDate('2026-03-29T03:30:00').toISOString(), '2026-03-29T01:30:00.000Z');  // CEST
});

test('numbers are milliseconds, as a Date takes them; a Date is itself', () => {
    const utc = T.make('UTC');
    assert.equal(utc.clock(Date.UTC(2026, 10, 14, 23, 46, 40)), '23:46:40');
    assert.equal(utc.clock(new Date(Date.UTC(2026, 10, 14, 23, 46, 40))), '23:46:40');
});

test('nothing, or nonsense, is shown as nothing', () => {
    const utc = T.make('UTC');
    assert.equal(utc.format(null, HM), '');
    assert.equal(utc.format('', HM), '');
    assert.equal(utc.format('not a time', HM), '');
    assert.equal(utc.toDate('not a time'), null);
});

test('a zone the browser does not know is said, and the browser\'s zone stands in', () => {
    const warn = console.warn;
    const said = [];
    console.warn = (...a) => said.push(a.join(' '));
    try {
        assert.equal(T.make('Mars/Olympus_Mons').zone, undefined);
    } finally {
        console.warn = warn;
    }
    assert.ok(said.some(s => s.includes('Mars/Olympus_Mons')));
});

test('the zone has a short name to show beside a time', () => {
    assert.equal(T.make('Europe/Copenhagen').zoneLabel(Date.UTC(2026, 10, 14)), 'CET');
    assert.equal(T.make('Europe/Copenhagen').zoneLabel(Date.UTC(2026, 6, 14)), 'CEST');
});
