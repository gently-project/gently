// Records the guide's walkthrough of two-view imaging on the SIMULATED rig.
//
// Start the simulated rig and the app on a store of its own (CLAUDE.md), with
// the app freshly started so the launch screen shows:
//   uv run --no-sync python tools/sim_rig.py
//   GENTLY_STORAGE_PATH="$TEMP/gently-sim" uv run --no-sync python launch_gently.py --no-api --no-auth --no-browser
// Then run this through Playwright's run-code with `page` (any page of the
// browser). Recording needs Playwright's ffmpeg: `npx playwright install ffmpeg`.
// It returns the take's path and `marks`, for tools/cut_walkthrough.py.
//
// The page draws no pointer into a recording, so one is drawn here: an arrow
// with a halo that glides to each target, a ripple where it presses, and a
// caption saying what the step is.
async (page) => {
  const W = 1920, H = 940;
  const browser = page.context().browser();
  const ctx = await browser.newContext({
    viewport: { width: W, height: H },
    recordVideo: { dir: '.playwright-mcp/walkthrough-take', size: { width: W, height: H } },
  });
  // A pointer that can be seen, a ripple where it presses, and a caption.
  await ctx.addInitScript(() => {
    try { localStorage.setItem('gently-theme', 'dark'); } catch (_) {}
    const mount = () => {
      if (document.getElementById('__cur')) return;
      const css = document.createElement('style');
      css.textContent = `
        #__cur { position: fixed; left: 0; top: 0; width: 26px; height: 26px; z-index: 2147483647; pointer-events: none;
                 transform: translate(-3px, -2px); filter: drop-shadow(0 1px 2px rgba(0,0,0,.7)); }
        #__halo { position: fixed; left: 0; top: 0; width: 46px; height: 46px; margin: -23px 0 0 -23px; border-radius: 50%;
                  z-index: 2147483646; pointer-events: none; background: rgba(255, 213, 0, .22); border: 2px solid rgba(255, 213, 0, .75); }
        .__rip { position: fixed; width: 18px; height: 18px; margin: -9px 0 0 -9px; border-radius: 50%; z-index: 2147483646;
                 pointer-events: none; border: 3px solid #ffd500; animation: __rip .55s ease-out forwards; }
        @keyframes __rip { from { transform: scale(.6); opacity: 1; } to { transform: scale(4.2); opacity: 0; } }
        #__cap { position: fixed; left: 50%; bottom: 26px; transform: translateX(-50%); z-index: 2147483645; pointer-events: none;
                 max-width: 1200px; padding: 12px 22px; border-radius: 10px; background: rgba(13, 17, 23, .93);
                 border: 1px solid rgba(255,255,255,.22); color: #fff; font: 600 21px/1.35 "Segoe UI", system-ui, sans-serif;
                 text-align: center; box-shadow: 0 6px 24px rgba(0,0,0,.5); opacity: 0; transition: opacity .25s; }
        #__cap.on { opacity: 1; }
        #__cap small { display: block; font: 400 15px/1.4 "Segoe UI", system-ui, sans-serif; color: #c9d1d9; margin-top: 3px; }`;
      document.documentElement.appendChild(css);
      const halo = document.createElement('div'); halo.id = '__halo';
      const cur = document.createElement('div'); cur.id = '__cur';
      cur.innerHTML = '<svg viewBox="0 0 24 24" width="26" height="26"><path d="M3 2l7.5 19 2.6-7.4L20.5 11z" fill="#fff" stroke="#111" stroke-width="1.6" stroke-linejoin="round"/></svg>';
      const cap = document.createElement('div'); cap.id = '__cap';
      document.documentElement.append(halo, cur, cap);
      const at = (x, y) => { cur.style.left = halo.style.left = x + 'px'; cur.style.top = halo.style.top = y + 'px'; };
      const last = JSON.parse(sessionStorage.getItem('__curAt') || '[960,470]');
      at(last[0], last[1]);
      window.addEventListener('mousemove', e => { at(e.clientX, e.clientY); sessionStorage.setItem('__curAt', JSON.stringify([e.clientX, e.clientY])); }, true);
      window.addEventListener('mousedown', e => {
        const r = document.createElement('div'); r.className = '__rip';
        r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
        document.documentElement.appendChild(r); setTimeout(() => r.remove(), 600);
      }, true);
      window.__say = (t, sub) => { cap.innerHTML = ''; if (!t) { cap.classList.remove('on'); return; }
        cap.textContent = t; if (sub) { const s = document.createElement('small'); s.textContent = sub; cap.appendChild(s); } cap.classList.add('on'); };
    };
    if (document.documentElement) mount();
    document.addEventListener('DOMContentLoaded', mount);
  });

  const p = await ctx.newPage();
  p.on('dialog', d => d.accept().catch(() => {}));
  const errs = []; p.on('pageerror', e => errs.push(String(e).slice(0, 160)));
  const marks = [];                         // [label, seconds since the recording began]
  const t0 = Date.now();
  const mark = label => marks.push([label, Math.round((Date.now() - t0) / 100) / 10]);
  const wait = ms => p.waitForTimeout(ms);
  const say = async (t, sub, ms = 0) => { await p.evaluate(([a, b]) => window.__say && window.__say(a, b), [t, sub || '']); if (ms) await wait(ms); };
  let pos = [W / 2, H / 2];
  const moveTo = async (x, y) => {
    const d = Math.hypot(x - pos[0], y - pos[1]);
    await p.mouse.move(x, y, { steps: Math.max(12, Math.min(45, Math.round(d / 22))) });
    pos = [x, y];
  };
  const centre = async loc => {
    const el = typeof loc === 'string' ? p.locator(loc).first() : loc;
    await el.scrollIntoViewIfNeeded().catch(() => {});
    const b = await el.boundingBox();
    if (!b) throw new Error('nothing to point at: ' + loc);
    return [b.x + b.width / 2, b.y + b.height / 2];
  };
  const point = async loc => { const [x, y] = await centre(loc); await moveTo(x, y); await wait(350); };
  const press = async (loc, after = 700) => { await point(loc); await p.mouse.down(); await wait(90); await p.mouse.up(); await wait(after); };
  // A native select's list is drawn by the system and is not in the picture:
  // the pointer goes to it, it is pressed, and the choice is made.
  const choose = async (sel, value, after = 900) => { await point(sel); await p.mouse.down(); await p.mouse.up(); await wait(250); await p.keyboard.press('Escape').catch(() => {}); await p.locator(sel).first().selectOption(value); await wait(after); };
  const type = async (sel, text, after = 700) => { await press(sel, 200); await p.locator(sel).first().fill(''); await p.keyboard.type(String(text), { delay: 110 }); await p.keyboard.press('Tab'); await wait(after); };
  const until = async (fn, every = 1500, max = 240) => { for (let i = 0; i < max; i++) { if (await fn()) return true; await wait(every); } return false; };

  const out = { errs, marks };
  try {
    // ── 1. launch ───────────────────────────────────────────────────────
    await p.goto('http://localhost:8080/', { waitUntil: 'domcontentloaded' });
    await wait(1800);
    mark('launch');
    await say('Gently: setting up two-view imaging', 'A walkthrough on the simulated rig', 3200);
    if (p.url().includes('/launch')) {
      await say('Start a session', 'Who is here, what to bring up, and a new session or one to carry on from', 2600);
      const fresh = p.getByText('A new session').first();
      if (await fresh.count()) await press(fresh, 900);
      await press('#go', 500);
      await say('The microscope takes a moment to come up');
      await p.waitForURL(u => !String(u).includes('/launch'), { timeout: 180000 }).catch(() => {});
    }
    await wait(5000);
    // The names beside the icons, for someone who has not learnt the icons.
    if ((await p.locator('#v2-rail-collapse').getAttribute('aria-expanded')) === 'false') await press('#v2-rail-collapse', 900);
    mark('home');

    // ── 2. Scope: find the embryos ──────────────────────────────────────
    await say('Devices › Scope is the instrument', 'Cameras, detection, light, the two sheets, calibration, head and stage', 600);
    await press(p.locator('[title="Devices"]:visible, :text-is("Devices"):visible').first(), 3200);
    mark('scope');
    await say('Start the bottom camera to see the dish');
    await press(p.locator('button', { hasText: /^Start camera$/ }).first(), 4500);
    await say('Say how the dish is lit, then press Detect', 'Here: the LED, so embryos are dark');
    await choose('select:has(option[value="dark"])', 'dark');
    for (const name of ['Claude filter', 'SAM outline']) {
      const chip = p.locator('.mk-stage', { hasText: name });
      if ((await chip.getAttribute('aria-pressed')) === 'true') await press(chip, 350);
    }
    await press(p.locator('button', { hasText: /^Detect$/ }).first(), 800);
    await until(async () => !(await p.evaluate(() => /Detecting/i.test((document.querySelector('.mk-detect') || {}).innerText || ''))), 1000, 60);
    await wait(1200);
    await say('Three candidates, outlined on the picture', 'Register them and they join the embryo list with their stage positions');
    await press(p.locator('button:visible', { hasText: /register/i }).first(), 3000);
    mark('registered');
    await press(p.locator('button', { hasText: /^Stop camera$/ }).first(), 1200).catch(() => {});

    // ── 3. light ────────────────────────────────────────────────────────
    await say('Route a laser line in Light', 'The beams only emit when a view or a run asks for them');
    await press(p.locator('.lp-chip', { hasText: /^488$/ }), 2200);

    // ── 4. calibrate every embryo on both sides ─────────────────────────
    await say('Calibration: each embryo needs a fit on side A and on side B', '', 2600);
    await say('Choose Side “A then B”');
    await choose('#cal-side', 'AB');
    await say('Open “Several embryos” to do them all in one go');
    await press('#op-cal-several > summary', 900);
    await press('[data-pick-set="all"]', 900);
    await say('Calibrate: the stage walks from one embryo to the next');
    mark('walk-start');
    await press('#op-cal-all', 2500);
    await say('The run is a list of steps', 'The step being measured is open; finished steps fold to one line with what they found');
    await until(async () => (await p.evaluate(() => document.querySelectorAll('.cp-step').length)) >= 3, 1000, 90);
    await wait(6000);
    await say('Each sweep draws its curve as the exposures arrive');
    await until(async () => !(await p.evaluate(() => !!document.querySelector('#op-cal-all').dataset.busy)), 2000, 400);
    mark('walk-end');
    await wait(9000);
    out.walk = await p.evaluate(() => ({ head: (document.querySelector('.cp-head') || {}).innerText.replace(/\s+/g, ' '), secs: [...document.querySelectorAll('.cp-sec')].map(e => e.innerText), result: document.querySelector('#op-cal-result').innerText }));
    await say('Done: every embryo is CAL on both sides', 'The names along the top choose whose steps are shown', 3000);
    const owners = p.locator('.cp-sec');
    if (await owners.count() > 1) { await press(owners.nth(0), 1600); await press(owners.nth(1), 1600); }

    // ── 5. look through a step ──────────────────────────────────────────
    const sweeps = p.locator('.cp-step-head', { hasText: /Focus at/ });
    if (await sweeps.count()) {
      await say('Open any step to look through it');
      await press(sweeps.nth(Math.min(1, (await sweeps.count()) - 1)), 1500);
      await say('The graph is the navigator', 'Hover a point to see that exposure; click to pin it');
      const pts = p.locator('.cp-graph .pt .hit');
      const n = await pts.count();
      for (const k of [0.15, 0.3, 0.42, 0.5, 0.58, 0.7, 0.85]) {
        const i = Math.max(0, Math.min(n - 1, Math.round(k * (n - 1))));
        const [x, y] = await centre(pts.nth(i)); await moveTo(x, y); await wait(650);
      }
      await say('The row of exposures runs along the sweep', 'The one the step picked is labelled “sharpest”');
      const pick = p.locator('.cp-thumb.is-pick').first();
      if (await pick.count()) await press(pick, 1800);
      const fit = p.locator('.cp-step-head', { hasText: /^.?\s*The fit/ }).first();
      if (await fit.count()) { await say('The fit: the line through the sharpest piezo at each angle'); await press(fit, 2600); }
    }
    mark('looked');
    await press('#op-cal-several > summary', 600).catch(() => {});
    await say('Graphs goes back to the camera, and shows the latest run again any time');
    await press('#op-fit-show', 1800).catch(() => {});

    // ── 6. piezo follows galvo ──────────────────────────────────────────
    await say('Sheets: with a fit, the piezo follows the galvo', 'Move the galvo and the piezo goes along the calibration line');
    await press(p.locator('.rp-row .rp-label').first(), 1200);
    await type('#op-gv-a', '0.10', 1600);
    await type('#op-gv-a', '0.05', 1600);
    await type('#op-gv-a', '0', 1200);
    mark('follow');

    // A calibration puts the lasers out when it ends; the run needs a line.
    await say('Route the laser line again', 'A calibration leaves the lasers off when it ends');
    await press(p.locator('.lp-chip', { hasText: /^488$/ }), 2000);

    // ── 7. plan the run ─────────────────────────────────────────────────
    await say('Devices › Acquisition: plan the run');
    await press(p.locator(':text-is("Acquisition"):visible').first(), 2600);
    mark('plan');
    await say('How often', 'Here every 5 minutes');
    await choose('#op-plan-unit', 'min', 500);
    await type('#op-tl-interval', '5', 900);
    await say('Views: A and B', 'Every round, each embryo gets a stack from side A and then from side B');
    await choose('#op-plan-sides', 'AB', 1500);
    await say('How it ends: at hatching', 'The number is how many more timepoints to take once it has hatched');
    await choose('#op-tl-stop', 'hatching', 2200);
    await say('Before it starts', 'Who is in the run, the fits, the light, the cadence, the disk, the head: read it once before pressing Start');
    await point('#op-preflight'); await wait(5200);
    await say('For this walkthrough: a short run', 'Every 30 seconds, three timepoints');
    await choose('#op-plan-unit', 's', 400);
    await type('#op-tl-interval', '30', 600);
    await choose('#op-tl-stop', 'timepoints', 500);
    await type('#op-tl-condval', '3', 1500);
    out.pre = await p.evaluate(() => document.querySelector('#op-preflight').innerText.replace(/\n+/g, ' | '));

    // ── 8. run ──────────────────────────────────────────────────────────
    await say('Start timelapse');
    mark('run-start');
    await press('#op-run-start', 3000);
    await say('Each tile is an embryo’s latest volume', 'The Run box counts down to the next round');
    await until(async () => (await p.evaluate(() => fetch('/api/devices/timelapse/status').then(r => r.json()).then(s => s.status))) !== 'running', 3000, 80);
    mark('run-end');
    await wait(3000);
    await say('The run has ended after three timepoints', '', 2600);

    // ── 9. Embryos ──────────────────────────────────────────────────────
    await say('Embryos: every timepoint of every embryo');
    await press(p.locator('[title="Embryos"]:visible, :text-is("Embryos"):visible').first(), 3000);
    const card = p.getByText('E1', { exact: true }).first();
    if (await card.count()) await press(card, 3200);
    const b = p.locator('button:visible', { hasText: /^SPIM B$/ }).first();
    if (await b.count()) { await say('Switch between SPIM A and SPIM B'); await press(b, 2600); }
    mark('embryos');

    // ── 10. HALT ────────────────────────────────────────────────────────
    await say('HALT is in the rig menu and on the Devices page', 'It stops every stage, puts the lasers and LED out, and stops the cameras');
    await press('#status-button', 1800);
    await press('#rig-halt', 3800);
    out.halt = await p.evaluate(() => (document.querySelector('#rig-halt-says') || {}).innerText);
    await press('#status-button', 700).catch(() => {});
    await say('That is two-view imaging in Gently', 'The written guide is in docs/guide', 4200);
    mark('end');
  } catch (e) {
    out.failed = String(e).slice(0, 300);
    await p.screenshot({ path: '.claude/vid-failed.png' }).catch(() => {});
  }
  const v = p.video();
  await ctx.close();
  out.video = v ? await v.path() : null;
  return out;
}
