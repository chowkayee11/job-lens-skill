# 平台安装

## Codex

```bash
ln -s "/absolute/path/job-lens-skill" ~/.agents/skills/job-lens-skill
```

重新打开会话后使用 `$job-lens-skill`，或直接提出岗位匹配、岗位雷达需求。

## Claude Code

```bash
ln -s "/absolute/path/job-lens-skill" ~/.claude/skills/job-lens-skill
```

重新打开 Claude Code 后调用 `/job-lens-skill`。

## DeepSeek Harness

把仓库目录加入 DeepSeek Harness filesystem skill provider 的扫描根目录，或链接到其用户 Skill 根目录。确认会话技能目录中出现 `job-lens-skill` 后再运行。

## 豆包电脑版

`doubao-plugin/` 是豆包电脑版插件包。它只适用于能访问本机项目、Python 和 Chrome 的本地任务。按当前豆包开发者工具要求校验并导入插件；手机端与云端任务不支持本地 BOSS 采集。

豆包插件协议仍在演进。发布前使用当前版本 `dbx` 校验 `plugin.json` 与 `com.doubao/cli.json`，不要绕过校验上传。
