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
            disks TEXT,                     -- 磁盘各分区 JSON
            net_in_bytes REAL,
            net_out_bytes REAL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON metrics(ts)")
    return conn


def save(metric: dict):
    """保存一次采集结果。"""
    conn = _connect()
    conn.execute(
        "INSERT INTO metrics (ts, cpu_percent, mem_percent, disks, net_in_bytes, net_out_bytes) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            metric["timestamp"],
            metric["cpu_percent"],
            metric["mem_percent"],
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
        "SELECT ts, cpu_percent, mem_percent, disks, net_in_bytes, net_out_bytes "
        "FROM metrics ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()

    result = []
    for r in reversed(rows):
        result.append({
            "timestamp": r[0],
            "cpu_percent": r[1],
            "mem_percent": r[2],
            "disks": json.loads(r[3]) if r[3] else {},
            "net_in_bytes": r[4],
            "net_out_bytes": r[5],
        })
    return result
