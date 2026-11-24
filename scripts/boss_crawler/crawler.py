#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
爬取引擎：关键词列表翻页与详情采集
"""

import csv
import json
import os
import time
import urllib.parse

from .auth import check_login_elements, check_login_status, check_page_status, wait_for_user_action
from .config import (
    CSV_FIELDS, ENCODING, DUP_PAGE_MIN_LINKS, DUP_PAGE_RATIO, sleep_config,
)
from .data_loader import init_csv_file
from .state import time_stats


# ==================== 列表数据处理 ====================

def process_job_list(job_list, file_path, existing_links, csv_writer, run_seen=None):
    """处理岗位列表数据（去重写入 CSV）

    两个去重集合语义不同，不要合并：
      existing_links —— 本文件已有的行 + 本文件本次新写入的，决定是否写盘。
      run_seen       —— 本轮运行（所有关键词 × 城市）遇到过的全部 link。
                        既参与写盘决策，也是「这一页全是同义关键词的重复」的判据。

    run_seen 为 None 时行为与拆分前完全一致（本函数是 __init__ 导出的公开 API）。

    Returns:
        (written, skipped, run_dups)
        run_dups 只数「本轮其他地方已见过」的，是 skipped 的子集。
    """
    written = 0
    skipped = 0
    run_dups = 0

    for job in job_list:
        job_link = f"https://www.zhipin.com/job_detail/{job['encryptJobId']}.html"

        seen_this_run = run_seen is not None and job_link in run_seen
        if seen_this_run:
            run_dups += 1

        if job_link in existing_links or seen_this_run:
            skipped += 1
            if run_seen is not None:
                run_seen.add(job_link)
            continue

        dit = {
            'link': job_link,
            '职位': job.get('jobName', ''),
            '城市': job.get('cityName', ''),
            '区域': job.get('areaDistrict', ''),
            '商圈': job.get('businessDistrict', ''),
            '公司': job.get('brandName', ''),
            '薪资': job.get('salaryDesc', ''),
            '经验': job.get('jobExperience', ''),
            '学历': job.get('jobDegree', ''),
            '领域': job.get('brandIndustry', ''),
            '性质': job.get('brandStageName', ''),
            '规模': job.get('brandScaleName', ''),
            '技能标签': ' '.join(job.get('skills', [])),
            '福利标签': ' '.join(job.get('welfareList', [])),
            '位置': str(job.get('gps', '')),
            '岗位要求和职责': '',
            '公司信息': '',
            # 以下字段只存在于详情 API，列表阶段一律留空，由 crawl_job_details 回填。
            # 空串 = 未采集，不要写成 '否'
            '地址': '',
            '已失效': '',
            '代招': '',
            'HR活跃度': '',
            'HR在线': '',
            'HR职位': '',
            'HR姓名': '',
            'HR公司': ''
        }

        csv_writer.writerow(dit)
        existing_links.add(job_link)
        if run_seen is not None:
            run_seen.add(job_link)
        written += 1

    return written, skipped, run_dups


# ==================== 单页爬取循环（共用） ====================

def should_skip_remaining_pages(page_size, run_dups):
    """本页是否已经基本全是本轮其他关键词采过的岗位 → 跳到下一个关键词。

    只看 run_dups（本轮其他关键词已采），不看总重复数 —— 理由见
    config.DUP_PAGE_RATIO 的注释：用总重复数会打断「同一关键词续爬更深的页」。
    """
    if page_size < DUP_PAGE_MIN_LINKS:
        return False
    return run_dups / page_size >= DUP_PAGE_RATIO


def _crawl_paginated(dp, url, file_path, count_limit, existing_links, run_seen=None,
                     job_filter=None):
    """
    通用的翻页爬取循环。
    岗位分类和关键词搜索共用此翻页逻辑。job_filter 可选，接收单个岗位并决定是否写入。

    Returns:
        (total_processed, total_written, total_skipped, total_run_dups)
    """
    dp.get(url)
    dp.listen.start('zpgeek/search/joblist.json')
    time_stats.end_request(True, url)

    total_written = 0
    total_skipped = 0
    total_run_dups = 0
    page_num = 1
    consecutive_no_data = 0

    with open(file_path, 'a', encoding=ENCODING, newline='') as f:
        csv_writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)

        while True:
            if count_limit and total_written >= count_limit:
                print(f"\n已达到数量限制 {count_limit} 条")
                break

            print(f"\n[第{page_num}页] 爬取中...")

            try:
                time_stats.start_request('scroll')
                dp.scroll.to_bottom()
                time_stats.end_request(True)
            except Exception as e:
                time_stats.end_request(False, str(e))
                print(f"滚动失败: {e}")
                continue

            time_stats.start_request('api', 'zpgeek/search/joblist.json')
            r = dp.listen.wait(timeout=3)
            status = check_page_status(dp, r)

            if status == 'need_login':
                time_stats.end_request(False, '需要登录')
                print(f"[第{page_num}页] [!] 检测到需要登录，请手动登录...")
                if not wait_for_user_action(dp):
                    print("等待超时，停止爬取")
                    break
                continue

            if status == 'no_data':
                time_stats.end_request(False, '无数据')
                consecutive_no_data += 1
                if consecutive_no_data >= 2:
                    print(f"\n连续 {consecutive_no_data} 次无数据（已重试一次），爬取结束")
                    break
                print(f"[第{page_num}页] 无数据，等待重试...")
                sleep_config.sleep('retry')
                continue

            consecutive_no_data = 0

            try:
                job_list = r.response.body.get('zpData', {}).get('jobList', [])
                if job_filter is not None:
                    job_list = [j for j in job_list if job_filter(j)]
                if count_limit:
                    # BOSS 每页通常返回 15 条；最后一页必须按剩余额度截断，
                    # 否则 limit=50 会在第 4 页写成 60 条。
                    job_list = job_list[:max(0, count_limit - total_written)]
                written, skipped, run_dups = process_job_list(
                    job_list, file_path, existing_links, csv_writer, run_seen
                )
                total_written += written
                total_skipped += skipped
                total_run_dups += run_dups

                time_stats.end_request(True, f"获取{len(job_list)}条,写入{written}条")
                print(f"[第{page_num}页] 获取到 {len(job_list)} 条数据，已写入 {written} 条（跳过 {skipped} 条重复）")

                if should_skip_remaining_pages(len(job_list), run_dups):
                    pct = round(run_dups / len(job_list) * 100)
                    print(f"[第{page_num}页] 本页 {len(job_list)} 条中 {run_dups} 条"
                          f"已由本轮其他关键词采过（{pct}%），跳过剩余分页")
                    break
            except Exception as e:
                time_stats.end_request(False, str(e))
                print(f"[第{page_num}页] 处理数据失败: {e}")

            page_num += 1
            sleep_config.sleep('page')

    dp.listen.stop()
    return total_written + total_skipped, total_written, total_skipped, total_run_dups


# ==================== 按岗位 code 爬取 ====================

def crawl_jobs_by_position(dp, position_code, city_code, file_path, count_limit,
                           existing_links, filter_query='', run_seen=None):
    """按岗位code爬取"""
    init_csv_file(file_path)

    url = f'https://www.zhipin.com/web/geek/job?position={position_code}&city={city_code}{filter_query}'
    print(f"\n访问: {url}")
    time_stats.start_request('page', url)

    return _crawl_paginated(dp, url, file_path, count_limit, existing_links, run_seen)


# ==================== 按关键词爬取 ====================

def crawl_jobs_by_query(dp, query, city_code, file_path, count_limit,
                        existing_links, filter_query='', run_seen=None):
    """按关键词爬取"""
    init_csv_file(file_path)

    encoded_query = urllib.parse.quote(query)
    url = f'https://www.zhipin.com/web/geek/jobs?city={city_code}&query={encoded_query}{filter_query}'
    print(f"\n访问: {url}")
    time_stats.start_request('page', url)

    return _crawl_paginated(dp, url, file_path, count_limit, existing_links, run_seen)


# ==================== 详情爬取 ====================

def get_single_job_detail(dp, url):
    """
    获取单个岗位详情（优先API直调，兜底DOM解析）

    Returns:
        dict: {'jd', 'company_info', 'hr_active', 'hr_online', 'hr_title'}
              HR 三项仅 API 直调分支可得，DOM 兜底时为空串。
        None: 获取失败或需要登录
    """
    import re
    try:
        time_stats.start_request('detail', url)

        # Step 1: 快速加载详情页 HTML（不等 JS 渲染，~0.8s）
        dp.get(url)
        html = dp.html

        # Step 2: 从 HTML 中提取 securityId 和 jobId
        m_sid = re.search(r"securityId:\s*'([^']+)'", html)
        m_jid = re.search(r"job_id:\s*'([^']+)'", html)

        if not m_sid or not m_jid:
            # securityId 提取失败，回退到 DOM 解析
            if check_login_elements(dp):
                time_stats.end_request(False, '需要登录')
                return None
            return _extract_detail_from_dom(dp)

        security_id = m_sid.group(1)
        job_id = m_jid.group(1)

        # Step 3: 直接调用详情 API（~0.1s）
        api_url = (
            f'https://www.zhipin.com/wapi/zpgeek/job/detail.json'
            f'?securityId={security_id}&jobId={job_id}'
        )
        dp.listen.start('job/detail.json')
        dp.get(api_url)
        r = dp.listen.wait(timeout=8)
        dp.listen.stop()

        if not r:
            # API 超时，回退 DOM
            dp.get(url)
            return _extract_detail_from_dom(dp)

        body = r.response.body
        zp = body.get('zpData', {})

        # 提取岗位描述
        job_info = zp.get('jobInfo', {})
        post_desc = job_info.get('postDescription', '')
        if not post_desc:
            # 备用：某些岗位可能用不同字段名
            post_desc = job_info.get('postDesc', '')

        # 拼装完整描述：岗位职责 + 任职要求等
        for key in ('job_description', 'job_require', 'jobRequire', 'jobDescription'):
            val = job_info.get(key, '')
            if val:
                post_desc += '\n' + val

        # 提取公司信息。
        #
        # 真实键名是 `introduce`（2026-08-13 对 job_detail.json 实测确认）。
        # 这里原先只试了 content / companyInfo / introduction —— 差两个字母，
        # 于是 15/15 的岗位公司简介全是空的，而同批 HR 活跃度全部正常，
        # 看起来像「BOSS 没提供简介」而不是「键名取错了」。所以 introduce 放第一位，
        # 其余保留作兜底（不同版本的接口可能换名）。
        brand_info = zp.get('brandComInfo', {})
        comp_info = ''
        if isinstance(brand_info, dict):
            for key in ('introduce', 'content', 'companyInfo', 'introduction'):
                value = brand_info.get(key, '')
                if value and str(value).strip():
                    comp_info = str(value).strip()
                    break
        elif isinstance(brand_info, str):
            comp_info = brand_info

        if post_desc:
            time_stats.end_request(True, 'API直调')
            return {
                'jd': post_desc,
                'company_info': comp_info if comp_info else '',
                **_extract_job_extras(job_info),
                **_extract_brand_extras(brand_info),
                **_extract_hr_info(zp),
            }

        # API 没有描述内容，回退 DOM
        dp.get(url)
        return _extract_detail_from_dom(dp)

    except Exception as e:
        time_stats.end_request(False, str(e))
        print(f"获取详情失败: {e}")
        return None


def _tri_state(value):
    """布尔字段 → '是'/'否'/''。

    取不到时留空串而非 '否' —— 「未采集」不能被读成「不是」。
    整个技能里 hr_online、已失效、代招 都用这一个语义。
    """
    return '' if value is None else ('是' if value else '否')


# 详情缺失时的空值集。DOM 兜底路径和 API 路径必须返回同一套键，
# 否则 crawl_job_details 回填时会 KeyError。
EMPTY_DETAIL_EXTRAS = {
    'address': '', 'invalid': '', 'proxy': '', 'welfare': '',
    'hr_active': '', 'hr_online': '', 'hr_title': '', 'hr_name': '', 'hr_company': '',
}


def _extract_job_extras(job_info):
    """从 zpData.jobInfo 提取列表页拿不到的岗位事实。

    - invalidStatus：岗位是否已失效。失效岗位投了也是白投，值得单独一列。
    - proxyJob：代招标记。为 1 时跟你聊的是猎头/外包，不是用人公司自己的 HR。
    - address：具体上班地址（列表页只有经纬度）。
    """
    if not isinstance(job_info, dict):
        return {'address': '', 'invalid': '', 'proxy': ''}

    return {
        'address': (job_info.get('address') or '').strip(),
        'invalid': _tri_state(job_info.get('invalidStatus')),
        'proxy': _tri_state(job_info.get('proxyJob')),
    }


def _extract_brand_extras(brand_info):
    """从 zpData.brandComInfo 提取完整福利标签。

    详情里的 labels 通常比列表页的 welfareList 全得多（实测 20 条 vs 几条），
    所以单独取出来，由调用方在列表页值为空时回填。
    """
    if not isinstance(brand_info, dict):
        return {'welfare': ''}

    labels = brand_info.get('labels')
    if not isinstance(labels, list):
        return {'welfare': ''}

    return {'welfare': ' '.join(str(x).strip() for x in labels if str(x).strip())}


def _extract_hr_info(zp):
    """
    从详情 API 的 zpData.bossInfo 提取招聘者信息。

    快照语义：活跃度是爬取瞬间的状态。bossOnline 波动极快，
    投递时基本已过期；activeTimeDesc 粒度粗但相对稳定，是排序的主要依据。

    hr_company 是 HR **自己**所属的公司，和岗位挂的公司可能不是一家 ——
    实测见过岗位公司「深圳某大型ICT…」而 HR 是「途聚人力」的猎头。
    两者不一致就是代招的旁证，所以单独存一列。
    """
    boss = zp.get('bossInfo') or {}
    if not isinstance(boss, dict):
        return {'hr_active': '', 'hr_online': '', 'hr_title': '',
                'hr_name': '', 'hr_company': ''}

    return {
        'hr_active': boss.get('activeTimeDesc') or '',
        'hr_online': _tri_state(boss.get('bossOnline')),
        'hr_title': boss.get('title') or '',
        'hr_name': boss.get('name') or '',
        'hr_company': boss.get('brandName') or '',
    }


def _extract_detail_from_dom(dp):
    """兜底方案：从 DOM 中提取详情（需要等 JS 渲染完成）

    DOM 里只有 JD 和公司简介两段文本，其余字段一律留空 ——
    空串的语义是「未采集」，下游据此显示，不会被误读成「否」。
    """
    if dp.wait.ele_displayed('css:.job-sec-text', timeout=15):
        pass  # 元素已出现

    if check_login_elements(dp):
        time_stats.end_request(False, '需要登录')
        return None

    res = dp.eles('css:.job-sec-text')

    if len(res) == 1:
        time_stats.end_request(True, 'DOM解析')
        return {'jd': res[0].text, 'company_info': '', **EMPTY_DETAIL_EXTRAS}
    elif len(res) == 2:
        time_stats.end_request(True, 'DOM解析')
        return {'jd': res[0].text, 'company_info': res[1].text, **EMPTY_DETAIL_EXTRAS}
    else:
        time_stats.end_request(False, '未找到详情元素')
        return None


def crawl_job_details(dp, file_path, existing_links):
    """
    爬取岗位详情
    使用传入的dp实例，不创建新浏览器
    """
    if not os.path.exists(file_path):
        print(f"文件不存在: {file_path}")
        return 0

    rows = []
    links_to_update = []

    with open(file_path, 'r', encoding=ENCODING) as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
            if not row.get('岗位要求和职责') and row['link'] not in existing_links:
                links_to_update.append(row['link'])

    if not links_to_update:
        print("所有岗位详情已存在，无需爬取")
        return 0

    print(f"\n正在爬取 {len(links_to_update)} 个岗位详情...")

    success_count = 0

    for i, link in enumerate(links_to_update, 1):
        print(f"\n[{i}/{len(links_to_update)}] {link}")

        detail = get_single_job_detail(dp, link)

        if detail is None:
            print(f"  [!] 可能需要登录或遇到验证码，自动等待检测...")
            retry_start = time.time()
            retry_timeout = 120
            retry_success = False

            while time.time() - retry_start < retry_timeout:
                elapsed = int(time.time() - retry_start)
                try:
                    dp.get('https://www.zhipin.com/web/geek/jobs')
                    if check_login_status(dp):
                        print(f"  [恢复] 登录状态恢复，重试获取详情...")
                        detail = get_single_job_detail(dp, link)
                        retry_success = True
                        break
                except:
                    pass
                if elapsed % 15 < 3:
                    print(f"  [等待恢复] {elapsed}s / {retry_timeout}s ...")

            if not retry_success:
                print(f"  [跳过] 等待超时，跳过此岗位详情")
                continue

        if detail:
            for row in rows:
                if row['link'] == link:
                    row['岗位要求和职责'] = detail['jd']
                    row['公司信息'] = detail['company_info']
                    row['地址'] = detail.get('address', '')
                    row['已失效'] = detail.get('invalid', '')
                    row['代招'] = detail.get('proxy', '')
                    row['HR活跃度'] = detail.get('hr_active', '')
                    row['HR在线'] = detail.get('hr_online', '')
                    row['HR职位'] = detail.get('hr_title', '')
                    row['HR姓名'] = detail.get('hr_name', '')
                    row['HR公司'] = detail.get('hr_company', '')
                    # 详情的福利列表比列表页全得多，但只在列表页没采到时才覆盖，
                    # 避免用一份可能为空的详情数据抹掉已有值
                    welfare = detail.get('welfare', '')
                    if welfare and not (row.get('福利标签') or '').strip():
                        row['福利标签'] = welfare
                    break
            success_count += 1
            existing_links.add(link)
        else:
            print(f"  [FAIL] 获取失败")

        # 增量保存：每获取 5 个详情或最后一条时写入文件
        if success_count % 5 == 0 or i == len(links_to_update):
            try:
                with open(file_path, 'w', encoding=ENCODING, newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction='ignore')
                    writer.writeheader()
                    writer.writerows(rows)
            except Exception as save_err:
                print(f"  [警告] 增量保存失败: {save_err}")

        # 分批冷却：每 detail_batch 个详情请求暂停一次（模拟人类阅读节奏、给风控降温）。
        # 用序号 i 而非成功数，因为失败的请求也占风控额度。
        if i % sleep_config.detail_batch == 0 and i > 0:
            print(f"  [冷却] 已请求 {i}/{len(links_to_update)}，暂停 {sleep_config.batch_cooldown}s ...")
            sleep_config.sleep('batch')
        sleep_config.sleep('detail')  # 请求间隔（带随机抖动，见 SleepConfig）

    # 最终保存
    try:
        with open(file_path, 'w', encoding=ENCODING, newline='') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction='ignore')
            writer.writeheader()
            writer.writerows(rows)
    except Exception as final_save_err:
        print(f"  [警告] 最终保存失败: {final_save_err}")

    print(f"\n详情爬取完成！成功 {success_count} 条")
    return success_count
