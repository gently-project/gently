/**
 * Gently's clock. Times are kept in UTC; every time the page shows is shown
 * in the microscope's zone, which the server writes into
 * <meta name="gently-time-zone">: Settings › Views › Time zone if set, else
 * the zone of the computer Gently runs on. So a page opened anywhere says the
 * times the people at the rig saw. Empty (neither known): this browser's own.
 *
 * Two kinds of time reach the page:
 * - one written with its zone (UTC's Z, or an offset) is a moment, and is
 *   shown in the set zone;
 * - one the rig wrote with no zone is its own wall clock. It is read in the
 *   set zone, not this browser's, so its digits stand.
 *
 * Numbers are milliseconds, as a Date takes them.
 *
 * Classic script (window global `GentlyTime`), loaded before utils.js; also
 * CJS-exported for node tests (tests/js/gently-time.test.mjs).
 */
const GentlyTime = (() => {
    const fromPage = () => {
        if (typeof document === 'undefined') return '';
        const m = document.querySelector('meta[name="gently-time-zone"]');
        return m ? (m.getAttribute('content') || '').trim() : '';
    };

    function make(zoneName) {
        let zone = zoneName || undefined;
        if (zone) {
            try {
                new Intl.DateTimeFormat('en-GB', { timeZone: zone });
            } catch (err) {
                console.warn(`Time zone "${zone}" is not one this browser knows; showing times in its own zone`);
                zone = undefined;
            }
        }
        const made = new Map();
        const fmt = (opts, locale) => {
            const key = `${locale || ''}|${JSON.stringify(opts || {})}`;
            if (!made.has(key)) made.set(key, new Intl.DateTimeFormat(locale, { ...(opts || {}), timeZone: zone }));
            return made.get(key);
        };
        const PARTS = { year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' };

        // The zone's offset from UTC at a moment, in minutes.
        function offsetAt(ms) {
            const p = {};
            for (const x of fmt(PARTS, 'en-GB').formatToParts(new Date(ms))) p[x.type] = x.value;
            const wall = Date.UTC(+p.year, +p.month - 1, +p.day, +p.hour % 24, +p.minute, +p.second);
            return Math.round((wall - Math.floor(ms / 1000) * 1000) / 60000);
        }

        // Any time the page is given, as a Date, or null.
        function toDate(v) {
            if (v == null || v === '') return null;
            if (v instanceof Date) return isNaN(v) ? null : v;
            if (typeof v === 'number') return Number.isFinite(v) ? new Date(v) : null;
            const s = String(v).trim();
            const m = s.match(/^(\d{4})-(\d\d)-(\d\d)(?:[T ](\d\d):(\d\d)(?::(\d\d)(?:\.(\d+))?)?)?$/);
            if (!m) {
                // With its zone, or a form only the browser reads: a moment.
                const d = new Date(s);
                return isNaN(d) ? null : d;
            }
            // No zone: the rig's wall clock, read in the set zone. The offset
            // is asked twice, so a wall time beside a clock change finds its own.
            const wall = Date.UTC(+m[1], +m[2] - 1, +m[3], +(m[4] || 0), +(m[5] || 0), +(m[6] || 0),
                m[7] ? Math.round(Number(`0.${m[7]}`) * 1000) : 0);
            let t = wall - offsetAt(wall) * 60000;
            t = wall - offsetAt(t) * 60000;
            return new Date(t);
        }

        // A time, in the set zone, in whatever form a view asks for.
        const format = (v, opts, locale) => {
            const d = toDate(v);
            return d ? fmt(opts, locale).format(d) : '';
        };
        const clock = v => format(v, { hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23' }, 'en-GB');
        const zoneLabel = v => {
            const d = toDate(v) || new Date();
            const part = fmt({ timeZoneName: 'short' }, 'en-GB').formatToParts(d).find(x => x.type === 'timeZoneName');
            return part ? part.value : '';
        };
        return { zone, toDate, format, clock, zoneLabel, offsetAt };
    }

    return { ...make(fromPage()), make };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = GentlyTime;
