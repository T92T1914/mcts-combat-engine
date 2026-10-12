import assert from 'node:assert/strict';
import {before, after, test} from 'node:test';
import {createServer} from 'node:http';
import {createHash} from 'node:crypto';
import {readFile, mkdir} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {chromium} from 'playwright';

// Only an owned loopback server and fresh headless contexts. No saved profiles,
// visible fallback, desktop input or connection to an existing browser.
const root = path.resolve(fileURLToPath(new URL('../../_site/', import.meta.url)));
const mime = {'.html':'text/html', '.css':'text/css', '.js':'text/javascript',
  '.mjs':'text/javascript', '.json':'application/json', '.svg':'image/svg+xml', '.png':'image/png'};
let browser, server, base;
before(async () => {
  const published = process.env.MCTS_BROWSER_BASE_URL;
  if (published) {
    if (published !== 'https://t92t1914.github.io/mcts-combat-engine/')
      throw Error('Only the published MCTS project base is supported');
    base = published.slice(0,-1);
  } else {
    const presentation = JSON.parse(await readFile(path.join(root,'presentation.json'),'utf8'));
    const allowed = new Set([...Object.keys(presentation.files),'presentation.json']);
    server = createServer(async (request, response) => {
      const raw = request.url.split('?')[0];
      if (raw === '/favicon.ico') { response.writeHead(204).end(); return; }
      const name = raw === '/' ? 'index.html' : raw.slice(1);
      const segments = name.split('/');
      if (!raw.startsWith('/') || segments.some(s => !/^[a-z0-9._-]+$/i.test(s) || s === '.' || s === '..') || !allowed.has(name)) {
        response.writeHead(404).end(); return;
      }
      const file = path.resolve(root,...segments);
      if (!file.startsWith(root + path.sep)) { response.writeHead(404).end(); return; }
      try {
        const bytes = await readFile(file);
        response.writeHead(200, {'Content-Type': mime[path.extname(name)] ?? 'text/plain'});
        response.end(bytes);
      } catch (_) { response.writeHead(404).end(); }
    });
    await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
    base = `http://127.0.0.1:${server.address().port}`;
  }
  const channel = process.env.MCTS_BROWSER_CHANNEL;
  if (channel && !['chrome','chromium'].includes(channel)) throw Error('Unsupported channel');
  browser = await chromium.launch({headless:true, chromiumSandbox:true, args:['--mute-audio','--disable-gpu'], ...(channel ? {channel} : {})});
  console.log(`Isolated headless browser ${browser.version()}; sandbox requested; fresh contexts`);
});
after(async () => {
  if (browser) await browser.close();
  if (server) await new Promise(resolve => server.close(resolve));
});
async function fixture(t, options = {}, blockedStorage = false) {
  const context = await browser.newContext({viewport:{width:1280,height:900}, ...options});
  const failures = [], external = [];
  const admitted = new URL(base);
  await context.route('**/*', route => {
    const requested = new URL(route.request().url());
    const inProject = admitted.pathname === '/' || requested.pathname === admitted.pathname || requested.pathname.startsWith(admitted.pathname + '/');
    if (requested.origin !== admitted.origin || !inProject) {
      external.push(route.request().url()); return route.abort();
    }
    return route.continue();
  });
  if (blockedStorage) await context.addInitScript(() => {
    Object.defineProperty(window, 'localStorage', {get() { throw new DOMException('Blocked','SecurityError'); }});
  });
  const page = await context.newPage();
  page.on('pageerror', error => failures.push(error.message));
  page.on('console', message => { if (message.type() === 'error') failures.push(message.text()); });
  page.on('response', response => { if (response.status() >= 400) failures.push(`${response.status()} ${response.url()}`); });
  t.after(async () => {
    await context.close();
    assert.deepEqual(failures, []);
    assert.deepEqual(external, [], 'No font, analytics or other external page requests');
  });
  return page;
}
const background = page => page.locator('body').evaluate(e => getComputedStyle(e).backgroundColor);
async function ready(page, location = '/') {
  await page.goto(base + location);
  await page.locator('#appearance:not([disabled])').waitFor();
}
async function capture(page, name, locator = 'body') {
  if (!process.env.MCTS_SCREENSHOT_DIR) return;
  await mkdir(process.env.MCTS_SCREENSHOT_DIR, {recursive:true});
  await page.locator(locator).screenshot({path:path.join(process.env.MCTS_SCREENSHOT_DIR, name+'.png')});
}

async function fonts(page, selector) {
  const session = await page.context().newCDPSession(page);
  try {
    await session.send('DOM.enable'); await session.send('CSS.enable');
    const {root} = await session.send('DOM.getDocument');
    const {nodeId} = await session.send('DOM.querySelector', {nodeId:root.nodeId, selector});
    return (await session.send('CSS.getPlatformFontsForNode', {nodeId})).fonts.filter(f => f.glyphCount > 0);
  } finally { await session.detach(); }
}

for (const mode of ['clair','obscur']) test(`${mode} repeated execution report preserves paired values and public downloads`, async t => {
  const page = await fixture(t, {colorScheme:'dark'});
  await ready(page);
  await page.getByRole('link', {name:'Read the repeated execution report'}).click();
  await page.locator('#appearance:not([disabled])').waitFor();
  await page.locator('#appearance').selectOption(mode);
  const data = JSON.parse(await readFile(path.join(root,'same-forest-repeatability-public-receipts.json'),'utf8'));
  const table = page.getByRole('region',{name:'Paired ratios and individual intervals'});
  const expected = [];
  for (const scenario of ['duel','gauntlet','boss']) for (const roots of [2,4])
    for (const metric of ['elapsed_s','complete_call_s']) for (const phase of ['cold','warm']) {
      const means = data.blocks.map(block => {
        const logs = [0,1].map(iteration => {
          const cells = Object.fromEntries(block.record.cells.filter(c => c.scenario === scenario && c.roots === roots && c.iteration === iteration).map(c => [c.phase,c]));
          return Math.log(cells.sequential[metric]/cells[phase][metric]);
        });
        return (logs[0]+logs[1])/2;
      });
      const mean = means.reduce((sum,value) => sum+value,0)/6;
      const variance = means.reduce((sum,value) => sum+(value-mean)**2,0)/5;
      const half = 2.571*Math.sqrt(variance/6);
      const low = Math.exp(mean-half), high = Math.exp(mean+half);
      expected.push([scenario,String(roots),metric,phase,Math.exp(mean).toFixed(3),`${low.toFixed(3)} to ${high.toFixed(3)}`,low>1?'bounded advantage':high<1?'bounded disadvantage':'inconclusive']);
    }
  assert.deepEqual(await table.locator('tbody tr').evaluateAll(rows => rows.map(row => [...row.cells].map(cell => cell.textContent))),expected);
  const before = await table.textContent();
  assert.equal(await page.getByRole('img').count(),2);
  for (const image of await page.getByRole('img').all()) {
    await image.scrollIntoViewIfNeeded();
    await image.evaluate(async e => { if (!e.complete || !e.naturalWidth) await e.decode(); });
    assert.equal(await image.evaluate(e => e.naturalWidth),1000);
  }
  const names = ['same-forest-repeatability-public-receipts.json','same-forest-repeatability-public-failed-attempt.json','same-forest-repeatability-public-fields.json','same-forest-repeatability-provenance.json','same-forest-repeatability-results.md','same-forest-repeatability-protocol.json','same-forest-repeatability-figure.json'];
  for (const name of names) {
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(),200);
    assert.deepEqual(await response.body(),await readFile(path.join(root,name)));
  }
  const [download] = await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'Download public receipts',exact:true}).click()]);
  assert.equal(download.suggestedFilename(),'same-forest-repeatability-public-receipts.json');
  assert.deepEqual(await readFile(await download.path()),await readFile(path.join(root,download.suggestedFilename())));
  await capture(page,`${mode}-repeatability-wide`, 'main');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
  await table.focus();
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('.table-wrap').scrollLeft > 0);
  assert.equal(await table.evaluate(e => getComputedStyle(e).outlineStyle),'solid');
  await capture(page,`${mode}-repeatability-narrow-table`, '.table-wrap');
  await page.addStyleTag({content:'html{font-size:200% !important}'});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
  assert.equal(await table.textContent(),before);
  await page.locator('#appearance').selectOption(mode==='clair'?'obscur':'clair');
  assert.equal(await table.textContent(),before);
  await page.reload();
  assert.equal(await page.locator('#appearance').inputValue(),mode==='clair'?'obscur':'clair');
  await page.getByRole('link',{name:'Original control',exact:true}).click();
  assert.equal(new URL(page.url()).pathname,'/same-forest.html');
  await page.goBack();
  assert.equal(await table.textContent(),before);
  const noScript = await fixture(t,{javaScriptEnabled:false,colorScheme:mode==='obscur'?'dark':'light',hasTouch:true,viewport:{width:390,height:844}});
  await noScript.goto(base+'/same-forest-repeatability.html');
  assert.equal(await noScript.locator('tbody tr').count(),24);
  assert.equal(await noScript.getByRole('img').count(),2);
  assert.equal(await noScript.getByRole('link',{name:'Download public receipts',exact:true}).count(),1);
  assert.equal(await noScript.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
});

for (const mode of ['obscur','clair']) test(`${mode} same forest report preserves identity, timings and downloads`, async t => {
  const page = await fixture(t, {colorScheme:'dark'});
  await ready(page);
  await page.getByRole('link', {name:'Read the same forest report'}).click();
  await page.locator('#appearance:not([disabled])').waitFor();
  await page.locator('#appearance').selectOption(mode);
  const raw = JSON.parse(await readFile(path.join(root, 'same-forest-results.json'), 'utf8'));
  const tables = await page.locator('tbody').allTextContents();
  assert.deepEqual(await page.locator('tbody').evaluateAll(es => es.map(e => e.rows.length)), [6,18,18]);
  const summary = page.getByRole('region', {name:'Observed wall seconds and ratios'});
  for (const [i, comparison] of raw.comparisons.entries()) {
    const cells = Object.fromEntries(raw.cells.filter(c => c.scenario === comparison.scenario && c.roots === comparison.roots).map(c => [c.phase,c]));
    const values = await summary.locator('tbody tr').nth(i).locator('td').allTextContents();
    assert.deepEqual(values, [comparison.scenario,String(comparison.roots),...['sequential','cold','warm'].map(p => cells[p].elapsed_s.toFixed(6)),...['cold','warm'].map(p => comparison.sequential_wall_ratio[p].toFixed(3))]);
  }
  for (const [i, cell] of raw.cells.entries()) {
    const work = await page.getByRole('region', {name:'All 18 execution receipts'}).locator('tbody tr').nth(i).locator('td').allTextContents();
    assert.deepEqual(work, [cell.scenario,String(cell.roots),cell.phase,'12000','60000','0','0']);
  }
  for (const name of ['same-forest-results.json','same-forest-results.md','same-forest-protocol.json']) {
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(), 200);
    assert.deepEqual(await response.body(), await readFile(path.join(root,name)));
  }
  for (const [label, name] of [['Download raw results','same-forest-results.json'],['Download Markdown report','same-forest-results.md']]) {
    const [download] = await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:label,exact:true}).click()]);
    assert.equal(download.suggestedFilename(), name);
    assert.deepEqual(await readFile(await download.path()), await readFile(path.join(root,name)));
  }
  assert.match(await page.locator('main').textContent(), /3adf64e618c277721d7ea36629cc934d0145a3ac/);
  assert.match(await page.locator('main').textContent(), /warm execution took 0.794376 seconds while cold execution took 0.759412/);
  assert.match(await page.locator('main').textContent(), /not a playing strength study/);
  for (const [selector, expected] of [['h1','Inter-Bold'],['main p:not(.eyebrow)','Inter-Regular'],['label[for="appearance"]','Inter-SemiBold']]) {
    const providers = await fonts(page,selector);
    console.log('Execution report actual glyphs:',JSON.stringify({mode,selector,providers}));
    if (process.env.MCTS_REQUIRE_INTER === '1') assert.ok(providers.some(f => f.postScriptName === expected && f.glyphCount > 0));
  }
  await capture(page, `${mode}-same-forest-summary`, '.table-wrap[aria-label="Observed wall seconds and ratios"]');
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.evaluate(() => scrollTo(0,0));
  if (process.env.MCTS_SCREENSHOT_DIR) await page.screenshot({path:path.join(process.env.MCTS_SCREENSHOT_DIR,`${mode}-same-forest-narrow.png`)});
  await summary.scrollIntoViewIfNeeded();
  assert.equal(await summary.locator('tbody tr').nth(2).locator('td').first().evaluate(e => {
    const range=document.createRange(); range.selectNodeContents(e);
    return range.getClientRects().length;
  }),1,'Scenario labels stay on one line instead of stacking letters');
  if (process.env.MCTS_SCREENSHOT_DIR) await page.screenshot({path:path.join(process.env.MCTS_SCREENSHOT_DIR,`${mode}-same-forest-narrow-table.png`)});
  await page.locator('#appearance').focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.textContent),'Download raw results');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  assert.equal(await summary.evaluate(e => document.activeElement === e),true);
  assert.equal(await summary.evaluate(e => getComputedStyle(e).outlineStyle),'solid');
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(() => document.querySelector('.table-wrap').scrollLeft > 0);
  await page.emulateMedia({media:'print'});
  assert.equal(await background(page),'rgb(248, 247, 243)');
  assert.equal(await page.locator('#appearance').inputValue(),mode);
  assert.deepEqual(await page.locator('tbody').allTextContents(),tables);
  await page.emulateMedia({media:'screen'});
  await page.addStyleTag({content:'html{font-size:200% !important}'});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true);
  await page.locator('#appearance').selectOption(mode === 'clair' ? 'obscur' : 'clair');
  assert.deepEqual(await page.locator('tbody').allTextContents(),tables);
  await page.reload();
  assert.equal(await page.locator('#appearance').inputValue(),mode === 'clair' ? 'obscur' : 'clair');
  await page.getByRole('link',{name:'Earlier process study',exact:true}).click();
  assert.equal(new URL(page.url()).pathname,'/parallel-scaling.html');
  await page.goBack();
  assert.deepEqual(await page.locator('tbody').allTextContents(),tables);
  const noScript = await fixture(t,{javaScriptEnabled:false,colorScheme:mode === 'obscur' ? 'dark' : 'light'});
  await noScript.goto(base+'/same-forest.html');
  assert.deepEqual(await noScript.locator('tbody').allTextContents(),tables);
  assert.equal(await background(noScript),mode === 'obscur' ? 'rgb(9, 9, 9)' : 'rgb(248, 247, 243)');
});

test('Auto, prepaint preference, reload, selection and browser history stay independent', async t => {
  const page = await fixture(t, {colorScheme:'dark'});
  await ready(page);
  await page.locator('#interactive:visible').waitFor();
  assert.equal(await background(page), 'rgb(9, 9, 9)');
  await page.locator('#choice').selectOption('1');
  const before = await page.locator('#metrics').textContent();
  const table = await page.locator('#table').textContent();
  const url = page.url();
  const history = await page.evaluate(() => window.history.length);
  await page.locator('#appearance').selectOption('clair');
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  assert.equal(await page.locator('#metrics').textContent(), before);
  assert.equal(await page.locator('#table').textContent(), table);
  assert.equal(page.url(), url);
  assert.equal(await page.evaluate(() => window.history.length), history);
  // Inspect the root at the next inline script after the prepaint script, before
  // CSS or the rest of the page can run. This is separate from the final UI state.
  await page.route(url => url.pathname === '/index.html', async route => {
    const response = await route.fetch();
    const html = (await response.text()).replace('</script>', '</script><script>window.prepaintAppearance=document.documentElement.dataset.appearance</script>');
    await route.fulfill({response, body:html});
  });
  await page.goto(base+'/index.html?example=Pass');
  await page.locator('#interactive:visible').waitFor();
  assert.equal(await page.evaluate(() => window.prepaintAppearance), 'clair');
  assert.equal(await page.locator('#choice').inputValue(), '1');
  await page.reload();
  await page.locator('#interactive:visible').waitFor();
  assert.equal(await page.locator('#appearance').inputValue(), 'clair');
  await page.emulateMedia({colorScheme:'dark'});
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  await page.locator('#appearance').selectOption('auto');
  assert.equal(await background(page), 'rgb(9, 9, 9)');
  await page.emulateMedia({colorScheme:'light'});
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  await page.locator('#choice').selectOption('2');
  await page.goBack();
  assert.equal(await page.locator('#choice').inputValue(), '1');
  await page.goForward();
  assert.equal(await page.locator('#choice').inputValue(), '2');
  assert.equal(await page.locator('#example-link').getAttribute('href'), page.url());
});

test('blocked storage keeps an in-memory override and no-script Auto preserves evidence', async t => {
  const page = await fixture(t, {colorScheme:'light'}, true);
  await ready(page);
  await page.locator('#appearance').selectOption('obscur');
  assert.equal(await background(page), 'rgb(9, 9, 9)');
  await page.reload();
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  const noScript = await fixture(t, {javaScriptEnabled:false, colorScheme:'dark'});
  await noScript.goto(base);
  assert.equal(await background(noScript), 'rgb(9, 9, 9)');
  assert.equal(await noScript.locator('#appearance').isDisabled(), true);
  await noScript.locator('#decision-figure img:visible').scrollIntoViewIfNeeded();
  assert.equal(await noScript.locator('#decision-figure img:visible').evaluate(async e => { await e.decode(); return e.naturalWidth > 0; }), true);
  assert.equal(await noScript.locator('#decision-figure a[href="data.json"]').count(), 1);
  assert.equal(await noScript.locator('#decision-figure a[href="example.svg"]').count(), 1);
  await noScript.emulateMedia({colorScheme:'light'});
  assert.equal(await background(noScript), 'rgb(248, 247, 243)');
});

for (const mode of ['clair','obscur']) test(`${mode} preserves every action, figure and keyboard/narrow layouts`, async t => {
  const page = await fixture(t);
  await ready(page);
  await page.locator('#interactive:visible').waitFor();
  const data = await (await page.request.get(base+'/data.json')).json();
  await page.locator('#appearance').selectOption(mode);
  for (const [index, action] of data.actions.entries()) {
    await page.locator('#choice').selectOption(String(index));
    const values = await page.locator('.metric strong').allTextContents();
    assert.deepEqual(values, [action.reward.toFixed(3), action.visits.toLocaleString('en-US'),
      (Math.round(1000 * action.visits / data.actions.reduce((sum, a) => sum + a.visits, 0)) / 10).toFixed(1)+'%']);
  }
  assert.equal(await page.locator('#table tbody tr').count(), data.actions.length);
  assert.match(await page.locator('#context').textContent(), /safety cap not reached/);
  assert.match(await page.locator('main').textContent(), /not a probability of winning/);
  assert.equal(await page.locator('#decision-figure img:visible').evaluate(e => getComputedStyle(e).filter), 'none');
  await capture(page, `${mode}-wide`);
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  assert.equal(await page.locator('tbody td:nth-child(3)').first().evaluate(e => getComputedStyle(e).whiteSpace), 'nowrap');
  await page.locator('#appearance').focus();
  assert.equal(await page.evaluate(() => document.activeElement.id), 'appearance');
  assert.equal(await page.locator('#appearance').evaluate(e => getComputedStyle(e).outlineStyle), 'solid');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.getAttribute('href')),
    'https://github.com/T92T1914/mcts-combat-engine#run-it');
  await page.locator('#choice').focus();
  await page.keyboard.press('Home');
  await page.keyboard.press('ArrowDown');
  assert.equal(await page.locator('#choice').inputValue(), '1');
  await capture(page, `${mode}-narrow`);
  // Increase the root text size so rem-based headings and labels scale too.
  await page.addStyleTag({content:'html{font-size:200% !important}'});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#table').focus();
  assert.equal(await page.locator('#table').evaluate(e => getComputedStyle(e).outlineStyle), 'solid');
  await capture(page, `${mode}-large-text`);
});

test('print and forced colors keep readable roles without saving a different preference', async t => {
  const page = await fixture(t);
  await ready(page);
  await page.locator('#appearance').selectOption('obscur');
  await page.emulateMedia({media:'print'});
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  assert.equal(await page.evaluate(() => localStorage.getItem('mcts-combat-engine.appearance.v1')), 'obscur');
  await page.emulateMedia({media:'screen', forcedColors:'active'});
  assert.equal(await page.evaluate(() => matchMedia('(forced-colors: active)').matches), true);
  await page.locator('#choice').focus();
  assert.equal(await page.locator('#choice').evaluate(e => getComputedStyle(e).outlineStyle), 'solid');
  await page.emulateMedia({forcedColors:'none'});
  assert.equal(await background(page), 'rgb(9, 9, 9)');
});

test('the deliberately missing face remains a separate readable fallback', async t => {
  const page = await fixture(t);
  await ready(page);
  await page.evaluate(() => {
    const p = document.createElement('p'); p.id='missing-face';
    p.style.fontFamily='"MCTS deliberately absent face", Arial, sans-serif';
    p.textContent='Readable fallback 123'; document.body.append(p);
  });
  const providers = await fonts(page, '#missing-face');
  assert.ok(providers.length > 0);
  assert.ok(providers.every(f => !f.postScriptName.startsWith('Inter')));
  console.log('Separate missing-font fallback:', JSON.stringify(providers));
});

test('controlled installed Inter provides all six faces and ordinary content uses the intended weights',
  {skip:process.env.MCTS_REQUIRE_INTER !== '1'}, async t => {
  const page = await fixture(t);
  await ready(page);
  await page.locator('#interactive:visible').waitFor();
  const faces = [[400,'normal','Inter-Regular'],[600,'normal','Inter-SemiBold'],[700,'normal','Inter-Bold'],
    [400,'italic','Inter-Italic'],[600,'italic','Inter-SemiBoldItalic'],[700,'italic','Inter-BoldItalic']];
  await page.evaluate(faces => {
    for (const [weight, style, name] of faces) {
      const sample = document.createElement('p'); sample.id=name;
      sample.style.fontWeight=String(weight); sample.style.fontStyle=style;
      sample.textContent='Search typography sample 123'; document.body.append(sample);
    }
  }, faces);
  await page.evaluate(() => document.fonts.ready);
  for (const mode of ['obscur','clair']) {
    await page.locator('#appearance').selectOption(mode);
    for (const [, , name] of faces) {
      const providers = await fonts(page, '#'+name);
      assert.ok(providers.some(f => f.postScriptName === name && f.glyphCount > 0), JSON.stringify({mode,name,providers}));
      assert.ok(providers.every(f => f.postScriptName === name), 'Latin specimen must not use fallback');
      console.log('Controlled font specimen:', JSON.stringify({mode,name,providers}));
    }
    for (const [selector, expected] of [['h1','Inter-Bold'],['.lead','Inter-Regular'],['label[for="appearance"]','Inter-SemiBold']]) {
      const providers = await fonts(page, selector);
      assert.ok(providers.some(f => f.postScriptName === expected && f.glyphCount > 0));
      console.log('Ordinary page content:', JSON.stringify({mode,selector,providers}));
    }
    await page.locator('details').evaluate(e => { e.open=true; });
    const codeFonts = await fonts(page, 'pre code');
    assert.ok(codeFonts.length > 0);
    assert.ok(codeFonts.every(f => !f.postScriptName.startsWith('Inter')));
  }
});

for (const mode of ['obscur','clair']) test(`${mode} process report keeps every saved cell, downloads and narrow layout`, async t => {
  const page = await fixture(t);
  await ready(page);
  await page.getByRole('link', {name:'Read the process scaling report'}).click();
  await page.locator('#appearance:not([disabled])').waitFor();
  await page.locator('#appearance').selectOption(mode);
  const tables = await page.locator('tbody').allTextContents();
  assert.deepEqual(await page.locator('tbody').evaluateAll(elements => elements.map(e => e.rows.length)), [4,54,54,54]);
  const raw = JSON.parse(await readFile(path.join(root, 'parallel-scaling-results.json'), 'utf8'));
  const measured = page.locator('.table-wrap').nth(1).locator('tbody tr');
  for (const [index, cell] of raw.cells.entries()) {
    const values = await measured.nth(index).locator('td').allTextContents();
    assert.deepEqual(values.slice(0,5), [cell.scenario,String(cell.search_seed),String(cell.workers),cell.phase,cell.elapsed_s.toFixed(6)]);
    assert.ok(values[7].startsWith(cell.ranked[0].label));
  }
  for (const name of ['parallel-scaling-results.json','parallel-scaling-results.md','parallel-scaling-protocol.json']) {
    assert.equal(await page.locator(`a[href="${name}"]`).count(), 1);
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(), 200);
    assert.deepEqual(await response.body(), await readFile(path.join(root, name)));
  }
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('link', {name:'Download raw results'}).click(),
  ]);
  assert.equal(download.suggestedFilename(), 'parallel-scaling-results.json');
  assert.deepEqual(await readFile(await download.path()), await readFile(path.join(root, 'parallel-scaling-results.json')));
  assert.match(await page.locator('main').textContent(), /No episodes or playing strength comparison ran/);
  assert.match(await page.locator('main').textContent(), /not pure IPC latency/);
  if (process.env.MCTS_SCREENSHOT_DIR) {
    await page.screenshot({path:path.join(process.env.MCTS_SCREENSHOT_DIR, `${mode}-process-wide.png`)});
    await capture(page, `${mode}-process-summary`, '.table-wrap[aria-label="Paired time ratios"]');
  }
  await page.setViewportSize({width:390,height:844});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.evaluate(() => scrollTo(0,0));
  if (process.env.MCTS_SCREENSHOT_DIR) {
    await page.screenshot({path:path.join(process.env.MCTS_SCREENSHOT_DIR, `${mode}-process-narrow.png`)});
  }
  await page.locator('#appearance').focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.textContent), 'Download raw results');
  await page.locator('.table-wrap').nth(1).focus();
  assert.equal(await page.locator('.table-wrap').nth(1).evaluate(e => getComputedStyle(e).outlineStyle), 'solid');
  await page.addStyleTag({content:'html{font-size:200% !important}'});
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true);
  await page.locator('#appearance').selectOption(mode === 'clair' ? 'obscur' : 'clair');
  assert.deepEqual(await page.locator('tbody').allTextContents(), tables);
  await page.reload();
  assert.equal(await page.locator('#appearance').inputValue(), mode === 'clair' ? 'obscur' : 'clair');
  if (process.env.MCTS_REQUIRE_INTER === '1') {
    for (const [selector, expected] of [['h1','Inter-Bold'],['main p:not(.eyebrow)','Inter-Regular'],['label[for="appearance"]','Inter-SemiBold']]) {
      const providers = await fonts(page, selector);
      assert.ok(providers.some(f => f.postScriptName === expected && f.glyphCount > 0));
      console.log('Report content glyphs:', JSON.stringify({mode:await page.locator('#appearance').inputValue(),selector,providers}));
    }
  }
  await page.getByRole('link', {name:'Decision explorer', exact:true}).click();
  await page.waitForURL(base+'/index.html');
  await page.locator('#parallel-study').waitFor();
  assert.equal(await page.locator('#parallel-study').count(), 1);
  await page.goBack();
  await page.waitForURL(base+'/parallel-scaling.html');
  await page.getByRole('heading', {name:'Fixed work process scaling', exact:true}).waitFor();
  assert.equal(await page.locator('h1').textContent(), 'Fixed work process scaling');
});

test('process report needs no script and handles unavailable storage and print separately', async t => {
  const noScript = await fixture(t, {javaScriptEnabled:false, colorScheme:'dark'});
  await noScript.goto(base+'/parallel-scaling.html');
  assert.equal(await background(noScript), 'rgb(9, 9, 9)');
  assert.equal(await noScript.locator('tbody tr').count(), 166);
  const page = await fixture(t, {colorScheme:'light'}, true);
  await ready(page, '/parallel-scaling.html');
  await page.locator('#appearance').selectOption('obscur');
  assert.equal(await background(page), 'rgb(9, 9, 9)');
  await page.emulateMedia({media:'print'});
  assert.equal(await background(page), 'rgb(248, 247, 243)');
  await page.emulateMedia({media:'screen'});
  assert.equal(await background(page), 'rgb(9, 9, 9)');
  await page.reload();
  assert.equal(await background(page), 'rgb(248, 247, 243)');
});


test('decision editions follow effective appearance, preserve scale and download exact SVGs', async t => {
  const page = await fixture(t, {colorScheme:'dark',viewport:{width:390,height:844}});
  await ready(page);
  const visible = page.locator('#decision-figure img:visible');
  assert.equal(await visible.getAttribute('src'), 'decision-obscur.png');
  const data = await (await page.request.get(base+'/data.json')).json();
  const receipt = await (await page.request.get(base+'/decision-figure.json')).json();
  assert.deepEqual(receipt.evidence.retained_decision, data);
  for (const mode of ['clair','obscur']) {
    await page.locator('#appearance').selectOption(mode);
    await page.emulateMedia({colorScheme:mode === 'clair' ? 'dark' : 'light'});
    assert.equal(await visible.count(), 1);
    assert.equal(await visible.getAttribute('src'), `decision-${mode}.png`);
    await visible.scrollIntoViewIfNeeded();
    await visible.evaluate(e => e.decode());
    assert.deepEqual(await visible.evaluate(e => [e.naturalWidth,e.naturalHeight]), [960,1960]);
    assert.equal(Math.round((await visible.boundingBox()).width), 350);
    assert.equal(await visible.evaluate(e => getComputedStyle(e).filter), 'none');
    await capture(page, `decision-${mode}-mobile`, '#decision-figure img:visible');
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.locator(`#decision-figure a[href="decision-${mode}.svg"]`).click(),
    ]);
    assert.equal(download.suggestedFilename(), `decision-${mode}.svg`);
    assert.deepEqual(await readFile(await download.path()), await readFile(path.join(root, `decision-${mode}.svg`)));
    await page.reload();
    assert.equal(await visible.getAttribute('src'), `decision-${mode}.png`);
  }
  await page.emulateMedia({media:'print'});
  assert.equal(await visible.getAttribute('src'), 'decision-clair.png');
  assert.equal(await page.locator('#appearance').inputValue(), 'obscur');
  await page.emulateMedia({media:'screen',colorScheme:'light'});
  await page.locator('#appearance').selectOption('auto');
  assert.equal(await visible.getAttribute('src'), 'decision-clair.png');
  await page.emulateMedia({colorScheme:'dark'});
  assert.equal(await visible.getAttribute('src'), 'decision-obscur.png');
  const noScript = await fixture(t, {javaScriptEnabled:false,colorScheme:'dark',viewport:{width:390,height:844}});
  await noScript.goto(base);
  const noScriptImage = noScript.locator('#decision-figure img:visible');
  assert.equal(await noScriptImage.getAttribute('src'), 'decision-obscur.png');
  await noScript.emulateMedia({colorScheme:'light'});
  assert.equal(await noScriptImage.getAttribute('src'), 'decision-clair.png');
});


test('wide figure follows its container and preserves every delivered file', async t => {
  const page = await fixture(t, {viewport:{width:1280,height:900},colorScheme:'dark'});
  await page.goto(base+'/'); await page.locator('#appearance:not([disabled])').waitFor();
  for (const mode of ['clair','obscur']) {
    await page.locator('#appearance').selectOption(mode);
    const visible=page.locator('#decision-figure img:visible');
    assert.equal(await visible.count(),1);
    assert.equal(await visible.getAttribute('src'),`decision-${mode}-wide.png`);
    await visible.scrollIntoViewIfNeeded(); await visible.evaluate(e=>e.decode());
    assert.deepEqual(await visible.evaluate(e=>[e.naturalWidth,e.naturalHeight]),[1800,1160]);
    const destination=process.env.MCTS_SCREENSHOT_DIR;
    if(destination){await mkdir(destination,{recursive:true});await visible.screenshot({path:path.join(destination,`decision-${mode}-wide.png`)});}
    await page.locator('#decision-figure').evaluate(e=>e.style.width='400px');
    assert.equal(await visible.getAttribute('src'),`decision-${mode}.png`);
    await page.locator('#decision-figure').evaluate(e=>e.style.removeProperty('width'));
    for(const suffix of ['','-wide'])for(const ext of ['png','svg']){
      const file=`decision-${mode}${suffix}.${ext}`;
      const response=await page.request.get(base+'/'+file);assert.equal(response.status(),200);
      assert.deepEqual(await response.body(),await readFile(path.join(root,file)));
    }
  }
});

for (const mode of ['clair','obscur']) test(`${mode} accepted evidence routes preserve source values and narrow reading`, async t => {
  const page = await fixture(t,{viewport:{width:390,height:844},colorScheme:'dark'});
  await ready(page);
  await page.locator('#appearance').selectOption(mode);
  // Exercise keyboard navigation so :focus-visible tests keyboard modality.
  // A mouse click followed by focus() does not request a keyboard focus ring.
  await page.locator('#appearance').focus();
  await page.keyboard.press('Tab');
  assert.equal(await page.getByRole('link',{name:'Run the Python project',exact:true})
    .evaluate(e=>document.activeElement===e),true);
  await page.keyboard.press('Tab');
  const entry = page.getByRole('link',{name:'Inspect the accepted evidence',exact:true});
  assert.equal(await entry.evaluate(e=>document.activeElement===e),true);
  await page.keyboard.press('Enter');
  assert.equal(new URL(page.url()).hash,'#accepted-evidence');
  const routes = page.locator('#accepted-evidence');
  const links = {
    'Install the engine and separate companion':'episode-companion.md',
    'Read the one-round and aggregation guide':'episode-reference.md',
    'Run the two-round adaptive example':'episode-adaptive-reference.md',
    'Download the modeled adaptive state':'adaptive-state.json',
    'Inspect the 8-versus-64 allowance study':'episode-search-allowance.md',
    'Read the same-work timing study':'request-edge-reuse.md',
  };
  for (const [label,name] of Object.entries(links)) {
    const link = routes.getByRole('link',{name:label,exact:true});
    assert.equal(await link.getAttribute('href'),name);
    await page.keyboard.press('Tab');
    assert.equal(await link.evaluate(e=>document.activeElement===e),true);
    assert.equal(await link.evaluate(e=>getComputedStyle(e).outlineStyle),'solid');
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(),200,name);
    assert.deepEqual(await response.body(),await readFile(path.join(root,name)),name);
  }
  // The newly exposed one-round guide links to the companion. Its existing
  // setup/inspection siblings are literal files, not a second guide renderer.
  for (const name of ['episode-record-replay.md','episode-inspection.md','episode-decision.md','episode-stability.md']) {
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(),200,name);
    assert.deepEqual(await response.body(),await readFile(path.join(root,name)),name);
  }
  const allowance = JSON.parse(await readFile(path.join(root,'search-allowance/results.json'),'utf8'));
  const fraction = allowance.deciding_gate.relative_reduction;
  const reduction = 100*Number(fraction.numerator)/Number(fraction.denominator);
  assert.ok((await routes.textContent()).includes(reduction.toFixed(2)+'%'));
  assert.match(await routes.textContent(),/22 improved, 3 worsened and 39 tied/);
  assert.match(await routes.textContent(),/adverse exploratory E2/);
  assert.match(await routes.textContent(),/Eight times the declared simulations/);
  assert.match(await routes.textContent(),/second choice can depend on the complete first-round observation/);
  assert.match(await routes.textContent(),/do not establish general optimal play or calibrated win odds/);

  const sourceName = 'request-edge-reuse/results.json';
  const sourceResponse = await page.request.get(base+'/'+sourceName);
  assert.equal(sourceResponse.status(),200);
  const sourceBytes = await sourceResponse.body();
  assert.deepEqual(sourceBytes,await readFile(path.join(root,sourceName)));
  const source = JSON.parse(sourceBytes.toString('utf8'));
  const receiptResponse = await page.request.get(base+'/request-edge-reuse-figure.json');
  assert.equal(receiptResponse.status(),200);
  const receiptBytes = await receiptResponse.body();
  assert.deepEqual(receiptBytes,await readFile(path.join(root,'request-edge-reuse-figure.json')));
  const receipt = JSON.parse(receiptBytes.toString('utf8'));
  assert.equal(receipt.source.revision,'56120034dcb34a9c1321eec5fc27437e5bc4deca');
  const sourceText = sourceBytes.toString('utf8').replace(/\r\n?/g,'\n');
  assert.equal(receipt.source.sha256,createHash('sha256').update(sourceText).digest('hex'));
  assert.equal(receipt.values.baseline,100);
  assert.equal(receipt.values.aggregate_ratio,source.geometric_mean_condition_median_paired_baseline_over_candidate);
  assert.equal(receipt.values.lower_search_time_percent.toFixed(2),(100*source.elapsed_reduction_from_geometric_mean_paired_ratio).toFixed(2));
  assert.equal(receipt.values.individual_timing_pairs,30);
  assert.equal(source.conditions.reduce((sum,c)=>sum+c.pairs.length,0),30);
  assert.equal(receipt.values.adverse_individual_pairs,source.adverse_individual_pairs.length);
  const expected = source.conditions.map(condition => {
    const ratios = condition.pairs.map(pair=>pair.baseline_seconds/pair.candidate_seconds).sort((a,b)=>a-b);
    const median = ratios[2];
    assert.equal(median,condition.median_paired_baseline_over_candidate);
    return [condition.controls.scenario[0].toUpperCase()+condition.controls.scenario.slice(1),
      String(condition.controls.horizon),String(median),(100/median).toFixed(2)];
  });
  assert.deepEqual(receipt.values.conditions.map(c=>[c.condition,String(c.median_baseline_over_candidate),c.relative_search_time.toFixed(2)]),
    expected.map(row=>[row[0]+', horizon '+row[1],row[2],row[3]]));
  const table = page.getByRole('region',{name:'Same-work relative search timing'});
  assert.deepEqual(await table.locator('tbody tr').evaluateAll(rows=>rows.map(row=>[...row.cells].map(cell=>cell.textContent))),expected);
  const study = page.locator('#request-edge-reuse-study');
  const before = await study.textContent();
  assert.match(before,/not raw milliseconds or confidence intervals/);
  assert.match(before,/11\.75% lower search time/);
  assert.match(before,/one shared Windows host/);
  assert.match(before,/two slower pairs remain in the data/);
  assert.match(before,/do not establish whole-command speed/);
  const visible = page.locator('#request-edge-reuse-figure img:visible');
  assert.equal(await visible.count(),1);
  assert.equal(await visible.getAttribute('src'),`request-edge-reuse-${mode}.png`);
  for (const row of expected) assert.ok((await visible.getAttribute('alt')).includes(row[3]));
  await visible.scrollIntoViewIfNeeded();
  await visible.evaluate(e=>e.decode());
  assert.deepEqual(await visible.evaluate(e=>[e.naturalWidth,e.naturalHeight]),[1440,1000]);
  for (const edition of ['clair','obscur']) for (const extension of ['png','svg']) {
    const name = `request-edge-reuse-${edition}.${extension}`;
    const response = await page.request.get(base+'/'+name);
    assert.equal(response.status(),200,name);
    const bytes = await response.body();
    assert.deepEqual(bytes,await readFile(path.join(root,name)),name);
    assert.equal(createHash('sha256').update(bytes).digest('hex'),receipt.editions[edition][extension].sha256);
    if (extension === 'svg') {
      assert.match(bytes.toString('utf8'),/<title[ >]/);
      assert.match(bytes.toString('utf8'),/<desc[ >]/);
      assert.match(bytes.toString('utf8'),/<text[ >]/);
    }
  }
  const [download] = await Promise.all([page.waitForEvent('download'),
    study.getByRole('link',{name:mode==='clair'?'Clair timing SVG':'Obscur timing SVG',exact:true}).click()]);
  assert.equal(download.suggestedFilename(),`request-edge-reuse-${mode}.svg`);
  assert.deepEqual(await readFile(await download.path()),await readFile(path.join(root,download.suggestedFilename())));
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  const contrast = await routes.evaluate(e=>{
    const style=getComputedStyle(e);
    const luminance=color=>{
      const channels=color.match(/[\d.]+/g).slice(0,3).map(Number).map(value=>{
        const channel=value/255;
        return channel<=0.04045?channel/12.92:((channel+0.055)/1.055)**2.4;
      });
      return 0.2126*channels[0]+0.7152*channels[1]+0.0722*channels[2];
    };
    const text=luminance(style.color),background=luminance(style.backgroundColor);
    return (Math.max(text,background)+0.05)/(Math.min(text,background)+0.05);
  });
  assert.ok(contrast>=4.5,`Evidence text contrast ${contrast}`);
  await page.setViewportSize({width:320,height:844});
  await page.addStyleTag({content:'html{font-size:200% !important}'});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
  await table.focus();
  await page.keyboard.press('ArrowRight');
  await page.waitForFunction(()=>document.querySelector('[aria-label="Same-work relative search timing"]').scrollLeft>0);
  assert.equal(await table.evaluate(e=>getComputedStyle(e).outlineStyle),'solid');
  await capture(page,`${mode}-accepted-evidence-narrow`,'#accepted-evidence');
  await capture(page,`${mode}-search-time-narrow`,'#request-edge-reuse-study');
  await page.locator('#appearance').selectOption(mode==='clair'?'obscur':'clair');
  assert.equal(await study.textContent(),before);
  assert.equal(await visible.getAttribute('src'),`request-edge-reuse-${mode==='clair'?'obscur':'clair'}.png`);
  await page.emulateMedia({media:'print'});
  assert.equal(await visible.getAttribute('src'),'request-edge-reuse-clair.png');
  const noScript = await fixture(t,{javaScriptEnabled:false,colorScheme:mode==='clair'?'light':'dark',viewport:{width:390,height:844}});
  await noScript.goto(base+'/');
  assert.equal(await noScript.locator('#accepted-evidence').isVisible(),true);
  assert.deepEqual(await noScript.getByRole('region',{name:'Same-work relative search timing'}).locator('tbody tr').evaluateAll(rows=>rows.map(row=>[...row.cells].map(cell=>cell.textContent))),expected);
  assert.equal(await noScript.locator('#request-edge-reuse-figure img:visible').getAttribute('src'),`request-edge-reuse-${mode}.png`);
  assert.match(await noScript.locator('#decision-figure').textContent(),/earlier saved decision from source a82e1a6/);
  assert.equal(await noScript.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
});
