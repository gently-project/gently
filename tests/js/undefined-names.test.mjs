/**
 * No UI script reads a name that nothing defines.
 *
 *   node --test tests/js/undefined-names.test.mjs
 *
 * A variable left behind by a removal throws only when its line runs, and no
 * browser runs here. TypeScript reads every script as one global program (which
 * is what the page's <script> tags make of them) and reports each name it cannot
 * find; every other kind of type error it reports is ignored. Names it cannot
 * see for itself are declared in ui-globals.d.ts.
 *
 * Needs the network once: npx fetches the pinned compiler.
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { readdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const js = join(here, '../../gently/ui/web/static/js');
const scripts = readdirSync(js, { recursive: true })
    .filter((f) => f.endsWith('.js'))
    .map((f) => join(js, f));

test('every name a UI script reads is defined somewhere', { timeout: 300_000 }, () => {
    const tsc = spawnSync(
        'npx',
        ['-y', '-p', 'typescript@5.9.3', 'tsc', '--allowJs', '--checkJs', '--noEmit',
         '--target', 'es2022', '--lib', 'dom,dom.iterable,es2022',
         join(here, 'ui-globals.d.ts'), ...scripts],
        { encoding: 'utf8', shell: process.platform === 'win32' },
    );
    assert.equal(tsc.error, undefined, `could not run tsc: ${tsc.error}`);
    const out = tsc.stdout + tsc.stderr;
    assert.match(out, /error TS\d+/, `tsc did not check the scripts:\n${out.slice(0, 2000)}`);
    const missing = out.split('\n').filter((l) => l.includes('Cannot find name'));
    assert.deepEqual(missing, []);
});
