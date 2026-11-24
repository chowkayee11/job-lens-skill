---
name: job-lens-skill
description: 本地岗位发现与求职决策助手。读取 PDF/DOCX/Markdown/TXT 简历，采集或导入 BOSS 岗位，排除历史已采集岗位，建立岗位要求与简历原文的证据账本，生成推荐等级、简历修改建议、招呼语、HTML 报告和邮件通知。用户要求找岗位、分析 JD、匹配简历、定时岗位雷达或求职邮件推送时使用。
---

# job-lens-skill

面向 Codex、Claude Code、DeepSeek Harness 和豆包电脑版。所有语义分析由当前会话模型完成；禁止要求用户配置模型 API。

## 不可突破的边界

- 不自动投递、不自动联系招聘者、不上传简历。
- 不编造经历、技能、职责、成果或到岗承诺。
- 证据不足不能写成已匹配；真实缺口不能用文字包装掩盖。
- 验证码、登录失效或访问限制出现时停止，交给用户处理。
- 真实邮件发送前展示摘要并取得用户确认；定时任务使用用户预先确认的通知规则。
- 不读取、打印或提交 Cookie、`.env`、邮箱授权码和运行目录中的隐私数据。

## 固定数量

- 每次最多保存 50 个历史库中从未出现过的岗位。
- 规则初筛后最多交给当前模型分析 30 个岗位。
- Agent 消息和邮件详细展示前 10 个岗位，其余进入 HTML 报告。

“未采集过”不是“新发布”：以岗位 ID 为主、规范化 URL 为辅，与 `data/job_history.json` 比较。

## 工作流

从本 Skill 根目录执行命令。每次只推进一个阶段，并以磁盘产物判断是否完成。

### 1. 创建运行目录

```bash
python scripts/job_lens_cli.py new-run "/absolute/path/to/resume.pdf"
```

记录输出的 `runs/<timestamp>` 绝对路径。不要把简历全文贴回聊天。

### 2A. 在线采集

先向用户一次确认关键词、城市及必要筛选，再执行：

```bash
python scripts/job_lens_crawl.py "<run_dir>" -k "Java后端" -c "武汉" --limit 50
```

可重复 `-k`、`-c` 或使用逗号分隔。命令会复用本机 Chrome 登录态、全局跳过历史岗位，并在总计 50 个未采集岗位后停止。

### 2B. 文件导入

```bash
python scripts/job_lens_cli.py ingest "<run_dir>" jobs.csv more-jobs.json
```

在线采集和文件导入二选一。不要重复导入本次已处理文件。

### 3. 准备语义分析

```bash
python scripts/job_lens_cli.py prepare "<run_dir>"
```

读取 `<run_dir>/agent_request.json`。它最多包含 30 个岗位，并给出输出文件与 Schema 路径。

### 4. 当前会话完成分析

根据请求文件写入 `<run_dir>/analysis.json`：

- `profile`：只包含简历可支持的信息。
- `jobs[].grade`：A/B/C/D。
- `jobs[].evidence[].status`：`matched`、`insufficient` 或 `gap`。
- 每条 `matched` 必须引用 `resume_evidence` 中的简历原文或忠实短摘。
- `resume_suggestions` 只能重组、澄清和突出已有事实。
- `greeting` 不得包含未经用户确认的到岗承诺。

必须使用 `schemas/analysis.schema.json` 的字段结构，不添加替代字段名。

### 5. 校验和报告

```bash
python scripts/job_lens_cli.py validate "<run_dir>"
python scripts/job_lens_cli.py report "<run_dir>"
```

校验失败时只修正 `analysis.json`，不要重新爬取。向用户返回前 10 个岗位摘要和 `report.html` 路径。

### 6. 邮件

先用以下命令验证是否满足通知条件，不发送邮件：

```bash
python scripts/job_lens_cli.py notify "<run_dir>" --dry-run
```

用户确认或定时任务已有授权后，移除 `--dry-run`。默认仅在出现 A 级岗位或至少 3 个 B 级岗位时发送；`--force` 仅在用户明确要求时使用。失败会写入 `notification_retry.json`，只重试邮件，不重新采集和分析。

## 定时岗位雷达

默认建议工作日每天一次。定时提示词必须包含简历路径、关键词、城市、时区、邮件是否已授权和结束条件。涉及本机采集时，电脑、宿主 Agent 和 Chrome 必须可用。无重要岗位时静默更新报告；登录、验证码、采集失败或邮件失败时通知用户。

## 平台说明

- Codex：使用桌面端 Scheduled Tasks；本地文件任务要求电脑开机且应用运行。
- Claude Code：使用当前会话模型，调度交给 `launchd`、systemd timer、cron 或 Windows 任务计划程序。
- DeepSeek Harness：通过本地 Skill provider 加载；使用 Harness 调度或操作系统定时器。
- 豆包电脑版：通过 `doubao-plugin/` 的 Skill + 本地 CLI 入口；不支持本产品的手机端或云端采集。

## 完成标准

只有 `analysis.json` 校验通过、`report.html` 已生成、历史库已更新，才算本轮完成。邮件是通知渠道，发送失败不推翻本轮成果。
