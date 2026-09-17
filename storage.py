# -*- coding: utf-8 -*-
"""历史数据存储：SQLite 单表，自动清理过期数据。

面试要点：
- 为什么 SQLite：单机部署零依赖、数据量小（分钟级）足够
- 指标以 JSON 文本存磁盘/网络细节，避免为每个分区建表
- 建表/迁移只在进程内执行一次；每次读写新开短连接 + WAL，避免与多客户端轮询争锁
"""
import json
import os
import sqlite3
import threading
import time

import config

_schema_lock = threading.Lock()
_schema_ready = False


def _ensure_schema(conn):
    """建表与轻量迁移：进程内只跑一次。"""
    global _schema_ready
    if _schema_ready:
        return
    with _schema_lock:
        if _schema_ready:
            return
        conn.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,               -- 采集时间戳
                cpu_percent REAL,
                mem_percent REAL,
                mem_used_gb REAL,               -- 内存已用/总量（GB，里程碑 2 新增）
                mem_total_gb REAL,
                disks TEXT,                     -- 磁盘各分区 JSON
                net_in_bytes REAL,
                net_out_bytes REAL,
                node TEXT DEFAULT 'local'       -- 来源节点（多节点监控，里程碑 6 新增）
            )
        """)
        # 旧库迁移：早期版本的表缺新列，用 ALTER TABLE 补齐（SQLite 轻量迁移）
        cols = {row[1] for row in conn.execute("PRAGMA table_info(metrics)")}
        for col, ddl in (("mem_used_gb", "REAL"), ("mem_total_gb", "REAL"),
                         ("node", "TEXT DEFAULT 'local'")):
            if col not in cols:
                conn.execute(f"ALTER TABLE metrics ADD COLUMN {col} {ddl}")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON metrics(ts)")
        # 告警历史表（里程碑 3）
        conn.execute("""
            CREATE TABLE IF NOT EXISTS alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,        -- P0 / P1 / P2
                metric TEXT NOT NULL,       -- cpu_percent / mem_percent / disk_percent
                target TEXT,                -- 磁盘分区挂载点（如 C:\\），其他指标为空
                threshold REAL,
                peak_value REAL,            -- 告警期间峰值
                started_at REAL NOT NULL,
                ended_at REAL,              -- NULL 表示尚未恢复
                notified INTEGER DEFAULT 0,
                top_procs TEXT,             -- 告警触发时 top 进程快照 JSON（里程碑 4 新增）
                node TEXT DEFAULT 'local'   -- 来源节点（里程碑 6 新增）
            )
        """)
        # 轻量迁移：旧库 alerts 表缺新列时补齐
        alert_cols = {row[1] for row in conn.execute("PRAGMA table_info(alerts)")}
        if "top_procs" not in alert_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN top_procs TEXT")
        if "node" not in alert_cols:
            conn.execute("ALTER TABLE alerts ADD COLUMN node TEXT DEFAULT 'local'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_started ON alerts(started_at)")

        # ===== 校园数字孪生（独立模块：通用 key-value 业务指标，与主机 metrics 表隔离）=====
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campus_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,               -- 采集时间戳
                node TEXT NOT NULL,             -- 楼号（对应 Unity 建筑对象名，如 North_Teaching）
                data TEXT NOT NULL              -- 该楼本次 4 个指标的 JSON：{key: value}
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campus_ts ON campus_metrics(ts)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campus_node_ts ON campus_metrics(node, ts)")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS campus_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                level TEXT NOT NULL,            -- P1(预警) / P0(严重)
                metric TEXT NOT NULL,           -- occupancy / power / temp / network
                threshold REAL,
                peak_value REAL,
                started_at REAL NOT NULL,
                ended_at REAL,
                node TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_campus_alerts_started ON campus_alerts(started_at)")
        _schema_ready = True


def _connect():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    # timeout/busy_timeout：多客户端（采集线程 + Flask + Unity 轮询）下避免 database is locked
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0)
    conn.execute("PRAGMA busy_timeout=30000")
    try:
        conn.execute("PRAGMA journal_mode=WAL")
    except sqlite3.Error:
        pass
    _ensure_schema(conn)
    return conn


def save(metric: dict, node: str = "local"):
    """保存一次采集结果（node 为来源节点标识）。"""
    conn = _connect()
    conn.execute(
        "INSERT INTO metrics (ts, cpu_percent, mem_percent, mem_used_gb, mem_total_gb, "
        "disks, net_in_bytes, net_out_bytes, node) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            metric["timestamp"],
            metric["cpu_percent"],
            metric["mem_percent"],
            metric.get("mem_used_gb"),
            metric.get("mem_total_gb"),
            json.dumps(metric["disks"]),
            metric["net_in_bytes"],
            metric["net_out_bytes"],
            node,
        ),
    )
    conn.commit()
    conn.close()


def cleanup():
    """删除超过保留期的旧数据。"""
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    conn = _connect()
    conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
    # 校园模块沿用同一保留期
    conn.execute("DELETE FROM campus_metrics WHERE ts < ?", (cutoff,))
    conn.commit()
    conn.close()


def recent(limit: int = 500, node: str = None) -> list:
    """取最近 limit 条记录（时间正序），可按 node 过滤。"""
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT ts, cpu_percent, mem_percent, mem_used_gb, mem_total_gb, "
            "disks, net_in_bytes, net_out_bytes, node "
            "FROM metrics WHERE node = ? ORDER BY ts DESC LIMIT ?", (node, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts, cpu_percent, mem_percent, mem_used_gb, mem_total_gb, "
            "disks, net_in_bytes, net_out_bytes, node "
            "FROM metrics ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()

    result = []
    for r in reversed(rows):
        result.append({
            "timestamp": r[0],
            "cpu_percent": r[1],
            "mem_percent": r[2],
            "mem_used_gb": r[3],
            "mem_total_gb": r[4],
            "disks": json.loads(r[5]) if r[5] else {},
            "net_in_bytes": r[6],
            "net_out_bytes": r[7],
            "node": r[8],
        })
    return result


def aggregate_range(start: float, end: float, max_points: int = 300, node: str = None) -> dict:
    """取 [start, end] 时间范围内的聚合序列，超过 max_points 时按时间桶抽稀。

    面试要点：
    - 7 天分钟级数据约 12 万条，全部发给前端画图会卡顿
    - 服务端按时间桶取均值（桶内多取平均、桶间保持趋势），图表只画 max_points 个点
    """
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT ts, cpu_percent, mem_percent, net_in_bytes, net_out_bytes "
            "FROM metrics WHERE node = ? AND ts BETWEEN ? AND ? ORDER BY ts", (node, start, end)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT ts, cpu_percent, mem_percent, net_in_bytes, net_out_bytes "
            "FROM metrics WHERE ts BETWEEN ? AND ? ORDER BY ts", (start, end)
        ).fetchall()
    conn.close()

    series = {"ts": [], "cpu": [], "mem": [], "net_in": [], "net_out": []}

    def append(r):
        series["ts"].append(r[0])
        series["cpu"].append(r[1])
        series["mem"].append(r[2])
        series["net_in"].append(r[3])
        series["net_out"].append(r[4])

    if not rows:
        return {"series": series, "raw_count": 0, "buckets": 0}

    if len(rows) <= max_points:
        for r in rows:
            append(r)
        return {"series": series, "raw_count": len(rows), "buckets": len(rows)}

    # 抽稀：按时间桶聚合，桶内取均值
    bucket_sec = (end - start) / max_points
    buckets = {}
    for r in rows:
        idx = min(int((r[0] - start) / bucket_sec), max_points - 1)
        b = buckets.setdefault(idx, [0.0, 0, 0.0, 0.0, 0.0, 0.0])  # ts, n, cpu, mem, in, out
        b[0] += r[0]
        b[1] += 1
        b[2] += r[1] if r[1] is not None else 0.0
        b[3] += r[2] if r[2] is not None else 0.0
        b[4] += r[3] if r[3] is not None else 0.0
        b[5] += r[4] if r[4] is not None else 0.0

    for idx in sorted(buckets):
        b = buckets[idx]
        n = b[1]
        series["ts"].append(round(b[0] / n, 2))
        series["cpu"].append(round(b[2] / n, 1))
        series["mem"].append(round(b[3] / n, 1))
        series["net_in"].append(round(b[4] / n, 1))
        series["net_out"].append(round(b[5] / n, 1))
    return {"series": series, "raw_count": len(rows), "buckets": len(series["ts"])}


# ===== 告警记录（里程碑 3）=====

def _alert_from_row(r) -> dict:
    return {
        "id": r[0],
        "level": r[1],
        "metric": r[2],
        "target": r[3],
        "threshold": r[4],
        "peak_value": r[5],
        "started_at": r[6],
        "ended_at": r[7],
        "node": r[8] if len(r) > 8 else "local",
        "top_procs": json.loads(r[9]) if len(r) > 9 and r[9] else [],
    }


def create_alert(level, metric, target, threshold, peak_value, top_procs=None, node="local") -> int:
    """新告警入库，返回告警 id。top_procs 为触发时进程快照（可空），node 为来源节点。"""
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO alerts (level, metric, target, threshold, peak_value, started_at, top_procs, node) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (level, metric, target, threshold, peak_value, time.time(),
         json.dumps(top_procs, ensure_ascii=False) if top_procs else None, node),
    )
    conn.commit()
    alert_id = cur.lastrowid
    conn.close()
    return alert_id


def update_alert_peak(alert_id: int, peak_value: float):
    """持续告警期间更新峰值（不重复通知）。"""
    conn = _connect()
    conn.execute(
        "UPDATE alerts SET peak_value = MAX(peak_value, ?) WHERE id = ?",
        (peak_value, alert_id),
    )
    conn.commit()
    conn.close()


def close_alert(alert_id: int, ended_at: float):
    """告警恢复，记录结束时间。"""
    conn = _connect()
    conn.execute("UPDATE alerts SET ended_at = ? WHERE id = ?", (ended_at, alert_id))
    conn.commit()
    conn.close()


def active_alerts(node: str = None) -> list:
    """当前未恢复的告警（可按 node 过滤）。"""
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at, node, top_procs "
            "FROM alerts WHERE ended_at IS NULL AND node = ? ORDER BY started_at DESC", (node,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at, node, top_procs "
            "FROM alerts WHERE ended_at IS NULL ORDER BY started_at DESC"
        ).fetchall()
    conn.close()
    return [_alert_from_row(r) for r in rows]


def recent_alerts(limit: int = 50, node: str = None) -> list:
    """最近 limit 条告警记录（含已恢复），新→旧（可按 node 过滤）。"""
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at, node, top_procs "
            "FROM alerts WHERE node = ? ORDER BY started_at DESC LIMIT ?", (node, limit)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at, node, top_procs "
            "FROM alerts ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [_alert_from_row(r) for r in rows]


def list_nodes() -> list:
    """返回所有已知节点（按最近活跃排序），供仪表盘切换节点。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT node, MAX(ts) AS last_ts, COUNT(*) AS cnt "
        "FROM metrics GROUP BY node ORDER BY last_ts DESC"
    ).fetchall()
    conn.close()
    return [{"node": r[0], "last_ts": r[1], "count": r[2]} for r in rows]


# ======================================================================
# 校园数字孪生模块（独立存取，与主机监控互不影响）
# ======================================================================
def save_campus(ts: float, node: str, data: dict):
    """保存一栋楼一次采样（data 为 {指标key: 值}）。"""
    conn = _connect()
    conn.execute(
        "INSERT INTO campus_metrics (ts, node, data) VALUES (?, ?, ?)",
        (ts, node, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()
    conn.close()


def _campus_row(r):
    return {"timestamp": r[0], "id": r[1], "node": r[1],
            "metrics": json.loads(r[2]) if r[2] else {}}


def latest_campus_all() -> list:
    """每栋楼最近一条采样（按 node 分组取最大 ts），返回时间新→旧的列表。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT cm.ts, cm.node, cm.data FROM campus_metrics cm "
        "JOIN (SELECT node, MAX(ts) AS m FROM campus_metrics GROUP BY node) g "
        "ON cm.node = g.node AND cm.ts = g.m ORDER BY cm.ts DESC"
    ).fetchall()
    conn.close()
    return [_campus_row(r) for r in rows]


def recent_campus(node: str, limit: int = 300) -> list:
    """某栋楼最近 limit 条，时间正序（供画趋势曲线）。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT ts, node, data FROM campus_metrics WHERE node = ? "
        "ORDER BY ts DESC LIMIT ?", (node, limit)
    ).fetchall()
    conn.close()
    return [_campus_row(r) for r in reversed(rows)]


# ---- 校园告警（独立表 campus_alerts，状态机见 campus_alert.py）----
def create_campus_alert(level, metric, threshold, peak_value, node) -> int:
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO campus_alerts (level, metric, threshold, peak_value, started_at, node) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (level, metric, threshold, peak_value, time.time(), node),
    )
    conn.commit()
    aid = cur.lastrowid
    conn.close()
    return aid


def update_campus_alert_peak(alert_id, peak_value):
    conn = _connect()
    conn.execute("UPDATE campus_alerts SET peak_value = MAX(peak_value, ?) WHERE id = ?",
                 (peak_value, alert_id))
    conn.commit()
    conn.close()


def close_campus_alert(alert_id, ended_at):
    conn = _connect()
    conn.execute("UPDATE campus_alerts SET ended_at = ? WHERE id = ?", (ended_at, alert_id))
    conn.commit()
    conn.close()


def _campus_alert_row(r):
    return {"id": r[0], "level": r[1], "metric": r[2], "threshold": r[3],
            "peak_value": r[4], "started_at": r[5], "ended_at": r[6], "node": r[7]}


def active_campus_alerts(node: str = None) -> list:
    """当前未恢复的校园告警。"""
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT id, level, metric, threshold, peak_value, started_at, ended_at, node "
            "FROM campus_alerts WHERE ended_at IS NULL AND node = ? ORDER BY started_at DESC",
            (node,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, level, metric, threshold, peak_value, started_at, ended_at, node "
            "FROM campus_alerts WHERE ended_at IS NULL ORDER BY started_at DESC").fetchall()
    conn.close()
    return [_campus_alert_row(r) for r in rows]


def recent_campus_alerts(limit: int = 50, node: str = None) -> list:
    conn = _connect()
    if node:
        rows = conn.execute(
            "SELECT id, level, metric, threshold, peak_value, started_at, ended_at, node "
            "FROM campus_alerts WHERE node = ? ORDER BY started_at DESC LIMIT ?",
            (node, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, level, metric, threshold, peak_value, started_at, ended_at, node "
            "FROM campus_alerts ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
    conn.close()
    return [_campus_alert_row(r) for r in rows]
