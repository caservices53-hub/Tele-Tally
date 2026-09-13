from __future__ import annotations

import json
from pathlib import Path

from .classifier import OptionalAIClassifier
from .config import Settings
from .db import Database
from .importers import load_file
from .learning import LearningEngine
from .models import LedgerEntry, Voucher, entries_from_json, items_from_json, norm_text, fmt_date
from .tally_gateway import TallyGateway, TallyError


class JobEngine:
    def __init__(self, settings: Settings | None = None, db: Database | None = None, gateway: TallyGateway | None = None):
        self.settings = settings or Settings()
        self.settings.ensure_dirs()
        self.db = db or Database(self.settings.db_path)
        self.gateway = gateway or TallyGateway(self.settings.tally_url, self.settings.tally_company)
        self.learning = LearningEngine(self.db)
        self.ai = OptionalAIClassifier(self.settings.openai_model)

    # ---------- company study ----------
    def study_company(self, from_date: str, to_date: str, company: str = "") -> dict:
        actual = company.strip() or self.gateway.current_company()
        if self.gateway.company and actual != self.gateway.company:
            raise ValueError(f"Configured TALLY_COMPANY is {self.gateway.company!r}, not {actual!r}.")
        ledgers = self.gateway.list_ledgers()
        stocks = self.gateway.list_stock_items()
        vouchers = self.gateway.day_book(from_date, to_date)
        learned = self.learning.observe_vouchers(actual, vouchers)
        self.db.save_company_snapshot(actual, ledgers, stocks, from_date, to_date)
        return {
            "company": actual, "from": from_date, "to": to_date,
            "ledgers": len(ledgers), "stock_items": len(stocks), **learned,
            "rules": len(self.learning.list_rules(actual, 100000)),
        }

    # ---------- row classification ----------
    @staticmethod
    def _scaled_entries(template: dict, amount: float, override_party: str = "", override_bank: str = "") -> list[dict]:
        legs = template.get("entries") or []
        out=[]
        for leg in legs:
            ledger=leg.get("ledger", "")
            if leg.get("role") == "party" and override_party:
                ledger=override_party
            elif leg.get("role") == "bank" and override_bank:
                ledger=override_bank
            val=round(float(amount)*float(leg.get("ratio",0)),2)
            val = val if int(leg.get("sign",1)) > 0 else -val
            out.append({"ledger":ledger,"amount":val})
        if out:
            diff=round(sum(float(x["amount"]) for x in out),2)
            if abs(diff)>0:
                # adjust the largest non-party leg to remove rounding drift only;
                # reject material imbalance later in Voucher.validate().
                idx=max(range(len(out)), key=lambda i: abs(float(out[i]["amount"])))
                if abs(diff)<=0.05:
                    out[idx]["amount"]=round(float(out[idx]["amount"])-diff,2)
        return out

    def _voucher_from_row(self, company: str, row: dict) -> tuple[dict | None, float, str]:
        vt=(row.get("voucher_type") or "").strip()
        date=(row.get("date") or "").strip()
        party=(row.get("party") or "").strip()
        party_ledger=(row.get("party_ledger") or "").strip()
        narration=(row.get("narration") or "").strip()
        reference=(row.get("reference") or "").strip()
        items_raw=row.get("items_json") or ""

        if not vt: return None,0,"voucher_type is missing"
        if not date: return None,0,"date is missing"

        # Most reliable path: explicit accounting entries.
        if row.get("entries_json"):
            try:
                entries=[e.__dict__ for e in entries_from_json(row["entries_json"])]
                items=[i.__dict__ for i in items_from_json(items_raw)] if items_raw else []
                v=Voucher(vt,date,[LedgerEntry(**{k:v for k,v in e.items() if k in {"ledger","amount","bill_name","bill_type"}}) for e in entries],
                          narration=narration,reference=reference,party_ledger=party_ledger or party,
                          items=items_from_json(items) if items else [])
                v.validate()
                return self._voucher_dict(v),1.0,"explicit entries supplied"
            except Exception as e:
                return None,0,f"invalid entries_json/items_json: {e}"

        amount=row.get("amount")
        try: amount=float(amount)
        except (TypeError,ValueError): return None,0,"amount is missing or invalid"
        if amount<=0: return None,0,"amount must be positive"

        debit=(row.get("debit_ledger") or "").strip()
        credit=(row.get("credit_ledger") or "").strip()
        if debit and credit:
            invoice_like=any(x in vt.lower() for x in ("sales","purchase","invoice","credit note","debit note"))
            v=Voucher(vt,date,[LedgerEntry(debit,amount),LedgerEntry(credit,-amount)],narration=narration,reference=reference,party_ledger=party_ledger or (party if invoice_like else ""))
            try: v.validate()
            except Exception as e: return None,0,str(e)
            return self._voucher_dict(v),1.0,"explicit debit and credit ledgers supplied"

        if not party:
            return None,0,"party/counterparty is required when ledger entries are not supplied"

        rule=self.learning.resolve(company,party,vt)
        if rule:
            tpl=rule["template"]
            learned_party=(tpl.get("party_ledger") or rule.get("party_ledger") or "").strip()
            learned_bank=(tpl.get("bank_ledger") or rule.get("bank_ledger") or "").strip()
            bank=(row.get("bank_ledger") or learned_bank or self.settings.default_bank_ledger).strip()
            # For invoice types, the source party text often is the actual Tally ledger.
            override_party=party_ledger or learned_party or party
            entries=self._scaled_entries(tpl,amount,override_party,bank)
            try:
                v=Voucher(vt,date,[LedgerEntry(x["ledger"],x["amount"]) for x in entries],narration=narration,reference=reference,
                          party_ledger=override_party if any(w in vt.lower() for w in ("sales","purchase","invoice","credit note","debit note")) else "")
                v.validate()
            except Exception as e:
                return None,rule["confidence"],f"learned pattern produced invalid voucher: {e}"
            reason=f"{rule['source']} {rule['match']} pattern; occurrences={rule['occurrences']}"
            return self._voucher_dict(v),float(rule["confidence"]),reason

        # Optional GPT fallback. It may only choose an existing ledger and remains review-only by default.
        snapshot=self.db.company_snapshot(company)
        ai=self.ai.classify(row,snapshot.get("ledgers",[]),self.learning.list_rules(company,20))
        if ai:
            bank=(row.get("bank_ledger") or self.settings.default_bank_ledger).strip()
            target=ai["target_ledger"]
            low=vt.lower()
            if "payment" in low:
                if not bank: return None,ai["confidence"],"AI suggested a ledger, but no bank ledger is configured"
                entries=[{"ledger":target,"amount":amount},{"ledger":bank,"amount":-amount}]
            elif "receipt" in low:
                if not bank: return None,ai["confidence"],"AI suggested a ledger, but no bank ledger is configured"
                entries=[{"ledger":bank,"amount":amount},{"ledger":target,"amount":-amount}]
            elif "purchase" in low:
                entries=[{"ledger":target,"amount":amount},{"ledger":party_ledger or party,"amount":-amount}]
            elif "sales" in low or "invoice" in low:
                entries=[{"ledger":party_ledger or party,"amount":amount},{"ledger":target,"amount":-amount}]
            else:
                return None,ai["confidence"],f"AI suggestion needs teaching for voucher type {vt}: {ai.get('reason','')}"
            v=Voucher(vt,date,[LedgerEntry(x["ledger"],x["amount"]) for x in entries],narration=narration,reference=reference,
                      party_ledger=(party_ledger or party) if any(x in low for x in ("sales","purchase","invoice")) else "")
            try: v.validate()
            except Exception as e: return None,ai["confidence"],f"AI suggestion invalid: {e}"
            return self._voucher_dict(v),float(ai["confidence"]),f"AI suggestion: {ai.get('reason','')}"

        return None,0,"no verified/history rule matched; teach this entry once"

    @staticmethod
    def _voucher_dict(v: Voucher) -> dict:
        return {
            "voucher_type":v.voucher_type,"date":v.date,"narration":v.narration,"reference":v.reference,
            "voucher_number":v.voucher_number,"party_ledger":v.party_ledger,
            "entries":[e.__dict__ for e in v.entries],"items":[i.__dict__ for i in v.items],
        }

    @staticmethod
    def _dict_to_voucher(d: dict) -> Voucher:
        return Voucher(
            d["voucher_type"],d["date"],entries_from_json(d.get("entries",[])),
            narration=d.get("narration", ""),reference=d.get("reference", ""),voucher_number=d.get("voucher_number", ""),
            party_ledger=d.get("party_ledger", ""),items=items_from_json(d.get("items",[])),
        )

    def create_job_from_rows(self, rows: list[dict], source_name: str = "bulk-json", company: str = "") -> str:
        company=company.strip() or self.settings.tally_company
        if not company:
            company=self.gateway.current_company()
        jid=self.db.create_job(company,source_name)
        for idx,row in enumerate(rows,1):
            voucher,conf,reason=self._voucher_from_row(company,row)
            status="ready" if voucher and conf>=self.settings.auto_threshold else "needs_review"
            fp=""
            if voucher:
                try: fp=self._dict_to_voucher(voucher).fingerprint(company)
                except Exception: fp=""
            self.db.add_job_row(jid,idx,row,voucher,status,conf,reason,fp)
        self.db.set_job(jid,status="review")
        self.db.audit(company,jid,"create_job",{"rows":len(rows),"source":source_name})
        return jid

    def create_job_from_file(self, path: str, sheet: str = "", company: str = "") -> str:
        rows=load_file(path,sheet)
        return self.create_job_from_rows(rows,Path(path).name,company)

    def summary(self, job_id: str) -> dict:
        job=self.db.job(job_id)
        if not job: raise KeyError(job_id)
        rows=self.db.rows(job_id)
        counts={}
        for r in rows: counts[r["status"]]=counts.get(r["status"],0)+1
        return {"job_id":job_id,"company":job["company"],"source":job["source_name"],"status":job["status"],
                "approved":bool(job["approved"]),"total":len(rows),"counts":counts}

    def exceptions(self, job_id: str) -> list[dict]:
        out=[]
        for r in self.db.rows(job_id,("needs_review","failed")):
            out.append({"row_id":r["id"],"source_row":r["source_row"],"raw":json.loads(r["raw_json"]),"reason":r["reason"],"confidence":r["confidence"],"tally_result":r["tally_result"]})
        return out

    def preview(self, job_id: str, limit: int = 500) -> list[dict]:
        out=[]
        for r in self.db.rows(job_id)[:max(1,limit)]:
            out.append({
                "row_id": r["id"], "source_row": r["source_row"], "status": r["status"],
                "confidence": r["confidence"], "reason": r["reason"],
                "source": json.loads(r["raw_json"]),
                "voucher": json.loads(r["voucher_json"]) if r["voucher_json"] else None,
                "tally_result": r["tally_result"],
            })
        return out

    def teach_row(self, job_id: str, row_id: int, entries: list[dict], party_ledger: str = "", bank_ledger: str = "", apply_to_similar: bool = True) -> dict:
        job=self.db.job(job_id)
        if not job: raise KeyError(job_id)
        rows={r["id"]:r for r in self.db.rows(job_id)}
        if row_id not in rows: raise KeyError(row_id)
        r=rows[row_id]; raw=json.loads(r["raw_json"])
        pattern=(raw.get("party") or raw.get("narration") or "").strip()
        vt=(raw.get("voucher_type") or "").strip()
        self.learning.teach(job["company"],pattern,vt,entries,party_ledger,bank_ledger)
        targets=self.db.rows(job_id) if apply_to_similar else [r]
        changed=0
        for tr in targets:
            raw2=json.loads(tr["raw_json"])
            if tr["status"] not in ("needs_review","failed"): continue
            if apply_to_similar and (norm_text(raw2.get("party", ""))!=norm_text(pattern) or norm_text(raw2.get("voucher_type", ""))!=norm_text(vt)):
                continue
            voucher,conf,reason=self._voucher_from_row(job["company"],raw2)
            if voucher:
                fp=self._dict_to_voucher(voucher).fingerprint(job["company"])
                self.db.update_row(tr["id"],voucher_json=json.dumps(voucher,ensure_ascii=False),status="ready",confidence=conf,reason=reason,fingerprint=fp,tally_result="")
                changed+=1
        self.db.audit(job["company"],job_id,"teach_rule",{"row_id":row_id,"pattern":pattern,"voucher_type":vt,"rows_reclassified":changed},row_id)
        return {"rule_saved":True,"rows_reclassified":changed}

    def approve(self, job_id: str) -> dict:
        s=self.summary(job_id)
        if s["counts"].get("needs_review",0) or s["counts"].get("failed",0):
            raise ValueError(f"Job still has unresolved rows: {s['counts']}")
        self.db.set_job(job_id,status="approved",approved=True)
        return self.summary(job_id)

    # ---------- posting ----------
    def _preflight_ledgers(self, company: str, vouchers: list[Voucher]) -> dict[int,list[str]]:
        try:
            ledgers=set(self.gateway.list_ledgers())
        except TallyError:
            ledgers=set(self.db.company_snapshot(company).get("ledgers",[]))
        missing={}
        for i,v in enumerate(vouchers):
            names={e.ledger for e in v.entries}
            names.update(i2.ledger for i2 in v.items)
            bad=sorted(n for n in names if ledgers and n not in ledgers)
            if bad: missing[i]=bad
        return missing

    def _isolate_post(self, pairs: list[tuple[object,Voucher]]) -> list[tuple[object,bool,str]]:
        if not pairs: return []
        result=self.gateway.import_vouchers([v for _,v in pairs])
        if result.ok and result.created >= len(pairs):
            return [(r,True,result.summary()) for r,_ in pairs]
        if len(pairs)==1:
            return [(pairs[0][0],False,result.summary())]
        mid=len(pairs)//2
        return self._isolate_post(pairs[:mid])+self._isolate_post(pairs[mid:])

    def post(self, job_id: str, confirm_company: str) -> dict:
        job=self.db.job(job_id)
        if not job: raise KeyError(job_id)
        if not job["approved"]:
            raise ValueError("Job is not approved. Resolve exceptions and approve first.")
        current=self.gateway.current_company()
        if norm_text(current)!=norm_text(job["company"]):
            raise ValueError(f"COMPANY GUARD: job belongs to {job['company']!r}, but Tally has {current!r} open.")
        if norm_text(confirm_company)!=norm_text(current):
            raise ValueError(f"Confirm the open company by passing confirm_company={current!r}.")

        rows=self.db.rows(job_id,("ready",))
        pairs=[]
        seen=set()
        for r in rows:
            if r["fingerprint"] and r["fingerprint"] in seen:
                self.db.update_row(r["id"],status="duplicate",reason="duplicate inside this import job")
                continue
            seen.add(r["fingerprint"])
            d=json.loads(r["voucher_json"]); pairs.append((r,self._dict_to_voucher(d)))

        # Duplicate check against vouchers already in Tally. One Day Book read
        # covers the whole job instead of one HTTP call per row.
        if pairs:
            dates=sorted(v.date for _,v in pairs)
            try:
                existing=self.gateway.day_book(dates[0],dates[-1])
            except Exception:
                existing=[]
            filtered=[]
            for r,v in pairs:
                duplicate=False
                vd=fmt_date(v.date); vt=norm_text(v.voucher_type); ref=norm_text(v.reference); party=norm_text(v.party_ledger)
                for old in existing:
                    try: od=fmt_date(str(old.get("date", "")))
                    except Exception: od=str(old.get("date", "")).replace("-","").replace("/","")
                    if od != vd or norm_text(old.get("voucher_type", old.get("type", ""))) != vt:
                        continue
                    old_ref=norm_text(old.get("reference", ""))
                    try: old_amt=abs(float(old.get("amount", 0) or 0))
                    except Exception: old_amt=0.0
                    strong_ref=bool(ref) and old_ref==ref
                    party_amount=bool(party) and norm_text(old.get("party", ""))==party and abs(old_amt-v.amount)<=0.02
                    if strong_ref or party_amount:
                        duplicate=True; break
                if duplicate:
                    self.db.update_row(r["id"],status="duplicate",reason="matching voucher already exists in Tally Day Book")
                else:
                    filtered.append((r,v))
            pairs=filtered

        missing=self._preflight_ledgers(job["company"],[v for _,v in pairs])
        safe=[]
        for idx,(r,v) in enumerate(pairs):
            if idx in missing:
                self.db.update_row(r["id"],status="failed",reason=f"missing Tally ledger(s): {', '.join(missing[idx])}")
            else:
                safe.append((r,v))

        results=[]
        for start in range(0,len(safe),self.settings.batch_size):
            results.extend(self._isolate_post(safe[start:start+self.settings.batch_size]))
        for r,ok,detail in results:
            self.db.update_row(r["id"],status="posted" if ok else "failed",tally_result=detail,reason="" if ok else "Tally import failed")
            self.db.audit(job["company"],job_id,"post_row",{"ok":ok,"result":detail},r["id"])

        final=self.summary(job_id)
        if final["counts"].get("failed",0)==0 and final["counts"].get("needs_review",0)==0:
            self.db.set_job(job_id,status="completed")
            final=self.summary(job_id)
        return final
