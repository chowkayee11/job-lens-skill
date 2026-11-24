#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from job_lens.core import (  # noqa: E402
    CRAWL_LIMIT,
    create_run,
    digest_html,
    ingest_unseen,
    mail_settings,
    prepare_agent_request,
    record_notification_failure,
    render_report,
    send_email,
    send_system_notification,
    validate_analysis,
)


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="job-lens-skill 本地流水线")
    sub = cli.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new-run", help="创建运行目录并提取简历文本")
    new.add_argument("resume", type=Path)
    new.add_argument("--run-id")

    ingest = sub.add_parser("ingest", help="导入未采集过的 CSV/JSON 岗位")
    ingest.add_argument("run_dir", type=Path)
    ingest.add_argument("sources", type=Path, nargs="+")
    ingest.add_argument("--limit", type=int, default=CRAWL_LIMIT)

    prepare = sub.add_parser("prepare", help="生成供当前 Agent 处理的请求文件")
    prepare.add_argument("run_dir", type=Path)

    validate = sub.add_parser("validate", help="校验 Agent 写入的 analysis.json")
    validate.add_argument("run_dir", type=Path)

    report = sub.add_parser("report", help="生成静态 HTML 报告")
    report.add_argument("run_dir", type=Path)

    notify = sub.add_parser("notify", help="按规则发送邮件通知")
    notify.add_argument("run_dir", type=Path)
    notify.add_argument("--env-file", type=Path, default=ROOT / ".env")
    notify.add_argument("--force", action="store_true")
    notify.add_argument("--dry-run", action="store_true")
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command == "new-run":
        print(create_run(ROOT, args.resume, args.run_id))
        return 0
    if args.command == "ingest":
        jobs = ingest_unseen(args.run_dir, ROOT / "data" / "job_history.json", args.sources, args.limit)
        print(f"已导入 {len(jobs)} 个此前未采集的岗位")
        return 0
    if args.command == "prepare":
        request = prepare_agent_request(args.run_dir, ROOT / "schemas" / "analysis.schema.json")
        print(f"已准备 {len(request['jobs'])} 个岗位，输出：{args.run_dir / 'agent_request.json'}")
        return 0
    if args.command == "validate":
        result = validate_analysis(args.run_dir, ROOT / "data" / "job_history.json")
        print(f"校验通过：{len(result['jobs'])} 个岗位")
        return 0
    if args.command == "report":
        print(render_report(args.run_dir))
        return 0
    if args.command == "notify":
        subject, _, important = digest_html(args.run_dir)
        if args.dry_run:
            print(f"dry-run：important={important}，subject={subject}")
            return 0
        try:
            if important or args.force:
                send_system_notification("Job Lens", subject)
            sent = send_email(args.run_dir, mail_settings(args.env_file), force=args.force)
            print("邮件已发送" if sent else "邮件未发送")
            return 0
        except Exception as exc:
            record_notification_failure(args.run_dir, exc)
            send_system_notification("Job Lens 邮件失败", str(exc))
            print(f"邮件发送失败，已记录待重试：{exc}", file=sys.stderr)
            return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
