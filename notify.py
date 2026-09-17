# -*- coding: utf-8 -*-
"""告警通知模块：钉钉机器人 + SMTP 邮件 + 控制台降级。

设计要点（面试素材）：
- 渠道可插拔：config 里没配的渠道自动跳过，本地开发只有控制台输出
- 每个渠道独立 try/except：某个渠道发送失败不影响其他渠道，更不影响采集主链路
- 用标准库 urllib/smtplib 实现，不额外引入 requests 依赖
"""
import json
import smtplib
import socket
import time
import urllib.request
from email.header import Header
from email.mime.text import MIMEText

import config

# Windows 控制台/重定向输出默认 GBK 编码，emoji（如 🚨）无法编码会抛
# UnicodeEncodeError；统一把 stdout 转成 UTF-8（面试坑点：Windows 下中文/emoji 输出编码）
try:
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def fmt_time(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))


class Notifier:
    """多渠道通知器：钉钉 / 邮件 / 控制台（控制台永远可用）。"""

    def __init__(self):
        self.dingtalk_enabled = bool(config.DINGTALK_WEBHOOK)
        self.email_enabled = bool(
            config.SMTP_HOST and config.SMTP_USER and config.SMTP_PASSWORD and config.ALERT_EMAIL_TO
        )

    def send(self, title: str, text: str) -> list:
        """发送通知，返回实际使用的渠道列表。"""
        channels = []
        # 控制台：始终可用（本地开发模式）；打印本身也兜底，任何情况下不因通知抛异常
        try:
            print(f"[通知/控制台] {title}\n{text}\n", flush=True)
            channels.append("console")
        except Exception:
            pass

        if self.dingtalk_enabled:
            try:
                self._send_dingtalk(title, text)
                channels.append("dingtalk")
            except Exception as e:
                print(f"[通知] 钉钉发送失败: {e}", flush=True)

        if self.email_enabled:
            try:
                self._send_email(title, text)
                channels.append("email")
            except Exception as e:
                print(f"[通知] 邮件发送失败: {e}", flush=True)

        return channels

    # ===== 钉钉机器人（Webhook 自定义机器人，markdown 消息）=====
    @staticmethod
    def _send_dingtalk(title: str, text: str):
        payload = json.dumps({
            "msgtype": "markdown",
            "markdown": {"title": title, "text": text},
        }).encode("utf-8")
        req = urllib.request.Request(
            config.DINGTALK_WEBHOOK,
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if body.get("errcode") != 0:
            raise RuntimeError(f"钉钉返回错误: {body}")

    # ===== SMTP 邮件 =====
    @staticmethod
    def _send_email(title: str, text: str):
        msg = MIMEText(text, "plain", "utf-8")
        msg["Subject"] = Header(title, "utf-8")
        msg["From"] = config.SMTP_USER
        msg["To"] = ", ".join(config.ALERT_EMAIL_TO)

        if config.SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
        else:
            server = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
            server.starttls()
        try:
            server.login(config.SMTP_USER, config.SMTP_PASSWORD)
            server.sendmail(config.SMTP_USER, config.ALERT_EMAIL_TO, msg.as_string())
        finally:
            server.quit()


def build_alert_message(level, metric_label, target, value, threshold, hostname, ts, top_procs=None) -> tuple:
    """组装告警/恢复通知的标题与正文（钉钉 markdown / 邮件纯文本通用）。"""
    title = f"🚨 [{level}] 告警触发: {metric_label}"
    lines = [
        f"**主机**: {hostname}",
        f"**指标**: {metric_label}" + (f" ({target})" if target else ""),
        f"**当前值**: {value}%  (阈值 {threshold}%)",
        f"**时间**: {fmt_time(ts)}",
    ]
    if top_procs:
        lines.append("**高负载进程**:")
        lines += [f"  {i}. {p['name']} (PID {p['pid']}) — {p['cpu']}%"
                  for i, p in enumerate(top_procs, 1)]
    return title, "\n\n".join(lines) + "\n"


def build_recovery_message(level, metric_label, target, value, duration_sec, hostname, ts) -> tuple:
    """组装恢复通知。"""
    title = f"✅ [{level}] 告警恢复: {metric_label}"
    lines = [
        f"**主机**: {hostname}",
        f"**指标**: {metric_label}" + (f" ({target})" if target else ""),
        f"**当前值**: {value}%  (已低于阈值)",
        f"**持续时长**: {int(duration_sec // 60)} 分 {int(duration_sec % 60)} 秒",
        f"**时间**: {fmt_time(ts)}",
    ]
    return title, "\n\n".join(lines) + "\n"


def build_campus_alert_message(level, building_name, node, metric_label, unit,
                               value, threshold, ts) -> tuple:
    """组装校园数字孪生业务告警通知（钉钉 markdown / 邮件通用）。"""
    title = f"🚨 [校园][{level}] 告警触发: {building_name}·{metric_label}"
    level_txt = "严重" if level == "P0" else "预警"
    lines = [
        f"**模块**: 校园数字孪生",
        f"**建筑**: {building_name}（{node}）",
        f"**级别**: [{level}] {level_txt}",
        f"**指标**: {metric_label}",
        f"**当前值**: {value}{unit}  (阈值 {threshold}{unit})",
        f"**时间**: {fmt_time(ts)}",
    ]
    return title, "\n\n".join(lines) + "\n"


def build_campus_recovery_message(level, building_name, node, metric_label, unit,
                                  value, duration_sec, ts) -> tuple:
    """组装校园数字孪生告警恢复通知。"""
    title = f"✅ [校园][{level}] 告警恢复: {building_name}·{metric_label}"
    lines = [
        f"**模块**: 校园数字孪生",
        f"**建筑**: {building_name}（{node}）",
        f"**级别**: [{level}]",
        f"**指标**: {metric_label}",
        f"**当前值**: {value}{unit}  (已低于阈值)",
        f"**持续时长**: {int(duration_sec // 60)} 分 {int(duration_sec % 60)} 秒",
        f"**时间**: {fmt_time(ts)}",
    ]
    return title, "\n\n".join(lines) + "\n"
