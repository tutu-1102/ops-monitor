# -*- coding: utf-8 -*-
"""校园数字孪生模块的 Web 接口与页面（Flask Blueprint，独立挂载，不改动主机接口）。

接口：
  POST /api/campus/ingest        生成器上报一栋楼一次采样
  GET  /api/campus/latest        10 栋楼最新快照（扁平结构，Unity JsonUtility 可直接解析）
  GET  /api/campus/history?node= 某楼最近序列（页面画曲线）
  GET  /api/campus/alerts/active 当前未恢复校园告警
  GET  /campus                   校园仪表盘页面（独立于主机仪表盘）
"""
import time

from flask import Blueprint, jsonify, render_template, request

import campus_config
import storage
from campus_alert import CampusAlertEngine

campus_bp = Blueprint("campus", __name__)
_engine = CampusAlertEngine()   # 中心端唯一校园告警引擎（与主机 engine 互不干扰）


def _worst_status(metrics: dict) -> int:
    worst = 0
    for k, v in metrics.items():
        if v is None:
            continue
        worst = max(worst, campus_config.status_of(k, float(v)))
    return worst


@campus_bp.route("/api/campus/ingest", methods=["POST"])
def campus_ingest():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid json"}), 400
    node = str(data.get("node") or "").strip()
    metrics = data.get("metrics") or {}
    if node not in campus_config.BUILDINGS:
        return jsonify({"error": f"unknown node: {node}"}), 400
    if not isinstance(metrics, dict):
        return jsonify({"error": "metrics must be an object"}), 400

    # 只保留目录里定义的指标，并统一转 float（容错：非法值丢弃）
    clean = {}
    for k in campus_config.METRIC_ORDER:
        if k in metrics and metrics[k] is not None:
            try:
                clean[k] = round(float(metrics[k]), 3)
            except (TypeError, ValueError):
                pass
    if not clean:
        return jsonify({"error": "no valid metric"}), 400

    ts = data.get("ts") or time.time()
    storage.save_campus(float(ts), node, clean)
    try:
        _engine.check(node, clean)
    except Exception as e:
        print(f"[校园模块] 告警检查异常（不影响入库）: {e}", flush=True)
    return jsonify({"ok": True, "node": node})


@campus_bp.route("/api/campus/latest")
def campus_latest():
    rows = {r["node"]: r for r in storage.latest_campus_all()}
    active = {}
    for a in storage.active_campus_alerts():
        active.setdefault(a["node"], []).append(a)

    now = time.time()
    nodes = []
    for node, (name, campus, curve) in campus_config.BUILDINGS.items():
        row = rows.get(node)
        metrics = row["metrics"] if row else {}
        item = {
            "id": node, "name": name, "campus": campus, "curve": curve,
            "ts": row["timestamp"] if row else 0,
            "online": bool(row) and (now - row["timestamp"] < 15),
            "worstStatus": _worst_status(metrics),
            "activeAlerts": len(active.get(node, [])),
        }
        # 扁平展开 4 个指标字段（Unity 端用固定 DTO 直接接）
        for k in campus_config.METRIC_ORDER:
            item[k] = metrics.get(k)
        nodes.append(item)
    return jsonify({"serverTime": now,
                    "meta": campus_config.METRICS,
                    "order": campus_config.METRIC_ORDER,
                    "nodes": nodes})


@campus_bp.route("/api/campus/history")
def campus_history():
    node = request.args.get("node", "")
    if node not in campus_config.BUILDINGS:
        return jsonify({"error": "unknown node"}), 400
    limit = min(int(request.args.get("limit", 300)), 2000)
    rows = storage.recent_campus(node, limit)
    return jsonify({"node": node, "rows": rows})


@campus_bp.route("/api/campus/alerts/active")
def campus_alerts_active():
    return jsonify(storage.active_campus_alerts(node=request.args.get("node")))


@campus_bp.route("/api/campus/alerts")
def campus_alerts_recent():
    limit = min(int(request.args.get("limit", 50)), 500)
    return jsonify(storage.recent_campus_alerts(limit=limit, node=request.args.get("node")))


@campus_bp.route("/campus")
def campus_page():
    return render_template("campus.html")
