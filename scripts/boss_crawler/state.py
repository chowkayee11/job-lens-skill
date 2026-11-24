#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
采集请求耗时统计
"""

import time

# ==================== 时间统计 ====================

class TimeStats:
    """
    时间统计器
    统计每次请求的耗时和总耗时
    """
    def __init__(self):
        self.reset()

    def reset(self):
        """重置统计"""
        self.start_time = None
        self.end_time = None
        self.requests = []  # 每次请求的记录
        self.current_request_start = None
        self.current_request_type = None
        self.current_request_url = None

    def start(self):
        """开始计时"""
        self.start_time = time.time()

    def stop(self):
        """停止计时"""
        self.end_time = time.time()

    def start_request(self, request_type, url=None):
        """
        开始单次请求计时
        request_type: 'page', 'detail', 'scroll', 'api'
        """
        self.current_request_start = time.time()
        self.current_request_type = request_type
        self.current_request_url = url

    def end_request(self, success=True, extra_info=None):
        """
        结束单次请求计时
        """
        if self.current_request_start is None:
            return

        elapsed = time.time() - self.current_request_start
        record = {
            'type': self.current_request_type,
            'url': self.current_request_url,
            'elapsed': elapsed,
            'success': success,
            'extra': extra_info,
            'timestamp': time.time()
        }
        self.requests.append(record)

        # 打印本次请求耗时
        status = "OK" if success else "FAIL"
        elapsed_str = f"{elapsed:.2f}s"
        type_name = {
            'page': '列表页',
            'detail': '详情页',
            'scroll': '滚动加载',
            'api': 'API请求'
        }.get(self.current_request_type, self.current_request_type)

        extra_str = f" - {extra_info}" if extra_info else ""
        print(f"  [{status}] {type_name}: {elapsed_str}{extra_str}")

        self.current_request_start = None
        self.current_request_type = None
        self.current_request_url = None

        return elapsed

    def get_summary(self):
        """获取统计摘要"""
        if not self.start_time:
            return None

        total_time = (self.end_time or time.time()) - self.start_time
        total_requests = len(self.requests)
        success_requests = sum(1 for r in self.requests if r['success'])
        failed_requests = total_requests - success_requests

        # 按类型统计
        by_type = {}
        for r in self.requests:
            t = r['type']
            if t not in by_type:
                by_type[t] = {'count': 0, 'total_time': 0, 'success': 0}
            by_type[t]['count'] += 1
            by_type[t]['total_time'] += r['elapsed']
            if r['success']:
                by_type[t]['success'] += 1

        return {
            'total_time': total_time,
            'total_requests': total_requests,
            'success_requests': success_requests,
            'failed_requests': failed_requests,
            'by_type': by_type,
            'requests': self.requests
        }

    def print_summary(self):
        """打印统计摘要"""
        summary = self.get_summary()
        if not summary:
            print("\n无统计数据")
            return

        print("\n" + "=" * 50)
        print("  运行时间统计")
        print("=" * 50)

        # 总时间
        total_minutes = int(summary['total_time'] // 60)
        total_seconds = summary['total_time'] % 60
        print(f"\n  总运行时间: {total_minutes}分 {total_seconds:.2f}秒")

        # 请求统计
        print(f"  总请求数: {summary['total_requests']} 次")
        print(f"  成功: {summary['success_requests']} 次")
        print(f"  失败: {summary['failed_requests']} 次")

        # 按类型统计
        print("\n  按类型统计:")
        type_names = {
            'page': '列表页',
            'detail': '详情页',
            'scroll': '滚动加载',
            'api': 'API请求'
        }

        for rtype, stats in summary['by_type'].items():
            type_name = type_names.get(rtype, rtype)
            avg_time = stats['total_time'] / stats['count'] if stats['count'] > 0 else 0
            print(f"    {type_name}: {stats['count']} 次, 平均 {avg_time:.2f}秒/次")

        print()


# 全局时间统计器
time_stats = TimeStats()
