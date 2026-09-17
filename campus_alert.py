# -*- coding: utf-8 -*-
"""校园数字孪生 —— 通用业务指标告警状态机（独立模块）。

与主机监控 alert.py 的区别：
- 主机告警面向固定的 CPU/内存/磁盘，且触发时抓进程快照；
- 校园告警面向任意业务指标（人流/用电/室温/网络），规则阈值来自 campus_config，
  写独立的 campus_alerts 表，供校园仪表盘与 Unity 读取，不打扰主机链路；
- 通知复用主机 Notifier（钉钉/邮件/控制台），只在触发与恢复两个边沿各发一次。

状态机：正常 → 连续 sustain 次越限则触发 → 持续期只更新峰值（降噪）→ 回落则恢复。
进程重启后从未恢复记录里自愈，不重复发告警（与主机引擎同一约定）。
"""
import time

import campus_config
import config
import notify
import storage

# Unity MetricStatus：1=预警(Warn)→P1，2=严重(Critical)→P0
SUSTAIN = 2  # 连续 2 次采样越限才告警，滤掉单拍毛刺


def _building_name(node: str) -> str:
    info = campus_config.BUILDINGS.get(node)
    return info[0] if info else node


def _metric_unit(metric: str) -> str:
    meta = campus_config.METRICS.get(metric) or {}
    return meta.get("unit") or ""


def _metric_label(metric: str) -> str:
    meta = campus_config.METRICS.get(metric) or {}
    return meta.get("label") or metric


class CampusAlertEngine:
    def __init__(self, notifier: notify.Notifier = None):
        self.notifier = notifier or notify.Notifier()
        self.notify_enabled = bool(getattr(config, "CAMPUS_NOTIFY", True))
        # key=(node, level, metric) -> 状态
        self._state = {}
        self._resume()
        mode = "钉钉/邮件/控制台" if self.notifier.dingtalk_enabled else "控制台"
        print(f"[校园告警] 通知渠道: {mode}（CAMPUS_NOTIFY={'开' if self.notify_enabled else '关'}）",
              flush=True)

    def _resume(self):
        """启动恢复未结束告警：不重复通知，等后续恢复边沿再发。"""
        for a in storage.active_campus_alerts():
            key = (a["node"], a["level"], a["metric"])
            self._state[key] = {"count": 0, "firing": True,
                                "alert_id": a["id"], "peak": a["peak_value"],
                                "started_at": a["started_at"]}
            print(f"[校园告警] 恢复未结束告警: [{a['node']}] {a['level']} {a['metric']}", flush=True)

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
                                          "started_at": None,
                                          "level": level, "metric": metric,
                                          "threshold": threshold, "node": node})
        return st

    def _advance(self, st, value, sustain):
        if st["firing"]:
            if st["peak"] is None or value > st["peak"]:
                st["peak"] = value
                if st["alert_id"] is not None:
                    storage.update_campus_alert_peak(st["alert_id"], value)
            return
        st["count"] += 1
        if st["count"] < sustain:
            return

        st["firing"] = True
        st["peak"] = value
        st["started_at"] = time.time()
        st["alert_id"] = storage.create_campus_alert(
            st["level"], st["metric"], st["threshold"], value, st["node"])

        node, level, metric = st["node"], st["level"], st["metric"]
        label, unit = _metric_label(metric), _metric_unit(metric)
        channels = []
        if self.notify_enabled:
            title, text = notify.build_campus_alert_message(
                level, _building_name(node), node, label, unit,
                value, st["threshold"], st["started_at"])
            try:
                channels = self.notifier.send(title, text)
            except Exception as e:
                print(f"[校园告警] 通知失败（不影响状态机）: {e}", flush=True)
        print(f"[校园告警] 触发 [{node}] {level} {label}={value}"
              f"（阈值 {st['threshold']}，渠道: {','.join(channels) or '仅入库'}）", flush=True)

    def _recover_if_firing(self, st, value):
        if not st["firing"]:
            return

        now = time.time()
        started = st.get("started_at") or now
        duration = max(0.0, now - started)
        if st["alert_id"] is not None:
            storage.close_campus_alert(st["alert_id"], now)

        node, level, metric = st["node"], st["level"], st["metric"]
        label, unit = _metric_label(metric), _metric_unit(metric)
        channels = []
        if self.notify_enabled:
            title, text = notify.build_campus_recovery_message(
                level, _building_name(node), node, label, unit,
                value, duration, now)
            try:
                channels = self.notifier.send(title, text)
            except Exception as e:
                print(f"[校园告警] 恢复通知失败（不影响状态机）: {e}", flush=True)
        print(f"[校园告警] 恢复 [{node}] {level} {label}，回落至 {value}"
              f"（持续 {int(duration // 60)} 分 {int(duration % 60)} 秒，"
              f"渠道: {','.join(channels) or '仅入库'}）", flush=True)

        st["firing"] = False
        st["count"] = 0
        st["peak"] = None
        st["alert_id"] = None
        st["started_at"] = None
