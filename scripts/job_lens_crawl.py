#!/usr/bin/env python3
"""历史感知的 BOSS 岗位采集入口；只保存本地历史库中未出现过的岗位。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from job_lens.core import CRAWL_LIMIT, history_links, ingest_unseen  # noqa: E402


def split_values(values: list[str]) -> list[str]:
    return [item.strip() for value in values for item in value.split(",") if item.strip()]


def build_parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description="采集最多 50 个此前未采集过的 BOSS 岗位")
    cli.add_argument("run_dir", type=Path)
    cli.add_argument("--keyword", "-k", action="append", required=True)
    cli.add_argument("--city", "-c", action="append", required=True)
    cli.add_argument("--limit", type=int, default=CRAWL_LIMIT)
    cli.add_argument("--no-detail", action="store_true")
    cli.add_argument("--job-type", action="append", default=[])
    cli.add_argument("--salary", action="append", default=[])
    cli.add_argument("--experience", action="append", default=[])
    cli.add_argument("--degree", action="append", default=[])
    cli.add_argument("--scale", action="append", default=[])
    return cli


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not 1 <= args.limit <= CRAWL_LIMIT:
        raise SystemExit(f"--limit 必须在 1 到 {CRAWL_LIMIT} 之间")
    if not args.run_dir.exists():
        raise SystemExit(f"运行目录不存在：{args.run_dir}")

    # 延迟导入：查看 --help、导入数据或生成报告时不要求安装浏览器依赖。
    from DrissionPage import WebPage
    from boss_crawler.auth import ensure_login
    from boss_crawler.config import co
    from boss_crawler.crawler import crawl_job_details, crawl_jobs_by_query
    from boss_crawler.data_loader import find_cities_by_name, load_city_data
    from boss_crawler.utils import build_filter_query_string, resolve_filter_values

    keywords = split_values(args.keyword)
    city_names = split_values(args.city)
    cities = find_cities_by_name(load_city_data(), city_names)
    if not keywords or not cities:
        raise SystemExit("关键词或城市无效")

    filters = {
        "jobType": resolve_filter_values(split_values(args.job_type), "jobType"),
        "salary": resolve_filter_values(split_values(args.salary), "salary"),
        "experience": resolve_filter_values(split_values(args.experience), "experience"),
        "degree": resolve_filter_values(split_values(args.degree), "degree"),
        "scale": resolve_filter_values(split_values(args.scale), "scale"),
    }
    filter_query = build_filter_query_string(filters)
    if not ensure_login():
        print("登录未完成，已安全停止。", file=sys.stderr)
        return 1

    raw_file = args.run_dir / "jobs_raw.csv"
    history_file = ROOT / "data" / "job_history.json"
    existing = history_links(history_file)
    run_seen: set[str] = set()
    written = 0
    dp = WebPage(chromium_options=co)
    try:
        # 城市与关键词交错轮转，每个组合最多取 2 条，避免第一个关键词/城市
        # 独占全局 50 条额度。轮次偏移确保四个关键词都能覆盖不同城市。
        combinations = [
            (keywords[(city_index + round_index) % len(keywords)], city_code)
            for round_index in range(len(keywords))
            for city_index, (_, city_code) in enumerate(cities)
        ]
        for keyword, city_code in combinations:
            remaining = args.limit - written
            if remaining <= 0:
                break
            query_limit = min(2, remaining)
            stats = crawl_jobs_by_query(
                dp, keyword, city_code, str(raw_file), query_limit, existing, filter_query, run_seen
            )
            written += stats[1]
        if written and not args.no_detail:
            crawl_job_details(dp, str(raw_file), set())
    finally:
        dp.quit()

    jobs = ingest_unseen(args.run_dir, history_file, [raw_file], args.limit)
    print(f"采集完成：{len(jobs)} 个此前未采集的岗位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
