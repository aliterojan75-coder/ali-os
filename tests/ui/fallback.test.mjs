/* Prove the dashboard still works when charts.js fails to load. */
import { JSDOM } from 'jsdom';
const BASE='http://127.0.0.1:8080';
let html=await (await fetch(BASE+'/')).text();
html=html.replace('<script src="/static/charts.js"></script>','');  // simulate a 404
const dom=new JSDOM(html,{runScripts:'dangerously',url:BASE+'/',pretendToBeVisual:true});
const {window}=dom;
window.fetch=(u,o)=>fetch(u.startsWith('http')?u:BASE+u,o);
window.CSS={escape:s=>s}; window.scrollTo=()=>{};
await new Promise(r=>setTimeout(r,5000));
const d=window.document;
const ok=[];
ok.push(['app still boots', d.querySelector('#conn').textContent==='متصل']);
ok.push(['stat tiles render', d.querySelectorAll('#stats .stat').length===6]);
ok.push(['numbers still Persian', /[۰-۹]/.test(d.querySelector('#stats .n').textContent)]);
ok.push(['urgent list renders', d.querySelectorAll('#urgentList .item').length>0]);
ok.push(['graceful chart message', d.querySelector('#trendChart').textContent.includes('در دسترس نیست')]);
ok.forEach(([n,c])=>console.log((c?'  ✅ ':'  ❌ ')+n));
process.exit(ok.every(x=>x[1])?0:1);
