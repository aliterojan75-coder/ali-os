/* Ali OS — tiny inline-SVG chart toolkit.
 *
 * Deliberately dependency-free: the dashboard must render on networks where
 * CDNs (and even telegram.org) are unreachable, and inside the Telegram
 * webview where every extra request costs visible latency. Everything below
 * is plain SVG strings — no canvas, no runtime, works offline, prints sharp.
 *
 * All functions return an SVG string; callers drop it straight into innerHTML.
 * Charts are viewBox-based so they scale fluidly to the container width.
 */
(function (global) {
  'use strict';

  const esc = (s) => String(s == null ? '' : s)
    .replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // Persian digits — the whole UI is fa-IR, numbers should match.
  const FA = ['۰', '۱', '۲', '۳', '۴', '۵', '۶', '۷', '۸', '۹'];
  function faNum(n) {
    if (n === null || n === undefined || n === '') return '—';
    return String(n).replace(/[0-9]/g, (d) => FA[+d]);
  }
  function compact(n) {
    if (n === null || n === undefined) return '—';
    const abs = Math.abs(n);
    if (abs >= 1e9) return faNum((n / 1e9).toFixed(1)) + ' میلیارد';
    if (abs >= 1e6) return faNum((n / 1e6).toFixed(1)) + ' میلیون';
    if (abs >= 1e3) return faNum(Math.round(n / 1e3)) + ' هزار';
    return faNum(Math.round(n));
  }

  let _uid = 0;
  const uid = (p) => `${p}${++_uid}`;

  /* ── Sparkline / dual-area line chart ─────────────────────────────────── */
  function lineChart(opts) {
    const {
      labels = [], series = [], height = 170,
      width = 340, showAxis = true,
    } = opts;
    const pad = { t: 12, r: 6, b: showAxis ? 20 : 6, l: 6 };
    const w = width, h = height;
    const iw = w - pad.l - pad.r, ih = h - pad.t - pad.b;

    const all = series.flatMap((s) => s.data);
    const max = Math.max(1, ...all);
    const n = Math.max(1, labels.length - 1);
    const x = (i) => pad.l + (i / n) * iw;
    const y = (v) => pad.t + ih - (v / max) * ih;

    // Smooth the polyline with a monotone-ish cubic so the chart reads as a
    // trend rather than a zigzag.
    function path(data) {
      if (!data.length) return '';
      if (data.length === 1) return `M${x(0)},${y(data[0])}`;
      let d = `M${x(0)},${y(data[0])}`;
      for (let i = 0; i < data.length - 1; i++) {
        const x0 = x(i), y0 = y(data[i]), x1 = x(i + 1), y1 = y(data[i + 1]);
        const cx = (x0 + x1) / 2;
        d += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
      }
      return d;
    }

    let gridLines = '';
    for (let g = 0; g <= 3; g++) {
      const gy = pad.t + (ih / 3) * g;
      gridLines += `<line x1="${pad.l}" y1="${gy}" x2="${w - pad.r}" y2="${gy}"
        stroke="rgba(255,255,255,.06)" stroke-width="1" ${g === 3 ? '' : 'stroke-dasharray="3 4"'}/>`;
    }

    let body = '';
    series.forEach((s) => {
      const gid = uid('g'), cid = uid('c');
      const p = path(s.data);
      const area = `${p} L${x(s.data.length - 1)},${pad.t + ih} L${x(0)},${pad.t + ih} Z`;
      const len = 700;
      body += `
        <defs>
          <linearGradient id="${gid}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="${s.color}" stop-opacity=".38"/>
            <stop offset="100%" stop-color="${s.color}" stop-opacity="0"/>
          </linearGradient>
        </defs>
        <path d="${area}" fill="url(#${gid})">
          <animate attributeName="opacity" from="0" to="1" dur=".7s" fill="freeze"/>
        </path>
        <path d="${p}" fill="none" stroke="${s.color}" stroke-width="2.5"
              stroke-linecap="round" stroke-linejoin="round"
              stroke-dasharray="${len}" stroke-dashoffset="${len}">
          <animate attributeName="stroke-dashoffset" from="${len}" to="0" dur=".9s"
                   fill="freeze" calcMode="spline" keySplines=".25 .1 .25 1" keyTimes="0;1"/>
        </path>`;
      // Emphasise the most recent point — that's the one Ali cares about.
      const li = s.data.length - 1;
      if (li >= 0) {
        body += `<circle cx="${x(li)}" cy="${y(s.data[li])}" r="4" fill="${s.color}"
                   stroke="#0f1524" stroke-width="2">
                   <animate attributeName="r" from="0" to="4" dur=".4s" begin=".8s" fill="freeze"/>
                 </circle>`;
      }
    });

    let axis = '';
    if (showAxis && labels.length) {
      const step = Math.ceil(labels.length / 5);
      labels.forEach((lb, i) => {
        if (i % step !== 0 && i !== labels.length - 1) return;
        axis += `<text x="${x(i)}" y="${h - 5}" fill="rgba(255,255,255,.38)"
                   font-size="9" text-anchor="middle">${esc(faNum(lb))}</text>`;
      });
    }

    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}"
              preserveAspectRatio="none" role="img">${gridLines}${body}${axis}</svg>`;
  }

  /* ── Donut ────────────────────────────────────────────────────────────── */
  function donut(opts) {
    const { data = [], size = 132, thickness = 15, centerLabel = '', centerValue = '' } = opts;
    const total = data.reduce((a, d) => a + d.value, 0);
    const r = (size - thickness) / 2;
    const c = size / 2;
    const circ = 2 * Math.PI * r;

    if (!total) {
      return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}">
        <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="rgba(255,255,255,.07)" stroke-width="${thickness}"/>
        <text x="${c}" y="${c + 4}" text-anchor="middle" fill="rgba(255,255,255,.35)" font-size="11">بدون داده</text>
      </svg>`;
    }

    let offset = 0, arcs = '';
    data.forEach((d, i) => {
      const frac = d.value / total;
      const len = frac * circ;
      arcs += `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${d.color}"
        stroke-width="${thickness}" stroke-linecap="round"
        stroke-dasharray="${len} ${circ - len}" stroke-dashoffset="${-offset}"
        transform="rotate(-90 ${c} ${c})" opacity="0">
        <animate attributeName="opacity" from="0" to="1" dur=".35s" begin="${i * 0.09}s" fill="freeze"/>
      </circle>`;
      offset += len;
    });

    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img">
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="rgba(255,255,255,.05)" stroke-width="${thickness}"/>
      ${arcs}
      <text x="${c}" y="${c - 1}" text-anchor="middle" fill="#eef2fb" font-size="21" font-weight="800">${esc(centerValue)}</text>
      <text x="${c}" y="${c + 15}" text-anchor="middle" fill="rgba(255,255,255,.45)" font-size="9.5">${esc(centerLabel)}</text>
    </svg>`;
  }

  /* ── Radial gauge (single KPI) ────────────────────────────────────────── */
  function gauge(opts) {
    const { percent = 0, size = 96, thickness = 9, label = '', color = '#6c8cff' } = opts;
    const pct = Math.max(0, Math.min(percent, 100));
    const r = (size - thickness) / 2;
    const c = size / 2;
    // 270° sweep, leaving a gap at the bottom.
    const circ = 2 * Math.PI * r;
    const sweep = circ * 0.75;
    const len = sweep * (pct / 100);

    return `<svg viewBox="0 0 ${size} ${size}" width="${size}" height="${size}" role="img">
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="rgba(255,255,255,.07)"
        stroke-width="${thickness}" stroke-linecap="round"
        stroke-dasharray="${sweep} ${circ - sweep}" transform="rotate(135 ${c} ${c})"/>
      <circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${color}"
        stroke-width="${thickness}" stroke-linecap="round"
        stroke-dasharray="0 ${circ}" transform="rotate(135 ${c} ${c})">
        <animate attributeName="stroke-dasharray" from="0 ${circ}" to="${len} ${circ - len}"
                 dur=".9s" fill="freeze" calcMode="spline" keySplines=".2 .8 .2 1" keyTimes="0;1"/>
      </circle>
      <text x="${c}" y="${c + 2}" text-anchor="middle" fill="#eef2fb" font-size="17" font-weight="800">${esc(faNum(Math.round(pct)))}٪</text>
      <text x="${c}" y="${c + 16}" text-anchor="middle" fill="rgba(255,255,255,.42)" font-size="8.5">${esc(label)}</text>
    </svg>`;
  }

  /* ── Horizontal bars ──────────────────────────────────────────────────── */
  function barList(opts) {
    const { data = [], showValue = true, unit = '' } = opts;
    if (!data.length) return '<div class="empty">داده‌ای نیست</div>';
    const max = Math.max(1, ...data.map((d) => d.value));
    return data.map((d, i) => {
      const pct = (d.value / max) * 100;
      const color = d.color || '#6c8cff';
      return `<div class="hbar">
        <div class="hbar-l" title="${esc(d.label)}">${esc(d.label)}</div>
        <div class="hbar-t">
          <div class="hbar-f" style="--w:${pct}%;background:linear-gradient(90deg,${color},${color}bb);animation-delay:${i * 60}ms"></div>
        </div>
        ${showValue ? `<div class="hbar-v">${esc(faNum(d.value))}${esc(unit)}</div>` : ''}
      </div>`;
    }).join('');
  }

  /* ── Activity heatmap (GitHub-style) ──────────────────────────────────── */
  function heatmap(opts) {
    const { days = [], values = [], max = 0, cell = 13, gap = 3 } = opts;
    if (!days.length) return '<div class="empty">داده‌ای نیست</div>';
    const weeks = Math.ceil(days.length / 7);
    const w = weeks * (cell + gap);
    const h = 7 * (cell + gap);
    let rects = '';
    values.forEach((v, i) => {
      const col = Math.floor(i / 7), row = i % 7;
      // RTL: newest week on the left.
      const x = w - (col + 1) * (cell + gap);
      const y = row * (cell + gap);
      const level = max ? v / max : 0;
      let fill = 'rgba(255,255,255,.05)';
      if (v > 0) {
        const a = 0.18 + level * 0.72;
        fill = `rgba(54,226,176,${a.toFixed(2)})`;
      }
      rects += `<rect x="${x}" y="${y}" width="${cell}" height="${cell}" rx="3"
        fill="${fill}" opacity="0">
        <title>${esc(days[i])}: ${esc(faNum(v))} رویداد</title>
        <animate attributeName="opacity" from="0" to="1" dur=".3s" begin="${(i % 40) * 0.012}s" fill="freeze"/>
      </rect>`;
    });
    return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img">${rects}</svg>`;
  }

  /* ── Stacked progress bar ─────────────────────────────────────────────── */
  function stackedBar(opts) {
    const { data = [], height = 10 } = opts;
    const total = data.reduce((a, d) => a + d.value, 0);
    if (!total) return `<div class="track" style="height:${height}px"></div>`;
    const segs = data.filter((d) => d.value > 0).map((d, i) => {
      const pct = (d.value / total) * 100;
      return `<div class="sseg" style="width:${pct}%;background:${d.color};animation-delay:${i * 80}ms"
                title="${esc(d.label)}: ${esc(faNum(d.value))}"></div>`;
    }).join('');
    return `<div class="sbar" style="height:${height}px">${segs}</div>`;
  }

  global.Charts = { lineChart, donut, gauge, barList, heatmap, stackedBar, faNum, compact, esc };
})(window);
