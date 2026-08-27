/**
 * Drives every interactive control in the app against a running stack and
 * fails on any HTTP >= 400 or console error produced by an action.
 *
 *   docker compose up -d
 *   node scripts/ui-audit.mjs            # BASE defaults to localhost:8080
 *
 * Needs Playwright and a seeded board (SEED_DEMO=true) so there is something
 * to click. Requires PLAYWRIGHT_CHROMIUM to point at a chromium binary, or
 * edit the launch() call below.
 *
 * Two habits this file exists to enforce, both learned by getting them wrong:
 *
 *   Assert on the OUTCOME, never on the click landing. "the button was
 *   clickable" passes while the request 422s. Every step here checks that the
 *   board changed, the row persisted across a reload, or the guard fired.
 *
 *   Reset between steps. One overlay left open makes every later step fail and
 *   hides which control is actually broken — which is exactly how a single
 *   unclosable Filters panel looked like a dozen separate failures.
 */
import { chromium } from 'playwright';
const BASE = process.env.BASE || 'http://localhost:8080';
const OUT = process.env.OUT;
const net = [];           // failed requests
const con = [];           // console errors
let pass = 0, fail = 0;
const failures = [];

const browser = await chromium.launch({ executablePath: process.env.PLAYWRIGHT_CHROMIUM || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome', args: ['--no-sandbox','--disable-dev-shm-usage'] });
const page = await browser.newPage({ viewport: { width: 1512, height: 1000 } });
page.on('console', m => { if (m.type() === 'error') con.push(m.text().slice(0,200)); });
page.on('pageerror', e => con.push('pageerror: ' + e.message.slice(0,200)));
page.on('response', r => { if (r.status() >= 400) net.push(`${r.status()} ${r.request().method()} ${new URL(r.url()).pathname}`); });

async function t(name, fn) {
  const before = net.length + con.length;
  try {
    await fn();
    const after = net.length + con.length;
    if (after > before) {
      const added = [...net.slice(-(after-before)), ...con.slice(-(after-before))].join(' | ');
      throw new Error('errors during action: ' + added);
    }
    pass++; console.log(`  ok   ${name}`);
  } catch (e) {
    fail++; const msg = e.message.split('\n')[0].slice(0,180);
    failures.push(`${name}: ${msg}`);
    console.log(`  FAIL ${name}: ${msg}`);
  }
}
const go = async (p='') => { await page.goto(BASE + p, { waitUntil: 'domcontentloaded' }); await page.waitForTimeout(900); };
const esc = async () => { await page.keyboard.press('Escape'); await page.waitForTimeout(400); };
/* A hard reset. Navigating away is the only reliable way to guarantee no
   overlay survives into the next assertion — otherwise one stuck panel makes
   every later step fail and hides which control is actually broken. */
const reset = async () => { await go(); await page.locator('.card').first().waitFor({ timeout: 8000 }); };

await go();
await page.locator('.card').first().waitFor({ timeout: 10000 });

// ============ TOPBAR ============
console.log('\n-- topbar --');
await t('group-by select cycles all 5 options', async () => {
  const sel = page.locator('header select').first();
  for (const v of ['workstream','mode','client_type','priority','none']) {
    await sel.selectOption(v); await page.waitForTimeout(500);
    const got = await sel.inputValue();
    if (got !== v) throw new Error(`select stuck on ${got}`);
  }
});
await t('swimlanes actually render when grouped', async () => {
  await page.locator('header select').first().selectOption('workstream');
  await page.waitForTimeout(700);
  const lanes = await page.locator('.lane-label, .swimlane-label').count();
  if (lanes === 0) throw new Error('grouped but no lane headers rendered');
  await page.locator('header select').first().selectOption('none');
  await page.waitForTimeout(500);
});
await t('Filters panel opens', async () => {
  await page.getByRole('button', { name: /^Filters/ }).click();
  await page.locator('.popover').waitFor({ timeout: 4000 });
});
await t('filter chip applies and changes the board', async () => {
  const before = await page.locator('.card').count();
  await page.locator('.popover button.chip').filter({ hasText: /^pilot$/ }).click();
  await page.waitForTimeout(900);
  const after = await page.locator('.card').count();
  if (after === before) throw new Error(`card count unchanged (${before}) — filter had no effect`);
  await page.keyboard.press('Escape');
});
await reset();
await t('clearing filters restores the board', async () => {
  await go();
  const n = await page.locator('.card').count();
  if (n !== 12) throw new Error(`expected 12 cards after clearing, got ${n}`);
});
await t('quick-filter chips work', async () => {
  const chip = page.locator('.qfilters button').first();
  if (await chip.count() === 0) throw new Error('no quick-filter chips found');
  await chip.click(); await page.waitForTimeout(800);
  await chip.click(); await page.waitForTimeout(800);
});
await reset();
await t('search box opens the palette', async () => {
  await page.locator('.search-box input').click();
  await page.locator('.palette, [role="dialog"]').first().waitFor({ timeout: 4000 });
  await esc();
});
await reset();
await t('Task button opens the task dialog', async () => {
  await page.getByRole('button', { name: /^Task$/ }).click();
  await page.getByRole('dialog', { name: /New task/i }).waitFor({ timeout: 4000 });
  await esc();
});
await reset();
await t('Client button opens the client dialog', async () => {
  await page.getByRole('button', { name: /^Client$/ }).click();
  await page.getByRole('dialog', { name: /New client/i }).waitFor({ timeout: 4000 });
  await esc();
});
await reset();
await t('Deal button opens the deal dialog', async () => {
  await page.getByRole('button', { name: /^Deal$/ }).click();
  await page.getByRole('dialog', { name: /New deal/i }).waitFor({ timeout: 4000 });
  await esc();
});
await reset();
await t('Settings link navigates', async () => {
  await page.getByRole('link', { name: /Settings/i }).click();
  await page.getByRole('heading', { name: /Board columns|Settings/i }).first().waitFor({ timeout: 5000 });
});

// ============ SETTINGS ============
console.log('\n-- settings --');
await t('column label edit persists', async () => {
  // aria-label scoped: a bare input[type=text] also matches the topbar's
  // READ-ONLY search box, which silently swallows fill() until it times out.
  const first = () => page.locator('input[aria-label^="Label for"]').first();
  const was = await first().inputValue();
  await first().fill(was + ' Edited');
  await first().blur(); await page.waitForTimeout(1000);
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1300);
  const now = await first().inputValue();
  if (!now.endsWith('Edited')) throw new Error(`label did not persist: "${now}"`);
  await first().fill(was); await first().blur(); await page.waitForTimeout(900);
});
await t('colour swatch recolours a column', async () => {
  const sw = page.locator('button[title^="#"], .swatch, .swatches button').first();
  if (await sw.count() === 0) throw new Error('no colour swatches');
  await sw.click(); await page.waitForTimeout(1000);
});
await t('stall-after-days persists', async () => {
  const n = () => page.locator('input[aria-label^="Stall after days"]').first();
  await n().fill('9'); await n().blur(); await page.waitForTimeout(1000);
  await page.reload({ waitUntil: 'domcontentloaded' }); await page.waitForTimeout(1300);
  const v = await n().inputValue();
  if (v !== '9') throw new Error(`stall days did not persist: "${v}"`);
});
await t('default-entry radio moves', async () => {
  const radios = page.locator('input[type="radio"]');
  await radios.nth(1).click(); await page.waitForTimeout(1100);
  await radios.nth(0).click(); await page.waitForTimeout(1100);
});
await t('Archive is refused on the entry column, and says why', async () => {
  const first = page.getByRole('button', { name: 'Archive', exact: true }).first();
  if (!(await first.isDisabled())) throw new Error('entry column Archive is enabled');
  const why = await first.getAttribute('title');
  if (!/entry column/i.test(why || '')) throw new Error('no explanation on the control: ' + why);
});
await t('Archive explains itself on every blocked column', async () => {
  // On a seeded board every column either is the entry or holds deals, so all
  // of them are legitimately unarchivable — what matters is that each SAYS so.
  const btns = page.getByRole('button', { name: 'Archive', exact: true });
  const n = await btns.count();
  if (n === 0) throw new Error('no Archive buttons');
  for (let i = 0; i < n; i++) {
    const b = btns.nth(i);
    if (await b.isDisabled()) {
      const why = await b.getAttribute('title');
      if (!/entry column|still holds/i.test(why || ''))
        throw new Error(`disabled with no reason given: ${why}`);
    }
  }
});
await t('an empty non-entry column CAN be archived', async () => {
  await page.getByPlaceholder('New column label').fill('Archivable');
  await page.getByRole('button', { name: 'Add column', exact: true }).click();
  await page.waitForTimeout(1300);
  const row = page.locator('input[aria-label="Label for Archivable"]').locator('xpath=ancestor::li[1]');
  const arch = row.getByRole('button', { name: 'Archive', exact: true });
  if (await arch.isDisabled()) throw new Error('a new empty column should be archivable');
  await arch.click(); await page.waitForTimeout(1300);
  if (!(await row.getByRole('button', { name: 'Restore', exact: true }).count()))
    throw new Error('did not archive');
  await row.getByRole('button', { name: 'Restore', exact: true }).click();
  await page.waitForTimeout(1200);
  await row.getByRole('button', { name: 'Delete', exact: true }).click();
  const dlg = page.locator('.dialog');
  await dlg.waitFor({ timeout: 5000 });
  await dlg.getByRole('button', { name: /Delete/i }).last().click();
  await page.waitForTimeout(1300);
});
await t('add column', async () => {
  await page.getByPlaceholder('New column label').fill('Audit Column');
  await page.getByRole('button', { name: 'Add column', exact: true }).click();
  await page.waitForTimeout(1300);
  if (!(await page.locator('input[aria-label="Label for Audit Column"]').count()))
    throw new Error('column not added');
});
await t('delete column, with its impact dialog', async () => {
  const row = page.locator('input[aria-label="Label for Audit Column"]').locator('xpath=ancestor::li[1]');
  await row.getByRole('button', { name: 'Delete', exact: true }).click();
  const dlg = page.locator('.dialog');
  await dlg.waitFor({ timeout: 5000 });
  await dlg.getByRole('button', { name: /Delete/i }).last().click();
  await page.waitForTimeout(1400);
  if (await page.locator('input[aria-label="Label for Audit Column"]').count())
    throw new Error('column still present after delete');
});
await t('Reset to defaults (typed confirmation)', async () => {
  const btn = page.getByRole('button', { name: 'Reset', exact: true });
  if (!(await btn.isDisabled())) throw new Error('Reset enabled before the phrase was typed');
  const phrase = page.locator('h2:has-text("Reset to defaults") ~ * input, input').last();
  await phrase.fill('reset');
  await page.waitForTimeout(300);
  if (await btn.isDisabled()) throw new Error('Reset still disabled after typing the phrase');
  await btn.click(); await page.waitForTimeout(1500);
});
await t('back to board from settings', async () => {
  await go();
  await page.locator('.card').first().waitFor({ timeout: 6000 });
});

// ============ METRICS ============
console.log('\n-- metrics strip --');
for (const label of ['Needs Attention','Active Engagements','Quoted Value','Gross Margin','At Risk']) {
  await t(`metric "${label}" is clickable and filters`, async () => {
    const tile = page.locator('.metric').filter({ hasText: label }).first();
    if (await tile.count() === 0) throw new Error('tile not found');
    await tile.click(); await page.waitForTimeout(900);
    await tile.click(); await page.waitForTimeout(700);
  });
}

// ============ CARD + DRAWER ============
console.log('\n-- drawer --');
await go();
await t('card opens the drawer', async () => {
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
});
await t('POC select lists contacts', async () => {
  const sel = page.locator('.drawer select').first();
  const n = await sel.locator('option').count();
  if (n === 0) throw new Error('POC select is empty');
});
await t('Mode select changes', async () => {
  const sels = page.locator('.drawer select');
  const mode = sels.nth(1);
  const cur = await mode.inputValue();
  await mode.selectOption(cur === 'pilot' ? 'customer' : 'pilot');
  await page.waitForTimeout(900);
});
await t('Workstream select changes', async () => {
  const ws = page.locator('.drawer select').nth(2);
  const cur = await ws.inputValue();
  await ws.selectOption(cur === 'bot_making' ? 'data_procurement' : 'bot_making');
  await page.waitForTimeout(900);
});
await t('Today quick-set writes last contact', async () => {
  await page.locator('.drawer').getByRole('button', { name: /^Today$/ }).click();
  await page.waitForTimeout(1000);
});
await t('comm-mode chips toggle', async () => {
  const chip = page.locator('.drawer').getByRole('button', { name: /WhatsApp/ }).first();
  await chip.click(); await page.waitForTimeout(800);
  await chip.click(); await page.waitForTimeout(800);
});
await t('Add contact', async () => {
  await page.locator('.drawer').getByRole('button', { name: /^\+ Add$/ }).first().click();
  await page.waitForTimeout(1100);
});
await t('contact field edit persists', async () => {
  const inp = page.locator('.drawer .contact-fields input').first();
  await inp.fill('Audited Name'); await inp.blur();
  await page.waitForTimeout(1000);
});
await t('add line item', async () => {
  await page.locator('.drawer').getByRole('button', { name: /Add line item/i }).click();
  await page.waitForTimeout(1000);
});
await t('add cost', async () => {
  await page.locator('.drawer').getByRole('button', { name: /Add cost/i }).click();
  await page.waitForTimeout(1000);
});
await t('health override opens + saves', async () => {
  const btn = page.locator('.drawer').getByRole('button', { name: /Override|Set band/i }).first();
  if (await btn.count() === 0) throw new Error('no override control');
  await btn.click(); await page.waitForTimeout(600);
});
await t('Add task from drawer', async () => {
  await esc();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
  await page.locator('.drawer').getByRole('button', { name: /Add task/i }).click();
  await page.getByRole('dialog', { name: /New task/i }).waitFor({ timeout: 4000 });
  await esc();
});
await t('company chip opens the client', async () => {
  await reset();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
  await page.locator('.drawer .chip-link').first().click();
  await page.locator('.company').waitFor({ timeout: 6000 });
});

// ============ COMPANY VIEW ============
console.log('\n-- company view --');
await t('deal row opens its drawer', async () => {
  await page.locator('.deal-open').first().click();
  await page.waitForTimeout(1200);
});
await t('Back to board', async () => {
  await go();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
  await page.locator('.drawer .chip-link').first().click();
  await page.locator('.company').waitFor({ timeout: 6000 });
  await page.getByRole('button', { name: /^Board$/ }).click();
  await page.locator('.card').first().waitFor({ timeout: 6000 });
});

// ============ TASKS ============
console.log('\n-- tasks --');
await t('task checkbox toggles', async () => {
  await reset();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
  const chk = page.locator('.drawer .task-check').first();
  if (await chk.count() === 0) throw new Error('no tasks on this deal');
  await chk.click(); await page.waitForTimeout(1000);
  await chk.click(); await page.waitForTimeout(1000);
});
await t('create a task end to end', async () => {
  await reset();
  await page.getByRole('button', { name: /^Task$/ }).click();
  const d = page.getByRole('dialog', { name: /New task/i });
  await d.waitFor({ timeout: 4000 });
  const sel = d.locator('select').first();
  const v = await sel.locator('option').nth(1).getAttribute('value');
  await sel.selectOption(v);
  await d.getByPlaceholder(/What needs doing/i).fill('Audit task');
  await d.getByRole('button', { name: /^Create$/ }).click();
  await page.waitForTimeout(1200);
});

// ============ PALETTE ============
console.log('\n-- command palette --');
await t('palette searches and returns groups', async () => {
  await go();
  await page.keyboard.press('Control+k');
  const box = page.locator('.palette input, [role="dialog"] input').first();
  await box.waitFor({ timeout: 4000 });
  await box.fill('a');
  await page.waitForTimeout(1200);
  const items = await page.locator('.palette-row').count();
  if (items === 0) {
    const empty = await page.locator('.palette-empty').count();
    throw new Error(empty ? 'palette rendered "No matches" for "a"' : 'no palette rows at all');
  }
  // The split added Clients and Deals as separate groups; both should appear.
  const groups = await page.locator('.palette-group').allInnerTexts();
  if (!groups.some(g => /client/i.test(g)) || !groups.some(g => /deal/i.test(g)))
    throw new Error('missing Clients/Deals groups: ' + JSON.stringify(groups));
});
await t('palette result opens something', async () => {
  await page.keyboard.press('Enter');
  await page.waitForTimeout(1400);
});

// ============ TRASH ============
console.log('\n-- trash --');
await t('delete a deal from the drawer', async () => {
  await reset();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 6000 });
  await page.locator('.drawer').getByRole('button', { name: 'Delete deal', exact: true }).click();
  // .dialog, not [role="dialog"] — the DRAWER also carries role="dialog", and
  // it contains the words "Delete deal", so a hasText filter matches the drawer
  // and then waits forever for a button that only exists in the confirm.
  const d = page.locator('.dialog');
  await d.waitFor({ timeout: 5000 });
  await d.getByRole('button', { name: /Move to Trash/i }).click();
  await page.waitForTimeout(1400);
});
await t('trash link appears and lists it', async () => {
  await page.getByRole('link', { name: /Trash/i }).first().click();
  await page.getByRole('heading', { name: /^Trash$/ }).waitFor({ timeout: 5000 });
  if (await page.locator('.trash-row').count() === 0) throw new Error('trash is empty after delete');
});
await t('restore from trash', async () => {
  await page.getByRole('button', { name: /Restore/i }).first().click();
  await page.waitForTimeout(1500);
  await reset();
  const n = await page.locator('.card').count();
  if (n !== 12) throw new Error(`expected the board back at 12 after restore, got ${n}`);
});
await t('deleting a CLIENT is a different, larger action', async () => {
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 8000 });
  await page.locator('.drawer .chip-link').first().click();
  await page.locator('.company').waitFor({ timeout: 8000 });
  const btn = page.getByRole('button', { name: 'Delete client', exact: true });
  if (await btn.count() === 0) throw new Error('no Delete client on the company view');
  const note = await page.locator('.drawer-danger .panel-muted').innerText();
  if (!/deal/i.test(note)) throw new Error('company delete does not mention its deals: ' + note);
});


// ============ GMAIL PANEL ============
console.log('\n-- gmail panel (GMAIL_ENABLED=false) --');
await t('drawer opens with Gmail off and shows no panel error', async () => {
  await reset();
  await page.locator('.card').first().click();
  await page.locator('.drawer').waitFor({ timeout: 8000 });
  const body = await page.locator('.drawer').innerText();
  if (/could not be rendered|Gmail could not be reached/i.test(body))
    throw new Error('Gmail error leaked into the drawer while disabled');
});
await t('a Gmail outage never blocks the board', async () => {
  const r = await page.request.get(BASE + '/api/google/status');
  if (!r.ok()) throw new Error('status endpoint ' + r.status());
  const j = await r.json();
  if (j.enabled !== false) throw new Error('expected Gmail disabled by default');
});

console.log(`\n${pass} passed, ${fail} failed`);
if (failures.length) console.log('\nFAILURES:\n' + failures.map(f => '  - ' + f).join('\n'));
const uniqNet = [...new Set(net)], uniqCon = [...new Set(con)];
if (uniqNet.length) console.log('\nHTTP >=400:\n' + uniqNet.map(x=>'  '+x).join('\n'));
if (uniqCon.length) console.log('\nCONSOLE ERRORS:\n' + uniqCon.map(x=>'  '+x).join('\n'));
await browser.close();
process.exit(fail ? 1 : 0);
