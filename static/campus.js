/* 校园数字孪生仪表盘（独立脚本，不依赖/不改动主机 dashboard.js） */
(function () {
  "use strict";

  var META = null, ORDER = [];
  var selected = null;
  var chart = null;
  var STATUS_CLS = ["", "warn", "crit"];
  var LEVEL_TXT = { P0: "严重", P1: "预警" };
  var MISSING = -99999;

  function $(id) { return document.getElementById(id); }
  function isMissing(v) {
    return v === null || v === undefined || v <= MISSING + 1;
  }
  function fmtTime(ts) {
    if (!ts) return "--";
    var d = new Date(ts * 1000);
    return d.toLocaleTimeString("zh-CN", { hour12: false });
  }
  function metricLabel(k) { return META && META[k] ? META[k].label : k; }
  function fmtVal(k, v) {
    if (isMissing(v)) return "--";
    var m = META[k]; var d = m ? m.decimals : 1;
    return Number(v).toFixed(d) + (m ? " " + m.unit : "");
  }
  function norm(k, v) {
    var m = META[k]; if (!m || isMissing(v)) return null;
    var span = m.max - m.min; return span ? ((v - m.min) / span) * 100 : 0;
  }

  // ---------- 楼宇卡片 ----------
  function renderNodes(data) {
    META = data.meta; ORDER = data.order || [];
    var grids = { north: $("grid-north"), south: $("grid-south") };
    grids.north.innerHTML = ""; grids.south.innerHTML = "";
    var online = 0;
    data.nodes.forEach(function (n) {
      if (n.online) online++;
      var card = document.createElement("div");
      var st = n.worstStatus || 0;
      card.className = "b-card" + (st === 1 ? " st-warn" : st === 2 ? " st-crit" : "")
        + (n.online ? "" : " offline") + (selected === n.id ? " selected" : "");
      card.onclick = function () { selectBuilding(n.id); };

      var rows = ORDER.map(function (k) {
        var cls = stOf(n, k);
        return '<div class="b-m"><span class="ml">' + metricLabel(k) +
          '</span><span class="mv ' + STATUS_CLS[cls] + '">' + fmtVal(k, n[k]) + "</span></div>";
      }).join("");

      card.innerHTML =
        '<div class="b-head"><span class="b-name">' + n.name + "</span>" +
        '<span class="b-dot ' + (n.online ? "" : "off") + '"></span></div>' +
        '<div class="b-metrics">' + rows + "</div>";
      (grids[n.campus] || grids.north).appendChild(card);
    });

    $("status-text").textContent = online + "/" + data.nodes.length + " 栋在线";
    $("last-update").textContent = fmtTime(data.serverTime);
    $("status-dot").style.background = online > 0 ? "#4caf8d" : "#ea6668";
    renderBanner(data);
  }

  function stOf(n, k) {
    var m = META[k], v = n[k];
    if (!m || isMissing(v)) return 0;
    if (v >= m.critical) return 2;
    if (v >= m.warn) return 1;
    return 0;
  }

  function renderBanner(data) {
    var crit = [], warn = [];
    data.nodes.forEach(function (n) {
      if (n.worstStatus === 2) crit.push(n.name);
      else if (n.worstStatus === 1) warn.push(n.name);
    });
    var banner = $("alert-banner");
    var msg = [];
    if (crit.length) msg.push("严重：" + crit.join("、"));
    if (warn.length) msg.push("预警：" + warn.join("、"));
    if (msg.length) { banner.className = "alert-banner"; banner.textContent = "⚠ " + msg.join("　"); }
    else { banner.className = "alert-banner hidden"; banner.textContent = ""; }
  }

  // ---------- 趋势图 ----------
  function selectBuilding(id) {
    selected = id;
    fetch("/api/campus/history?node=" + encodeURIComponent(id) + "&limit=240")
      .then(function (r) { return r.json(); })
      .then(renderTrend)
      .catch(function () { });
    // 刷新选中边框
    document.querySelectorAll(".b-card").forEach(function (c) { c.classList.remove("selected"); });
  }

  function renderTrend(d) {
    if (!chart) chart = echarts.init($("chart-trend"));
    var rows = d.rows || [];
    var xs = rows.map(function (r) { return fmtTime(r.timestamp); });
    var series = ORDER.map(function (k) {
      return {
        name: metricLabel(k), type: "line", smooth: true, showSymbol: false,
        data: rows.map(function (r) {
          var nv = norm(k, r.metrics[k]);
          // 归一化值用于画线，真实值塞进 value 供 tooltip
          return nv === null ? null : { value: nv, real: r.metrics[k], key: k };
        })
      };
    });
    var name = d.node;
    $("detail-title").textContent = name + " · 指标趋势（纵轴为占量程百分比，悬停看真实值）";
    chart.setOption({
      backgroundColor: "transparent",
      tooltip: { trigger: "axis", confine: true,
        formatter: function (ps) {
          var s = ps[0].axisValue + "<br/>";
          ps.forEach(function (p) {
            var raw = p.data && p.data.real !== undefined ? fmtVal(p.data.key, p.data.real) : "--";
            s += p.marker + p.seriesName + ": " + raw + "<br/>";
          });
          return s;
        } },
      legend: { textStyle: { color: "#cfe0f5" }, top: 0 },
      grid: { left: 48, right: 20, top: 36, bottom: 28 },
      xAxis: { type: "category", data: xs, axisLabel: { color: "#9fb0c8", fontSize: 10 } },
      yAxis: { type: "value", min: 0, max: 100, name: "量程%",
        axisLabel: { color: "#9fb0c8" }, splitLine: { lineStyle: { color: "rgba(255,255,255,.08)" } } },
      series: series
    }, true);
  }

  // ---------- 最近告警 ----------
  function loadAlerts() {
    fetch("/api/campus/alerts?limit=20").then(function (r) { return r.json(); }).then(function (list) {
      var box = $("campus-alert-list");
      if (!list || !list.length) { box.innerHTML = '<div class="alert-empty">暂无告警记录</div>'; return; }
      box.innerHTML = list.map(function (a) {
        var cls = a.level === "P0" ? "crit" : "warn";
        var state = a.ended_at ? "已恢复 " + fmtTime(a.ended_at) : "未恢复";
        return '<div class="alert-item ' + cls + '"><span class="alert-level">' +
          (LEVEL_TXT[a.level] || a.level) + "</span><span>" + (a.node) + " · " +
          metricLabel(a.metric) + "（峰值 " + a.peak_value + "，阈值 " + a.threshold + "）</span>" +
          '<span class="alert-time">' + fmtTime(a.started_at) + " · " + state + "</span></div>";
      }).join("");
    }).catch(function () { });
  }

  function poll() {
    fetch("/api/campus/latest").then(function (r) { return r.json(); }).then(function (d) {
      renderNodes(d);
      if (selected) selectBuilding(selected);   // 跟随刷新
    }).catch(function () {
      $("status-text").textContent = "后端未连接";
    });
  }

  poll(); loadAlerts();
  setInterval(poll, 2000);
  setInterval(loadAlerts, 4000);
  window.addEventListener("resize", function () { if (chart) chart.resize(); });
})();
