/**
 * Before a run starts — what stands in its way, said where the press is.
 *
 * The page knew, and did not say. With three embryos registered and none
 * calibrated the plan's sentence read "SPIM volumes of 3 embryos" with no
 * problem under it, and the press answered "Start failed (409 — not
 * calibrated: embryo_2 … or pass allow_uncalibrated=true to acquire
 * anyway...)". Nothing said what a run would write, either: the form opens at
 * every 30 s for 16 h, which for three embryos is about 576 GB, and "every
 * 30 s" holds seven embryos and no more (docs/workspace/
 * calibration-and-acquisition.md, A4 and A5).
 *
 * So the lines an operator leaving for the night needs: who is in the run,
 * whether each has a fit, what the lasers will be, whether a round fits the
 * cadence, what it will write against what is free, where the head is. Each
 * is derived from what the page has already read, each says its fix, and the
 * ones that would refuse the run are counted onto Start.
 *
 * Pure. Nothing here touches the DOM or the network: operate.js gathers what
 * is known and draws what comes back.
 */
const RunPreflight = (() => {
    'use strict';

    // What one embryo costs a round beyond the scan itself: the move to it,
    // the settle, the arming, the save. Measured from this rig's own records,
    // the time from one embryo's volume to the next within a round: 4.0 s at
    // 50 slices and 10 ms (median of 6,919 pairs), 3.3 s at 5 ms.
    // shortcut: one constant for every rig and every plan; read it from the
    // session's own rounds once a run has some.
    const OVERHEAD_S = 3.5;

    // A saved volume's frame on this rig, in bytes: 512 × 2048 pixels of 16
    // bits. The caller passes the real figure when it has read one.
    const SLICE_BYTES = 512 * 2048 * 2;

    const DEFAULT_SLICES = 50;
    const DEFAULT_EXPOSURE_MS = 10;

    const num = v => (v == null || v === '' || !Number.isFinite(Number(v)) ? null : Number(v));

    /**
     * What a plan costs: an embryo, a round, the cadence that will be kept,
     * and the whole run where it has an end that can be counted.
     *
     * The cadence kept is not the cadence asked. Each embryo's next volume is
     * scheduled from when its last one finished (`_reschedule(from_now=True)`
     * in the orchestrator), so an interval is the interval plus one
     * acquisition: 303 s kept for 300 asked, 33.5 s for 30. And when a round
     * takes longer than the interval, the round is the cadence.
     *
     * @param plan   from AcquisitionPlan.fromForm()
     * @param n      embryos in the run
     * @param opts   {slices, exposureMs} — what the embryos hold, for a plan
     *               that leaves them alone; {sliceBytes, overheadS}
     */
    function estimate(plan, n, opts) {
        const o = opts || {};
        const volumes = plan.spim.enabled !== false;
        const slices = num(plan.spim.slices) || num(o.slices) || DEFAULT_SLICES;
        const exposureMs = num(plan.spim.exposureMs) || num(o.exposureMs) || DEFAULT_EXPOSURE_MS;
        const asked = plan.intervalSeconds;
        const perEmbryoS = (num(o.overheadS) != null ? num(o.overheadS) : OVERHEAD_S) + slices * exposureMs / 1000;
        const roundS = volumes ? n * perEmbryoS : 0;
        const keptS = !volumes || !n ? asked : Math.max(asked + perEmbryoS, roundS);
        const kind = plan.stop.kind, value = num(plan.stop.value);
        const rounds = kind === 'duration' && value > 0 ? Math.floor(value * 3600 / keptS)
            : kind === 'timepoints' && value >= 1 ? Math.round(value) : null;
        const volumeBytes = slices * (num(o.sliceBytes) || SLICE_BYTES);
        return {
            volumes, n, slices, exposureMs, asked, perEmbryoS, roundS, keptS, rounds,
            // How many embryos the asked cadence holds before a round overruns it.
            holds: Math.max(0, Math.floor(asked / perEmbryoS)),
            count: volumes && rounds != null ? rounds * n : null,
            bytes: volumes && rounds != null ? rounds * n * volumeBytes : null,
            bytesPerHour: volumes && n ? 3600 / keptS * n * volumeBytes : 0,
        };
    }

    /** "44 s", "5 min 4 s", "2 h 10 min" — a length of time, to the precision it is known. */
    function span(seconds) {
        const s = Math.max(0, Math.round(seconds));
        if (s < 90) return `${s} s`;
        if (s < 3600) return s % 60 ? `${Math.floor(s / 60)} min ${s % 60} s` : `${s / 60} min`;
        const h = Math.floor(s / 3600), m = Math.round((s % 3600) / 60);
        return m ? `${h} h ${m} min` : `${h} h`;
    }

    /** Bytes as a person says them: "218 GB", "1.5 TB". Decimal, as a disk is sold. */
    function size(bytes) {
        const gb = bytes / 1e9;
        if (gb >= 1000) return `${(gb / 1000).toFixed(1)} TB`;
        if (gb >= 10) return `${Math.round(gb)} GB`;
        if (gb >= 1) return `${gb.toFixed(1)} GB`;
        return `${Math.max(1, Math.round(bytes / 1e6))} MB`;
    }

    const count = n => Number(n).toLocaleString('en-US');
    const plural = (n, one, many) => (n === 1 ? one : many);

    /**
     * The cadence that will be kept, said beside the one asked. Empty when
     * they are the same to the second, or when the run takes no volumes.
     */
    function keptWords(est) {
        if (!est.volumes || !est.n) return '';
        if (Math.round(est.keptS) === Math.round(est.asked)) return '';
        return `kept as about ${span(est.keptS)}`;
    }

    /**
     * The lines. Each is {kind, text, fix?}: kind is 'ok', 'warn' (the run
     * will start, and this is worth knowing first) or 'no' (the run will be
     * refused, or will not do what was asked). `fix` names what would clear
     * it: {action, label}, for the page to wire.
     *
     * @param ctx
     *   plan        AcquisitionPlan.fromForm()
     *   est         estimate(plan, subjects.length, …)
     *   subjects    [{id, label, calibrated, r2}] — the embryos the run images
     *   references  how many embryos are marked as references
     *   notSelected how many subjects the "Selected" scope leaves out
     *   problems    AcquisitionPlan.validate()'s sentences
     *   routed      [488, 561] | null — the lines the rig routes now; null unread
     *   powers      {488: 3.1} — each line's power now, where read
     *   limits      {488: {min, max}} | null
     *   head        {um, gotoMin} | null
     *   freeBytes   number | null
     *   refs        {have} | null — the overview's dark and flat
     *   lowR2       below this a fit is called poor
     */
    function lines(ctx) {
        const out = [];
        const add = (kind, text, fix) => out.push(fix ? { kind, text, fix } : { kind, text });
        const plan = ctx.plan, est = ctx.est;
        const subjects = ctx.subjects || [];
        const n = subjects.length;
        const volumes = plan.spim.enabled !== false;
        const asked = AcquisitionPlan.intervalWords(plan.intervalSeconds);

        // ── who ──
        if (volumes) {
            const aside = [];
            if (ctx.references) aside.push(`${ctx.references} ${plural(ctx.references, 'reference', 'references')} left out`);
            if (ctx.notSelected) aside.push(`${ctx.notSelected} not selected`);
            if (n) add('ok', `${n} ${plural(n, 'embryo', 'embryos')} in the run${aside.length ? '; ' + aside.join('; ') : ''}.`);
        } else {
            add('ok', 'A brightfield run: no embryo is imaged, and no calibration is asked for.');
        }

        // ── what the plan itself gets wrong: the sentences Start used to toast ──
        (ctx.problems || []).forEach(p => add('no', p));

        if (volumes && n) {
            // ── a fit each ──
            const without = subjects.filter(s => !s.calibrated);
            if (without.length) {
                const k = without.length;
                const fixes = [{ action: 'calibrate', label: `Calibrate ${k === 1 ? 'it' : `the ${k}`}` }];
                if (k < n) fixes.push({ action: 'without', label: `Run without ${plural(k, 'it', 'them')}` });
                add('no', `${k} of ${n} ${plural(k, 'is', 'are')} not calibrated: ${without.map(s => s.label).join(', ')}. `
                    + `A run refuses ${plural(k, 'it', 'them')}.`, fixes);
            } else {
                add('ok', n === 1 ? 'The embryo has a fit.' : 'Every embryo in the run has a fit.');
            }
            const low = ctx.lowR2 != null ? subjects.filter(s => s.calibrated && s.r2 != null && s.r2 < ctx.lowR2) : [];
            if (low.length) {
                add('warn', `${plural(low.length, 'A poor fit', 'Poor fits')}: `
                    + low.map(s => `${s.label} (R² ${s.r2.toFixed(2)})`).join(', ') + '.');
            }

            // ── the light the volumes are taken in ──
            const named = !!plan.spim.laserConfig;
            const routed = named ? AcquisitionPlan.linesOf(plan.spim.laserConfig) : ctx.routed;
            if (routed && !routed.length) {
                add('warn', named ? `${plan.spim.laserConfig} routes no line: the volumes would be dark.`
                    : 'Lasers as they are, and no line is routed: the volumes would be dark.');
            } else if (routed) {
                const said = routed.map(wl => {
                    const set = (plan.spim.laserPowers || {})[wl];
                    const pct = set != null ? set : (ctx.powers || {})[wl];
                    return pct != null && Number.isFinite(Number(pct)) ? `${wl} at ${Number(pct)} %` : `${wl} nm`;
                });
                add('ok', `${said.join(', ')}${named ? '' : ', as the rig has them now'}.`);
            }

            // ── a round against the cadence ──
            const round = span(est.roundS);
            if (est.roundS > est.asked) {
                add('warn', `A round takes about ${round} (${n} × ${est.perEmbryoS.toFixed(1)} s): every ${asked} cannot be kept. `
                    + `Every ${asked} holds ${est.holds} ${plural(est.holds, 'embryo', 'embryos')}.`);
            } else {
                add('ok', `A round takes about ${round} of the ${asked} between rounds.`);
            }

            // ── what it writes ──
            const free = ctx.freeBytes != null && Number.isFinite(ctx.freeBytes) ? ctx.freeBytes : null;
            const freeSaid = free != null ? `; ${size(free)} free` : '';
            if (est.bytes != null) {
                const kind = free != null && est.bytes > free ? 'no' : free != null && est.bytes > free / 2 ? 'warn' : 'ok';
                add(kind, `About ${count(est.count)} ${plural(est.count, 'volume', 'volumes')}, ${size(est.bytes)}${freeSaid}.`
                    + (kind === 'no' ? ' The disk would fill before the run ends.' : ''));
            } else {
                const hours = free != null && est.bytesPerHour > 0 ? free / est.bytesPerHour : null;
                add(hours != null && hours < 24 ? 'warn' : 'ok',
                    `About ${size(est.bytesPerHour)} an hour, with no end set${freeSaid}`
                    + (hours != null ? `: room for about ${span(hours * 3600)}.` : '.'));
            }

            // ── where the head is ──
            const head = ctx.head;
            if (head && Number.isFinite(head.um)) {
                const at = `${count(Math.round(head.um * 10) / 10)} µm`;
                if (Number.isFinite(head.gotoMin) && head.um > head.gotoMin) {
                    add('warn', `The head is at ${at}, off the sample.`,
                        [{ action: 'head', label: `To ${count(head.gotoMin)} µm` }]);
                } else {
                    add('ok', `The head is at ${at}.`);
                }
            }
        }

        // ── the overview's dark and flat ──
        if (plan.bf.enabled && ctx.refs && ctx.refs.have === false) {
            add('warn', `${volumes ? 'Overview' : 'Brightfield'}: no dark and flat yet, so the frames cannot be corrected.`,
                [{ action: 'overview', label: 'Set up on Scope' }]);
        }
        return out;
    }

    /** What Start wears: how many lines would refuse the run. */
    function verdict(all) {
        const blocked = (all || []).filter(l => l.kind === 'no').length;
        return { blocked, says: blocked ? `${blocked} ${plural(blocked, 'thing', 'things')} in the way` : '' };
    }

    /**
     * A calibration was refused with nothing to see. The server cannot tell
     * an unlit sheet from a raised head from a stage that is somewhere else,
     * so it advises checking all three. The page can read all three: what it
     * can see to be wrong, and the panel that puts it right. Nothing it
     * cannot read is guessed at.
     *
     *   emitting   true | false | null   a laser line is emitting (null: not read)
     *   ledOpen    boolean               the LED is open
     *   head       {um, gotoMin} | null  as in `lines`
     *   atEmbryo   true | false | null   the stage is at the selected embryo
     *
     * @returns {Array<{panel: 'light'|'head'|'stage', says: string}>}
     */
    function calibrationPoints(ctx) {
        const c = ctx || {};
        const out = [];
        if (c.emitting === false) out.push({ panel: 'light', says: 'No laser line is emitting.' });
        else if (c.ledOpen) out.push({ panel: 'light', says: 'The LED is open.' });
        const head = c.head;
        if (head && Number.isFinite(head.um) && Number.isFinite(head.gotoMin) && head.um > head.gotoMin) {
            out.push({ panel: 'head', says: `The head is at ${count(Math.round(head.um * 10) / 10)} µm, off the sample.` });
        }
        if (c.atEmbryo === false) out.push({ panel: 'stage', says: 'The stage is not at this embryo.' });
        return out;
    }

    return { OVERHEAD_S, SLICE_BYTES, estimate, span, size, keptWords, lines, verdict, calibrationPoints };
})();

if (typeof module !== 'undefined' && module.exports) module.exports = RunPreflight;
