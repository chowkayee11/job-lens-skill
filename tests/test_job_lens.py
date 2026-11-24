import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from job_lens.core import (  # noqa: E402
    ANALYSIS_LIMIT,
    CRAWL_LIMIT,
    PUSH_LIMIT,
    digest_html,
    ingest_unseen,
    prepare_agent_request,
    render_report,
    send_email,
    validate_analysis,
)


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_jobs(count: int) -> list[dict]:
    return [
        {
            "link": f"https://www.zhipin.com/job_detail/job-{index}.html?from=search",
            "职位": f"Python 后端 {index}",
            "公司": f"公司 {index}",
            "城市": "武汉",
            "薪资": "15-20K",
            "技能标签": "Python Redis",
            "岗位要求和职责": "使用 Python、Redis 开发后端服务",
        }
        for index in range(count)
    ]


def analysis_for(jobs: list[dict]) -> dict:
    return {
        "profile": {"skills": ["Python", "Redis"]},
        "jobs": [
            {
                "job_id": job["job_id"],
                "grade": "A" if index == 0 else "B",
                "score": 90 - index,
                "summary": "技术栈与项目经历匹配",
                "evidence": [{
                    "requirement": "熟悉 Python",
                    "status": "matched",
                    "resume_evidence": ["使用 Python 开发服务"],
                    "reason": "简历存在直接项目证据",
                }],
                "risks": [],
                "resume_suggestions": ["突出 Python 项目"],
                "greeting": "您好，我有相关项目经验。",
            }
            for index, job in enumerate(jobs)
        ],
    }


class JobLensTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_ingest_only_unseen_and_limit_50(self):
        source = self.root / "jobs.json"
        dump(source, make_jobs(60))
        history = self.root / "history.json"
        first = self.root / "run-1"
        second = self.root / "run-2"
        first.mkdir()
        second.mkdir()

        jobs_1 = ingest_unseen(first, history, [source])
        jobs_2 = ingest_unseen(second, history, [source])

        self.assertEqual(len(jobs_1), CRAWL_LIMIT)
        self.assertEqual(len(jobs_2), 10)
        self.assertFalse({job["job_id"] for job in jobs_1} & {job["job_id"] for job in jobs_2})
        self.assertEqual(len(json.loads(history.read_text(encoding="utf-8"))["jobs"]), 60)

    def test_prepare_caps_analysis_at_30(self):
        run = self.root / "run"
        run.mkdir()
        (run / "resume.txt").write_text("使用 Python 和 Redis 开发服务", encoding="utf-8")
        source = self.root / "jobs.json"
        dump(source, make_jobs(50))
        jobs = ingest_unseen(run, self.root / "history.json", [source])

        request = prepare_agent_request(run, ROOT / "schemas" / "analysis.schema.json")

        self.assertEqual(len(jobs), 50)
        self.assertEqual(len(request["jobs"]), ANALYSIS_LIMIT)
        self.assertTrue(request["constraints"]["no_fabrication"])

    def test_validate_report_and_digest_only_detail_top_10(self):
        run = self.root / "run"
        run.mkdir()
        jobs = []
        for row in make_jobs(15):
            row["job_id"] = row["link"].split("/")[-1].split(".")[0]
            row.update({"title": row["职位"], "company": row["公司"], "city": "武汉", "salary": "15-20K"})
            jobs.append(row)
        dump(run / "jobs.json", jobs)
        dump(run / "analysis.json", analysis_for(jobs))

        self.assertEqual(len(validate_analysis(run)["jobs"]), 15)
        report = render_report(run)
        subject, body, important = digest_html(run)

        self.assertTrue(report.exists())
        self.assertIn("JOB", report.read_text(encoding="utf-8"))
        self.assertTrue(important)
        self.assertTrue(subject)
        self.assertEqual(body.count("<li><strong>"), PUSH_LIMIT)

    def test_validation_rejects_fabricated_job_id(self):
        run = self.root / "run"
        run.mkdir()
        jobs = make_jobs(1)
        jobs[0]["job_id"] = "real"
        dump(run / "jobs.json", jobs)
        value = analysis_for(jobs)
        value["jobs"][0]["job_id"] = "invented"
        dump(run / "analysis.json", value)

        with self.assertRaisesRegex(ValueError, "未知岗位"):
            validate_analysis(run)

    def test_matched_result_requires_resume_evidence(self):
        run = self.root / "run"
        run.mkdir()
        jobs = make_jobs(1)
        jobs[0]["job_id"] = "real"
        dump(run / "jobs.json", jobs)
        value = analysis_for(jobs)
        value["jobs"][0]["evidence"][0]["resume_evidence"] = []
        dump(run / "analysis.json", value)

        with self.assertRaisesRegex(ValueError, "缺少简历证据"):
            validate_analysis(run)

    def test_email_uses_smtp_without_network(self):
        run = self.root / "run"
        run.mkdir()
        jobs = make_jobs(1)
        jobs[0].update({"job_id": "real", "title": jobs[0]["职位"], "company": jobs[0]["公司"], "city": "武汉", "salary": "15-20K"})
        dump(run / "jobs.json", jobs)
        dump(run / "analysis.json", analysis_for(jobs))
        settings = {
            "JOB_LENS_SMTP_HOST": "smtp.example.com",
            "JOB_LENS_SMTP_PORT": "465",
            "JOB_LENS_SMTP_USER": "sender@example.com",
            "JOB_LENS_SMTP_PASSWORD": "secret",
            "JOB_LENS_SMTP_USE_TLS": "true",
            "JOB_LENS_EMAIL_FROM": "sender@example.com",
            "JOB_LENS_EMAIL_TO": "reader@example.com",
        }

        with patch("job_lens.core.smtplib.SMTP_SSL") as smtp:
            client = smtp.return_value
            client.__enter__.return_value = client
            self.assertTrue(send_email(run, settings))
            client.login.assert_called_once_with("sender@example.com", "secret")
            client.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
