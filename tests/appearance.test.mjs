import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import test from 'node:test';
import vm from 'node:vm';

const script = await readFile(new URL('../site/appearance.js', import.meta.url), 'utf8');
const key = 'mcts-combat-engine.appearance.v1';
function open(saved, blocked = false) {
  const values = new Map([['unrelated', 'keep']]);
  if (saved !== null) values.set(key, saved);
  const root = {dataset:{appearance:'obscur'}};
  let ready, changed;
  const control = {disabled:true, addEventListener:(_, listener) => { changed = listener; }};
  vm.runInNewContext(script, {
    document:{documentElement:root, addEventListener:(_, listener) => { ready = listener; },
      getElementById:() => control},
    localStorage:{
      getItem(name) { if (blocked) throw Error('blocked'); return values.get(name); },
      setItem(name, value) { if (blocked) throw Error('blocked'); values.set(name, value); }
    }
  });
  // The saved choice is applied before DOMContentLoaded.
  const prepaint = root.dataset.appearance;
  ready();
  return {root, prepaint, control, values,
    choose(value) { control.value=value; changed(); }};
}

test('new and invalid preferences use the declared Obscur default before paint', () => {
  for (const saved of [null, '', 'invalid']) {
    const page = open(saved);
    assert.equal(page.prepaint, 'obscur');
    assert.equal(page.control.value, 'obscur');
    assert.equal(page.control.disabled, false);
  }
});

test('every explicit choice survives reopening without touching other storage', () => {
  for (const choice of ['auto','clair','obscur']) {
    const page = open(null);
    page.choose(choice);
    assert.equal(page.values.get(key), choice);
    assert.equal(page.values.get('unrelated'), 'keep');
    const reopened = open(page.values.get(key));
    assert.equal(reopened.prepaint, choice);
    assert.equal(reopened.control.value, choice);
  }
});

test('unavailable storage retains Obscur on reopen and memory-only switching', () => {
  const page = open(null, true);
  assert.equal(page.prepaint, 'obscur');
  page.choose('clair');
  assert.equal(page.root.dataset.appearance, 'clair');
  page.choose('auto');
  assert.equal(page.root.dataset.appearance, 'auto');
  assert.equal(open(null, true).prepaint, 'obscur');
  assert.equal(page.values.get(key), undefined);
});

