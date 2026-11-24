from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import smtplib
import ssl
import subprocess
import sys
from collections import Counter
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable


CRAWL_LIMIT = 50
ANALYSIS_LIMIT = 30
PUSH_LIMIT = 10
GRADES = {"A", "B", "C", "D"}
EVIDENCE_STATUSES = {"matched", "insufficient", "gap"}
GRADE_ORDER = {"A": 0, "B": 1, "C": 2, "D": 3}


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(value, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def parse_resume(path: Path) -> str:
    # 复用上游经过测试的 PDF/DOCX/文本读取器；语义结构化由当前 Agent 完成。
    from resume_matcher.parsers import parse_resume_file

    text = parse_resume_file(str(path))
    if not text.strip():
        raise ValueError(f"无法从简历中读取文本：{path}")
    return text


def create_run(root: Path, resume: Path, run_id: str | None = None) -> Path:
    run_id = run_id or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "resume.txt").write_text(parse_resume(resume), encoding="utf-8")
    write_json(
        run_dir / "run.json",
        {"run_id": run_id, "created_at": now_iso(), "resume_source": str(resume.resolve())},
    )
    return run_dir


def canonical_link(value: str) -> str:
    value = (value or "").strip()
    return value.split("?", 1)[0].rstrip("/")


def job_identity(job: dict[str, Any]) -> str:
    link = canonical_link(str(job.get("link") or job.get("url") or ""))
    match = re.search(r"/job_detail/([^/.]+)", link)
    if match:
        return match.group(1)
    if link:
        return hashlib.sha256(link.encode()).hexdigest()[:20]
    basis = "|".join(
        str(job.get(key, "")).strip().lower()
        for key in ("公司", "company", "职位", "title", "城市", "city", "岗位要求和职责", "jd")
    )
    return hashlib.sha256(basis.encode()).hexdigest()[:20]


FIELD_ALIASES = {
    "title": ("title", "职位", "岗位"),
    "company": ("company", "公司"),
    "city": ("city", "城市"),
    "salary": ("salary", "薪资"),
    "experience": ("experience", "经验"),
    "education": ("education", "学历"),
    "skills": ("skills", "技能标签"),
    "jd": ("jd", "岗位要求和职责", "职位描述"),
    "company_info": ("company_info", "公司信息"),
    "link": ("link", "url", "岗位链接"),
    "invalid": ("invalid", "已失效"),
}


def _pick(row: dict[str, Any], names: Iterable[str]) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def normalize_job(row: dict[str, Any]) -> dict[str, Any]:
    job = {key: _pick(row, aliases) for key, aliases in FIELD_ALIASES.items()}
    job["link"] = canonical_link(job["link"])
    job["job_id"] = job_identity({**row, **job})
    job["content_hash"] = hashlib.sha256(
        "|".join(job.get(key, "") for key in ("title", "company", "salary", "jd")).encode()
    ).hexdigest()
    return job


def load_job_file(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as fh:
            return [normalize_job(row) for row in csv.DictReader(fh)]
    data = read_json(path, [])
    if isinstance(data, dict):
        data = data.get("jobs", data.get("data", []))
    if not isinstance(data, list):
        raise ValueError(f"岗位文件必须包含数组：{path}")
    return [normalize_job(row) for row in data if isinstance(row, dict)]


def history_links(history_path: Path) -> set[str]:
    history = read_json(history_path, {"jobs": {}}) or {"jobs": {}}
    return {
        canonical_link(str(item.get("link", "")))
        for item in history.get("jobs", {}).values()
        if item.get("link")
    }


def ingest_unseen(
    run_dir: Path,
    history_path: Path,
    sources: Iterable[Path],
    limit: int = CRAWL_LIMIT,
) -> list[dict[str, Any]]:
    if limit > CRAWL_LIMIT:
        raise ValueError(f"单次采集上限不能超过 {CRAWL_LIMIT}")
    history = read_json(history_path, {"version": 1, "jobs": {}}) or {"version": 1, "jobs": {}}
    known = history.setdefault("jobs", {})
    unseen: list[dict[str, Any]] = []
    run_seen: set[str] = set()
    for source in sources:
        for job in load_job_file(source):
            job_id = job["job_id"]
            if job_id in known or job_id in run_seen:
                continue
            run_seen.add(job_id)
            unseen.append(job)
            if len(unseen) >= limit:
                break
        if len(unseen) >= limit:
            break

    timestamp = now_iso()
    for job in unseen:
        known[job["job_id"]] = {
            "job_id": job["job_id"],
            "title": job["title"],
            "company": job["company"],
            "link": job["link"],
            "first_seen_at": timestamp,
            "last_checked_at": timestamp,
            "content_hash": job["content_hash"],
            "status": "active",
            "analysis_status": "pending",
        }
    write_json(history_path, history)
    write_json(run_dir / "jobs.json", unseen)
    return unseen


TECH_TERMS = (
    "python", "java", "javascript", "typescript", "go", "rust", "c++", "spring",
    "django", "flask", "react", "vue", "mysql", "postgresql", "redis", "kafka",
    "docker", "kubernetes", "linux", "git", "sql", "机器学习", "深度学习", "大模型",
)


def rule_score(job: dict[str, Any], resume_text: str) -> int:
    haystack = " ".join(str(job.get(key, "")) for key in ("title", "skills", "jd")).lower()
    resume = resume_text.lower()
    overlap = sum(1 for term in TECH_TERMS if term in haystack and term in resume)
    score = overlap * 10
    if job.get("jd"):
        score += 5
    if str(job.get("invalid", "")).strip() in {"是", "true", "1"}:
        score -= 100
    return score


def prepare_agent_request(run_dir: Path, schema_path: Path) -> dict[str, Any]:
    jobs = read_json(run_dir / "jobs.json", []) or []
    resume_text = (run_dir / "resume.txt").read_text(encoding="utf-8")
    ranked = sorted(jobs, key=lambda job: rule_score(job, resume_text), reverse=True)[:ANALYSIS_LIMIT]
    request = {
        "task": "分析简历与岗位，输出可核验的证据账本、推荐等级和投递材料",
        "constraints": {
            "language": "zh-CN",
            "no_fabrication": True,
            "evidence_statuses": sorted(EVIDENCE_STATUSES),
            "grades": ["A", "B", "C", "D"],
            "max_jobs": ANALYSIS_LIMIT,
        },
        "output_schema": str(schema_path.resolve()),
        "output_file": str((run_dir / "analysis.json").resolve()),
        "resume_text": resume_text,
        "jobs": ranked,
    }
    write_json(run_dir / "agent_request.json", request)
    return request


def validate_analysis(run_dir: Path, history_path: Path | None = None) -> dict[str, Any]:
    analysis = read_json(run_dir / "analysis.json")
    if not isinstance(analysis, dict) or not isinstance(analysis.get("profile"), dict) or not isinstance(analysis.get("jobs"), list):
        raise ValueError("analysis.json 必须包含 jobs 数组")
    if len(analysis["jobs"]) > ANALYSIS_LIMIT:
        raise ValueError(f"分析岗位不能超过 {ANALYSIS_LIMIT} 个")
    source_ids = {job["job_id"] for job in read_json(run_dir / "jobs.json", [])}
    seen: set[str] = set()
    for index, job in enumerate(analysis["jobs"], 1):
        job_id = str(job.get("job_id", ""))
        if job_id not in source_ids:
            raise ValueError(f"第 {index} 项引用了未知岗位：{job_id}")
        if job_id in seen:
            raise ValueError(f"岗位重复分析：{job_id}")
        seen.add(job_id)
        if job.get("grade") not in GRADES:
            raise ValueError(f"岗位 {job_id} 的 grade 无效")
        if not isinstance(job.get("score"), int) or not 0 <= job["score"] <= 100:
            raise ValueError(f"岗位 {job_id} 的 score 必须是 0 到 100 的整数")
        for field in ("summary", "greeting"):
            if not str(job.get(field, "")).strip():
                raise ValueError(f"岗位 {job_id} 缺少 {field}")
        for field in ("risks", "resume_suggestions"):
            if not isinstance(job.get(field), list):
                raise ValueError(f"岗位 {job_id} 的 {field} 必须是数组")
        evidence = job.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            raise ValueError(f"岗位 {job_id} 缺少证据账本")
        for item in evidence:
            if item.get("status") not in EVIDENCE_STATUSES:
                raise ValueError(f"岗位 {job_id} 存在无效证据状态")
            if not str(item.get("requirement", "")).strip():
                raise ValueError(f"岗位 {job_id} 存在空要求")
            resume_evidence = item.get("resume_evidence")
            if not isinstance(resume_evidence, list):
                raise ValueError(f"岗位 {job_id} 的 resume_evidence 必须是数组")
            if item.get("status") == "matched" and not any(str(x).strip() for x in resume_evidence):
                raise ValueError(f"岗位 {job_id} 的 matched 结论缺少简历证据")
    if history_path is not None:
        history = read_json(history_path, {"version": 1, "jobs": {}}) or {"version": 1, "jobs": {}}
        saved = history.setdefault("jobs", {})
        timestamp = now_iso()
        for job in analysis["jobs"]:
            if job["job_id"] in saved:
                saved[job["job_id"]]["analysis_status"] = "analyzed"
                saved[job["job_id"]]["recommendation_grade"] = job["grade"]
                saved[job["job_id"]]["analyzed_at"] = timestamp
        write_json(history_path, history)
    return analysis


def ranked_results(analysis: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted(
        analysis["jobs"],
        key=lambda item: (GRADE_ORDER[item["grade"]], -int(item.get("score", 0))),
    )


def should_notify(results: list[dict[str, Any]]) -> bool:
    return any(item["grade"] == "A" for item in results) or sum(
        item["grade"] == "B" for item in results
    ) >= 3


def _job_card(item: dict[str, Any], source: dict[str, Any]) -> str:
    status_labels = {"matched": "已匹配", "insufficient": "证据不足", "gap": "真实缺口"}
    evidence = "".join(
        f"<li><strong>{html.escape(str(e.get('requirement', '')))}</strong> — "
        f"{status_labels.get(e.get('status'), e.get('status', ''))}：{html.escape(str(e.get('reason', '')))}</li>"
        for e in item.get("evidence", [])
    )
    risks = "".join(f"<li>{html.escape(str(x))}</li>" for x in item.get("risks", []))
    suggestions = "".join(f"<li>{html.escape(str(x))}</li>" for x in item.get("resume_suggestions", []))
    link = html.escape(str(source.get("link", "")), quote=True)
    return f"""
    <article class="job grade-{item['grade'].lower()}">
      <div class="job-head"><span class="grade">{item['grade']}</span>
      <h2>{html.escape(source.get('title', ''))} · {html.escape(source.get('company', ''))}</h2></div>
      <p class="meta">{html.escape(source.get('city', ''))} · {html.escape(source.get('salary', ''))}</p>
      <p>{html.escape(str(item.get('summary', '')))}</p>
      <h3>证据账本</h3><ul>{evidence}</ul>
      <h3>风险与缺口</h3><ul>{risks or '<li>无</li>'}</ul>
      <h3>简历修改建议</h3><ul>{suggestions or '<li>无需修改</li>'}</ul>
      <p class="greeting"><strong>招呼语：</strong>{html.escape(str(item.get('greeting', '')))}</p>
      <a href="{link}">查看原岗位</a>
    </article>"""


def render_report(run_dir: Path) -> Path:
    analysis = validate_analysis(run_dir)
    sources = {job["job_id"]: job for job in read_json(run_dir / "jobs.json", [])}
    results = ranked_results(analysis)
    cards = "\n".join(_job_card(item, sources[item["job_id"]]) for item in results)
    counts = {grade: sum(item["grade"] == grade for item in results) for grade in "ABCD"}
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>job-lens 岗位报告</title><style>
:root{{--ink:#18211d;--paper:#f5f1e8;--green:#174f3c;--line:#c9c1b2;--gold:#d9a441}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:16px/1.65 system-ui,sans-serif}}
main{{max-width:980px;margin:auto;padding:48px 24px}}header{{border-bottom:2px solid var(--ink);padding-bottom:24px}}
h1{{font:700 clamp(36px,7vw,76px)/.95 Georgia,serif;margin:0 0 18px}}.stats{{display:flex;gap:12px;flex-wrap:wrap}}
.stats span{{border:1px solid var(--line);padding:7px 12px}}.job{{background:#fff;border:1px solid var(--line);padding:24px;margin:24px 0}}
.job-head{{display:flex;gap:16px;align-items:center}}.job h2{{margin:0}}.grade{{display:grid;place-items:center;background:var(--green);color:#fff;width:46px;height:46px;font:bold 24px Georgia}}
.grade-a{{border-left:8px solid var(--gold)}}.grade-b{{border-left:8px solid var(--green)}}.meta{{color:#5a625e}}a{{color:var(--green)}}
</style></head><body><main><header><h1>JOB<br>LENS</h1><p>岗位证据匹配报告 · {html.escape(now_iso())}</p>
<div class="stats"><span>分析 {len(results)}</span>{''.join(f'<span>{g} 级 {counts[g]}</span>' for g in 'ABCD')}</div></header>
{cards or '<p>本次没有可展示的岗位。</p>'}</main></body></html>"""
    output = run_dir / "report.html"
    output.write_text(document, encoding="utf-8")
    return output


def digest_html(run_dir: Path) -> tuple[str, str, bool]:
    analysis = validate_analysis(run_dir)
    sources = {job["job_id"]: job for job in read_json(run_dir / "jobs.json", [])}
    results = ranked_results(analysis)
    top = results[:PUSH_LIMIT]
    items = ""
    for item in top:
        source = sources[item["job_id"]]
        proof = next((e for e in item.get("evidence", []) if e.get("status") == "matched"), None)
        proof_text = proof.get("reason", "") if proof else "暂无直接匹配证据"
        risk_text = "；".join(str(x) for x in item.get("risks", [])[:2]) or "无明显风险"
        items += (
            f"<li><strong>{item['grade']} · {html.escape(source['title'])}</strong>"
            f" — {html.escape(source['company'])}<br>{html.escape(str(item.get('summary', '')))}"
            f"<br><em>证据：</em>{html.escape(str(proof_text))}"
            f"<br><em>风险：</em>{html.escape(risk_text)}</li>"
        )
    important = should_notify(results)
    if important:
        subject = f"job-lens：{len(results)} 个岗位分析完成，重点推荐 {len(top)} 个"
        body = f"<h1>job-lens 岗位摘要</h1><p>本次详细展示前 {len(top)} 个岗位。</p><ol>{items}</ol>"
    else:
        counts = Counter(item["grade"] for item in results)
        subject = "job-lens：本轮暂无合适岗位"
        body = (
            "<h1>job-lens 检查完成</h1>"
            f"<p>本轮采集并分析 {len(results)} 个新岗位，暂无达到推荐条件的岗位。</p>"
            f"<p>A/B/C/D：{counts['A']}/{counts['B']}/{counts['C']}/{counts['D']}。下轮将继续采集。</p>"
        )
    return subject, body, important


def load_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def mail_settings(env_file: Path | None = None) -> dict[str, str]:
    values = load_env_file(env_file) if env_file else {}
    keys = (
        "JOB_LENS_SMTP_HOST", "JOB_LENS_SMTP_PORT", "JOB_LENS_SMTP_USER",
        "JOB_LENS_SMTP_PASSWORD", "JOB_LENS_SMTP_USE_TLS", "JOB_LENS_EMAIL_FROM",
        "JOB_LENS_EMAIL_TO",
    )
    return {key: os.environ.get(key, values.get(key, "")) for key in keys}


def send_email(run_dir: Path, settings: dict[str, str], force: bool = False) -> bool:
    subject, body, important = digest_html(run_dir)
    required = ("JOB_LENS_SMTP_HOST", "JOB_LENS_SMTP_USER", "JOB_LENS_SMTP_PASSWORD", "JOB_LENS_EMAIL_TO")
    missing = [key for key in required if not settings.get(key)]
    if missing:
        raise ValueError("邮件配置缺失：" + ", ".join(missing))
    report = render_report(run_dir)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.get("JOB_LENS_EMAIL_FROM") or settings["JOB_LENS_SMTP_USER"]
    message["To"] = settings["JOB_LENS_EMAIL_TO"]
    message.set_content("请使用支持 HTML 的邮件客户端查看岗位摘要。")
    message.add_alternative(body, subtype="html")
    message.add_attachment(report.read_bytes(), maintype="text", subtype="html", filename="job-lens-report.html")

    host = settings["JOB_LENS_SMTP_HOST"]
    port = int(settings.get("JOB_LENS_SMTP_PORT") or 465)
    use_tls = settings.get("JOB_LENS_SMTP_USE_TLS", "true").lower() not in {"0", "false", "no"}
    if port == 465:
        client: smtplib.SMTP = smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30)
    else:
        client = smtplib.SMTP(host, port, timeout=30)
        if use_tls:
            client.starttls(context=ssl.create_default_context())
    with client:
        client.login(settings["JOB_LENS_SMTP_USER"], settings["JOB_LENS_SMTP_PASSWORD"])
        client.send_message(message)
    retry = run_dir / "notification_retry.json"
    if retry.exists():
        retry.unlink()
    return True


def send_system_notification(title: str, message: str) -> bool:
    """使用操作系统自带通知能力；不可用时静默降级为 Agent/邮件通知。"""
    try:
        if sys.platform == "darwin":
            esc = lambda value: value.replace("\\", "\\\\").replace('"', '\\"')
            command = ["osascript", "-e", f'display notification "{esc(message)}" with title "{esc(title)}"']
        elif sys.platform.startswith("linux"):
            command = ["notify-send", title, message]
        elif sys.platform == "win32":
            safe_title = title.replace("'", "''")
            safe_message = message.replace("'", "''")
            command = [
                "powershell", "-NoProfile", "-Command",
                f"Add-Type -AssemblyName PresentationFramework;[System.Windows.MessageBox]::Show('{safe_message}','{safe_title}')",
            ]
        else:
            return False
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        return True
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def record_notification_failure(run_dir: Path, error: Exception) -> None:
    write_json(
        run_dir / "notification_retry.json",
        {"channel": "email", "status": "pending", "error": str(error), "updated_at": now_iso()},
    )
