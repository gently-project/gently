// A line that asks a person draws them as a chip, however the @word was
// cased, and the inbox's badge counts what is still waiting on you
// (gently/ui/web/static/js/utils.js, inbox.js).
//
// "@Ryan kindly annotate" is stored asking ryan (the server reads the word
// by lower case), and the page compared the typed word to the stored id as
// written: the ask reached Ryan and was drawn as plain words. And an ask
// answered on its session without being opened from the inbox went on
// counting as unopened on the badge.

import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const JS = new URL('../../gently/ui/web/static/js/', import.meta.url);
const ctx = vm.createContext({ document: { addEventListener() {} }, window: {}, console });
vm.runInContext(fs.readFileSync(new URL('utils.js', JS), 'utf8'), ctx);
const html = (text, mentions) => vm.runInContext(`Mentions.html(${JSON.stringify(text)}, ${JSON.stringify(mentions)})`, ctx);

test('a person is a chip however their name was cased', () => {
    for (const typed of ['@ryan', '@Ryan', '@RYAN']) {
        const out = html(`${typed} kindly annotate`, ['ryan']);
        assert.match(out, /<b class="rd-mention"[^>]*title="ryan">@ryan<\/b> kindly annotate$/, typed);
    }
});

test('an @word that asks nobody stays words', () => {
    assert.equal(html('mail x@ryan.org and @nobody', ['ryan']), 'mail x@ryan.org and @nobody');
    assert.equal(html('@ryans data', ['ryan']), '@ryans data');
});

test('an answered ask is not counted as unopened', () => {
    const inbox = fs.readFileSync(new URL('inbox.js', JS), 'utf8');
    assert.ok(inbox.includes('const waiting = i => !i.seen && !i.answered;'));
    assert.ok(!inbox.includes('filter(i => !i.seen)'));
});

test('wherever a notebook note is written or shown, a person can be asked and is drawn', () => {
    // A finding, a line in the Notebook tab: both are notebook notes, and the
    // server already read their @words; the boxes offered nobody and the
    // cards drew "@ryan" as words.
    const campaigns = fs.readFileSync(new URL('campaigns.js', JS), 'utf8');
    const notebook = fs.readFileSync(new URL('notebook.js', JS), 'utf8');
    assert.ok(!campaigns.includes('<div class="pj-body">${esc(n.body)}</div>'));
    assert.equal(campaigns.split('<div class="pj-body">${Mentions.html(n.body, n.mentions)}</div>').length - 1, 2);
    assert.ok(campaigns.includes(`e.target.matches('textarea[data-field="body"]')) Mentions.attach(e.target);`));
    assert.ok(notebook.includes('if (input) Mentions.attach(input);'));
    assert.ok(notebook.includes("Mentions.html(n.body || '', n.mentions)"));
    // The list of people hangs from its box's container.
    const css = fs.readFileSync(new URL('../css/main.css', JS), 'utf8');
    assert.ok(css.includes('.nb-ask, .pj-form { position: relative; }'));
});
