# -*- coding: utf-8 -*-
"""Flask Web 应用：仪表盘页面 + JSON API。"""
import time

from flask import Flask, jsonify, render_template, request
import storage

app = Flask(__name__)

# /static/ 与 /templates/ 由 Flask 自动服务（本地 echarts.min.js，离线可用）


@app.route("/")
def index():
    return render_template("dashboard.html")


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
    limit = min(int(request.args.get("limit", 500)), 5000)
    return jsonify(storage.recent(limit=limit))


@app.route("/api/metrics/range")
def api_range():
    """时间范围聚合序列：?minutes=N（最近 N 分钟），?max_points=M（抽稀上限）。

    服务端按时间桶抽稀取均值，避免 7 天数据全部下发导致前端卡顿。
    """
    try:
        minutes = float(request.args.get("minutes", 60))
    except ValueError:
        minutes = 60
    minutes = min(max(minutes, 1), 60 * 24 * 30)  # 1 分钟 ~ 30 天
    max_points = min(int(request.args.get("max_points", 300)), 2000)

    end = time.time()
    start = end - minutes * 60
    result = storage.aggregate_range(start, end, max_points)
    result["start"] = start
    result["end"] = end
    return jsonify(result)


@app.route("/api/alerts/active")
def api_alerts_active():
    """当前未恢复的告警。"""
    return jsonify(storage.active_alerts())


@app.route("/api/alerts")
def api_alerts():
    """最近 N 条告警记录（含已恢复），默认 50。"""
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify(storage.recent_alerts(limit=limit))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
