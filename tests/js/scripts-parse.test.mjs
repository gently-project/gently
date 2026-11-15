// Every page script parses. A second `const` of a name already taken stops
// the whole file loading, nothing but a browser says so, and CI drives no
// browser: a helper named like an existing one took the Devices tab down
// for the minutes it took to open the page (2026-11-14).

import test from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';

const root = join(dirname(fileURLToPath(import.meta.url)), '../../gently/ui/web/static/js');
const files = [];
for (const dir of [root, join(root, 'panels'), join(root, 'tools')]) {
    for (const f of readdirSync(dir)) if (f.endsWith('.js')) files.push(join(dir, f));
}

test('every page script parses', () => {
    assert.ok(files.length > 40);
    for (const f of files) {
        assert.doesNotThrow(() => new vm.Script(readFileSync(f, 'utf8'), { filename: f }), f);
    }
});
