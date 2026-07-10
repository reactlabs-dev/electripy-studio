"""Async Quickstart — all five LSAS layers, fully async, runs offline.

Run:
    pip install electripy-ai
    python recipes/async_quickstart/async_quickstart.py
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass

from electripy.ai.cost_ledger import CostLedger
from electripy.ai.llm_gateway import (
    AsyncLlmPort,
    LlmGatewayAsyncClient,
    LlmGatewaySettings,
    LlmMessage,
    LlmRequest,
    LlmResponse,
)
from electripy.ai.policy_gateway import (
    PolicyAction,
    PolicyGateway,
    PolicyRule,
    PolicySeverity,
    PolicyStage,
    build_llm_policy_hooks,
)
from electripy.concurrency import CircuitBreaker, CircuitOpenError
from electripy.observability.observe import InMemoryTracer, ObservabilityService

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

PROMPT = "Deploy the hotfix and notify ops@acme.com and cto@acme.com immediately."


@dataclass
class FakeAsyncProvider(AsyncLlmPort):
    """Offline async provider — swap for OpenAiAsyncAdapter in production."""

    async def complete(self, request: LlmRequest, *, timeout: float | None = None) -> LlmResponse:
        await asyncio.sleep(0.01)
        last = request.messages[-1].content
        return LlmResponse(text=f"Acknowledged: {last}", model=request.model, usage_total_tokens=22)


@dataclass
class FlakyAsyncProvider(AsyncLlmPort):
    """Always raises — used to trip the circuit breaker."""

    async def complete(self, request: LlmRequest, *, timeout: float | None = None) -> LlmResponse:
        await asyncio.sleep(0.005)
        raise RuntimeError("upstream timeout")


async def breaker_acall(breaker: CircuitBreaker, coro_fn):
    """Async-compatible circuit breaker: wraps state machine around an awaitable."""
    breaker._before_call()  # noqa: SLF001
    try:
        result = await coro_fn()
        breaker._on_success()  # noqa: SLF001
        return result
    except Exception:
        breaker._on_failure()  # noqa: SLF001
        raise


async def main() -> None:
    # L01 Governance
    gateway = PolicyGateway(
        rules=[
            PolicyRule(
                rule_id="pii-email",
                code="PII_EMAIL",
                description="Redact email addresses before the model sees them",
                stage=PolicyStage.PREFLIGHT,
                pattern=EMAIL_RE.pattern,
                action=PolicyAction.SANITIZE,
                severity=PolicySeverity.MEDIUM,
            ),
        ]
    )

    # L03 Reliability
    breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=30.0)

    # L02 Observability
    tracer = InMemoryTracer()
    obs = ObservabilityService(tracer=tracer)

    # L04 Model Runtime (async)
    request_hook, response_hook = build_llm_policy_hooks(gateway)
    client = LlmGatewayAsyncClient(
        port=FakeAsyncProvider(),
        settings=LlmGatewaySettings(request_hook=request_hook, response_hook=response_hook),
    )

    # L05 Cost Ledger
    ledger = CostLedger(cost_per_1k_tokens=0.00015)

    # --- Happy path ---
    print(f"\nPrompt  (raw):   {PROMPT}")

    t0 = time.monotonic()
    async with obs.start_llm_span(provider="openai", model="gpt-4o-mini") as span:
        response = await breaker_acall(
            breaker,
            lambda: client.complete(
                LlmRequest(
                    model="gpt-4o-mini",
                    messages=[LlmMessage.user(PROMPT)],
                )
            ),
        )
        span.set_attribute("gen_ai.usage.total_tokens", response.usage_total_tokens)

    elapsed_ms = (time.monotonic() - t0) * 1000
    ledger.record(
        tokens=response.usage_total_tokens, labels={"model": "gpt-4o-mini", "feature": "ops"}
    )

    print(f"Response        : {response.text}")
    print()
    print("L01 Governance     \u2713 SANITIZED    emails \u2192 [REDACTED] before model saw them")
    print(
        f"L02 Observability  \u2713 TRACED       {len(tracer.finished_spans)} span \u00b7 {elapsed_ms:.1f}ms"
    )
    print(f"L03 Reliability    \u2713 CLOSED       {breaker.failure_count}/3 failures")
    print(
        f"L04 Model Runtime  \u2713 RESPONDED    {response.usage_total_tokens} tokens (async \u26a1)"
    )
    print(
        f"L05 Cost Ledger    \u2713 RECORDED     ${ledger.total().estimated_cost:.6f} \u00b7 1 call"
    )

    # --- Circuit breaker failure demo ---
    print("\n" + "\u2500" * 60)
    print("Circuit Breaker \u2014 failure mode")
    print("\u2500" * 60)

    flaky = LlmGatewayAsyncClient(port=FlakyAsyncProvider(), settings=LlmGatewaySettings())
    fail_breaker = CircuitBreaker(failure_threshold=3, recovery_timeout=60.0)

    for attempt in range(1, 5):
        try:
            await breaker_acall(
                fail_breaker,
                lambda: flaky.complete(
                    LlmRequest(
                        model="gpt-4o-mini",
                        messages=[LlmMessage.user("ping")],
                    )
                ),
            )
        except CircuitOpenError:
            print(
                f"  Attempt {attempt}: \u26a1 CIRCUIT OPEN \u2014 fast-fail, upstream never called"
            )
        except RuntimeError as exc:
            print(
                f"  Attempt {attempt}: \u2717 upstream error ({exc}) [circuit={fail_breaker.state.name}]"
            )

    print()
    print(
        f"L03 Reliability    \u2713 OPEN after {fail_breaker.failure_count} failures \u2014 downstream protected"
    )


if __name__ == "__main__":
    asyncio.run(main())
