/**
 * The Run tab — what the live session's acquisition is set to do, and what
 * the hardware is doing.
 *
 * It replaced the Operations tab. Its Overview drew an operation spine the
 * agent declared, a roster lens and a panel linking the session to plan
 * items; its Rules listed the run's reactive rules. The plan lives in
 * Projects now, a run is set up and started on Devices › Operate, a session
 * is filed from Sessions — what was left to say is this:
 *
 * - The acquisition, said once: the plan in its own sentence (the one Operate
 *   and a plan card say it in, AcquisitionPlan.describe), how the run is
 *   going, each embryo's part, the bath, and any rules on top of the plan.
 * - Below it, the session's hardware timeline (hardware-timeline.js), kept
 *   current as volumes and frames land.
 *
 * Data: /api/sessions/{id} (plan, run, embryos), /api/experiments/{id}/strategy
 * (cadence, rules, monitoring) and the timeline's own read of the session.
 */
const RunView = {
    _hw: null,          // this tab's hardware timeline
    _sid: null,
    _subscribed: false,
    _watching: false,

    _el(tag, cls, text) {
        const n = document.createElement(tag);
        if (cls) n.className = cls;
        if (text != null) n.textContent = text;
        return n;
    },

    _visible() {
        const tab = document.getElementById('experiment-content');
        return !tab || tab.classList.contains('active') || !!tab.closest('.atrium-window');
    },

    async init() {
        const root = document.getElementById('run-root');
        if (!root) return;
        const sid = (typeof SharedState !== 'undefined' && SharedState.get('sessionId')) || null;
        this._watch();
        if (!sid) {
            // The live session is known once the page has the server's state.
            root.replaceChildren(this._el('div', 'empty-tab', 'Waiting for the live session…'));
            this._sid = null;
            return;
        }
        if (this._sid !== sid || !root.querySelector('.run-timeline')) {
            this._sid = sid;
            const summary = this._el('section', 'run-summary');
            summary.setAttribute('aria-label', 'The acquisition');
            const host = this._el('div', 'hwt-host run-timeline');
            root.replaceChildren(summary, host);
            this._hw = this._hw || HardwareTimeline.create();
            await this._hw.mount(host, sid);
        }
        await this.summarise();
        this._subscribe();
    },

    // The live session's id arrives after the page loads, and changes when
    // another session is made live: either way the tab follows it.
    _watch() {
        if (this._watching || typeof SharedState === 'undefined') return;
        this._watching = true;
        SharedState.on('sessionId', id => {
            if (id && id !== this._sid && this._visible()) this.init();
        });
    },

    _subscribe() {
        if (this._subscribed || typeof ClientEventBus === 'undefined') return;
        this._subscribed = true;
        let hw = null, plan = null;
        // A volume or a frame: the timeline reads the session again, keeping
        // where it is zoomed, and the summary follows it.
        const hardware = () => {
            clearTimeout(hw);
            hw = setTimeout(async () => {
                if (!this._hw || !this._visible()) return;
                await this._hw.refresh();
                this.summarise();
            }, 1500);
        };
        // Anything that changes what the run is set to do.
        const changed = () => {
            clearTimeout(plan);
            plan = setTimeout(() => { if (this._visible()) this.summarise(); }, 800);
        };
        ['VOLUME_ACQUIRED', 'IMAGE_ACQUIRED'].forEach(e => ClientEventBus.on(e, hardware));
        ['ACQUISITION_STARTED', 'ACQUISITION_COMPLETED', 'ACQUISITION_STOPPED', 'ACQUISITION_FAILED',
            'EMBRYO_CADENCE_CHANGED', 'POWER_RAMP_STEP', 'TEMPERATURE_SETPOINT_CHANGED',
            'TEMP_PROTOCOL_STARTED', 'TEMP_PROTOCOL_COMPLETED', 'BURST_START', 'BURST_COMPLETE',
            'TRIGGER_FIRED'].forEach(e => ClientEventBus.on(e, changed));
    },

    async summarise() {
        const box = document.querySelector('#run-root .run-summary');
        const sid = this._sid;
        if (!box || !sid) return;
        const get = url => fetch(url).then(r => (r.ok ? r.json() : null)).catch(() => null);
        const [s, strategy] = await Promise.all([
            get(`/api/sessions/${encodeURIComponent(sid)}`),
            get(`/api/experiments/${encodeURIComponent(sid)}/strategy`),
        ]);
        if (sid !== this._sid || !box.isConnected) return;
        const seq = this._hw && this._hw.data ? this._hw.data() : null;
        const head = this._el('div', 'run-summary-head');
        head.append(this._el('h3', 'run-summary-title', 'The acquisition'));
        const run = s && (s.run || s.last_run);
        if (run && typeof ReviewApp !== 'undefined') {
            const line = this._el('div', 'run-summary-run');
            line.innerHTML = ReviewApp.renderRun(run);  // escapes what it says
            head.append(line);
        }
        const grid = this._el('dl', 'run-grid');
        for (const [term, ...values] of this.facts(s, strategy, seq)) {
            grid.append(this._el('dt', null, term));
            const dd = this._el('dd');
            values.flat().forEach(v => dd.append(typeof v === 'string' ? this._el('div', null, v) : v));
            grid.append(dd);
        }
        box.replaceChildren(head, grid);
    },

    // A cadence as the plan's sentence says one: "30 s", "2 min".
    _every(seconds) {
        const s = Math.round(seconds);
        return typeof AcquisitionPlan !== 'undefined' ? AcquisitionPlan.intervalWords(s) : `${s} s`;
    },

    // [term, value, ...] rows: what the run is set to do, in words.
    facts(s, strategy, seq) {
        const M = HardwareTimelineMath;
        const rows = [];
        const embryos = (s && s.embryos) || [];
        const labelOf = id => {
            const e = embryos.find(x => x.embryo_id === id);
            return (e && (e.nickname || e.embryo_id)) || id;
        };
        const acq = s && s.acquisition;
        let sentence = 'No acquisition plan was kept for this session: the hardware below is what it ran.';
        if (acq && typeof AcquisitionPlan !== 'undefined') {
            try {
                const ids = Array.isArray(acq.embryo_ids) && acq.embryo_ids.length
                    ? acq.embryo_ids : embryos.map(e => e.embryo_id);
                sentence = AcquisitionPlan.describe(AcquisitionPlan.fromStructure(acq), ids.map(id => ({ id, label: labelOf(id) })));
            } catch (err) {
                sentence = 'The plan kept for this session could not be read.';
            }
        }
        rows.push(['Plan', sentence]);

        // Each embryo's part. The run takes them in turn, each as it comes due
        // on its own cadence; how often it managed is measured, not asked.
        const vols = (seq && seq.volumes) || [];
        const sidesOf = id => [...new Set(vols.filter(v => v.embryo === id).map(v => v.side))].sort();
        const planned = ((strategy && strategy.embryos) || []);
        const parts = embryos.map(e => {
            const id = e.embryo_id;
            const st = planned.find(x => x.id === id) || {};
            const bits = [labelOf(id)];
            if (e.role || st.role) bits.push(e.role || st.role);
            const sides = sidesOf(id);
            if (sides.length) bits.push(sides.length > 1 ? `sides ${sides.join(' and ')}` : `side ${sides[0]}`);
            const phase = (st.phases || [])[(st.phases || []).length - 1];
            const cadence = phase ? phase.cadence_s : st.projected_cadence_s;
            if (cadence) bits.push(`every ${this._every(cadence)}`);
            const tp = st.tp_acquired ?? e.timepoints;
            if (tp != null) bits.push(`${tp} timepoint${tp === 1 ? '' : 's'}`);
            if (e.dose_budget_ms > 0) bits.push(`dose ${M.fmtDuration((e.dose_ms || 0) / 1000)} of ${M.fmtDuration(e.dose_budget_ms / 1000)}`);
            return bits.join(' · ');
        });
        if (parts.length) {
            const kept = this.keptRound(vols);
            const asked = (strategy && strategy.base_interval_s) || (acq && (acq.interval_seconds || acq.cadence_s));
            const how = kept && asked && kept > asked * 1.2
                ? `Taken in turn, each as it comes due: a round took ${this._every(kept)} for the ${this._every(asked)} asked.`
                : 'Taken in turn, each as it comes due.';
            rows.push(['Embryos', how, ...parts]);
        }

        // The bath: its setpoint over the session, from what was recorded.
        const temps = (seq && seq.temperature) || [];
        if (temps.length) {
            const steps = [];
            for (const [t, , sp] of temps) {
                if (sp == null || (steps.length && steps[steps.length - 1][1] === sp)) continue;
                steps.push([t, sp]);
            }
            const said = steps.map(([t, sp], i) => (i === 0
                ? `held at ${sp.toFixed(1)} °C`
                : `${sp.toFixed(1)} °C from ${M.fmtClock(Math.max(0, t - seq.t0))}`));
            const waters = temps.map(r => r[1]);
            const lo = Math.min(...waters), hi = Math.max(...waters);
            const water = hi - lo < 0.05 ? `water at ${lo.toFixed(1)} °C` : `water between ${lo.toFixed(1)} and ${hi.toFixed(1)} °C`;
            rows.push(['Bath', said.length ? said.join(', then ') : `${water}; no setpoint recorded`]);
        }

        // Rules on top of the plan, and only when there are any.
        const rules = [];
        for (const r of (strategy && strategy.triggers) || []) {
            const who = (r.applies_to || []).length ? ` (${r.applies_to.join(', ')})` : '';
            rules.push(`${r.label}${who}: when ${r.when_text}, ${r.then_text}`);
        }
        for (const m of (strategy && strategy.monitoring_modes) || []) {
            if (!m.name || m.name === 'idle') continue;
            rules.push(`Watching: ${m.name}${m.description ? ` — ${m.description}` : ''}`);
        }
        if (rules.length) rows.push(['Rules', ...rules]);
        return rows;
    },

    // The round the run kept: the median time between an embryo's volumes.
    keptRound(vols) {
        const by = {};
        for (const v of vols) {
            const t = v.lasers_on ?? v.scan_started;
            if (t != null) (by[`${v.embryo}/${v.side}`] ||= []).push(t);
        }
        const gaps = [];
        for (const ts of Object.values(by)) {
            ts.sort((a, b) => a - b);
            for (let i = 1; i < ts.length; i++) gaps.push(ts[i] - ts[i - 1]);
        }
        if (!gaps.length) return null;
        gaps.sort((a, b) => a - b);
        return gaps[Math.floor(gaps.length / 2)];
    },
};

if (typeof module !== 'undefined' && module.exports) module.exports = RunView;
