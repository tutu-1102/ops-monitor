/* 服务器监控仪表盘 —— 前端逻辑
 *
 * 设计要点：
 * - 卡片每 3 秒拉 /api/metrics/latest 刷新一次
 * - 曲线按所选时间范围拉 /api/metrics/range（服务端已抽稀聚合，最多 300 个点）
 * - 范围越大刷新越慢，避免无意义的请求（实时 3s / 1h 10s / 24h 30s / 7d 60s）
 */
(function () {
  'use strict';

  // 时间范围配置：查询窗口（分钟） + 图表刷新周期（毫秒）
  const RANGES = {
    realtime: { minutes: 10,    refresh: 3000  },
    '1h':     { minutes: 60,    refresh: 10000 },
    '24h':    { minutes: 1440,  refresh: 30000 },
    '7d':     { minutes: 10080, refresh: 60000 },
  };
  const CARD_REFRESH = 3000; // 卡片刷新周期（毫秒）

  let currentRange = 'realtime';
  let chartTimer = null;

  // ===== 工具函数 =====
  function pad(n) { return String(n).padStart(2, '0'); }

  function fmtBytes(bps) { // 字节/秒 → 可读速率
    if (bps === null || bps === undefined || isNaN(bps)) return '--';
    if (bps >= 1024 * 1024) return (bps / 1024 / 1024).toFixed(2) + ' MB/s';
    if (bps >= 1024) return (bps / 1024).toFixed(1) + ' KB/s';
    return bps.toFixed(0) + ' B/s';
  }

  function fmtClock(ts) { // 秒时间戳 → 时:分:秒
    const d = new Date(ts * 1000);
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function fmtAxis(ts) { // 秒时间戳 → X 轴文本（长范围显示日期）
    const d = new Date(ts * 1000);
    if (currentRange === '24h' || currentRange === '7d') {
      return pad(d.getMonth() + 1) + '-' + pad(d.getDate()) + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
    }
    return pad(d.getHours()) + ':' + pad(d.getMinutes()) + ':' + pad(d.getSeconds());
  }

  function pctColor(v) { // 百分比 → 颜色（告警阈值预告片：>=90 红 / >=70 黄 / 其余绿）
    if (v === null || v === undefined) return '#64748b';
    if (v >= 90) return '#f87171';
    if (v >= 70) return '#fbbf24';
    return '#34d399';
  }

  async function fetchJson(url) {
    const r = await fetch(url);
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }

  // ===== 图表初始化 =====
  const axisLabel = { color: '#94a3b8' };
  const axisLine = { lineStyle: { color: '#334155' } };
  const splitLine = { lineStyle: { color: '#1e293b' } };
  const baseGrid = { left: 52, right: 20, top: 36, bottom: 30 };

  const mainChart = echarts.init(document.getElementById('chart-main'), 'dark');
  mainChart.setOption({
    backgroundColor: 'transparent',
    tooltip: {
      trigger: 'axis',
      valueFormatter: (v) => (v === null ? '--' : v + ' %'),
    },
    legend: { top: 0, textStyle: { color: '#94a3b8' }, data: ['CPU', '内存'] },
    grid: baseGrid,
    xAxis: { type: 'category', boundaryGap: false, data: [], axisLabel, axisLine },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { ...axisLabel, formatter: '{value}%' }, splitLine },
    dataZoom: [{ type: 'inside' }],
    series: [
      { name: 'CPU', type: 'line', smooth: true, showSymbol: false, data: [],
        lineStyle: { width: 2, color: '#22d3ee' }, itemStyle: { color: '#22d3ee' },
        areaStyle: { opacity: 0.08, color: '#22d3ee' } },
      { name: '内存', type: 'line', smooth: true, showSymbol: false, data: [],
        lineStyle: { width: 2, color: '#a78bfa' }, itemStyle: { color: '#a78bfa' },
        areaStyle: { opacity: 0.08, color: '#a78bfa' } },
    ],
  });

  const netChart = echarts.init(document.getElementById('chart-net'), 'dark');
  netChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', valueFormatter: (v) => fmtBytes(v) },
    legend: { top: 0, textStyle: { color: '#94a3b8' }, data: ['入流量', '出流量'] },
    grid: baseGrid,
    xAxis: { type: 'category', boundaryGap: false, data: [], axisLabel, axisLine },
    yAxis: { type: 'value', axisLabel: { ...axisLabel, formatter: (v) => fmtBytes(v) }, splitLine },
    dataZoom: [{ type: 'inside' }],
    series: [
      { name: '入流量', type: 'line', smooth: true, showSymbol: false, data: [],
        lineStyle: { width: 2, color: '#22d3ee' }, itemStyle: { color: '#22d3ee' },
        areaStyle: { opacity: 0.12, color: '#22d3ee' } },
      { name: '出流量', type: 'line', smooth: true, showSymbol: false, data: [],
        lineStyle: { width: 2, color: '#34d399' }, itemStyle: { color: '#34d399' },
        areaStyle: { opacity: 0.12, color: '#34d399' } },
    ],
  });

  const diskChart = echarts.init(document.getElementById('chart-disk'), 'dark');
  diskChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' }, valueFormatter: (v) => v + ' %' },
    grid: baseGrid,
    xAxis: { type: 'category', data: [], axisLabel: { ...axisLabel, interval: 0, rotate: 30 }, axisLine },
    yAxis: { type: 'value', min: 0, max: 100, axisLabel: { ...axisLabel, formatter: '{value}%' }, splitLine },
    series: [{
      type: 'bar', data: [], barMaxWidth: 56,
      itemStyle: { borderRadius: [6, 6, 0, 0], color: (p) => pctColor(p.value) },
      label: { show: true, position: 'top', color: '#94a3b8', formatter: '{c}%' },
    }],
  });

  window.addEventListener('resize', () => {
    mainChart.resize();
    netChart.resize();
    diskChart.resize();
  });

  // ===== 数据渲染 =====
  function setStatus(ok) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    dot.className = 'dot ' + (ok ? 'ok' : 'err');
    text.textContent = ok ? '采集中' : '连接失败';
    if (ok) {
      document.getElementById('last-update').textContent = fmtClock(Date.now() / 1000);
    }
  }

  function setBar(id, value) {
    const el = document.getElementById(id);
    el.style.width = Math.min(Math.max(value || 0, 0), 100) + '%';
    el.style.backgroundColor = pctColor(value);
  }

  function renderCards(d) {
    // CPU
    document.getElementById('kpi-cpu').innerHTML = d.cpu_percent + '<span class="unit">%</span>';
    setBar('bar-cpu', d.cpu_percent);
    document.getElementById('sub-cpu').textContent = 'psutil 1 秒窗口采样均值';

    // 内存
    document.getElementById('kpi-mem').innerHTML = d.mem_percent + '<span class="unit">%</span>';
    setBar('bar-mem', d.mem_percent);
    const memSub = (d.mem_used_gb !== null && d.mem_used_gb !== undefined)
      ? '已用 ' + d.mem_used_gb + ' / 共 ' + d.mem_total_gb + ' GB'
      : '等待新采样写入';
    document.getElementById('sub-mem').textContent = memSub;

    // 磁盘（取使用率最高的分区）
    const disks = d.disks || {};
    const mounts = Object.keys(disks);
    let maxMount = null, maxPct = null;
    mounts.forEach((m) => { if (maxPct === null || disks[m] > maxPct) { maxPct = disks[m]; maxMount = m; } });
    document.getElementById('kpi-disk').innerHTML = (maxPct === null ? '--' : maxPct) + '<span class="unit">%</span>';
    setBar('bar-disk', maxPct);
    document.getElementById('sub-disk').textContent = maxMount
      ? '最高分区 ' + maxMount + ' · 共 ' + mounts.length + ' 个分区'
      : '暂无分区数据';

    // 网络
    document.getElementById('kpi-net').textContent = '↓ ' + fmtBytes(d.net_in_bytes);
    document.getElementById('sub-net').textContent = '↑ 出流量 ' + fmtBytes(d.net_out_bytes);
  }

  function renderDisk(disks) {
    const mounts = Object.keys(disks).sort((a, b) => disks[b] - disks[a]);
    diskChart.setOption({
      xAxis: { data: mounts },
      series: [{ data: mounts.map((m) => disks[m]) }],
    });
  }

  function renderRange(data) {
    const s = data.series || {};
    const ts = (s.ts || []).map(fmtAxis);
    const empty = ts.length === 0;

    mainChart.setOption({
      xAxis: { data: ts },
      series: [{ data: s.cpu || [] }, { data: s.mem || [] }],
    });
    netChart.setOption({
      xAxis: { data: ts },
      series: [{ data: s.net_in || [] }, { data: s.net_out || [] }],
    });

    const caption = document.getElementById('main-caption');
    if (empty) {
      caption.textContent = '暂无数据，等待采集…';
    } else if (data.raw_count > (data.buckets || 0)) {
      caption.textContent = '共 ' + data.raw_count + ' 条原始数据 → 服务端抽稀为 ' + data.buckets + ' 个点';
    } else {
      caption.textContent = data.raw_count + ' 条原始数据';
    }
  }

  // ===== 轮询 =====
  async function loadLatest() {
    try {
      const d = await fetchJson('/api/metrics/latest');
      renderCards(d);
      renderDisk(d.disks || {});
      setStatus(true);
    } catch (e) {
      setStatus(false);
    }
  }

  async function loadRange() {
    try {
      const cfg = RANGES[currentRange];
      const d = await fetchJson('/api/metrics/range?minutes=' + cfg.minutes + '&max_points=300');
      renderRange(d);
    } catch (e) {
      document.getElementById('main-caption').textContent = '数据加载失败';
    }
  }

  function setRange(key) {
    currentRange = key;
    document.querySelectorAll('#range-btns button').forEach((b) => {
      b.classList.toggle('active', b.dataset.range === key);
    });
    clearInterval(chartTimer);
    loadRange(); // 切换后立即拉一次
    chartTimer = setInterval(loadRange, RANGES[key].refresh);
  }

  document.getElementById('range-btns').addEventListener('click', (e) => {
    const btn = e.target.closest('button');
    if (btn && RANGES[btn.dataset.range]) setRange(btn.dataset.range);
  });

  // ===== 启动 =====
  loadLatest();
  setInterval(loadLatest, CARD_REFRESH);
  setRange('realtime');
})();
