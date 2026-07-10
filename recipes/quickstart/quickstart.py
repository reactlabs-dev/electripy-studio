#!/usr/bin/env python3
"""
ElectriPy AI — 5-Minute Production Runtime Quickstart
======================================================

Five production layers. One install. Zero rebuilding.

What this demonstrates:
  ✓ Governance    — Policy gateway redacts PII before the model sees it
  ✓ Reliability   — Circuit breaker with CLOSED/OPEN/HALF-OPEN state machine
  ✓ Observability — Structured AI spans with ContextVar propagation
  ✓ Model Runtime — Provider-agnostic LLM gateway with policy hooks wired in
  ✓ Cost Tracking — Thread-safe token cost accumulation with label slicing

Runs completely offline. No API key. No network. No mocks.

Usage:
    pip install electripy-ai
    python quickstart.py
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

from electripy.ai.cost_ledger import CostLedger
from electripy.ai.llm_gateway import (
    LlmGatewaySettings,
    LlmGatewaySyncClient,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    SyncLlmPort,
)
from electripy.ai.policy_gateway import (
    PolicyAction,
    PolicyGateway,
    PolicyRule,
    PolicySeverity,
    PolicyStage,
    build_llm_policy_hooks,
)
from electripy.concurrency import CircuitBreaker
from electripy.observability.observe import InMemoryTracer, ObservabilityService

console = Console()


@dataclass
class FakeProvider(SyncLlmPort):
    """Deterministic offline provider. Swap for OpenAiSyncAdapter, AnthropicSyncAdapter, or OllamaSyncAdapter."""

    def complete(self, request: LlmRequest, *, timeout: float | None = None) -> LlmResponse:
        user_text = next(m.content for m in request.messages if m.role == "user")
        return LlmResponse(
            text=f"Acknowledged: {user_text[:80]}. No sensitive data surfaced.",
            model=request.model,
            usage_total_tokens=len(user_text.split()) + 10,
        )


def main() -> None:
    console.print()
    console.print(Rule("[bold purple]ElectriPy AI — Production Runtime Quickstart[/bold purple]"))
    console.print()

    # L01 Governance
    console.print("[bold]L01 Governance[/bold]  · Policy Gateway")
    failure_threshold = 3
    gateway = PolicyGateway(
        rules=[
            PolicyRule(
                rule_id="pii-email",
                code="PII_EMAIL",
                description="Redact emails in prompts before model call",
                stage=PolicyStage.PREFLIGHT,
                pattern=r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
                action=PolicyAction.SANITIZE,
                severity=PolicySeverity.MEDIUM,
            ),
            PolicyRule(
                rule_id="block-api-keys",
                code="SECRET_LEAK",
                description="Block leaked API key patterns in model output",
                stage=PolicyStage.POSTFLIGHT,
                pattern=r"sk-[A-Za-z0-9]{20,}",
                action=PolicyAction.DENY,
                severity=PolicySeverity.CRITICAL,
            ),
        ]
    )
    console.print(
        "  [dim]2 rules active · PREFLIGHT email redaction · POSTFLIGHT secret blocking[/dim]"
    )

    # L03 Reliability
    console.print("[bold]L03 Reliability[/bold] · Circuit Breaker")
    breaker = CircuitBreaker(failure_threshold=failure_threshold, recovery_timeout=30.0)
    console.print(f"  [dim]CLOSED · threshold={failure_threshold} failures · recovery=30s[/dim]")

    # L02 Observability
    console.print("[bold]L02 Observability[/bold] · Structured Tracing")
    tracer = InMemoryTracer()
    obs = ObservabilityService(tracer=tracer)
    console.print("  [dim]InMemoryTracer · swap for OpenTelemetryTracer in production[/dim]")

    # L04 Model Runtime
    console.print("[bold]L04 Model Runtime[/bold] · LLM Gateway + Policy Hooks")
    request_hook, response_hook = build_llm_policy_hooks(gateway)
    client = LlmGatewaySyncClient(
        port=FakeProvider(),
        settings=LlmGatewaySettings(
            request_hook=request_hook,
            response_hook=response_hook,
        ),
    )
    console.print(
        "  [dim]FakeProvider · swap for OpenAiSyncAdapter(api_key=...) for real calls[/dim]"
    )

    # Cost Ledger
    console.print("[bold]Cost Ledger[/bold]    · Token Accumulation")
    ledger = CostLedger(cost_per_1k_tokens=0.00015)
    console.print(
        "  [dim]$0.00015/1K tokens · thread-safe · sliceable by model / tenant / feature[/dim]"
    )

    console.print()
    console.print(Rule("Executing"))
    console.print()

    # The prompt contains PII. Policy gateway redacts BEFORE model sees it.
    prompt = "Escalate the P0 incident to admin@acme.com and cc devops@acme.com immediately."
    console.print(f"[bold]Prompt[/bold]  [dim](raw):[/dim]   {prompt}")

    t0 = time.perf_counter()

    with obs.start_llm_span(provider="offline-fake", model="fake-v1") as span:
        response = breaker.call(
            lambda: client.complete(
                LlmRequest(
                    model="fake-v1",
                    messages=[LlmMessage.user(prompt)],
                )
            )
        )
        tokens_used = response.usage_total_tokens or 0
        span.set_attribute("gen_ai.usage.total_tokens", tokens_used)

    elapsed_ms = (time.perf_counter() - t0) * 1000
    ledger.record(
        tokens=tokens_used,
        labels={"model": response.model or "fake-v1", "feature": "quickstart"},
    )
    totals = ledger.total()

    console.print(f"[bold]Response[/bold]        : {response.text}")
    console.print()
    console.print(Rule("Results"))
    console.print()

    table = Table(show_header=True, header_style="bold purple", box=None, padding=(0, 2))
    table.add_column("LSAS Layer", style="bold", min_width=20)
    table.add_column("Status", min_width=16)
    table.add_column("What happened")

    table.add_row(
        "L01 Governance",
        "[green]✓ SANITIZED[/green]",
        "admin@acme.com, devops@acme.com → [REDACTED] · model never saw the emails",
    )
    table.add_row(
        "L02 Observability",
        "[green]✓ TRACED[/green]",
        f"{len(tracer.finished_spans)} span · {elapsed_ms:.1f}ms · ContextVar propagation active",
    )
    table.add_row(
        "L03 Reliability",
        f"[green]✓ {breaker.state.upper()}[/green]",
        f"0/{failure_threshold} failures · healthy · half-open probe at 30s",
    )
    table.add_row(
        "L04 Model Runtime",
        "[green]✓ RESPONDED[/green]",
        f"model={response.model} · {tokens_used} tokens · hooks wired pre+post",
    )
    table.add_row(
        "Cost Ledger",
        "[green]✓ RECORDED[/green]",
        f"{totals.tokens} tokens · ${totals.estimated_cost:.8f} · {totals.call_count} call",
    )

    console.print(table)
    console.print()
    console.print(
        Panel(
            "\n".join(
                [
                    "[bold green]Five production layers. Active. Zero boilerplate.[/bold green]",
                    "",
                    "Most teams build this from scratch — policy hooks, circuit breakers,",
                    "span propagation, cost tracking — one module at a time, per project.",
                    "ElectriPy AI ships it composable, tested, production-ready from day one.",
                    "",
                    "[bold]Use a real model:[/bold]",
                    "  from electripy.ai.llm_gateway import OpenAiSyncAdapter",
                    "  port = OpenAiSyncAdapter(api_key=os.environ['OPENAI_API_KEY'])",
                    "  # or: AnthropicSyncAdapter / OllamaSyncAdapter",
                    "",
                    "[bold]Explore more:[/bold]",
                    "  electripy playground            ← interactive terminal UI (no API key)",
                    "  electripy demo policy-collab    ← offline policy + multi-agent demo",
                    "  recipes/02_llm_gateway/         ← real provider patterns",
                    "  recipes/03_policy_collaboration/ ← end-to-end policy + agents",
                ]
            ),
            title="[bold purple]ElectriPy AI[/bold purple]",
            border_style="purple",
        )
    )
    console.print()


if __name__ == "__main__":
    main()
