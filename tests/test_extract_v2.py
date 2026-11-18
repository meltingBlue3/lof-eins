"""
Tests for phase C: v2 extraction (schema check, evidence check, cached runs, rebuild)
and the assertion-level gold grader. No network: the model is a fake.

阶段 C 测试：抽取的格式校验、原文引用校验、缓存与重建，以及声明级金标核对。
"""

import json
import os
import sys
import unittest
from datetime import date
from types import SimpleNamespace

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.evaluation.assertions import Calendar, grade_gold  # noqa: E402
from src.pipeline import db, extract  # noqa: E402


def assertion(**kw):
    a = {"fund_code": "160723", "share_codes": ["*"], "channel": "all", "businesses": ["purchase", "fixed_invest"],
         "status": "closed", "amount": None, "currency": "CNY", "valid_from": "2022-01-17", "valid_to": None,
         "layer": "baseline", "kind": "change", "prior_status": None,
         "evidence": "本基金自2022年1月17日起暂停申购"}
    a.update(kw)
    return a


TEXT = ("关于嘉实原油(QDII-LOF)暂停申购的公告\n本基金自2022年1月17日起暂停申\n购。根据相关公告，本基金自 2020 年 3 月 16 日起"
        "暂停申购及定期定额投资业务。单日单个基金账户累计申购金额不超过 1000 元（含）。交易代码 160723 005665")


class TestPromptAndInput(unittest.TestCase):
    def test_prompt_has_a_version(self):
        version, text = extract.load_prompt()
        self.assertTrue(version.startswith("extract-v2"))
        self.assertIn("report_assertions", text)
        self.assertNotIn("prompt_version", text)

    def test_render_input_lists_codes_and_tables(self):
        s = extract.render_input(["161815", "161831"], "2022-06-28", "标题", "正文\f第二页",
                                 [{"page": 1, "rows": [["基金代码", "161815"], ["", ""]]}])
        self.assertIn("要抽取的基金代码：161815、161831", s)
        self.assertIn("正文\n第二页", s)
        self.assertIn("基金代码 | 161815", s)


class TestSchemaErrors(unittest.TestCase):
    def test_valid_payload(self):
        self.assertEqual(extract.schema_errors({"relevant": True, "assertions": [assertion()]}), [])
        self.assertEqual(extract.schema_errors({"relevant": False, "assertions": []}), [])

    def test_problems_are_named(self):
        errs = extract.schema_errors({"relevant": True, "assertions": [
            assertion(channel="online"), assertion(layer="overlay"), assertion(valid_to="2022-02-01"),
            assertion(valid_from="2022/01/17"), {"fund_code": "1"}]})
        text = "\n".join(errs)
        self.assertIn("channel='online'", text)
        self.assertIn("overlay needs valid_to", text)
        self.assertIn("baseline must have valid_to=null", text)
        self.assertIn("valid_from='2022/01/17'", text)
        self.assertIn("missing", text)
        self.assertEqual(extract.schema_errors(None), ["output is not a JSON object"])


class TestEvidence(unittest.TestCase):
    def setUp(self):
        self.hay = extract.haystack_of(TEXT, [{"page": 1, "rows": [["限制申购金额", "500.00"]]}])

    def test_whitespace_width_and_ellipsis(self):
        self.assertTrue(extract.evidence_ok("本基金自2022年1月17日起暂停申购", self.hay))  # line break inside
        self.assertTrue(extract.evidence_ok("根据相关公告，本基金自2020年3月16日起暂停申购", self.hay))
        self.assertTrue(extract.evidence_ok("暂停申购的公告……不超过 1000 元（含）", self.hay))
        self.assertTrue(extract.evidence_ok("限制申购金额 | 500.00", self.hay))  # rendered table row
        self.assertFalse(extract.evidence_ok("本基金自2022年1月18日起暂停申购", self.hay))
        self.assertFalse(extract.evidence_ok("", self.hay))

    def test_relaxed_levels(self):
        raw = ("决定对处于交易日的下列2023年境外主要市场节假日暂停本基金的申购、赎回与定投等业务。\n日期 节假日\n"
               "1月 3日（日本银行假日）\n（）根据相关公告，本基金自 年 月 日起暂停本基金的申购及定期定额投资业务。\n2 2022 3 7\n"
               "单笔金额不超过 元\n1000\n（以下简称“本公司”）决定于2022年1月17日起暂停\n"
               "并自 年 月 日起恢复下列基金的申购20221125业务")
        hay, spaced = extract.normalize(raw), extract.normalize_spaced(raw)

        def level(q):
            return extract.evidence_level(q, hay, spaced)

        self.assertEqual(level("并自2022年11月25日起恢复下列基金的申购业务"), 2)  # digits glued into one run
        self.assertEqual(level("（以下简称本公司）决定于2022年1月17日起暂停"), 1)  # quote marks ignored
        self.assertEqual(level("下列2023年境外主要市场节假日暂停本基金的申购、赎回与定投等业务 1月 3日（日本银行假日）"), 2)
        self.assertEqual(level("根据相关公告，本基金自2022年3月7日起暂停本基金的申购及定期定额投资业务"), 2)
        self.assertEqual(level("根据相关公告，本基金自2022年3月8日起暂停本基金的申购及定期定额投资业务"), 0)
        self.assertEqual(level("单笔金额不超过1000元"), 2)  # displaced amount, whole run
        self.assertEqual(level("单笔金额不超过100元"), 0)   # 100 never stands in for 1000
        self.assertEqual(level("本基金自即日起恢复申购业务"), 0)
        self.assertEqual(extract.evidence_level("根据相关公告，本基金自2022年3月7日起暂停本基金的申购及定期定额投资业务", hay), 0)

    def test_stray_page_digits_tolerated_but_amounts_strict(self):
        hay = extract.normalize("决定自2024年6月5日起恢复申1购及定期定额投资业务，金额不超过1000元")
        self.assertTrue(extract.evidence_ok("决定自2024年6月5日起恢复申购及定期定额投资业务", hay))
        self.assertFalse(extract.evidence_ok("金额不超过100元", hay))


class TestCheck(unittest.TestCase):
    def ctx(self):
        return {"codes": ["160723"], "observed_on": date(2022, 1, 13), "haystack": extract.haystack_of(TEXT, [])}

    def kinds(self, a):
        return [k for k, _ in extract.check(a, self.ctx())[1]]

    def test_clean_assertion(self):
        ok, issues = extract.check(assertion(), self.ctx())
        self.assertEqual((ok, issues), (1, []))

    def test_dates_amounts_codes(self):
        self.assertIn("date_out_of_range", self.kinds(assertion(valid_from="2022-06-01")))
        self.assertNotIn("date_out_of_range", self.kinds(assertion(valid_from="2022-12-26", valid_to="2022-12-26",
                                                                    layer="overlay")))
        self.assertNotIn("date_out_of_range", self.kinds(assertion(kind="restatement", valid_from="2020-03-16")))
        self.assertIn("null_amount", self.kinds(assertion(status="limited")))
        self.assertIn("amount_range", self.kinds(assertion(status="limited", amount=0.5)))
        self.assertIn("unknown_share_code", self.kinds(assertion(share_codes=["160723", "999999"])))
        self.assertNotIn("unknown_share_code", self.kinds(assertion(share_codes=["160723", "005665"])))
        self.assertIn("unrequested_fund", self.kinds(assertion(fund_code="161129")))


class FakeResult(SimpleNamespace):
    pass


def make_db():
    conn = db.connect(":memory:")
    conn.execute("INSERT INTO announcements (fund_code, announce_date, title, rel_path, sha256, size_bytes, triage, triage_by) "
                 "VALUES ('160723', '2022-01-13', '暂停申购的公告', '160723/2022-01-13_暂停申购的公告.pdf', 'sha1', 1, 'relevant', 'rule:state')")
    conn.execute("INSERT INTO pdf_texts (sha256, extractor, text, tables, n_pages, is_empty) VALUES ('sha1', 'x', ?, '[]', 1, 0)",
                 (TEXT,))
    conn.commit()
    return conn


class TestRunAndRebuild(unittest.TestCase):
    def chat_returning(self, *payloads):
        calls = []

        def chat(messages, tools=None, tool_choice=None):
            calls.append(messages)
            p = payloads[min(len(calls), len(payloads)) - 1]
            if isinstance(p, Exception):
                raise p
            return FakeResult(tool_args=p, finish_reason="tool_calls", usage={"prompt_tokens": 10, "completion_tokens": 2})
        return chat, calls

    def test_reask_once_then_ok_and_cache(self):
        conn = make_db()
        good = {"relevant": True, "assertions": [assertion(), assertion(kind="restatement", valid_from="2020-03-16",
                                                                         evidence="本基金自 2020 年 3 月 16 日起暂停申购")]}
        chat, calls = self.chat_returning({"relevant": True, "assertions": [assertion(layer="overlay")]}, good)
        counts = extract.run(conn, chat, "m", log=lambda s: None)
        self.assertEqual(counts["ok"], 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("overlay needs valid_to", calls[1][-1]["content"])
        raw = json.loads(conn.execute("SELECT raw_response FROM extractions").fetchone()[0])
        self.assertEqual((raw["attempts"], raw["requested_codes"]), (2, ["160723"]))
        # cached: no new call
        extract.run(conn, chat, "m", log=lambda s: None)
        self.assertEqual(len(calls), 2)
        # a new folder holding the same file changes the requested codes -> extracted again
        conn.execute("INSERT INTO announcements (fund_code, announce_date, title, rel_path, sha256, size_bytes, triage) "
                     "VALUES ('501018', '2022-01-13', '暂停申购的公告', '501018/2022-01-13_x.pdf', 'sha1', 1, 'relevant')")
        extract.run(conn, chat, "m", log=lambda s: None)
        self.assertEqual(len(calls), 3)
        # a refreshed text cache changes the model input -> extracted again; unchanged -> cached
        raw = json.loads(conn.execute("SELECT raw_response FROM extractions").fetchone()[0])
        self.assertEqual(len(raw["input_sha"]), 16)
        conn.execute("UPDATE pdf_texts SET text = text || ' ' WHERE sha256 = 'sha1'")
        extract.run(conn, chat, "m", log=lambda s: None)
        extract.run(conn, chat, "m", log=lambda s: None)
        self.assertEqual(len(calls), 4)

        version, _ = extract.load_prompt()
        r1 = extract.rebuild(conn, version, "m")
        r2 = extract.rebuild(conn, version, "m")
        self.assertEqual(r1, r2)  # pure: rebuilding twice gives the same tables
        self.assertEqual((r1["assertions"], r1["evidence_ok"]), (2, 2))
        rows = conn.execute("SELECT kind, observed_on FROM state_assertions ORDER BY id").fetchall()
        self.assertEqual([tuple(r) for r in rows], [("change", "2022-01-13"), ("restatement", "2022-01-13")])

    def test_schema_error_and_api_error(self):
        conn = make_db()
        chat, calls = self.chat_returning({"relevant": "yes"})
        self.assertEqual(extract.run(conn, chat, "m", log=lambda s: None)["schema_error"], 1)
        self.assertEqual(len(calls), 2)
        version, _ = extract.load_prompt()
        self.assertEqual(extract.rebuild(conn, version, "m")["schema_error_docs"], 1)
        self.assertEqual(conn.execute("SELECT kind FROM anomalies").fetchone()[0], "schema_error")
        chat, _ = self.chat_returning(RuntimeError("down"))
        self.assertEqual(extract.run(conn, chat, "m", log=lambda s: None)["api_error"], 1)


class TestGradeGold(unittest.TestCase):
    def setUp(self):
        self.conn = make_db()
        version, _ = extract.load_prompt()
        self.version = version
        payload = {"requested_codes": ["160723"], "tool_args": {"relevant": True, "assertions": [
            assertion(valid_from="2022-01-17", valid_to="2022-01-17", layer="overlay", evidence="暂停申购"),
            assertion(status="limited", amount=1000, valid_from="2022-01-19", prior_status="closed",
                      evidence="不超过 1000 元（含）"),
            assertion(channel="direct", status="limited", amount=5, valid_from="2022-01-19", evidence="暂停申购"),
        ]}}
        self.conn.execute("INSERT INTO extractions (sha256, prompt_version, model, raw_response, status) "
                          "VALUES ('sha1', ?, 'm', ?, 'ok')", (version, json.dumps(payload, ensure_ascii=False)))
        extract.rebuild(self.conn, version, "m")

    def grade(self, rows):
        cols = ["fund_code", "layer", "status", "amount", "valid_from", "valid_to", "confidence", "source_pdf",
                "evidence", "note"]
        gold = pd.DataFrame([dict(zip(cols, r)) for r in rows])
        days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-12-01", "2022-03-01")]
        return [g["grade"] for g in grade_gold(self.conn, gold, self.version, "m", days)]

    def test_grades(self):
        src = "160723/2022-01-13_暂停申购的公告.pdf"
        rows = [
            ("160723", "overlay", "closed", "", "2022-01-17", "2022-01-17", "high", src, "", ""),       # full
            ("160723", "baseline", "limited", "1000", "2022-01-19", "2022-02-28", "high", src, "q", ""),  # full
            ("160723", "baseline", "limited", "1000", "2022-01-20", "2022-02-28", "high", src, "q", ""),  # state
            ("160723", "baseline", "closed", "", "2021-12-01", "2022-01-18", "high", src, "q", ""),     # prior
            ("160723", "baseline", "limited", "5", "2022-01-19", "2022-02-28", "high", src, "q", ""),   # direct only
            ("167506", "overlay", "closed", "", "2022-01-17", "2022-01-17", "medium", src, "", ""),     # cross-cited
        ]
        self.assertEqual(self.grade(rows), ["full", "full", "state", "prior", "missing", "skipped"])

    def test_contradictions(self):
        import tempfile
        from src.evaluation.assertions import contradictions
        from src.evaluation.gold import load_gold
        src = "160723/2022-01-13_暂停申购的公告.pdf"
        csv_text = ("fund_code,layer,status,amount,valid_from,valid_to,confidence,source_pdf,evidence,note\n"
                    f"160723,baseline,closed,,2021-12-01,2022-02-28,high,{src},q,\n")
        with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding="utf-8") as fh:
            fh.write(csv_text)
        try:
            gold = load_gold(fh.name)
        finally:
            os.remove(fh.name)
        days = [d.strftime("%Y-%m-%d") for d in pd.bdate_range("2021-12-01", "2022-03-01")]
        r = contradictions(self.conn, gold, days)
        # overlay closed on 01-17 agrees; the limited 1000 change on 01-19 contradicts the gold "closed";
        # the direct-channel assertion is off the target path and not checked
        self.assertEqual(r["counts"], {"checked": 2, "agree": 1, "disagree": 1, "unlabeled": 0})
        self.assertEqual(r["disagreements"][0]["assertion"]["amount"], 1000)

    def test_calendar_snaps_weekends(self):
        cal = Calendar(["2024-06-14", "2024-06-17"])
        self.assertEqual(cal.start("2024-06-15"), "2024-06-17")
        self.assertEqual(cal.end("2024-06-16"), "2024-06-14")
        # beyond the calendar: unknown, not the last known day
        self.assertEqual(cal.start("2025-01-16"), "2025-01-16")
        self.assertEqual(cal.end("2025-01-15"), "2025-01-15")


if __name__ == "__main__":
    unittest.main()
