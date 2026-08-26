# -*- coding: utf-8 -*-
"""告警引擎：采集后逐条检查规则，状态机驱动 + 降噪 + 恢复通知。

面试要点：
- 状态机：正常 → 触发(发首条) → 持续(静默，只更新峰值) → 恢复(发恢复通知)
- 降噪：同一条告警只在"触发"和"恢复"两个时刻各发一次通知，
  持续期间每 5 秒都在超阈值，但绝不刷屏
- sustain（持续次数）：P0 要求连续 2 次采样超阈值才触发，滤掉瞬时毛刺
- 重启自愈：进程重启后从数据库恢复"未恢复"的告警状态，
  不会重复发告警、还能继续等到恢复通知
"""
import socket
import time

import config
import notify
import storage

# 指标名 → 展示名（通知与页面用）
METRIC_LABELS = {
    "cpu_percent": "CPU 使用率",
    "mem_percent": "内存使用率",
    "disk_percent": "磁盘使用率",
}


class AlertEngine:
    def __init__(self, notifier: notify.Notifier = None):
        self.notifier = notifier or notify.Notifier()
        self.hostname = socket.gethostname()
        # key = (level, metric, target) → 状态
        self._state = {}
        self._resume_active()

    def _resume_active(self):
        """启动时恢复未结束的告警：进程重启后不重复发告警、能继续等恢复。"""
        for a in storage.active_alerts():
            key = (a["level"], a["metric"], a["target"])
            self._state[key] = {
                "count": 0,
                "firing": True,
                "alert_id": a["id"],
                "peak": a["peak_value"],
                "started_at": a["started_at"],
            }
            print(f"[告警引擎] 恢复未结束告警: {a['level']} {a['metric']}"
                  f"{' (' + a['target'] + ')' if a['target'] else ''}", flush=True)

    def check(self, metric: dict):
        """对一次采集结果检查全部规则。异常只打印，不影响采集主链路。"""
        for level, rule in config.ALERT_RULES.items():
            metric_name = rule["metric"]
            threshold = rule["threshold"]
            sustain = rule["sustain"]

            if metric_name == "disk_percent":
                # 磁盘逐分区检查，target 记录挂载点
                for mount, pct in (metric.get("disks") or {}).items():
                    self._check_rule(level, metric_name, mount, pct, threshold, sustain)
            else:
                self._check_rule(level, metric_name, None,
                                 metric.get(metric_name), threshold, sustain)

    def _check_rule(self, level, metric_name, target, value, threshold, sustain):
        if value is None:
            return
        key = (level, metric_name, target)
        st = self._state.setdefault(key, {
            "count": 0, "firing": False, "alert_id": None,
            "peak": None, "started_at": None,
        })

        if value > threshold:
            if st["firing"]:
                # 持续告警：只更新峰值，不重复通知（降噪核心）
                if st["peak"] is None or value > st["peak"]:
                    st["peak"] = value
                    if st["alert_id"] is not None:
                        storage.update_alert_peak(st["alert_id"], value)
            else:
                st["count"] += 1
                if st["count"] >= sustain:
                    self._fire(level, metric_name, target, value, threshold, st)
                else:
                    print(f"[告警引擎] {level} {METRIC_LABELS[metric_name]}"
                          f"{' (' + target + ')' if target else ''} {value}% 超过阈值 "
                          f"{threshold}%（连续 {st['count']}/{sustain} 次，暂不告警）", flush=True)
        else:
            if st["firing"]:
                self._recover(level, metric_name, target, value, st)
            st["count"] = 0  # 回到正常区间，重置连续计数

    def _fire(self, level, metric_name, target, value, threshold, st):
        st["firing"] = True
        st["peak"] = value
        st["started_at"] = time.time()
        st["alert_id"] = storage.create_alert(level, metric_name, target, threshold, value)

        title, text = notify.build_alert_message(
            level, METRIC_LABELS[metric_name], target, value, threshold,
            self.hostname, st["started_at"],
        )
        channels = self.notifier.send(title, text)
        print(f"[告警引擎] 触发 {level} {METRIC_LABELS[metric_name]}"
              f"{' (' + target + ')' if target else ''}: {value}%（渠道: {','.join(channels)}）",
              flush=True)

    def _recover(self, level, metric_name, target, value, st):
        duration = time.time() - st["started_at"]
        if st["alert_id"] is not None:
            storage.close_alert(st["alert_id"], time.time())

        title, text = notify.build_recovery_message(
            level, METRIC_LABELS[metric_name], target, value, duration,
            self.hostname, time.time(),
        )
        channels = self.notifier.send(title, text)
        print(f"[告警引擎] 恢复 {level} {METRIC_LABELS[metric_name]}"
              f"{' (' + target + ')' if target else ''}: 回落至 {value}%"
              f"（持续 {int(duration // 60)} 分 {int(duration % 60)} 秒，渠道: {','.join(channels)}）",
              flush=True)
        st["firing"] = False
        st["count"] = 0
        st["peak"] = None
        st["alert_id"] = None


if __name__ == "__main__":
    # 独立运行：喂一次假数据快速自测状态机（配合 scripts/trigger_test.py 做完整演练）
    engine = AlertEngine()
    fake = {"cpu_percent": 97.0, "mem_percent": 92.0,
            "disks": {"C:\\": 88.0}, "net_in_bytes": 0, "net_out_bytes": 0}
    engine.check(fake)
