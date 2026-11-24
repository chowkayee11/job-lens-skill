---
name: job-lens-skill
description: 在豆包电脑版本地任务中采集或导入 BOSS 岗位，排除历史已采集岗位，根据简历原文生成证据匹配、推荐等级、HTML 报告和邮件摘要。用户要求找岗位、分析 JD、匹配简历或设置岗位雷达时使用。
---

# Job Lens（豆包电脑版）

仅在本地电脑任务中使用 `job-lens` 和 `job-lens-crawl` CLI。不要在手机端或云任务中承诺访问本机 Chrome、简历和历史库。

固定上限：采集 50 个未采集岗位、分析 30 个、详细展示 10 个。禁止自动投递、自动联系招聘者、上传简历、绕过验证码或编造简历事实。

流程：

1. `job-lens new-run <简历绝对路径>`，记录运行目录。
2. 用户确认关键词和城市后，执行 `job-lens-crawl <run_dir> -k <关键词> -c <城市> --limit 50`；也可用 `job-lens ingest <run_dir> <CSV/JSON>`。
3. `job-lens prepare <run_dir>`，读取生成的 `agent_request.json`。
4. 按其中 Schema 写 `analysis.json`。每项匹配都必须有简历证据，状态只能是 `matched`、`insufficient`、`gap`。
5. 执行 `job-lens validate <run_dir>` 和 `job-lens report <run_dir>`。
6. Agent 消息详细展示前 10 个；真实邮件先 `job-lens notify <run_dir> --dry-run`，获得用户确认后再发送。

验证码、登录失效、访问限制或邮件失败时停止并通知用户。邮件失败只重试通知，不重新采集。
