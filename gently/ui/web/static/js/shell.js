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

    function initCollapse() {
        const btn = document.getElementById('v2-rail-collapse');
        if (!btn) return;
        let saved = false;
        try { saved = localStorage.getItem(COLLAPSE_KEY) === '1'; } catch (e) { /* stays expanded */ }
        applyCollapsed(saved);
        btn.addEventListener('click', () => {
            const on = !document.body.classList.contains('rail-collapsed');
            applyCollapsed(on);
            try { localStorage.setItem(COLLAPSE_KEY, on ? '1' : '0'); } catch (e) { /* not fatal */ }
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
            dicFrames: st && st.dic ? (st.dic.frames || 0) : null,
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
        if (_run.dicFrames) bits.push(`DIC ${_run.dicFrames}`);
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
    }

    function init() {
        if (!document.body.classList.contains('ux-v2')) return;  // flag off → no-op

        railItems = Array.from(document.querySelectorAll('.v2-nav-item'));
        railItems.forEach(btn => btn.addEventListener('click', () => {
            if (typeof switchTab === 'function') switchTab(btn.dataset.tab);
        }));
        setActive(currentTab());

        if (typeof ClientEventBus !== 'undefined') {
            ClientEventBus.on('TAB_CHANGED', (tabName) => setActive(tabName));
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

        renderStrip();
    }

    document.addEventListener('DOMContentLoaded', init);
    return {};
})();
