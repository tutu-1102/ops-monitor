# -*- coding: utf-8 -*-
"""Flask Web 应用：仪表盘页面 + JSON API。"""
from flask import Flask, jsonify, render_template_string
import storage

app = Flask(__name__)

# 极简仪表盘（里程碑 2 会换成 ECharts 完整版）
INDEX_HTML = """
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>服务器监控</title></head>
<body>
  <h2>服务器监控（里程碑 1）</h2>
  <p id="info">加载中...</p>
  <script>
    async function refresh() {
      const r = await fetch('/api/metrics/latest');
      const d = await r.json();
      document.getElementById('info').innerHTML =
        'CPU: ' + d.cpu_percent + '% | 内存: ' + d.mem_percent + '%<br>' +
        '磁盘: ' + JSON.stringify(d.disks) + '<br>' +
        '网络入: ' + (d.net_in_bytes/1024).toFixed(1) + ' KB/s | 网络出: ' +
        (d.net_out_bytes/1024).toFixed(1) + ' KB/s';
    }
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
"""


@app.route("/")
def index():
    return render_template_string(INDEX_HTML)


@app.route("/api/metrics/latest")
def api_latest():
    """最新一条指标。"""
    rows = storage.recent(limit=1)
    if not rows:
        return jsonify({"error": "no data yet"}), 404
    return jsonify(rows[0])


@app.route("/api/metrics/history")
def api_history():
    """最近 N 条历史（默认 500）。"""
    from flask import request
    limit = min(int(request.args.get("limit", 500)), 5000)
    return jsonify(storage.recent(limit=limit))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
