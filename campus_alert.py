# -*- coding: utf-8 -*-
"""校园数字孪生 —— 通用业务指标告警状态机（独立模块）。

与主机监控 alert.py 的区别：
- 主机告警面向固定的 CPU/内存/磁盘，且触发时抓进程快照、发通知；
- 校园告警面向任意业务指标（人流/用电/室温/网络），规则阈值来自 campus_config，
  只写独立的 campus_alerts 表并打印日志，供校园仪表盘与 Unity 读取，不打扰主机链路。

状态机：正常 → 连续 sustain 次越限则触发 → 持续期只更新峰值（降噪）→ 回落则恢复。
进程重启后从未恢复记录里自愈，不重复告警。
"""
import time

import campus_config
import storage

# Unity MetricStatus：1=预警(Warn)→P1，2=严重(Critical)→P0
SUSTAIN = 2  # 连续 2 次采样越限才告警，滤掉单拍毛刺


class CampusAlertEngine:
    def __init__(self):
        # key=(node, level, metric) -> 状态
        self._state = {}
        self._resume()

    def _resume(self):
        for a in storage.active_campus_alerts():
            key = (a["node"], a["level"], a["metric"])
            self._state[key] = {"count": 0, "firing": True,
                                "alert_id": a["id"], "peak": a["peak_value"]}

    def check(self, node: str, metrics: dict):
        """对一栋楼的一次采样检查全部指标。异常不外抛，避免影响入库。"""
        for key in campus_config.METRIC_ORDER:
            if key not in metrics or metrics[key] is None:
                continue
            value = float(metrics[key])
            st = campus_config.status_of(key, value)  # 0/1/2
            meta = campus_config.METRICS[key]

            crit = self._slot(node, "P0", key, meta["critical"])
            warn = self._slot(node, "P1", key, meta["warn"])

            if st == 2:                       # 严重：推进 P0，同时让 P1 归位
                self._advance(crit, value, SUSTAIN)
                self._recover_if_firing(warn, value)
            elif st == 1:                     # 预警：推进 P1，P0 归位
                self._advance(warn, value, SUSTAIN)
                self._recover_if_firing(crit, value)
            else:                             # 正常：两条都恢复
                self._recover_if_firing(crit, value)
                self._recover_if_firing(warn, value)

    def _slot(self, node, level, metric, threshold):
        key = (node, level, metric)
        st = self._state.setdefault(key, {"count": 0, "firing": False,
                                          "alert_id": None, "peak": None,
                                          "level": level, "metric": metric,
                                          "threshold": threshold, "node": node})
        return st

    @staticmethod
    def _advance(st, value, sustain):
        if st["firing"]:
            if st["peak"] is None or value > st["peak"]:
                st["peak"] = value
                if st["alert_id"] is not None:
                    storage.update_campus_alert_peak(st["alert_id"], value)
            return
        st["count"] += 1
        if st["count"] >= sustain:
            st["firing"] = True
            st["peak"] = value
            st["alert_id"] = storage.create_campus_alert(
                st["level"], st["metric"], st["threshold"], value, st["node"])
            print(f"[校园告警] 触发 [{st['node']}] {st['level']} "
                  f"{campus_config.METRICS[st['metric']]['label']}={value}"
                  f"（阈值 {st['threshold']}）", flush=True)

    @staticmethod
    def _recover_if_firing(st, value):
        if st["firing"]:
            if st["alert_id"] is not None:
                storage.close_campus_alert(st["alert_id"], time.time())
            print(f"[校园告警] 恢复 [{st['node']}] {st['level']} "
                  f"{campus_config.METRICS[st['metric']]['label']}，回落至 {value}", flush=True)
        st["firing"] = False
        st["count"] = 0
        st["peak"] = None
        st["alert_id"] = None
