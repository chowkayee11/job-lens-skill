# Job Lens Skill

本地岗位发现与求职决策助手，支持 Codex、Claude Code、DeepSeek Harness 和豆包电脑版。简历输入支持 PDF、DOCX、Markdown、TXT 和 LaTeX 源文件。

Job Lens 从简历出发采集或导入岗位，把每项岗位要求与简历原文对应起来，区分“已匹配、证据不足、真实缺口”，再生成推荐等级、简历修改建议、招呼语、HTML 报告和邮件摘要。

> 基于 [zhansan379/boss-crawler-skill](https://github.com/zhansan379/boss-crawler-skill) 派生。保留其部分 DrissionPage 采集和文件解析能力，重做了 Agent 编排、历史去重、证据账本、通知与平台适配。感谢原作者。

## 特点

- 无模型 API 配置：语义分析直接使用当前 Agent 会话。
- 历史感知：每次最多保存 50 个从未采集过的岗位，而非只看发布时间。
- 可解释匹配：最多分析 30 个岗位，每项结论都要关联简历证据。
- 克制通知：Agent 消息和邮件详细展示前 10 个，其余进入本地报告。
- 本地优先：简历、Cookie、历史库和分析产物默认不离开电脑。
- 安全边界：不自动投递、不上传简历、不处理验证码、不编造经历。

## 流程

```text
简历 → 搜索条件 → 采集/导入 → 历史去重 → 规则初筛
     → 当前 Agent 证据分析 → HTML 报告 → Agent/系统/邮件通知
```

## 安装

要求 Python 3.10+、Chrome。在线采集需要安装 `requirements.txt`：

```bash
python -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

各 Agent 的安装方式见 [docs/platforms.md](docs/platforms.md)。豆包电脑版插件包位于 `doubao-plugin/`。

## 快速开始

```bash
python scripts/job_lens_cli.py new-run "/path/to/resume.pdf"

python scripts/job_lens_crawl.py "runs/<timestamp>" \
  -k "Java后端" -k "后端开发" -c "武汉" --limit 50

# 或导入已有数据
python scripts/job_lens_cli.py ingest "runs/<timestamp>" jobs.csv jobs.json

python scripts/job_lens_cli.py prepare "runs/<timestamp>"
```

让当前 Agent 读取 `agent_request.json`，按 `schemas/analysis.schema.json` 写入 `analysis.json`，然后：

```bash
python scripts/job_lens_cli.py validate "runs/<timestamp>"
python scripts/job_lens_cli.py report "runs/<timestamp>"
python scripts/job_lens_cli.py notify "runs/<timestamp>" --dry-run
```

## 邮件配置

复制 `.env.example` 为 `.env`，填写 SMTP 主机、邮箱和授权码。SMTP 只用于通知，不是模型 API。

默认仅在出现 A 级岗位或至少 3 个 B 级岗位时发送邮件。真实发送前应先运行 `--dry-run`；失败会生成 `notification_retry.json`，不会重新采集岗位。

## 数据目录

```text
data/job_history.json           # 跨任务岗位历史
runs/<timestamp>/resume.txt     # 本次简历文本
runs/<timestamp>/jobs.json      # 最多 50 个未采集岗位
runs/<timestamp>/agent_request.json
runs/<timestamp>/analysis.json # 最多 30 个分析结果
runs/<timestamp>/report.html
```

`data/job_history.json`、`runs/`、`.env` 和浏览器用户数据均不提交 Git。

## 定时任务

建议每个工作日运行一次。涉及在线采集时，电脑、宿主 Agent 和 Chrome 必须可用；登录失效或验证码出现时任务会停止并请求用户处理。

- Codex：Scheduled Tasks。
- Claude Code：launchd、systemd timer、cron 或 Windows 任务计划程序。
- DeepSeek Harness：Harness 调度或系统定时器。
- 豆包电脑版：本地任务与 CLI 扩展；不支持手机端或云端采集。

## 开发与测试

```bash
python -m unittest tests.test_job_lens -v
```

测试完全离线，不打开 Chrome、不连接 SMTP。

## 许可与合规

MIT License。请遵守招聘平台条款和适用法律，合理控制访问频率。项目不提供验证码规避、账号风控绕过或自动海投能力。
