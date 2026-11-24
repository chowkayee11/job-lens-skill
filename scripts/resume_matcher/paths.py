"""兼容上游采集器仍使用的少量运行路径。"""

import os


def state_dir(run_dir):
    return os.path.join(run_dir, "state")


def crawl_params_path(run_dir):
    return os.path.join(state_dir(run_dir), "crawl_params.json")


def crawl_summary_path(run_dir):
    return os.path.join(state_dir(run_dir), "crawl_summary.json")
