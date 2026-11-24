# job-lens-skill 开发约束

- 保持 Codex、Claude Code、DeepSeek Harness、豆包电脑版共用一套 Python 核心。
- Python 不调用任何模型 API；语义任务通过 `agent_request.json` / `analysis.json` 交接。
- 不增加自动投递、验证码规避、简历上传或隐私云同步。
- 单次采集、分析、详细推送上限固定为 50 / 30 / 10，修改时必须同步测试和文档。
- 新增非平凡逻辑必须有离线测试；测试不得打开浏览器或发送邮件。
