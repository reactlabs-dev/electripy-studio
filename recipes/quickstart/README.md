# Quickstart — 5-Minute Production Runtime

Five production layers. One install. Zero rebuilding.

## Run it

```bash
pip install electripy-ai
python quickstart.py
```

No API key. No network call. No mocks. It runs completely offline.

## What you'll see

```
L01 Governance  · Policy Gateway     2 rules active
L03 Reliability · Circuit Breaker    CLOSED
L02 Observability · Structured Tracing
L04 Model Runtime · LLM Gateway + Policy Hooks
Cost Ledger    · Token Accumulation

Prompt  (raw):   Escalate the P0 incident to admin@acme.com and cc devops@acme.com immediately.
Response        : Acknowledged: Escalate the P0 incident to [REDACTED] and cc [REDACTED] immediately.

L01 Governance     ✓ SANITIZED    emails → [REDACTED] before model saw them
L02 Observability  ✓ TRACED       1 span · 1.4ms
L03 Reliability    ✓ CLOSED       0/3 failures · healthy
L04 Model Runtime  ✓ RESPONDED    20 tokens · hooks wired pre+post
Cost Ledger        ✓ RECORDED     20 tokens · $0.000003
```

The emails never reached the model. They were redacted by the policy gateway at `PREFLIGHT` — before
the LLM call was made. The response confirms the redaction in real time.

## Use a real model

Replace `FakeProvider` in `quickstart.py` with any provider adapter:

```python
# OpenAI
from electripy.ai.llm_gateway import OpenAiSyncAdapter
port = OpenAiSyncAdapter(api_key=os.environ["OPENAI_API_KEY"])

# Anthropic
from electripy.ai.llm_gateway import AnthropicSyncAdapter
port = AnthropicSyncAdapter(api_key=os.environ["ANTHROPIC_API_KEY"])

# Ollama (self-hosted, free)
from electripy.ai.llm_gateway import OllamaSyncAdapter
port = OllamaSyncAdapter(base_url="http://localhost:11434")
```

Then pass it to the gateway client:

```python
client = LlmGatewaySyncClient(
    port=port,  # ← swap here
    settings=LlmGatewaySettings(
        request_hook=request_hook,
        response_hook=response_hook,
    ),
)
```

## The five layers

| Layer | LSAS | What it does in this demo |
|-------|------|--------------------------|
| Policy Gateway | L01 | Redacts emails PREFLIGHT, blocks secret keys POSTFLIGHT |
| Circuit Breaker | L03 | Trips open after 3 consecutive failures, auto-recovers at 30s |
| Observability | L02 | Records a structured LLM span with ContextVar propagation |
| LLM Gateway | L04 | Provider-agnostic call with request/response policy hooks |
| Cost Ledger | — | Thread-safe token accumulation, sliceable by model/feature/tenant |

## What to explore next

```bash
electripy playground            # interactive terminal UI — all layers, no API key
electripy demo policy-collab    # offline policy + multi-agent collaboration demo
```

Or browse the other recipes:

- [`02_llm_gateway/`](../02_llm_gateway/) — gateway patterns with real and fake providers
- [`03_policy_collaboration/`](../03_policy_collaboration/) — end-to-end policy + multi-agent
