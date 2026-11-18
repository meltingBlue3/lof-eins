"""
Tests for the phase B pipeline: registry, triage, text cache and LLM client.

阶段 B 流水线测试：公告登记、分诊、正文缓存、LLM 客户端。不访问网络，也不依赖本地公告数据。
"""

import json
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

import httpx
import openai

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.pipeline import db, registry, texts, triage  # noqa: E402
from src.pipeline.llm import ChatLLM, LLMConfig, is_retryable, parse_json_lenient  # noqa: E402


class TempCorpus(unittest.TestCase):
    """A throwaway <root>/<fund>/<date>_<title>.pdf tree and an in-memory database."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.conn = db.connect(":memory:")

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.root, ignore_errors=True)

    def put(self, fund, name, data=b"%PDF-1.4 fake"):
        os.makedirs(os.path.join(self.root, fund), exist_ok=True)
        with open(os.path.join(self.root, fund, name), "wb") as fh:
            fh.write(data)


class TestRegistry(TempCorpus):
    def test_parse_name(self):
        self.assertEqual(registry.parse_name("2022-01-13_关于暂停申购的公告.pdf"), ("2022-01-13", "关于暂停申购的公告"))
        self.assertIsNone(registry.parse_name("notes.pdf"))

    def test_register_inserts_every_pdf_without_title_filter(self):
        self.put("160723", "2022-01-13_关于嘉实原油暂停赎回业务的公告.pdf")
        self.put("160723", "2022-02-01_关于参加费率优惠活动的公告.pdf", b"other")
        r = registry.register(self.conn, self.root)
        self.assertEqual(r["inserted"], 2)
        rows = self.conn.execute("SELECT fund_code, announce_date, title, sha256 FROM announcements ORDER BY id").fetchall()
        self.assertEqual(rows[0]["fund_code"], "160723")
        self.assertEqual(rows[0]["announce_date"], "2022-01-13")
        self.assertEqual(len(rows[0]["sha256"]), 64)

    def test_same_content_in_two_funds_shares_sha(self):
        self.put("161815", "2022-01-13_旗下部分基金暂停及恢复申购的公告.pdf", b"family")
        self.put("161130", "2022-01-13_旗下部分基金暂停及恢复申购的公告.pdf", b"family")
        registry.register(self.conn, self.root)
        n, n_sha = self.conn.execute("SELECT COUNT(*), COUNT(DISTINCT sha256) FROM announcements").fetchone()
        self.assertEqual((n, n_sha), (2, 1))

    def test_rerun_is_idempotent_and_changed_content_resets_triage(self):
        self.put("160723", "2022-01-13_暂停申购的公告.pdf", b"v1")
        registry.register(self.conn, self.root)
        self.conn.execute("UPDATE announcements SET triage = 'relevant', triage_by = 'rule:state'")
        r = registry.register(self.conn, self.root)
        self.assertEqual((r["inserted"], r["unchanged"]), (0, 1))
        self.put("160723", "2022-01-13_暂停申购的公告.pdf", b"v2")
        r = registry.register(self.conn, self.root)
        self.assertEqual(r["changed"], 1)
        self.assertIsNone(self.conn.execute("SELECT triage FROM announcements").fetchone()[0])

    def test_removed_files_are_deleted_and_bad_names_reported(self):
        self.put("160723", "2022-01-13_a.pdf")
        registry.register(self.conn, self.root)
        os.remove(os.path.join(self.root, "160723", "2022-01-13_a.pdf"))
        self.put("160723", "readme.pdf")
        r = registry.register(self.conn, self.root)
        self.assertEqual(r["removed"], 1)
        self.assertEqual(r["unparsed"], ["160723/readme.pdf"])


class TestTriageRules(unittest.TestCase):
    CASES = [
        # (title, expected label)
        ("关于嘉实原油(QDII-LOF)2023年5月8日暂停赎回业务的公告", "relevant"),
        ("易方达黄金主题证券投资基金(LOF)A类人民币份额恢复申购及定期定额投资业务并暂停大额申购业务的公告", "relevant"),
        ("关于汇添富黄金及贵金属证券投资基金(LOF)调整大额申购、定期定额投资业务限制金额的公告", "relevant"),
        ("关于南方原油证券投资基金2022年境外主要市场节假日申购赎回安排的公告", "relevant"),
        ("兴证全球基金管理有限公司关于旗下部分基金2023年非港股通交易日暂停申购、赎回等业务安排的提示性公告", "relevant"),
        ("南方金利定期开放债券型证券投资基金开放申购、赎回业务的公告", "relevant"),
        ("银华基金管理股份有限公司关于对旗下部分基金于2023年7月17日的申购、赎回、转换(如有)及定期定额投资业务申请作无效处理的公告", "relevant"),
        ("华夏基金管理有限公司关于调整华夏智胜先锋股票型证券投资基金(LOF)申购及定期定额申购业务的公告", "relevant"),
        ("关于调整南方道琼斯美国精选REIT指数证券投资基金(QDII-LOF)申购和定投业务金额限制的公告", "relevant"),
        ("财通科创主题灵活配置混合型证券投资基金(LOF)开放日常申购(含定期定额投资)、赎回及转换业务并开展费率优惠活动的公告", "relevant"),
        ("景顺长城基金管理有限公司关于暂停海银基金销售有限公司办理旗下基金相关销售业务的公告", "irrelevant"),
        ("广发基金管理有限公司关于旗下基金在部分销售机构暂停办理相关销售业务的公告", "irrelevant"),
        ("关于暂停平安新兴产业混合型证券投资基金(LOF)申购和定期定额申购费率优惠活动的公告", "irrelevant"),
        ("关于调整旗下部分基金参与中国工商银行股份有限公司申购、定期定额申购费率优惠活动时间的公告", "irrelevant"),
        ("金鹰基金管理有限公司关于旗下部分基金参与国信证券股份有限公司代销机构费率优惠活动的公告", "irrelevant"),
        ("华安标普全球石油指数证券投资基金(LOF)2023年第2季度报告", "irrelevant"),
        ("关于万家社会责任18个月定期开放混合型证券投资基金(LOF)延长开放期的公告", "relevant"),
        ("南方基金关于调整货币基金实时赎回业务的公告", "unsure"),
    ]

    def test_cases(self):
        for title, want in self.CASES:
            with self.subTest(title=title):
                self.assertEqual(triage.triage_title(title).label, want)

    def test_apply_rules_keeps_llm_decisions_for_unsure_titles(self):
        conn = db.connect(":memory:")
        conn.execute("INSERT INTO announcements (fund_code, announce_date, title, rel_path, sha256, size_bytes, triage, triage_by) "
                     "VALUES ('1', '2022-01-01', '南方基金关于调整货币基金实时赎回业务的公告', '1/a.pdf', 'x', 1, 'irrelevant', 'llm:m@triage-v1')")
        counts = triage.apply_rules(conn)
        self.assertEqual(counts["kept_llm"], 1)
        self.assertEqual(conn.execute("SELECT triage FROM announcements").fetchone()[0], "irrelevant")

    @unittest.skipUnless(os.path.exists(os.path.join(os.path.dirname(__file__), "..", "data", "gold", "timeline.csv")),
                         "gold file missing")
    def test_every_gold_title_is_relevant(self):
        """Recall acceptance on titles alone: each high/medium gold source must pass the rules."""
        import csv
        path = os.path.join(os.path.dirname(__file__), "..", "data", "gold", "timeline.csv")
        for row in csv.DictReader(open(path, encoding="utf-8")):
            if row["confidence"] == "low":
                continue
            title = registry.parse_name(row["source_pdf"].split("/", 1)[1])[1]
            with self.subTest(source=row["source_pdf"]):
                self.assertEqual(triage.triage_title(title).label, "relevant")


class TestTextCache(TempCorpus):
    def test_empty_detection(self):
        self.assertTrue(texts.is_empty_text(" \n\f "))
        self.assertFalse(texts.is_empty_text("本基金自2022年3月7日起暂停申购及定期定额投资业务，赎回业务照常办理。"))

    def test_build_cache_dedupes_by_sha_and_flags_scans(self):
        self.put("161815", "2022-01-13_暂停申购的公告.pdf", b"family")
        self.put("161130", "2022-01-13_暂停申购的公告.pdf", b"family")
        self.put("160723", "2022-02-01_暂停申购的公告.pdf", b"scan")
        self.put("160723", "2022-03-01_费率优惠的公告.pdf", b"fee")
        registry.register(self.conn, self.root)
        triage.apply_rules(self.conn)
        seen = []

        def fake_extract(path):
            seen.append(os.path.basename(os.path.dirname(path)))
            if "160723" in path:
                return {"text": "", "tables": [], "n_pages": 1, "is_empty": True, "error": None}
            return {"text": "暂停申购" * 10, "tables": [{"page": 1, "rows": [["a"]]}], "n_pages": 1,
                    "is_empty": False, "error": None}

        counts = texts.build_cache(self.conn, self.root, extract_fn=fake_extract)
        self.assertEqual(counts, {"done": 2, "empty": 1, "errors": 0})
        self.assertEqual(len(seen), 2)  # the family copy and the fee notice are not extracted
        self.assertEqual(texts.build_cache(self.conn, self.root, extract_fn=fake_extract)["done"], 0)
        row = self.conn.execute("SELECT tables, is_empty FROM pdf_texts WHERE text != ''").fetchone()
        self.assertEqual(json.loads(row["tables"])[0]["rows"], [["a"]])
        # refresh: only texts cached by another extractor version are redone
        self.conn.execute("UPDATE pdf_texts SET extractor = 'pdfplumber@old' WHERE text != ''")
        self.assertEqual(texts.build_cache(self.conn, self.root, extract_fn=fake_extract)["done"], 0)
        self.assertEqual(texts.build_cache(self.conn, self.root, extract_fn=fake_extract, refresh=True)["done"], 1)
        self.assertEqual(texts.build_cache(self.conn, self.root, extract_fn=fake_extract, refresh=True)["done"], 0)

    def test_page_tolerance_scales_with_small_fonts(self):
        page = lambda size: SimpleNamespace(chars=[{"size": size}] * 5)
        self.assertEqual(texts.page_tolerance(page(10.5)), 3.0)    # ordinary text: pdfplumber default
        self.assertAlmostEqual(texts.page_tolerance(page(2.25)), 0.9)  # whole notice on one A4 page
        self.assertEqual(texts.page_tolerance(page(0.5)), texts.MIN_TOL)
        self.assertEqual(texts.page_tolerance(SimpleNamespace(chars=[])), 3.0)

    def test_extract_reports_unreadable_file(self):
        self.put("160723", "2022-01-01_x.pdf", b"not a pdf")
        r = texts.extract(os.path.join(self.root, "160723", "2022-01-01_x.pdf"))
        self.assertTrue(r["is_empty"])
        self.assertIsNotNone(r["error"])


# ----------------------------------------------------------------------------- LLM client

def _response(content=None, tool=None, args=None, reasoning=None):
    calls = [SimpleNamespace(function=SimpleNamespace(name=tool, arguments=args))] if tool else None
    msg = SimpleNamespace(content=content, tool_calls=calls, reasoning_content=reasoning, model_extra={})
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="tool_calls" if tool else "stop")],
                           usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5), model="m",
                           model_dump=lambda: {"ok": True})


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outcomes.pop(0)
        if isinstance(out, Exception):
            raise out
        return out


def _status_error(cls, code, headers=None):
    req = httpx.Request("POST", "http://gw/v1/chat/completions")
    return cls("boom", response=httpx.Response(code, request=req, headers=headers or {}), body=None)


CFG = LLMConfig(base_url="http://gw/v1", api_key="k", model="m", max_retries=3)


class TestLLMClient(unittest.TestCase):
    def test_config_from_env_and_missing_keys(self):
        cfg = LLMConfig.from_env({"LOF_LLM_BASE_URL": "u", "LOF_LLM_API_KEY": "secret-123", "LOF_LLM_MODEL": "m",
                                  "LOF_LLM_REASONING": "low"})
        self.assertEqual((cfg.base_url, cfg.model, cfg.reasoning, cfg.max_retries), ("u", "m", "low", 4))
        self.assertNotIn("secret-123", repr(cfg))
        with self.assertRaises(ValueError) as ctx:
            LLMConfig.from_env({"LOF_LLM_BASE_URL": "u"})
        self.assertIn("LOF_LLM_API_KEY", str(ctx.exception))

    def test_parse_json_lenient(self):
        self.assertEqual(parse_json_lenient('{"a": 1}'), {"a": 1})
        self.assertEqual(parse_json_lenient('```json\n[1, 2]\n```'), [1, 2])
        self.assertEqual(parse_json_lenient('结果如下：{"relevant": true} 完毕'), {"relevant": True})
        self.assertIsNone(parse_json_lenient("没有 JSON"))
        self.assertIsNone(parse_json_lenient(None))

    def test_tool_call_arguments_are_parsed_and_params_sent(self):
        fake = FakeClient([_response(tool="report_triage", args='{"relevant": false, "reason": "x"}', reasoning="r")])
        llm = ChatLLM(LLMConfig(base_url="u", api_key="k", model="m", reasoning="low"), client=fake)
        res = llm.chat([{"role": "user", "content": "q"}], tools=[{}], tool_choice="required")
        self.assertEqual(res.tool_name, "report_triage")
        self.assertEqual(res.tool_args, {"relevant": False, "reason": "x"})
        self.assertEqual(res.reasoning, "r")
        sent = fake.calls[0]
        self.assertEqual((sent["model"], sent["reasoning_effort"], sent["tool_choice"]), ("m", "low", "required"))
        self.assertEqual(llm.usage["prompt_tokens"], 10)

    def test_falls_back_to_json_in_content_when_no_tool_call(self):
        fake = FakeClient([_response(content='好的。{"relevant": true, "reason": "y"}')])
        res = ChatLLM(CFG, client=fake).chat([], tools=[{}])
        self.assertEqual(res.tool_args, {"relevant": True, "reason": "y"})

    def test_retries_transient_errors_with_backoff(self):
        req = httpx.Request("POST", "http://gw")
        fake = FakeClient([openai.APIConnectionError(request=req), _status_error(openai.InternalServerError, 502),
                           _response(content="ok")])
        waits = []
        llm = ChatLLM(CFG, client=fake, sleep=waits.append)
        self.assertEqual(llm.chat([]).content, "ok")
        self.assertEqual(len(waits), 2)
        self.assertEqual(llm.usage["retries"], 2)

    def test_honours_retry_after_on_rate_limit(self):
        fake = FakeClient([_status_error(openai.RateLimitError, 429, {"retry-after": "7"}), _response(content="ok")])
        waits = []
        ChatLLM(CFG, client=fake, sleep=waits.append).chat([])
        self.assertEqual(waits, [7.0])

    def test_does_not_retry_client_errors_and_gives_up_after_max(self):
        fake = FakeClient([_status_error(openai.BadRequestError, 400)])
        with self.assertRaises(openai.BadRequestError):
            ChatLLM(CFG, client=fake, sleep=lambda s: None).chat([])
        req = httpx.Request("POST", "http://gw")
        fake = FakeClient([openai.APITimeoutError(request=req)] * 4)
        with self.assertRaises(openai.APITimeoutError):
            ChatLLM(CFG, client=fake, sleep=lambda s: None).chat([])
        self.assertEqual(len(fake.calls), 4)  # 1 try + 3 retries
        self.assertFalse(is_retryable(ValueError("x")))


class TestLLMTriage(TempCorpus):
    def _setup(self):
        self.put("1", "2022-01-01_南方基金关于调整货币基金实时赎回业务的公告.pdf", b"a")
        self.put("2", "2022-01-01_南方基金关于调整货币基金实时赎回业务的公告.pdf", b"a")
        registry.register(self.conn, self.root)
        triage.apply_rules(self.conn)
        texts.build_cache(self.conn, self.root, extract_fn=lambda p: {
            "text": "正文" * 20, "tables": [], "n_pages": 1, "is_empty": False, "error": None})

    def test_decision_applies_to_every_copy_and_is_cached(self):
        self._setup()
        calls = []

        def chat(messages, tools, tool_choice):
            calls.append(messages)
            return SimpleNamespace(tool_args={"relevant": False, "reason": "货币基金"}, raw={})

        counts = triage.llm_triage(self.conn, chat, "m", log=lambda s: None)
        self.assertEqual((counts["irrelevant"], len(calls)), (1, 1))
        labels = {r[0] for r in self.conn.execute("SELECT triage FROM announcements")}
        self.assertEqual(labels, {"irrelevant"})
        self.assertEqual(self.conn.execute("SELECT status FROM extractions").fetchone()[0], "ok")
        self.assertIn("标题：", calls[0][1]["content"])

    def test_api_errors_are_recorded_and_rows_stay_unsure(self):
        self._setup()

        def chat(messages, tools, tool_choice):
            raise RuntimeError("gateway down")

        counts = triage.llm_triage(self.conn, chat, "m", log=lambda s: None)
        self.assertEqual(counts["api_error"], 1)
        self.assertEqual({r[0] for r in self.conn.execute("SELECT triage FROM announcements")}, {"unsure"})
        self.assertEqual(self.conn.execute("SELECT status FROM extractions").fetchone()[0], "api_error")


if __name__ == "__main__":
    unittest.main()
