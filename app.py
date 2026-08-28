# -*- coding: utf-8 -*-
"""Flask Web 应用：仪表盘页面 + JSON API（含多节点 agent 上报入口）。"""
import time

from flask import Flask, jsonify, render_template, request
import storage
import alert

app = Flask(__name__)

# 中心端唯一告警引擎：本机采集线程（run.py）与 agent 上报（/api/ingest）共用，
# 状态机按 node 隔离，各节点告警互不干扰。
engine = alert.AlertEngine()

# /static/ 与 /templates/ 由 Flask 自动服务（本地 echarts.min.js，离线可用）


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/ingest", methods=["POST"])
def api_ingest():
    """agent 上报入口：接收一个节点的指标，入库 + 中心端告警判定。

    请求体 JSON：
        { "node": "agent-1", "metric": { <collector.collect() 返回的指标字典> } }

    面试点：中心端统一判定告警（而不是 agent 各自发告警），
    好处是告警规则集中管理、通知统一出口；坏处是中心端挂了告警也没了
    （引出高可用话题）。
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid json"}), 400

    node = str(data.get("node") or "unknown").strip() or "unknown"
    metric = data.get("metric") or {}
    required = ("timestamp", "cpu_percent", "mem_percent", "disks",
                "net_in_bytes", "net_out_bytes")
    if not all(k in metric for k in required):
        return jsonify({"error": "metric missing fields"}), 400

    storage.save(metric, node)
    try:
        engine.check(metric, node)
    except Exception as e:
        print(f"[ingest] 告警检查异常（不影响入库）: {e}", flush=True)
    return jsonify({"ok": True, "node": node})


@app.route("/api/nodes")
def api_nodes():
    """所有已知节点列表（供仪表盘切换）。"""
    return jsonify(storage.list_nodes())


@app.route("/api/metrics/latest")
def api_latest():
    """最新一条指标（可按 ?node= 过滤）。"""
    node = request.args.get("node")
    rows = storage.recent(limit=1, node=node)
    if not rows:
        return jsonify({"error": "no data yet"}), 404
    return jsonify(rows[0])


@app.route("/api/metrics/history")
def api_history():
    """最近 N 条历史（默认 500，可按 ?node= 过滤）。"""
    limit = min(int(request.args.get("limit", 500)), 5000)
    node = request.args.get("node")
    return jsonify(storage.recent(limit=limit, node=node))


@app.route("/api/metrics/range")
def api_range():
    """时间范围聚合序列：?minutes=N（最近 N 分钟），?max_points=M（抽稀上限），?node=。

    服务端按时间桶抽稀取均值，避免 7 天数据全部下发导致前端卡顿。
    """
    try:
        minutes = float(request.args.get("minutes", 60))
    except ValueError:
        minutes = 60
    minutes = min(max(minutes, 1), 60 * 24 * 30)  # 1 分钟 ~ 30 天
    max_points = min(int(request.args.get("max_points", 300)), 2000)
    node = request.args.get("node")

    end = time.time()
    start = end - minutes * 60
    result = storage.aggregate_range(start, end, max_points, node)
    result["start"] = start
    result["end"] = end
    return jsonify(result)


@app.route("/api/alerts/active")
def api_alerts_active():
    """当前未恢复的告警（可按 ?node= 过滤）。"""
    return jsonify(storage.active_alerts(node=request.args.get("node")))


@app.route("/api/alerts")
def api_alerts():
    """最近 N 条告警记录（含已恢复，可按 ?node= 过滤），默认 50。"""
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify(storage.recent_alerts(limit=limit, node=request.args.get("node")))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
