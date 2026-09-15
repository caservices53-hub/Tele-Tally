from __future__ import annotations

import json
import os


class OptionalAIClassifier:
    """Optional fallback for rows not solved by deterministic company learning.

    It never invents ledger names: it is given the company's ledger list and
    must choose from that list. By default its answer is review-only.
    """
    def __init__(self, model: str = ""):
        self.model = model or os.getenv("OPENAI_MODEL", "")

    @property
    def enabled(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY") and self.model)

    def classify(self, row: dict, ledgers: list[str], learned_context: list[dict] | None = None) -> dict | None:
        if not self.enabled or not ledgers:
            return None
        try:
            from openai import OpenAI
        except ImportError:
            return None
        client=OpenAI()
        prompt={
            "transaction": row,
            "allowed_ledgers": ledgers[:2000],
            "learned_examples": (learned_context or [])[:20],
            "instruction": "Choose the most appropriate existing Tally ledger for the unresolved transaction. Do not invent ledger names. Return JSON only with keys target_ledger, confidence (0..1), reason. If uncertain set confidence below 0.8."
        }
        resp=client.responses.create(model=self.model,input=json.dumps(prompt,ensure_ascii=False),store=False)
        text=getattr(resp,"output_text","") or ""
        try:
            start=text.index("{"); end=text.rindex("}")+1
            data=json.loads(text[start:end])
        except Exception:
            return None
        if data.get("target_ledger") not in ledgers:
            return None
        try: data["confidence"]=float(data.get("confidence",0))
        except Exception: data["confidence"]=0
        return data
