# 服务器监控告警系统（运维求职项目）

一个从零实现的轻量服务器监控系统：采集服务器指标 → Web 可视化 → 阈值告警（钉钉/邮件）→ 历史数据留存。
面向运维岗位求职：**完整开发 + 部署上线 + 技术博客**。

## 技术栈

- Python 3.13 + psutil（指标采集）
- Flask（Web API + 页面）
- SQLite（历史数据存储）
- ECharts（前端图表）
- 钉钉/企业微信机器人 + SMTP 邮件（告警通知）
- Docker（部署）

## 功能规划

- [x] 里程碑 1：指标采集（CPU/内存/磁盘/网络）+ 存储 + Web API
- [x] 里程碑 2：Web 仪表盘（ECharts 实时曲线 + 历史趋势 + 时间范围切换）
- [x] 里程碑 3：阈值告警（分级 P0/P1/P2 + 钉钉/邮件 + 状态机降噪）
- [ ] 里程碑 4：实战细节（高负载进程快照、磁盘自动清理、压测脚本）
- [ ] 里程碑 5：Docker 化 + 云服务器部署上线
- [ ] 里程碑 6：技术博客 + 简历包装 + 面试预演

## 仪表盘功能（里程碑 2）

- 深色监控风单页仪表盘，本地引入 echarts.min.js（离线可用）
- 实时指标卡片：CPU / 内存 / 磁盘（最高分区）/ 网络速率，颜色随阈值变化（绿/黄/红）
- 图表：CPU 与内存双曲线、网络收发流量、磁盘各分区柱状图
- 时间范围切换：实时（10 分钟窗口）/ 1 小时 / 24 小时 / 7 天，范围越大刷新越慢
- 7 天长范围由服务端按时间桶抽稀聚合（最多 300 个点），前端不卡顿

## 告警功能（里程碑 3）

- 三级规则（config.py 可调）：P0（CPU>95% 连续 2 次采样）、P1（内存>90%）、P2（磁盘>85%，逐分区）
- 状态机降噪：正常 → 触发（发首条通知）→ 持续（静默，只更新峰值）→ 恢复（发恢复通知）
- 告警历史入库（alerts 表），仪表盘展示活跃告警横幅 + 最近告警列表
- 通知渠道可插拔：钉钉机器人 Webhook + SMTP 邮件，未配置时自动降级为控制台输出
- 重启自愈：进程重启后从数据库恢复未结束的告警，不重复发、还能继续等恢复
- 演练工具：`python scripts/trigger_test.py`（喂假数据端到端验证全链路）

## API

| 接口 | 说明 |
|------|------|
| `GET /api/metrics/latest` | 最新一条指标（含内存已用/总量 GB、磁盘各分区） |
| `GET /api/metrics/history?limit=N` | 最近 N 条原始记录（默认 500，上限 5000） |
| `GET /api/metrics/range?minutes=N&max_points=M` | 最近 N 分钟的聚合序列，超过 M 个点时按时间桶取均值抽稀 |
| `GET /api/alerts/active` | 当前未恢复的告警 |
| `GET /api/alerts?limit=N` | 最近 N 条告警记录（含已恢复），默认 50 |

## 快速开始

```bash
pip install -r requirements.txt
python run.py
# 打开 http://127.0.0.1:5000
```

## 目录结构

```
ops-monitor/
├─ run.py          # 启动入口（后台采集线程 + 告警检查 + Web 服务）
├─ config.py       # 配置（采集周期、告警阈值、通知渠道、数据路径）
├─ collector.py    # 指标采集器（psutil）
├─ storage.py      # SQLite 存储（指标 + 告警历史，含时间桶聚合抽稀）
├─ alert.py        # 告警引擎（状态机 + 降噪 + 恢复通知）
├─ notify.py       # 通知模块（钉钉 / 邮件 / 控制台降级）
├─ app.py          # Flask 应用（API + 页面）
├─ scripts/
│  └─ trigger_test.py  # 告警链路演练脚本（喂假数据端到端验证）
├─ templates/
│  └─ dashboard.html   # 仪表盘页面
├─ static/
│  ├─ echarts.min.js   # 本地 ECharts（离线可用）
│  ├─ dashboard.css    # 深色监控风样式
│  └─ dashboard.js     # 前端逻辑（轮询/图表/告警区）
├─ docs/
│  └─ dashboard.png    # 仪表盘截图
└─ data/
   └─ metrics.db       # SQLite 数据（已 gitignore）
```
