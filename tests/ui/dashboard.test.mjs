/* Headless render check for the dashboard.
 * Loads the real index.html in jsdom, points fetch at the running server and
 * asserts the charts actually produced SVG with real data. */
import { JSDOM } from 'jsdom';

const BASE = 'http://127.0.0.1:8080';
let html = await (await fetch(BASE + '/')).text();
// jsdom won't fetch <script src>, so inline charts.js in-place. This keeps a
// single evaluation pass — re-evaluating the app script would blow up on
// `const` redeclaration and give a false failure.
const chartsSrc = await (await fetch(BASE + '/static/charts.js')).text();
html = html.replace('<script src="/static/charts.js"></script>',
                    '<script>' + chartsSrc + '</script>');

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  resources: undefined,
  url: BASE + '/',
  pretendToBeVisual: true,
});
const { window } = dom;
window.addEventListener('error', e=>console.log('!! window error:', e.message));
const vc = new (await import('jsdom')).VirtualConsole();


// jsdom has no fetch; proxy to the real server.
window.fetch = (url, opts) => fetch(url.startsWith('http') ? url : BASE + url, opts);
window.CSS = { escape: (s) => s };
window.scrollTo = () => {};
window.confirm = () => true;

// Wait for boot + data load.
await new Promise((r) => setTimeout(r, 5000));


const d = window.document;
const q = (s) => d.querySelector(s);
const fails = [];
function check(name, cond, extra) {
  console.log((cond ? '  ✅ ' : '  ❌ ') + name + (extra ? ' — ' + extra : ''));
  if (!cond) fails.push(name);
}

console.log('\n── connection & header ──');
check('connected', q('#conn').textContent === 'متصل', q('#conn').textContent);
check('date rendered', q('#date').textContent.length > 4, q('#date').textContent);
check('model line', q('#model').textContent.includes('نسخه'));

console.log('\n── stat tiles ──');
const stats = d.querySelectorAll('#stats .stat');
check('6 stat tiles', stats.length === 6, stats.length + ' tiles');
check('tiles have numbers', [...stats].every((s) => s.querySelector('.n').textContent.trim().length > 0));
console.log('     ' + [...stats].map((s) => s.querySelector('.l').textContent + '=' + s.querySelector('.n').textContent).join(' | '));

console.log('\n── charts ──');
const trend = q('#trendChart');
check('trend chart is SVG', !!trend.querySelector('svg'));
check('trend has 2 series paths', trend.querySelectorAll('path[stroke]').length === 2,
  trend.querySelectorAll('path[stroke]').length + ' lines');
check('trend has axis labels', trend.querySelectorAll('text').length > 0,
  trend.querySelectorAll('text').length + ' labels');
check('trend summary', q('#trendSummary').textContent.includes('ایجاد'), q('#trendSummary').textContent);

const donut = q('#statusDonut');
check('donut is SVG', !!donut.querySelector('svg'));
check('donut has arcs', donut.querySelectorAll('circle[stroke-dasharray]').length >= 1,
  donut.querySelectorAll('circle').length + ' circles');
check('donut centre %', donut.textContent.includes('٪'), donut.textContent.trim());
check('donut legend rows', d.querySelectorAll('#statusLegend .dl').length >= 1,
  d.querySelectorAll('#statusLegend .dl').length + ' rows');

check('priority bars', d.querySelectorAll('#priorityBars .hbar').length >= 1,
  d.querySelectorAll('#priorityBars .hbar').length + ' bars');

const heat = q('#heatmap');
check('heatmap is SVG', !!heat.querySelector('svg'));
check('heatmap has 56 cells', heat.querySelectorAll('rect').length === 56,
  heat.querySelectorAll('rect').length + ' cells');
check('heatmap total', q('#heatTotal').textContent.includes('رویداد'), q('#heatTotal').textContent);

console.log('\n── velocity ──');
check('velocity chips', d.querySelectorAll('#velocity .trend-chip').length === 2,
  q('#velocity').textContent.trim());

console.log('\n── urgent list ──');
const urgent = d.querySelectorAll('#urgentList .item');
check('urgent tasks rendered', urgent.length > 0, urgent.length + ' items');
check('no skeletons left', d.querySelectorAll('#urgentList .sk').length === 0);

console.log('\n── tab navigation ──');
async function tab(name) {
  d.querySelector(`nav.tabs button[data-v="${name}"]`).onclick();
  await new Promise((r) => setTimeout(r, 900));
}
await tab('projects');
const projItems = d.querySelectorAll('#projList .item');
check('projects rendered', projItems.length > 0, projItems.length + ' projects');
check('projects have progress bars', d.querySelectorAll('#projList .hbar-f').length > 0);

await tab('approvals');
check('approval summary bar', !!q('#apSummary .sbar'));
check('approval items', d.querySelectorAll('#apList .item').length > 0,
  d.querySelectorAll('#apList .item').length + ' pending');
check('approval rate shown', q('#apRate').textContent.includes('٪'), q('#apRate').textContent);

await tab('conn');
check('connections rendered', d.querySelectorAll('#connList .item').length > 0,
  d.querySelectorAll('#connList .item').length + ' services');

await tab('more');
check('decisions rendered', d.querySelectorAll('#memList .item').length > 0);
check('events rendered', d.querySelectorAll('#logList .ev').length > 0,
  d.querySelectorAll('#logList .ev').length + ' events');

await tab('tasks');
check('tasks rendered', d.querySelectorAll('#taskList .item').length > 0,
  d.querySelectorAll('#taskList .item').length + ' tasks');

console.log('\n── badge ──');
check('approval badge on tab', !!d.querySelector('nav.tabs button[data-v="approvals"] .nb'),
  (d.querySelector('nav.tabs button[data-v="approvals"] .nb') || {}).textContent);

console.log('\n── project dossier sheet ──');
window.openProject('giahkade');
await new Promise((r) => setTimeout(r, 900));
check('dossier opened', q('#projBack').classList.contains('open'));
check('dossier gauges', d.querySelectorAll('#ps-body .gitem svg').length > 0,
  d.querySelectorAll('#ps-body .gitem').length + ' gauges');
check('dossier title', q('#ps-title').textContent.includes('گیاهکده'), q('#ps-title').textContent);

const errors = [];
window.addEventListener('error', (e) => errors.push(e.message));

console.log('\n' + (fails.length ? `❌ ${fails.length} FAILED: ${fails.join(', ')}` : '✅ ALL UI CHECKS PASSED'));
process.exit(fails.length ? 1 : 0);
