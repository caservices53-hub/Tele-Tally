import json
import tempfile
import unittest
from pathlib import Path

from gpt_tally_v2.config import Settings
from gpt_tally_v2.db import Database
from gpt_tally_v2.job_engine import JobEngine
from gpt_tally_v2.learning import LearningEngine
from gpt_tally_v2.models import LedgerEntry, Voucher
from gpt_tally_v2.tally_gateway import TallyGateway, ImportResult


class FakeGateway:
    def __init__(self, company="Demo Co"):
        self.company = company
        self.calls=[]
        self.fail_ledger=""
    def current_company(self): return self.company
    def ping(self): return self.company
    def list_ledgers(self): return ["Cash","HDFC Bank","Rent","Sales","Purchase","ABC Customer","XYZ Supplier","Output CGST","Output SGST"]
    def list_stock_items(self): return []
    def day_book(self, a,b): return []
    def import_vouchers(self, vouchers):
        vouchers=list(vouchers); self.calls.append(vouchers)
        if self.fail_ledger and any(any(e.ledger==self.fail_ledger for e in v.entries) for v in vouchers):
            return ImportResult(created=0,errors=1,line_errors=["forced failure"])
        return ImportResult(created=len(vouchers),errors=0)


class CoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        db=Database(str(Path(self.tmp.name)/"db.sqlite3"))
        settings=Settings(db_path=str(Path(self.tmp.name)/"db.sqlite3"), tally_company="Demo Co", default_bank_ledger="HDFC Bank", auto_threshold=0.90)
        self.gw=FakeGateway()
        self.eng=JobEngine(settings=settings,db=db,gateway=self.gw)
        db.save_company_snapshot("Demo Co", self.gw.list_ledgers(), [])
    def tearDown(self): self.tmp.cleanup()

    def test_voucher_balance(self):
        v=Voucher("Payment","2026-09-01",[LedgerEntry("Rent",1000),LedgerEntry("HDFC Bank",-1000)])
        v.validate()
        self.assertIn("<VOUCHER",v.to_xml())
        with self.assertRaises(ValueError):
            Voucher("Payment","2026-09-01",[LedgerEntry("Rent",1000),LedgerEntry("HDFC Bank",-900)]).validate()

    def test_explicit_rows_become_ready(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"debit_ledger":"Rent","credit_ledger":"Cash"}],company="Demo Co")
        s=self.eng.summary(jid)
        self.assertEqual(s["counts"].get("ready"),1)

    def test_unknown_becomes_exception_then_teach(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"party":"Landlord"}],company="Demo Co")
        ex=self.eng.exceptions(jid)
        self.assertEqual(len(ex),1)
        row_id=ex[0]["row_id"]
        out=self.eng.teach_row(jid,row_id,[{"ledger":"Rent","amount":500},{"ledger":"HDFC Bank","amount":-500}],bank_ledger="HDFC Bank")
        self.assertEqual(out["rows_reclassified"],1)
        self.assertEqual(self.eng.summary(jid)["counts"].get("ready"),1)

    def test_verified_rule_scales_amount(self):
        self.eng.learning.teach("Demo Co","Landlord","Payment",[{"ledger":"Rent","amount":100},{"ledger":"HDFC Bank","amount":-100}],bank_ledger="HDFC Bank")
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":7250,"party":"Landlord"}],company="Demo Co")
        row=self.eng.db.rows(jid)[0]
        v=json.loads(row["voucher_json"])
        amts={x["ledger"]:x["amount"] for x in v["entries"]}
        self.assertEqual(amts["Rent"],7250)
        self.assertEqual(amts["HDFC Bank"],-7250)

    def test_approve_blocks_exceptions(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"party":"Unknown"}],company="Demo Co")
        with self.assertRaises(ValueError): self.eng.approve(jid)

    def test_company_guard(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"debit_ledger":"Rent","credit_ledger":"Cash"}],company="Demo Co")
        self.eng.approve(jid)
        self.gw.company="Wrong Co"
        with self.assertRaises(ValueError): self.eng.post(jid,"Wrong Co")

    def test_post_success(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"debit_ledger":"Rent","credit_ledger":"Cash"}],company="Demo Co")
        self.eng.approve(jid)
        s=self.eng.post(jid,"Demo Co")
        self.assertEqual(s["counts"].get("posted"),1)
        self.assertEqual(s["status"],"completed")

    def test_batch_failure_isolation(self):
        # all ledgers exist, but gateway rejects one ledger to test recursive batch isolation
        self.gw.fail_ledger="Purchase"
        rows=[
            {"date":"2026-09-01","voucher_type":"Journal","amount":100,"debit_ledger":"Rent","credit_ledger":"Cash"},
            {"date":"2026-09-01","voucher_type":"Journal","amount":200,"debit_ledger":"Purchase","credit_ledger":"Cash"},
            {"date":"2026-09-01","voucher_type":"Journal","amount":300,"debit_ledger":"Rent","credit_ledger":"Cash"},
        ]
        jid=self.eng.create_job_from_rows(rows,company="Demo Co")
        self.eng.approve(jid)
        s=self.eng.post(jid,"Demo Co")
        self.assertEqual(s["counts"].get("posted"),2)
        self.assertEqual(s["counts"].get("failed"),1)
        self.assertGreaterEqual(len(self.gw.calls),3)

    def test_history_learning(self):
        vouchers=[]
        for _ in range(3):
            vouchers.append({"voucher_type":"Payment","party":"Rent","amount":1000,"entries":[{"ledger":"Rent","amount":1000},{"ledger":"HDFC Bank","amount":-1000}]})
        info=self.eng.learning.observe_vouchers("Demo Co",vouchers)
        self.assertEqual(info["patterns_observed"],3)
        rule=self.eng.learning.resolve("Demo Co","Rent","Payment")
        self.assertIsNotNone(rule)
        self.assertGreaterEqual(rule["confidence"],0.90)

    def test_parse_tally_import_response(self):
        raw="<ENVELOPE><BODY><DATA><CREATED>2</CREATED><ERRORS>0</ERRORS></DATA></BODY></ENVELOPE>"
        r=TallyGateway.parse_import_result(raw)
        self.assertTrue(r.ok); self.assertEqual(r.created,2)

    def test_existing_tally_duplicate_is_skipped(self):
        def existing(a,b):
            return [{"date":"20260901","voucher_type":"Payment","reference":"PAY-1","party":"","amount":500}]
        self.gw.day_book=existing
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"debit_ledger":"Rent","credit_ledger":"Cash","reference":"PAY-1"}],company="Demo Co")
        self.eng.approve(jid)
        s=self.eng.post(jid,"Demo Co")
        self.assertEqual(s["counts"].get("duplicate"),1)
        self.assertEqual(len(self.gw.calls),0)

    def test_preview_contains_voucher(self):
        jid=self.eng.create_job_from_rows([{"date":"2026-09-01","voucher_type":"Payment","amount":500,"debit_ledger":"Rent","credit_ledger":"Cash"}],company="Demo Co")
        pv=self.eng.preview(jid)
        self.assertEqual(pv[0]["status"],"ready")
        self.assertEqual(pv[0]["voucher"]["voucher_type"],"Payment")


if __name__=="__main__": unittest.main()
