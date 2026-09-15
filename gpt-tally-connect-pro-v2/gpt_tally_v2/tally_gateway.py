from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from typing import Iterable
from xml.sax.saxutils import escape

from .models import ImportResult, Voucher, fmt_date


class TallyError(RuntimeError):
    pass


class TallyGateway:
    def __init__(self, url: str = "http://localhost:9000", company: str = "", timeout: int = 20):
        self.url = url.rstrip("/")
        self.company = company.strip()
        self.timeout = timeout

    def _post(self, xml: str) -> str:
        req = urllib.request.Request(
            self.url,
            data=xml.encode("utf-8"),
            headers={"Content-Type": "text/xml; charset=utf-8"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                raw = r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise TallyError(f"Cannot reach Tally at {self.url}: {e}") from e
        for enc in ("utf-8-sig", "utf-16", "cp1252"):
            try:
                text = raw.decode(enc)
                break
            except UnicodeDecodeError:
                continue
        else:
            text = raw.decode("utf-8", errors="replace")
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text)
        return text

    def ping(self) -> str:
        return self.current_company()

    def current_company(self) -> str:
        if self.company:
            return self.company
        xml = """<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>EXPORT</TALLYREQUEST><TYPE>DATA</TYPE><ID>GPTCurrentCompany</ID></HEADER><BODY><DESC><TDL><TDLMESSAGE><REPORT NAME=\"GPTCurrentCompany\"><FORMS>GPTCurrentCompany</FORMS></REPORT><FORM NAME=\"GPTCurrentCompany\"><PARTS>GPTCurrentCompany</PARTS></FORM><PART NAME=\"GPTCurrentCompany\"><LINES>GPTCurrentCompany</LINES></PART><LINE NAME=\"GPTCurrentCompany\"><FIELDS>GPTCurrentCompany</FIELDS></LINE><FIELD NAME=\"GPTCurrentCompany\"><SET>##SVCurrentCompany</SET><XMLTAG>COMPANYNAME</XMLTAG></FIELD></TDLMESSAGE></TDL></DESC></BODY></ENVELOPE>"""
        raw = self._post(xml)
        m = re.search(r"<COMPANYNAME>(.*?)</COMPANYNAME>", raw, re.I | re.S)
        if not m or not m.group(1).strip():
            raise TallyError("Tally answered, but no current company was detected. Load a company or set TALLY_COMPANY.")
        return re.sub(r"<[^>]+>", "", m.group(1)).strip()

    def _static(self, from_date: str = "", to_date: str = "") -> str:
        bits = ["<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>"]
        if self.company:
            bits.append(f"<SVCURRENTCOMPANY>{escape(self.company)}</SVCURRENTCOMPANY>")
        if from_date:
            bits.append(f"<SVFROMDATE>{fmt_date(from_date)}</SVFROMDATE>")
        if to_date:
            bits.append(f"<SVTODATE>{fmt_date(to_date)}</SVTODATE>")
        return "".join(bits)

    def export_collection(self, collection_id: str) -> str:
        xml = (
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>EXPORT</TALLYREQUEST>"
            f"<TYPE>COLLECTION</TYPE><ID>{escape(collection_id)}</ID></HEADER>"
            f"<BODY><DESC><STATICVARIABLES>{self._static()}</STATICVARIABLES></DESC></BODY></ENVELOPE>"
        )
        return self._post(xml)

    def list_ledgers(self) -> list[str]:
        raw = self.export_collection("List of Ledgers")
        names = re.findall(r'<LEDGER[^>]*NAME="([^"]+)"', raw, flags=re.I)
        if not names:
            names = re.findall(r"<NAME>([^<]+)</NAME>", raw, flags=re.I)
        return sorted({x.strip() for x in names if x.strip()}, key=str.lower)

    def list_stock_items(self) -> list[str]:
        try:
            raw = self.export_collection("List of Stock Items")
        except TallyError:
            return []
        return sorted({x.strip() for x in re.findall(r'<STOCKITEM[^>]*NAME="([^"]+)"', raw, flags=re.I) if x.strip()}, key=str.lower)

    def day_book_raw(self, from_date: str, to_date: str) -> str:
        xml = (
            "<ENVELOPE><HEADER><VERSION>1</VERSION><TALLYREQUEST>EXPORT</TALLYREQUEST>"
            "<TYPE>DATA</TYPE><ID>Day Book</ID></HEADER><BODY><DESC><STATICVARIABLES>"
            f"{self._static(from_date, to_date)}"
            "<EXPLODEFLAG>Yes</EXPLODEFLAG>"
            "</STATICVARIABLES></DESC></BODY></ENVELOPE>"
        )
        return self._post(xml)

    @staticmethod
    def parse_day_book(raw: str) -> list[dict]:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise TallyError(f"Tally returned malformed XML: {e}") from e
        out = []
        for v in root.iter():
            if v.tag.upper().split("}")[-1] != "VOUCHER":
                continue
            def txt(tag: str) -> str:
                for el in v.iter():
                    if el.tag.upper().split("}")[-1] == tag.upper():
                        return (el.text or "").strip()
                return ""
            entries = []
            for le in v.iter():
                tag = le.tag.upper().split("}")[-1]
                if tag not in {"ALLLEDGERENTRIES.LIST", "LEDGERENTRIES.LIST"}:
                    continue
                name = ""; amount = ""
                for c in le:
                    ctag = c.tag.upper().split("}")[-1]
                    if ctag == "LEDGERNAME": name = (c.text or "").strip()
                    elif ctag == "AMOUNT": amount = (c.text or "").strip()
                try:
                    amt = -float(amount)  # convert Tally sign to user sign (+dr/-cr)
                except ValueError:
                    continue
                if name:
                    entries.append({"ledger": name, "amount": amt})
            party = txt("PARTYLEDGERNAME") or txt("PARTYNAME")
            total = 0.0
            if party:
                vals = [abs(e["amount"]) for e in entries if e["ledger"].strip().lower() == party.strip().lower()]
                total = vals[0] if vals else 0.0
            if not total and entries:
                total = max(abs(e["amount"]) for e in entries)
            out.append({
                "date": txt("DATE"), "voucher_type": txt("VOUCHERTYPENAME") or v.attrib.get("VCHTYPE", ""),
                "voucher_number": txt("VOUCHERNUMBER"), "reference": txt("REFERENCE"),
                "party": party, "narration": txt("NARRATION"), "entries": entries, "amount": round(total, 2),
            })
        return out

    def day_book(self, from_date: str, to_date: str) -> list[dict]:
        return self.parse_day_book(self.day_book_raw(from_date, to_date))

    def _company_var(self) -> str:
        return f"<SVCURRENTCOMPANY>{escape(self.company)}</SVCURRENTCOMPANY>" if self.company else ""

    def import_vouchers(self, vouchers: Iterable[Voucher]) -> ImportResult:
        vouchers = list(vouchers)
        if not vouchers:
            raise ValueError("No vouchers to import.")
        body = "".join(v.to_xml("Create") for v in vouchers)
        payload = (
            "<ENVELOPE><HEADER><TALLYREQUEST>Import Data</TALLYREQUEST></HEADER>"
            "<BODY><IMPORTDATA><REQUESTDESC><REPORTNAME>Vouchers</REPORTNAME>"
            f"<STATICVARIABLES>{self._company_var()}</STATICVARIABLES>"
            "</REQUESTDESC><REQUESTDATA>"
            f'<TALLYMESSAGE xmlns:UDF="TallyUDF">{body}</TALLYMESSAGE>'
            "</REQUESTDATA></IMPORTDATA></BODY></ENVELOPE>"
        )
        return self.parse_import_result(self._post(payload))

    @staticmethod
    def parse_import_result(raw: str) -> ImportResult:
        try:
            root = ET.fromstring(raw)
        except ET.ParseError as e:
            raise TallyError(f"Could not parse Tally import response: {e}; response={raw[:500]!r}") from e
        def num(tag: str) -> int:
            vals = [el.text for el in root.iter() if el.tag.upper().split("}")[-1] == tag and (el.text or "").strip()]
            try:
                return int(float(vals[-1])) if vals else 0
            except ValueError:
                return 0
        line_errors = [(el.text or "").strip() for el in root.iter() if el.tag.upper().split("}")[-1] == "LINEERROR" and (el.text or "").strip()]
        errors = num("ERRORS")
        if line_errors and errors == 0:
            errors = len(line_errors)
        return ImportResult(
            created=num("CREATED"), altered=num("ALTERED"), ignored=num("IGNORED"),
            errors=errors, cancelled=num("CANCELLED"), line_errors=line_errors, raw=raw,
        )
