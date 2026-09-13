from __future__ import annotations

import hashlib
import json
from datetime import datetime
from difflib import SequenceMatcher

from .db import Database
from .models import norm_text


TAX_WORDS = ("cgst", "sgst", "igst", "utgst", "cess", "vat", "round off", "roundoff")
BANK_WORDS = ("bank", "cash", "petty cash", "card", "credit card")


def _is_tax(name: str) -> bool:
    n = norm_text(name)
    return any(x in n for x in TAX_WORDS)


def _is_bank(name: str) -> bool:
    n = norm_text(name)
    return any(x in n for x in BANK_WORDS)


def _hash_template(tpl: dict) -> str:
    return hashlib.sha256(json.dumps(tpl, sort_keys=True).encode()).hexdigest()[:20]


class LearningEngine:
    def __init__(self, db: Database):
        self.db = db

    def _make_template(self, voucher: dict) -> tuple[str, str, dict] | None:
        entries = voucher.get("entries") or []
        if len(entries) < 2:
            return None
        vt = (voucher.get("voucher_type") or "").strip()
        party = (voucher.get("party") or "").strip()
        total = float(voucher.get("amount") or 0)
        if total <= 0:
            total = max(abs(float(e.get("amount", 0))) for e in entries)
        if total <= 0:
            return None

        bank = ""
        for e in entries:
            if _is_bank(e.get("ledger", "")) and abs(abs(float(e.get("amount",0))) - total) <= max(1.0, total*0.02):
                bank = e.get("ledger", "")
                break

        # If Tally did not populate PARTYLEDGERNAME on payment/receipt,
        # use the non-bank, non-tax ledger as the learnable counterparty key.
        if not party:
            candidates = [e for e in entries if not _is_bank(e.get("ledger", "")) and not _is_tax(e.get("ledger", ""))]
            if candidates:
                party = max(candidates, key=lambda x: abs(float(x.get("amount",0)))).get("ledger", "")
        if not party:
            return None

        legs=[]
        for e in entries:
            name = e.get("ledger", "")
            amt = float(e.get("amount", 0))
            role = "ledger"
            if norm_text(name) == norm_text(party): role = "party"
            elif bank and norm_text(name) == norm_text(bank): role = "bank"
            legs.append({"role": role, "ledger": name, "sign": 1 if amt > 0 else -1, "ratio": round(abs(amt)/total, 8)})
        tpl = {"voucher_type": vt, "party_ledger": party, "bank_ledger": bank, "entries": legs}
        return party, bank, tpl

    def observe_vouchers(self, company: str, vouchers: list[dict]) -> dict:
        observed=0
        now=datetime.now().isoformat(timespec="seconds")
        with self.db.connect() as c:
            for v in vouchers:
                made=self._make_template(v)
                if not made: continue
                party, bank, tpl=made
                pattern=norm_text(party)
                vt=norm_text(v.get("voucher_type", ""))
                h=_hash_template(tpl)
                existing=c.execute("SELECT id,occurrences FROM rules WHERE company=? AND pattern=? AND voucher_type=? AND template_hash=?",
                                   (company,pattern,vt,h)).fetchone()
                if existing:
                    c.execute("UPDATE rules SET occurrences=?,updated_at=? WHERE id=?", (existing["occurrences"]+1,now,existing["id"]))
                else:
                    c.execute("""INSERT INTO rules(company,pattern,voucher_type,party_ledger,bank_ledger,template_json,template_hash,source,confidence,occurrences,verified,updated_at)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                              (company,pattern,vt,party,bank,json.dumps(tpl),h,"tally_history",0.75,1,0,now))
                observed += 1
        return {"vouchers_seen": len(vouchers), "patterns_observed": observed}

    def teach(self, company: str, pattern: str, voucher_type: str, entries: list[dict], party_ledger: str = "", bank_ledger: str = "") -> int:
        pattern_n=norm_text(pattern)
        vt=norm_text(voucher_type)
        if not pattern_n or not vt or len(entries)<2:
            raise ValueError("pattern, voucher_type and at least two entry lines are required.")
        amount=max(abs(float(x["amount"])) for x in entries)
        if amount<=0: raise ValueError("Teaching entries must contain a non-zero amount.")
        tpl_entries=[]
        for x in entries:
            ledger=str(x["ledger"]); amt=float(x["amount"])
            role="ledger"
            if party_ledger and norm_text(ledger)==norm_text(party_ledger): role="party"
            elif bank_ledger and norm_text(ledger)==norm_text(bank_ledger): role="bank"
            tpl_entries.append({"role":role,"ledger":ledger,"sign":1 if amt>0 else -1,"ratio":round(abs(amt)/amount,8)})
        tpl={"voucher_type":voucher_type,"party_ledger":party_ledger,"bank_ledger":bank_ledger,"entries":tpl_entries}
        h=_hash_template(tpl); now=datetime.now().isoformat(timespec="seconds")
        with self.db.connect() as c:
            c.execute("DELETE FROM rules WHERE company=? AND pattern=? AND voucher_type=? AND verified=1", (company,pattern_n,vt))
            cur=c.execute("""INSERT INTO rules(company,pattern,voucher_type,party_ledger,bank_ledger,template_json,template_hash,source,confidence,occurrences,verified,updated_at)
                           VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (company,pattern_n,vt,party_ledger,bank_ledger,json.dumps(tpl),h,"user_verified",0.99,1,1,now))
            return int(cur.lastrowid)

    def resolve(self, company: str, pattern: str, voucher_type: str) -> dict | None:
        p=norm_text(pattern); vt=norm_text(voucher_type)
        if not p or not vt: return None
        with self.db.connect() as c:
            exact=c.execute("SELECT * FROM rules WHERE company=? AND pattern=? AND voucher_type=? ORDER BY verified DESC, occurrences DESC, confidence DESC",
                            (company,p,vt)).fetchall()
            if exact:
                top=exact[0]; total=sum(r["occurrences"] for r in exact)
                dominance=top["occurrences"]/max(total,1)
                conf=0.99 if top["verified"] else min(0.97,(0.70+0.07*min(top["occurrences"],4))*dominance)
                return {**dict(top),"confidence":conf,"match":"exact","template":json.loads(top["template_json"])}
            allr=c.execute("SELECT * FROM rules WHERE company=? AND voucher_type=?",(company,vt)).fetchall()
        scored=[]
        for r in allr:
            score=SequenceMatcher(None,p,r["pattern"]).ratio()
            if score>=0.90:
                scored.append((score,r))
        if not scored: return None
        scored.sort(key=lambda x:(x[0],x[1]["verified"],x[1]["occurrences"]), reverse=True)
        score,top=scored[0]
        conf=min(0.89, score*(0.99 if top["verified"] else 0.90))
        return {**dict(top),"confidence":conf,"match":f"fuzzy:{score:.2f}","template":json.loads(top["template_json"])}

    def list_rules(self, company: str, limit: int = 100) -> list[dict]:
        with self.db.connect() as c:
            rows=c.execute("SELECT * FROM rules WHERE company=? ORDER BY verified DESC, occurrences DESC, updated_at DESC LIMIT ?",(company,limit)).fetchall()
        return [dict(r) for r in rows]
