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
- [ ] 里程碑 2：Web 仪表盘（ECharts 实时曲线 + 历史趋势）
- [ ] 里程碑 3：阈值告警（分级 P0/P1/P2 + 钉钉/邮件 + 降噪合并）
- [ ] 里程碑 4：实战细节（高负载进程快照、磁盘自动清理、压测脚本）
- [ ] 里程碑 5：Docker 化 + 云服务器部署上线
- [ ] 里程碑 6：技术博客 + 简历包装 + 面试预演

## 快速开始

```bash
pip install -r requirements.txt
python run.py
# 打开 http://127.0.0.1:5000
```

## 目录结构

```
ops-monitor/
├─ run.py          # 启动入口（后台采集线程 + Web 服务）
├─ config.py       # 配置（采集周期、阈值、数据路径、告警渠道）
├─ collector.py    # 指标采集器（psutil）
├─ storage.py      # 历史数据存储（SQLite）
├─ app.py          # Flask 应用（API + 页面）
└─ ...
```
