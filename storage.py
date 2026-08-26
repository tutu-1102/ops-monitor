# -*- coding: utf-8 -*-
"""历史数据存储：SQLite 单表，自动清理过期数据。

面试要点：
- 为什么 SQLite：单机部署零依赖、数据量小（分钟级）足够
- 指标以 JSON 文本存磁盘/网络细节，避免为每个分区建表
"""
import json
import os
import sqlite3
import time
import config


def _connect():
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
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
            net_out_bytes REAL
        )
    """)
    # 旧库迁移：早期版本的表缺新列，用 ALTER TABLE 补齐（SQLite 轻量迁移）
    cols = {row[1] for row in conn.execute("PRAGMA table_info(metrics)")}
    for col in ("mem_used_gb", "mem_total_gb"):
        if col not in cols:
            conn.execute(f"ALTER TABLE metrics ADD COLUMN {col} REAL")
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
            notified INTEGER DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_alerts_started ON alerts(started_at)")
    return conn


def save(metric: dict):
    """保存一次采集结果。"""
    conn = _connect()
    conn.execute(
        "INSERT INTO metrics (ts, cpu_percent, mem_percent, mem_used_gb, mem_total_gb, "
        "disks, net_in_bytes, net_out_bytes) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            metric["timestamp"],
            metric["cpu_percent"],
            metric["mem_percent"],
            metric.get("mem_used_gb"),
            metric.get("mem_total_gb"),
            json.dumps(metric["disks"]),
            metric["net_in_bytes"],
            metric["net_out_bytes"],
        ),
    )
    conn.commit()
    conn.close()


def cleanup():
    """删除超过保留期的旧数据。"""
    cutoff = time.time() - config.RETENTION_DAYS * 86400
    conn = _connect()
    conn.execute("DELETE FROM metrics WHERE ts < ?", (cutoff,))
    conn.commit()
    conn.close()


def recent(limit: int = 500) -> list:
    """取最近 limit 条记录（时间正序）。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT ts, cpu_percent, mem_percent, mem_used_gb, mem_total_gb, "
        "disks, net_in_bytes, net_out_bytes "
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
        })
    return result


def aggregate_range(start: float, end: float, max_points: int = 300) -> dict:
    """取 [start, end] 时间范围内的聚合序列，超过 max_points 时按时间桶抽稀。

    面试要点：
    - 7 天分钟级数据约 12 万条，全部发给前端画图会卡顿
    - 服务端按时间桶取均值（桶内多取平均、桶间保持趋势），图表只画 max_points 个点
    """
    conn = _connect()
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
    }


def create_alert(level, metric, target, threshold, peak_value) -> int:
    """新告警入库，返回告警 id。"""
    conn = _connect()
    cur = conn.execute(
        "INSERT INTO alerts (level, metric, target, threshold, peak_value, started_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (level, metric, target, threshold, peak_value, time.time()),
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


def active_alerts() -> list:
    """当前未恢复的告警。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at "
        "FROM alerts WHERE ended_at IS NULL ORDER BY started_at DESC"
    ).fetchall()
    conn.close()
    return [_alert_from_row(r) for r in rows]


def recent_alerts(limit: int = 50) -> list:
    """最近 limit 条告警记录（含已恢复），新→旧。"""
    conn = _connect()
    rows = conn.execute(
        "SELECT id, level, metric, target, threshold, peak_value, started_at, ended_at "
        "FROM alerts ORDER BY started_at DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    return [_alert_from_row(r) for r in rows]
