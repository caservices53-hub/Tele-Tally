from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from xml.sax.saxutils import escape


def fmt_date(value: str) -> str:
    s = (value or "").strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y%m%d")
        except ValueError:
            pass
    raise ValueError(f"Invalid date {value!r}; use YYYY-MM-DD.")


def norm_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


@dataclass
class LedgerEntry:
    ledger: str
    amount: float  # user convention: + debit, - credit
    bill_name: str = ""
    bill_type: str = ""

    def validate(self) -> None:
        if not self.ledger.strip():
            raise ValueError("Ledger name cannot be blank.")
        if abs(float(self.amount)) < 0.0001:
            raise ValueError(f"Ledger {self.ledger!r} has a zero amount.")
        if self.bill_type and self.bill_type not in {"New Ref", "Agst Ref", "Advance", "On Account"}:
            raise ValueError(f"Unsupported bill_type {self.bill_type!r}.")

    def to_xml(self, list_tag: str = "ALLLEDGERENTRIES.LIST") -> str:
        self.validate()
        tally_amount = -float(self.amount)
        deemed = "Yes" if self.amount > 0 else "No"
        bill_xml = ""
        if self.bill_name:
            btype = self.bill_type or "Agst Ref"
            bill_xml = (
                "<BILLALLOCATIONS.LIST>"
                f"<NAME>{escape(self.bill_name)}</NAME>"
                f"<BILLTYPE>{escape(btype)}</BILLTYPE>"
                f"<AMOUNT>{tally_amount:.2f}</AMOUNT>"
                "</BILLALLOCATIONS.LIST>"
            )
        return (
            f"<{list_tag}>"
            f"<LEDGERNAME>{escape(self.ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{tally_amount:.2f}</AMOUNT>"
            f"{bill_xml}"
            f"</{list_tag}>"
        )


@dataclass
class InventoryEntry:
    item: str
    quantity: float
    rate: float
    unit: str
    ledger: str
    godown: str = ""
    batch: str = ""

    @property
    def value(self) -> float:
        return round(float(self.quantity) * float(self.rate), 2)

    def validate(self) -> None:
        if not self.item.strip() or not self.ledger.strip() or not self.unit.strip():
            raise ValueError("Inventory item, unit and allocation ledger are required.")
        if self.quantity <= 0 or self.rate < 0:
            raise ValueError("Inventory quantity must be >0 and rate must be >=0.")

    def to_xml(self, outward: bool) -> str:
        self.validate()
        value = self.value
        amount = value if outward else -value
        deemed = "No" if outward else "Yes"
        batch_xml = ""
        if self.godown or self.batch:
            batch_xml = (
                "<BATCHALLOCATIONS.LIST>"
                f"<GODOWNNAME>{escape(self.godown or 'Main Location')}</GODOWNNAME>"
                f"<BATCHNAME>{escape(self.batch or 'Primary Batch')}</BATCHNAME>"
                f"<AMOUNT>{amount:.2f}</AMOUNT>"
                f"<ACTUALQTY>{self.quantity:g} {escape(self.unit)}</ACTUALQTY>"
                f"<BILLEDQTY>{self.quantity:g} {escape(self.unit)}</BILLEDQTY>"
                "</BATCHALLOCATIONS.LIST>"
            )
        return (
            "<ALLINVENTORYENTRIES.LIST>"
            f"<STOCKITEMNAME>{escape(self.item)}</STOCKITEMNAME>"
            f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
            f"<RATE>{self.rate:g}/{escape(self.unit)}</RATE>"
            f"<AMOUNT>{amount:.2f}</AMOUNT>"
            f"<ACTUALQTY>{self.quantity:g} {escape(self.unit)}</ACTUALQTY>"
            f"<BILLEDQTY>{self.quantity:g} {escape(self.unit)}</BILLEDQTY>"
            f"{batch_xml}"
            "<ACCOUNTINGALLOCATIONS.LIST>"
            f"<LEDGERNAME>{escape(self.ledger)}</LEDGERNAME>"
            f"<ISDEEMEDPOSITIVE>{deemed}</ISDEEMEDPOSITIVE>"
            f"<AMOUNT>{amount:.2f}</AMOUNT>"
            "</ACCOUNTINGALLOCATIONS.LIST>"
            "</ALLINVENTORYENTRIES.LIST>"
        )


@dataclass
class Voucher:
    voucher_type: str
    date: str
    entries: list[LedgerEntry]
    narration: str = ""
    reference: str = ""
    voucher_number: str = ""
    party_ledger: str = ""
    items: list[InventoryEntry] = field(default_factory=list)

    def _outward(self) -> bool:
        t = self.voucher_type.lower()
        if "purchase" in t or "credit note" in t or "grn" in t:
            return False
        return "sales" in t or "invoice" in t or "debit note" in t

    def validate(self) -> None:
        if not self.voucher_type.strip():
            raise ValueError("voucher_type is required.")
        fmt_date(self.date)
        for e in self.entries:
            e.validate()
        for i in self.items:
            i.validate()
        if len(self.entries) + len(self.items) < 2:
            raise ValueError("Voucher needs at least two accounting/inventory lines.")
        inv = 0.0
        if self.items:
            total = sum(i.value for i in self.items)
            inv = -total if self._outward() else total
        balance = round(sum(float(e.amount) for e in self.entries) + inv, 2)
        if abs(balance) > 0.02:
            raise ValueError(f"Voucher does not balance; debit-credit difference is {balance:.2f}.")

    @property
    def amount(self) -> float:
        if self.party_ledger:
            for e in self.entries:
                if norm_text(e.ledger) == norm_text(self.party_ledger):
                    return abs(float(e.amount))
        values = [abs(float(e.amount)) for e in self.entries]
        values += [i.value for i in self.items]
        return max(values) if values else 0.0

    def fingerprint(self, company: str) -> str:
        payload = "|".join([
            norm_text(company), norm_text(self.voucher_type), fmt_date(self.date),
            norm_text(self.party_ledger), norm_text(self.reference), f"{self.amount:.2f}",
        ])
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_xml(self, action: str = "Create") -> str:
        self.validate()
        d = fmt_date(self.date)
        invoice_mode = bool(self.items)
        list_tag = "LEDGERENTRIES.LIST" if invoice_mode else "ALLLEDGERENTRIES.LIST"
        attrs = f' VCHTYPE="{escape(self.voucher_type)}" ACTION="{escape(action)}"'
        fields = [
            f"<DATE>{d}</DATE>",
            f"<VOUCHERTYPENAME>{escape(self.voucher_type)}</VOUCHERTYPENAME>",
        ]
        if invoice_mode:
            fields += ["<PERSISTEDVIEW>Invoice Voucher View</PERSISTEDVIEW>", "<ISINVOICE>Yes</ISINVOICE>"]
        if self.voucher_number:
            fields.append(f"<VOUCHERNUMBER>{escape(self.voucher_number)}</VOUCHERNUMBER>")
        if self.reference:
            fields.append(f"<REFERENCE>{escape(self.reference)}</REFERENCE>")
        if self.party_ledger:
            fields.append(f"<PARTYLEDGERNAME>{escape(self.party_ledger)}</PARTYLEDGERNAME>")
        if self.narration:
            fields.append(f"<NARRATION>{escape(self.narration)}</NARRATION>")
        fields.extend(e.to_xml(list_tag) for e in self.entries)
        fields.extend(i.to_xml(self._outward()) for i in self.items)
        return f"<VOUCHER{attrs}>{''.join(fields)}</VOUCHER>"


@dataclass
class ImportResult:
    created: int = 0
    altered: int = 0
    ignored: int = 0
    errors: int = 0
    cancelled: int = 0
    line_errors: list[str] = field(default_factory=list)
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.errors == 0 and not self.line_errors

    def summary(self) -> str:
        bits = [f"created={self.created}", f"altered={self.altered}", f"ignored={self.ignored}", f"errors={self.errors}"]
        if self.line_errors:
            bits.append("; ".join(self.line_errors[:5]))
        return ", ".join(bits)


def entries_from_json(value: str | list[dict[str, Any]]) -> list[LedgerEntry]:
    raw = json.loads(value) if isinstance(value, str) else value
    if not raw:
        return []
    return [LedgerEntry(
        ledger=str(x.get("ledger", "")), amount=float(x.get("amount", 0)),
        bill_name=str(x.get("bill_name", x.get("bill", "")) or ""),
        bill_type=str(x.get("bill_type", "") or ""),
    ) for x in raw]


def items_from_json(value: str | list[dict[str, Any]]) -> list[InventoryEntry]:
    raw = json.loads(value) if isinstance(value, str) else value
    if not raw:
        return []
    return [InventoryEntry(
        item=str(x.get("item", x.get("stock_item", ""))),
        quantity=float(x.get("quantity", x.get("qty", 0))),
        rate=float(x.get("rate", 0)), unit=str(x.get("unit", "")),
        ledger=str(x.get("ledger", x.get("sales_ledger", x.get("purchase_ledger", "")))),
        godown=str(x.get("godown", "") or ""), batch=str(x.get("batch", "") or ""),
    ) for x in raw]
