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

  const out = { errs, marks, skipped: [] };
  const btn = re => p.locator('button:visible').filter({ hasText: re }).first();
  // A step that is nice to have: if its control is not there, the take goes on.
  const soft = async (name, fn) => { try { await fn(); } catch (e) { out.skipped.push(name + ': ' + String(e).slice(0, 90)); } };
  const beams = () => p.evaluate(() => [...document.querySelectorAll('button')].filter(b => b.offsetParent && /^[AB] (on|off)$/i.test(b.innerText.trim())).map(b => b.innerText).join(','));
  const bothBeams = async () => {
    if (/A off/.test(await beams())) await press(btn(/^A off$/), 1500);
    if (/B off/.test(await beams())) await press(btn(/^B off$/), 1500);
  };
  const auto = async (after = 1800) => soft('auto levels', () => press(btn(/^Auto$/), after));
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
    mark('home');

    // ── 2. Scope: find the embryos ──────────────────────────────────────
    await say('Devices › Scope is the instrument', 'Cameras, detection, light, the two sheets, calibration, head and stage', 600);
    await press(p.locator('[title="Devices"]:visible, :text-is("Devices"):visible').first(), 3200);
    mark('scope');
    await say('Start the bottom camera to see the dish');
    await press(btn(/^Start camera$/), 4500);
    await say('Say how the dish is lit, then press Detect', 'Here: the LED, so embryos are dark');
    await choose('select:has(option[value="dark"])', 'dark');
    for (const name of ['Claude filter', 'SAM outline']) {
      const chip = p.locator('.mk-stage', { hasText: name });
      if ((await chip.getAttribute('aria-pressed')) === 'true') await press(chip, 350);
    }
    await press(btn(/^Detect$/), 800);
    await until(async () => !(await p.evaluate(() => /Detecting/i.test((document.querySelector('.mk-detect') || {}).innerText || ''))), 1000, 60);
    await wait(1200);
    await say('Three candidates, outlined on the picture', 'Register them and they join the embryo list with their stage positions');
    await press(p.locator('button:visible', { hasText: /register/i }).first(), 3000);
    mark('registered');
    await press(btn(/^Stop camera$/), 1200).catch(() => {});

    // ── 3. the light-sheet cameras, under the LED ───────────────────────
    await say('Go to an embryo', 'The target button on its row drives the stage there');
    await press(p.locator('.rp-row').first().locator('.rp-centre'), 2800);
    await say('SPIM A is the first light-sheet camera');
    await press('[data-source="A"]', 900);
    await press(btn(/^Start view$/), 2500);
    await say('Open the LED to see the embryo in transmitted light');
    await press(btn(/^Open$/), 2800);
    await auto(2600);
    await say('It is out of focus: the head is still above the sample', 'Step the head down and watch the picture', 2200);
    await press(btn(/▼\s*[−-]10\s*$/), 3200);
    await press(btn(/▼\s*[−-]5\s*$/), 3400);
    await auto(1500);
    await say('In focus: the eggshell and the cells are sharp', 'The head is now at the height the light sheets work at', 3800);
    mark('focused');

    // ── 4. the same embryo, by laser, from both sides ───────────────────
    await say('Close the LED and route a laser line');
    await press(btn(/^Closed$/), 1200);
    await press(p.locator('.lp-chip', { hasText: /^488$/ }), 1500);
    await say('Arm beam A', 'The Light panel says in words what is emitting');
    await press(btn(/^A off$/), 3200);
    await auto(2600);
    await say('SPIM A: nuclei, lit by the sheet from side A', '', 3200);
    await say('SPIM B is the other side', 'The beam follows the view');
    await press('[data-source="B"]', 4200);
    await auto(2600);
    await say('Side B sees the embryo mirrored, and here a little to one side', '', 3200);
    await say('Multi shows both at once: A in red, B in green');
    await press('[data-source="Multi"]', 2500);
    await bothBeams();
    await wait(4200);
    await say('The two views do not sit on one another yet', 'That is what “Align A and B” fixes, once both sides are calibrated', 4600);
    mark('views');
    await say('Stop the view before calibrating', 'Stopping it disarms the beams');
    await press(btn(/^Stop view$/), 2600);

    // ── 5. calibrate every embryo on both sides ─────────────────────────
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
    out.walk = await p.evaluate(() => ({ head: (document.querySelector('.cp-head') || {}).innerText.replace(/\s+/g, ' '), secs: [...document.querySelectorAll('.cp-sec')].map(e => e.innerText) }));
    await say('Done: every embryo is CAL on both sides', 'The names along the top choose whose steps are shown', 3000);
    const owners = p.locator('.cp-sec');
    if (await owners.count() > 1) { await press(owners.nth(0), 1600); }

    // ── 6. look through a step ──────────────────────────────────────────
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

    // ── 7. align the two views ──────────────────────────────────────────
    await say('Align A and B: bring the two views onto one another', 'It needs a fit on both sides, the stage at the embryo, and a laser line');
    await press(p.locator('.rp-row').first().locator('.rp-centre'), 2600);
    await press(p.locator('.lp-chip', { hasText: /^488$/ }), 1500);
    mark('align-start');
    await press('#op-ab-align', 2500);
    await say('It measures the gap in both cameras, probes the stage, then moves it', 'If a move does not help, the stage goes back');
    await until(async () => !(await p.evaluate(() => document.querySelector('#op-ab-align').disabled)), 1500, 80);
    mark('align-end');
    out.align = await p.evaluate(() => [...document.querySelectorAll('[class*="toast"]')].map(t => t.innerText).join(' / ').slice(0, 260));
    await say('Aligned: the gap is closed, and the embryo’s position is updated', '“Then align the two views” in Several embryos does this for each embryo of a walk', 5200);
    await say('Multi again: red and green now overlap');
    await press(p.locator('.lp-chip', { hasText: /^488$/ }), 1200).catch(() => {});
    await press('#op-fit-show', 900).catch(() => {});
    await press('[data-source="Multi"]', 1500);
    await soft('start multi', () => press(btn(/^Start view$/), 2500));
    await bothBeams();
    await wait(5200);
    mark('aligned');

    // ── 8. piezo follows galvo, on the live picture ─────────────────────
    await say('Sheets: with a fit, the piezo follows the galvo', 'Walk the sheet through the embryo and it stays in focus');
    await press('[data-source="A"]', 3500);
    await auto(2000);
    await type('#op-gv-a', '0.04', 3200);
    await type('#op-gv-a', '0.08', 3200);
    await type('#op-gv-a', '-0.03', 3200);
    await type('#op-gv-a', '0', 2000);
    mark('follow');
    await say('Stop the view when you are done looking', 'The beams are disarmed with it: nothing emits until the run takes a stack');
    await press(btn(/^Stop view$/), 3200);
    const emits = () => p.evaluate(() => [...document.querySelectorAll('[class*="lp-"]')].filter(e => /emit/i.test(e.innerText) && e.children.length < 3).map(e => e.innerText.trim())[0] || '');
    await until(async () => !/^EMITTING/i.test(await emits()), 800, 10);
    out.afterStop = (await beams()) + ' | ' + (await emits());
    await wait(1800);

    // ── 9. plan the run ─────────────────────────────────────────────────
    await say('The laser line stays routed for the run', 'Routed with the beams off, nothing emits: a stack gates its own light');
    await soft('route', async () => {
      const chip = p.locator('.lp-chip', { hasText: /^488$/ });
      if (!(await chip.evaluate(e => e.classList.contains('is-on')))) await press(chip, 1800);
    });
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
    await say('For this walkthrough: a short run', 'Every 20 seconds, five timepoints');
    await choose('#op-plan-unit', 's', 400);
    await type('#op-tl-interval', '20', 600);
    await choose('#op-tl-stop', 'timepoints', 500);
    await type('#op-tl-condval', '5', 1500);
    out.pre = await p.evaluate(() => document.querySelector('#op-preflight').innerText.replace(/\n+/g, ' | '));

    out.beamsAtStart = await p.evaluate(() => fetch('/api/devices/beam').then(r => r.json()).then(b => JSON.stringify(b.beam || b)).catch(e => String(e)));

    // ── 10. run ─────────────────────────────────────────────────────────
    await say('Start timelapse');
    mark('run-start');
    await press('#op-run-start', 3000);
    await say('Each tile is an embryo’s latest volume', 'The Run box counts down to the next round');
    await until(async () => (await p.evaluate(() => fetch('/api/devices/timelapse/status').then(r => r.json()).then(s => s.status))) !== 'running', 3000, 120);
    mark('run-end');
    await wait(3000);
    await say('The run has ended after five timepoints', '', 2600);

    // ── 11. Embryos: the viewer ─────────────────────────────────────────
    await say('Embryos: every timepoint of every embryo');
    await press(p.locator('[title="Embryos"]:visible, :text-is("Embryos"):visible').first(), 3000);
    mark('embryos-start');
    await soft('pick E1', () => press(p.getByText('E1', { exact: true }).first(), 3000));
    await say('Three projections of the volume', 'From above, from the side, and from the front');
    await wait(3000);
    await soft('play', async () => { await say('Play the timepoints as a movie'); await press(btn(/Play$/), 5200); await press(btn(/(Pause|Stop|Play)$/), 900); });
    await soft('previous', async () => { await say('Step with Previous and Next, or the arrow keys'); await press(btn(/Previous/), 1300); await press(btn(/Previous/), 1300); await press(btn(/Next/), 1300); });
    await soft('compare', async () => { await say('Compare with first: this timepoint beside the first one'); await press(btn(/^Compare with first$/), 3600); await press(btn(/^Compare with first$/), 900); });
    await soft('z', async () => {
      await say('The Z slider leaves the projection and walks through the slices');
      const z = p.locator('input[type="range"]:visible').last();
      const b = await z.boundingBox();
      for (const f of [0.3, 0.5, 0.7]) { await moveTo(b.x + b.width * f, b.y + b.height / 2); await p.mouse.down(); await p.mouse.up(); await wait(1500); }
      await moveTo(b.x + 2, b.y + b.height / 2); await p.mouse.down(); await p.mouse.up(); await wait(900);
    });
    await soft('spim b', async () => { await say('SPIM A and SPIM B: the same timepoint from the other side'); await press(btn(/^SPIM B$/), 3200); await press(btn(/^SPIM A$/), 1500); });
    await soft('perception', async () => { await say('Under the picture: what perception made of this timepoint', 'The stage it judged, in words, and a box to ask a follow-up'); await point(p.getByText('VLM SUMMARY').first()); await wait(4200); });
    await soft('table', async () => { await say('Table: every embryo against every timepoint'); await press(btn(/^Table$/), 3800); });
    await soft('vitals', async () => { await say('Vitals: each embryo’s stage over time'); await press(btn(/^Vitals$/), 3800); await press(btn(/^Watch$/), 1500); });
    mark('embryos');

    // ── 12. HALT ────────────────────────────────────────────────────────
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
