/**
 * Shell (ux_v2): the grouped left-rail nav (Now / Library / System) + the
 * session-context strip that replace the flat 8-tab bar.
 *
 * CRITICAL: the rail ROUTES THROUGH switchTab(tabId) for every reveal — it
 * never reimplements tab activation, so each tab's lazy-init side-effect
 * (HomeApp.init, EmbryosManager.clearDetectionBadge, CampaignsApp.init, …)
 * still fires. switchTab emits TAB_CHANGED, which keeps the rail's active
 * state in sync no matter who switched (rail, keyboard shortcut, home card,
 * hash route). No-ops unless body.ux-v2 is present (flag off → v1 untouched).
 */
const Shell = (() => {
    let railItems = [];

    const COLLAPSE_KEY = 'gently.rail.collapsed';
    // The same choice, kept apart for the Devices tab. There the rail starts
    // as the icon strip: the tab is the microscope's screen, and 156 px of
    // destination names is 156 px the picture and the instrument panels do
    // not get (at the desktop window's 1440 px it is the difference between
    // a frame beside its panels and a frame above them). The button still
    // opens it, and what is chosen there is remembered for there.
    const COLLAPSE_KEY_DEVICES = 'gently.rail.collapsed.devices';
    const WIDE_TABS = ['devices'];
    const keyFor = tab => (WIDE_TABS.includes(tab) ? COLLAPSE_KEY_DEVICES : COLLAPSE_KEY);
    const startsCollapsed = tab => WIDE_TABS.includes(tab);

    function setActive(tabName) {
        railItems.forEach(b => b.classList.toggle('active', b.dataset.tab === tabName));
    }

    // The rail collapses to an icon strip. The choice is per browser and
    // survives reloads: an operator who wants the width for the camera should
    // not have to reclaim it every session. localStorage can throw (private
    // window, blocked site data), so every access is guarded and the rail
    // simply stays expanded if it cannot be read.
    function applyCollapsed(on) {
        document.body.classList.toggle('rail-collapsed', on);
        const btn = document.getElementById('v2-rail-collapse');
        if (btn) {
            btn.setAttribute('aria-expanded', String(!on));
            btn.title = on ? 'Expand the sidebar' : 'Collapse the sidebar';
        }
    }

    // What the rail is on this tab: what was last chosen for it, or how it
    // starts there.
    function collapsedFor(tab) {
        let saved = null;
        try { saved = localStorage.getItem(keyFor(tab)); } catch (e) { /* as it starts */ }
        return saved === '1' || (saved == null && startsCollapsed(tab));
    }

    function initCollapse() {
        const btn = document.getElementById('v2-rail-collapse');
        if (!btn) return;
        applyCollapsed(collapsedFor(currentTab()));
        btn.addEventListener('click', () => {
            const on = !document.body.classList.contains('rail-collapsed');
            applyCollapsed(on);
            try { localStorage.setItem(keyFor(currentTab()), on ? '1' : '0'); } catch (e) { /* not fatal */ }
        });
    }

    function currentTab() {
        const active = document.querySelector('.tab.active');
        return (active && active.dataset.tab) ||
            (typeof state !== 'undefined' && state.tab) || 'home';
    }

    let _rosterCount = null;

    // ── The run, as a state of the whole interface ─────────────────────────
    // A camera's REC light is visible from across the room. A timelapse is
    // the longest thing this app does and until now nothing outside the
    // Acquisition pane said one was running: the rail, the strip and the
    // header looked the same idle, setting up, and forty rounds in. The run
    // becomes a state on <body> — data-run="running" | "paused" | "idle" —
    // that any surface can style from. Driven by the run's events, with a
    // slow status poll as the fallback for a page that opened mid-run.
    let _run = { status: 'idle', volumes: 0, nextIn: null };
    let _runPoll = null;

    function applyRun(st) {
        const status = st && (st.status === 'running' || st.status === 'paused') ? st.status : 'idle';
        _run = {
            status,
            volumes: (st && st.total_timepoints) || 0,
            nextIn: st && st.seconds_until_next_round != null ? st.seconds_until_next_round : null,
            bfFrames: st && st.bf ? (st.bf.frames || 0) : null,
        };
        document.body.dataset.run = status;
        renderStrip();
    }

    async function pollRun() {
        try {
            const r = await fetch('/api/devices/timelapse/status');
            if (!r.ok) { applyRun(null); return; }
            applyRun(await r.json());
        } catch (_) { applyRun(null); }
    }

    function runWords() {
        if (_run.status === 'idle') return '';
        const bits = [_run.status.toUpperCase()];
        if (_run.volumes) bits.push(`${_run.volumes} volume${_run.volumes === 1 ? '' : 's'}`);
        if (_run.status === 'running' && _run.nextIn != null) {
            const s = _run.nextIn;
            bits.push(`next ${s < 1 ? 'now' : s < 90 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`}`);
        }
        if (_run.bfFrames) bits.push(`brightfield ${_run.bfFrames}`);
        return bits.join(' · ') + ' · ';
    }

    function renderStrip(status) {
        const el = document.getElementById('v2-strip-status');
        if (!el) return;
        const s = status || (typeof ConnectionStatus !== 'undefined' ? ConnectionStatus.get() : {});
        // The roster, when it has spoken; before that, the image store's list
        // (embryos that have images), which is the number this used to show
        // always — "2 embryos" for a roster of four, until a hard refresh.
        const n = _rosterCount != null ? _rosterCount
            : ((typeof state !== 'undefined' && Array.isArray(state.embryos)) ? state.embryos.length : 0);
        const conn = s.gentlyConnected ? (s.microscopeConnected ? 'Connected' : 'Online') : 'Offline';
        el.textContent = `${runWords()}${n} embryo${n === 1 ? '' : 's'} · ${conn}`;
        // The Devices tab does not draw this strip, so its toolbar says the run.
        const tb = document.getElementById('devices-run');
        if (tb) {
            const words = runWords().replace(/ · $/, '');
            tb.textContent = words;
            tb.hidden = !words;
        }
        renderRunControls();
    }

    // ── The run, held from wherever it is said ─────────────────────────────
    // Pause and Stop were on the Acquisition surface alone, which has no
    // picture, while the Embryos tab, where a run is watched, could do
    // neither (docs/workspace/calibration-and-acquisition.md, A6). Any
    // element with `data-run-control` is one of the run's controls: "pause"
    // (which is Resume while paused), "stop", and "plan" (the way to where a
    // run is planned, shown while none is going). Drawn here from the run's
    // state, and answered here.
    function renderRunControls() {
        const going = _run.status !== 'idle';
        document.querySelectorAll('[data-run-control]').forEach(b => {
            const what = b.dataset.runControl;
            if (what === 'plan') { b.hidden = going; return; }
            b.hidden = !going;
            if (what === 'pause' && !b.dataset.busy) b.textContent = _run.status === 'paused' ? 'Resume' : 'Pause';
        });
    }

    function say(message, level) {
        if (typeof showGentlyToast === 'function') showGentlyToast(message, null, null, 4000, level || 'success');
    }

    async function post(url, body) {
        const r = await fetch(url, {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}),
        });
        const d = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : `${r.status}`);
        return d;
    }

    async function runControl(what, b) {
        if (what === 'plan') {
            if (typeof switchTab === 'function') switchTab('devices');
            if (typeof DevicesManager !== 'undefined' && DevicesManager.switchView) DevicesManager.switchView('operate');
            if (typeof OperateManager !== 'undefined' && OperateManager.roster) OperateManager.roster.goTo('acquire');
            return;
        }
        if (_run.status === 'idle' || (b && b.dataset.busy)) return;
        // Stopping a night's run is asked about; pausing it is not.
        if (what === 'stop' && !window.confirm('Stop the run?')) return;
        const paused = _run.status === 'paused';
        if (b) { b.dataset.busy = '1'; b.disabled = true; }
        try {
            if (what === 'stop') {
                await post('/api/devices/timelapse/stop', { reason: 'operator' });
                say('Run stopped');
            } else {
                const d = await post(paused ? '/api/devices/timelapse/resume' : '/api/devices/timelapse/pause');
                say(paused ? (d && d.continued ? 'Run carried on from its checkpoint' : 'Resumed') : 'Paused');
            }
        } catch (e) {
            say(`${what === 'stop' ? 'Not stopped' : paused ? 'Not resumed' : 'Not paused'} (${e.message})`, 'error');
        } finally {
            if (b) { delete b.dataset.busy; b.disabled = false; }
            pollRun();
        }
    }

    function init() {
        if (!document.body.classList.contains('ux-v2')) return;  // flag off → no-op

        railItems = Array.from(document.querySelectorAll('.v2-nav-item'));
        railItems.forEach(btn => btn.addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab(btn.dataset.tab);
        }));
        setActive(currentTab());

        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('TAB_CHANGED', (tabName) => {
                setActive(tabName);
                applyCollapsed(collapsedFor(tabName));
            });
            ClientEventBus.on('CONNECTION_STATUS', (s) => renderStrip(s));
            ClientEventBus.on('EMBRYOS_UPDATE', (p) => {
                _rosterCount = (p && Array.isArray(p.embryos)) ? p.embryos.length : null;
                renderStrip();
            });
            // The moments a run changes state, then the numbers by poll.
            ClientEventBus.on('ACQUISITION_STARTED', () => { applyRun({ status: 'running' }); pollRun(); });
            ['ACQUISITION_COMPLETED', 'ACQUISITION_STOPPED', 'ACQUISITION_FAILED']
                .forEach(ev => ClientEventBus.on(ev, () => applyRun(null)));
            ClientEventBus.on('TIMELAPSE_STATE', (st) => applyRun(st));
            ClientEventBus.on('VOLUME_ACQUIRED', () => pollRun());
            clearInterval(_runPoll);
            _runPoll = setInterval(pollRun, 10000);
            pollRun();
            // Embryo count lives in state.embryos; re-render the strip whenever it
            // changes (including the initial bootstrap) so the header doesn't sit
            // at the pre-load 0.
            ClientEventBus.on('EMBRYOS_UPDATE', () => renderStrip());
        }

        initCollapse();

        // One listener for the run's controls, wherever a surface puts them.
        document.addEventListener('click', e => {
            const b = e.target.closest('[data-run-control]');
            if (b) runControl(b.dataset.runControl, b);
        });

        renderStrip();
    }

    document.addEventListener('DOMContentLoaded', init);
    return {};
})();
