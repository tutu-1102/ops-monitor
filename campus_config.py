# -*- coding: utf-8 -*-
"""校园数字孪生 —— 业务指标目录（独立模块，不影响主机监控本体）。

这里集中定义：
  1) 10 栋楼（节点 id / 中文名 / 南北区 / 楼型曲线）；
  2) 每栋楼统一的 4 个业务指标（键、中文名、单位、量程、基线、阈值、抖动）；
  3) 与 Unity 端 SimulatedMetricProvider 同一套“日内活跃度曲线”，
     保证 Python 生成的数据规律和 Unity 本地模拟一致，切换数据源时观感连续。

campus_sim.py（生成器）、campus_api.py（接口/页面）都从这里取元数据，
新增/调整指标只改本文件。
"""
import math

# ----------------------------------------------------------------------
# 指标元数据：key -> 属性。顺序即展示顺序。
#   baseline : 空闲时最低占比（0~1，占量程）
#   warn/critical : 预警/严重阈值（真实单位，与 Unity MetricDef 对齐）
#   noise    : 随机抖动幅度（占量程比例）
#   decimals : 显示小数位
# ----------------------------------------------------------------------
METRICS = {
    "occupancy": {"label": "人流密度", "unit": "%",    "min": 0,    "max": 100,
                  "baseline": 0.05, "warn": 80,  "critical": 95,  "noise": 0.03,  "decimals": 0},
    "power":     {"label": "用电功率", "unit": "kW",   "min": 0,    "max": 500,
                  "baseline": 0.18, "warn": 400, "critical": 470, "noise": 0.025, "decimals": 0},
    "temp":      {"label": "室温",     "unit": "℃",   "min": 18,   "max": 30,
                  "baseline": 0.35, "warn": 27,  "critical": 29,  "noise": 0.02,  "decimals": 1},
    "network":   {"label": "网络负载", "unit": "Mbps", "min": 0,    "max": 1000,
                  "baseline": 0.12, "warn": 800, "critical": 950, "noise": 0.03,  "decimals": 0},
}
METRIC_ORDER = ["occupancy", "power", "temp", "network"]

# ----------------------------------------------------------------------
# 10 栋楼：node id（必须与 Unity 建筑对象名一致）-> (中文名, 南北区, 楼型曲线)
# 楼型曲线与 Unity MetricCurveType 同名：flat/teaching/dorm/canteen/library/sports
# ----------------------------------------------------------------------
BUILDINGS = {
    "North_Teaching":   ("北区教学楼",   "north", "teaching"),
    "North_Canteen":    ("北区食堂",     "north", "canteen"),
    "North_FemaleDorm": ("北区女生宿舍", "north", "dorm"),
    "North_MaleDorm":   ("北区男生宿舍", "north", "dorm"),
    "South_Teaching":   ("南区教学楼",   "south", "teaching"),
    "South_Library":    ("南区图书馆",   "south", "library"),
    "South_FemaleDorm": ("南区女生宿舍", "south", "dorm"),
    "South_MaleDorm":   ("南区男生宿舍", "south", "dorm"),
    "South_Gym":        ("南区体育馆",   "south", "sports"),
    "South_Stadium":    ("南区体育场",   "south", "sports"),
}

NODE_IDS = list(BUILDINGS.keys())


def building_curve(node: str) -> str:
    info = BUILDINGS.get(node)
    return info[2] if info else "flat"


# ======================================================================
# 日内活跃度曲线（移植自 Unity SimulatedMetricProvider，0~1）
# ======================================================================
def _bump(t: float, center: float, width: float) -> float:
    """以 center 为中心、width 为标准差的高斯峰，支持跨 24h 回绕。"""
    d = abs(t - center)
    d = ((d + 24 + 12) % 24) - 12          # 环形时间距离 -12~12
    return math.exp(-(d * d) / (2.0 * width * width))


def _max(*vals):
    return max(vals)


def _clamp01(x):
    return 0.0 if x < 0 else (1.0 if x > 1 else x)


def activity(curve: str, t: float) -> float:
    if curve == "flat":
        return _clamp01(0.5 + 0.12 * _bump(t, 14, 5))
    if curve == "teaching":
        return _clamp01(_max(_bump(t, 10, 2.2), _bump(t, 15, 2.2), 0.4 * _bump(t, 20, 1.4)))
    if curve == "dorm":
        night = _max(_bump(t, 2.5, 3.2), _bump(t, 23.5, 2.0))
        lunch = 0.55 * _bump(t, 12.5, 1.2)
        return _clamp01(_max(night, lunch))
    if curve == "canteen":
        return _clamp01(_max(_bump(t, 7.3, 0.8), _bump(t, 12, 0.9), _bump(t, 18, 0.9)))
    if curve == "library":
        return _clamp01(_max(_bump(t, 10, 2.6), _bump(t, 15, 2.4), _bump(t, 19.5, 2.0)))
    if curve == "sports":
        return _clamp01(_max(0.7 * _bump(t, 10, 1.6), _bump(t, 17, 2.2)))
    return 0.5


def status_of(key: str, value: float) -> int:
    """阈值判定：0 正常 / 1 预警 / 2 严重（对齐 Unity MetricStatus）。"""
    meta = METRICS.get(key)
    if not meta:
        return 0
    if value >= meta["critical"]:
        return 2
    if value >= meta["warn"]:
        return 1
    return 0
