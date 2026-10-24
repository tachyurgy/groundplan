"""Narrative: AI may write the prose, it never touches the math.

`TemplateNarrative` (default, offline) composes observations + the strategy matrix into 2-4 paragraphs.
`LLMNarrative` (opt-in via GP_LLM_PROVIDER=anthropic|bedrock) sends ONLY pre-computed, pre-formatted Figure values;
the prompt forbids arithmetic, and `number_guard` asserts every dollar amount / percentage in the output appears in
the allowed set. Any violation falls back to the template and logs a `narrative_number_guard` event.
Never called in tests; the provider is injected.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from typing import Protocol

from groundplan.engine.observations import usd

log = logging.getLogger("groundplan.narrative")

MONEY_RE = re.compile(r"-?\$\s?\d[\d,]*(?:\.\d+)?(?:\s?[kKmM]\b)?")
PCT_RE = re.compile(r"\d+(?:\.\d+)?%")

SYSTEM_PROMPT = """You write short, plain-English portfolio summaries for a financial advisor's client.
Rules you must follow exactly:
- Use ONLY the numbers given in FACTS, copied character-for-character. Never add, subtract, average, round,
  convert or estimate any number. If a number you want is not in FACTS, describe it without a number.
- Never recommend a path. Describe what each path leads or trails on.
- 2 to 4 paragraphs, no headings, no bullet points, no markdown."""


class NarrativeProvider(Protocol):
    name: str

    def generate(self, facts: dict) -> str: ...


def allowed_tokens(facts: dict) -> set[str]:
    toks: set[str] = set()
    blob = json.dumps(facts)
    for m in MONEY_RE.findall(blob):
        toks.add(_norm_money(m))
    for m in PCT_RE.findall(blob):
        toks.add(m)
    return toks


def _norm_money(s: str) -> str:
    return s.replace(" ", "").replace("$", "$")


def number_guard(text: str, facts: dict) -> list[str]:
    """Return the dollar amounts / percentages in `text` that do NOT appear in the facts."""
    ok = allowed_tokens(facts)
    bad = [m for m in MONEY_RE.findall(text) if _norm_money(m) not in ok]
    bad += [m for m in PCT_RE.findall(text) if m not in ok]
    return bad


class TemplateNarrative:
    name = "template"

    def generate(self, facts: dict) -> str:
        paras = []
        hh = facts["household"]
        goal = hh.get("goal") or "their long-term plan"
        paras.append(
            f"{hh['name']} holds {facts['property_count']} rental properties worth {facts['total_value']} with "
            f"{facts['total_debt']} of debt, for {facts['total_equity']} of equity. Together they produce "
            f"{facts['net_cash_flow']} a year of net cash flow after debt service. The stated goal is to {goal.rstrip('.')}."
        )
        obs = facts.get("observations", [])
        if obs:
            top = " ".join(o["message"] for o in obs[:4])
            paras.append(f"What stands out: {top}")
        if facts.get("exit_tax_total"):
            paras.append(
                f"Selling everything today would trigger about {facts['exit_tax_total']} of combined federal, NIIT and "
                f"state tax, which is why the timing and structure of any exit matters as much as the price. "
                + (f"The household also carries {facts['carryforward']} of suspended passive losses that a fully "
                   "taxable sale would release; a 1031 exchange would carry them forward instead." if facts.get("carryforward") else "")
            )
        strat = facts.get("strategy_matrix")
        if strat:
            paras.append(
                f"For {strat['property']}, over {strat['horizon']} years on identical assumptions: holding "
                f"{strat['hold_terminal_wealth']} terminal wealth, selling now {strat['sell_terminal_wealth']}, a 1031 "
                f"exchange {strat['exchange_terminal_wealth']}. Holding leads or trails on wealth as the matrix shows, "
                "selling leads on liquidity and management burden, and the exchange defers tax rather than eliminating it. "
                "No path is presented as the answer; the trade-offs belong in the conversation."
            )
        return "\n\n".join(paras)


class LLMNarrative:
    """Optional provider; requires network + credentials. Never used unless GP_LLM_PROVIDER is set."""

    def __init__(self, provider: str):
        self.provider = provider
        self.name = f"llm:{provider}"

    def generate(self, facts: dict) -> str:  # pragma: no cover - network
        user = "FACTS:\n" + json.dumps(facts, indent=2) + "\n\nWrite the summary."
        if self.provider == "anthropic":
            import anthropic  # type: ignore[import-not-found]

            client = anthropic.Anthropic()
            msg = client.messages.create(model=os.environ.get("GP_LLM_MODEL", "claude-haiku-4-5"), max_tokens=700,
                                         system=SYSTEM_PROMPT, messages=[{"role": "user", "content": user}])
            return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        if self.provider == "bedrock":
            import boto3  # type: ignore[import-not-found]

            rt = boto3.client("bedrock-runtime")
            resp = rt.converse(modelId=os.environ.get("GP_BEDROCK_MODEL", "anthropic.claude-haiku-4-5"),
                               system=[{"text": SYSTEM_PROMPT}], messages=[{"role": "user", "content": [{"text": user}]}])
            return resp["output"]["message"]["content"][0]["text"]
        raise ValueError(f"unknown LLM provider {self.provider!r}")


def provider_from_env() -> NarrativeProvider:
    p = os.environ.get("GP_LLM_PROVIDER", "").strip().lower()
    if p in ("anthropic", "bedrock"):
        return LLMNarrative(p)
    return TemplateNarrative()


def generate_narrative(facts: dict, provider: NarrativeProvider | None = None) -> dict:
    provider = provider or provider_from_env()
    template = TemplateNarrative()
    now = datetime.now(UTC).isoformat(timespec="seconds")
    if provider.name == "template":
        return {"text": template.generate(facts), "provider": "template", "generated_at": now, "guard": "n/a"}
    try:
        text = provider.generate(facts)
    except Exception as e:  # noqa: BLE001 - any provider failure falls back
        log.warning("narrative provider failed, using template: %s", e)
        return {"text": template.generate(facts), "provider": "template", "generated_at": now,
                "guard": f"provider_error: {type(e).__name__}"}
    bad = number_guard(text, facts)
    if bad:
        log.warning("narrative_number_guard", extra={"event": "narrative_number_guard", "unexpected": bad,
                                                     "provider": provider.name})
        return {"text": template.generate(facts), "provider": "template", "generated_at": now,
                "guard": f"narrative_number_guard: rejected {provider.name} output with numbers not in the input set: {bad}"}
    return {"text": text, "provider": provider.name, "generated_at": now, "guard": "passed"}


__all__ = ["NarrativeProvider", "TemplateNarrative", "LLMNarrative", "generate_narrative", "number_guard", "usd"]
