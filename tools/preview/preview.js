#!/usr/bin/env node
// Screenshot mini-program pages with realistic data.
//   node tools/preview/preview.js all            # every page → tools/preview/out/<name>.png (+ _full.png)
//   node tools/preview/preview.js index plan_done
// Needs Playwright + Chromium (NODE_PATH pointing at a global playwright install) and
// tools/preview/mockdata.json (cd backend && python ../tools/preview/gen_mockdata.py).
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { page } = require('./render');
const { runPage } = require('./pagerun');

const M = JSON.parse(fs.readFileSync(path.join(__dirname, 'mockdata.json'), 'utf8'));
const G = M.group_id; const P = M.plan_id;
const group = { id: G, name: M.group.name, members: M.group.member_list.length, role: 'admin', invite_code: M.group.invite_code };
const app = { globalData: { user: M.me.user, groups: [group], groupId: G, meta: M.meta } };
const common = {
  [`/api/groups/${G}/inventory`]: M.inventory, [`/api/groups/${G}/plans`]: M.plans, '/api/notifications': M.notifications,
  '/api/me/nutrition': M.nutrition, '/api/me/targets': M.targets, '/api/me/twin': M.twin, '/api/me': M.me, '/api/meta': M.meta,
  [`/api/groups/${G}/expenses/report`]: M.report, [`/api/groups/${G}/expenses`]: M.expenses, [`/api/groups/${G}/nutrition`]: M.group_nutrition,
  [`/api/groups/${G}/twin`]: M.twin, [`/api/groups/${G}`]: M.group, [`/api/plans/${P}/shopping`]: M.shopping,
  [`/api/plans/${P}`]: M.plan, '/api/wiki/dishes': M.dishes,
};
const genEvents = M.plan.events.filter((e) => ['intent', 'agent', 'framework'].includes(e.type)).slice(0, 4);

const PAGES = {
  index: { tab: 0, run: () => runPage('index', { app, responses: { ...common, '/api/me/nutrition': M.nutrition_today } }) },
  inventory: { tab: 1, run: () => runPage('inventory', { app, responses: common }) },
  planner: { tab: 2, run: () => runPage('planner', { app, responses: common }) },
  budget: { tab: 3, run: () => runPage('budget', { app, responses: common }) },
  profile: { tab: 4, run: () => runPage('profile', { app, responses: common }) },
  plan_done: { page: 'plan', run: () => runPage('plan', { app, query: { id: P }, responses: common }) },
  plan_gen: { page: 'plan', run: () => runPage('plan', { app, query: { id: P }, responses: common, events: genEvents, end: false }) },
  shopping: { run: () => runPage('shopping', { app, query: { id: P }, responses: common }) },
  nutrition: { run: () => runPage('nutrition', { app, responses: common }) },
  twin: { run: () => runPage('twin', { app, responses: common }) },
  group: { run: () => runPage('group', { app, responses: common }) },
  notifications: { run: () => runPage('notifications', { app, responses: common }) },
  recognize: { run: () => runPage('recognize', { app, query: { kind: 'ingredients' }, responses: common,
    after: (inst) => inst.setRec && inst.setRec(JSON.parse(JSON.stringify(M.recognition))) }) },
};

(async () => {
  const args = process.argv.slice(2);
  const names = !args.length || args.includes('all') ? Object.keys(PAGES) : args;
  const outDir = process.env.PREVIEW_OUT || path.join(__dirname, 'out');
  fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch(fs.existsSync('/opt/pw-browsers/chromium') ? { executablePath: '/opt/pw-browsers/chromium' } : {});
  for (const n of names) {
    const cfg = PAGES[n];
    if (!cfg) { console.error('unknown page', n, '— known:', Object.keys(PAGES).join(' ')); continue; }
    try {
      const data = await cfg.run();
      const html = page(cfg.page || n, data, { tab: cfg.tab });
      const file = path.join(outDir, `${n}.html`);
      fs.writeFileSync(file, html);
      const p = await browser.newPage({ viewport: { width: 375, height: 812 }, deviceScaleFactor: 2 });
      await p.goto('file://' + file);
      await p.evaluate(() => document.fonts.ready);
      await p.waitForTimeout(700); // let entrance animations settle
      await p.screenshot({ path: path.join(outDir, `${n}.png`) });
      await p.addStyleTag({ content: '.tb{display:none!important}' }); // fixed tab bar would cover mid-page content
      await p.screenshot({ path: path.join(outDir, `${n}_full.png`), fullPage: true });
      await p.close();
      console.log('ok', n, '→', path.join(outDir, `${n}.png`));
    } catch (e) {
      console.error('FAILED', n, e && e.stack ? e.stack.split('\n').slice(0, 3).join(' | ') : e);
    }
  }
  await browser.close();
})();
