---
name: llm-integration-review
description: Review changes that integrate LLMs or AI agents — prompts, tool calling,
  agent loops, RAG, MCP servers, and model loading — for prompt-injection, output-handling,
  and excessive-agency defects, aligned to the OWASP Top 10 for LLM Applications 2026.
---

# LLM Integration Review

Review the **pending changes on the current branch** that integrate LLMs or AI
agents — prompts, tool calling, agent loops, RAG and vector stores, MCP servers
and clients, model loading — for security defects, classified against the
[OWASP Top 10 for LLM Applications 2026](https://genai.owasp.org/resource/owasp-genai-llm-top-10-2026/)
([source](https://github.com/GenAI-Security-Project/GenAI-LLM-Top10/tree/main/2026/final)),
with patterns from the MCP
[Security Best Practices](https://modelcontextprotocol.io/docs/2026-07-28/tutorials/security/security_best_practices),
the MCP [tools specification](https://modelcontextprotocol.io/specification/2026-07-28/server/tools),
and Hugging Face's [custom models](https://huggingface.co/docs/transformers/models#custom-models)
guidance. Pair with `security-review` for general application security and
`dependency-review` for the packages an integration pulls in.

The model is not a trust boundary: anything in its context — user messages,
retrieved documents, tool and MCP results — can steer it, and no prompt wording
reliably prevents that. Judge each integration by **what the model's output can
reach**, and check that deterministic code, not the prompt, gates each sink. An
agent that ingests untrusted content, sees sensitive data, *and* can act
externally is high-risk by construction (the "Rule of Two" LLM01:2026 cites).

## Scope

1. Determine the diff: `git diff <base>...HEAD` (default base: `main`/`master`),
   plus any uncommitted or untracked changes. If you are already on the base
   branch, review the uncommitted changes instead.
2. Look for model SDK calls, prompts, tool schemas and handlers, agent loops,
   vector stores, MCP code and config, and model loading (`from_pretrained`,
   `torch.load`, `pickle`).
3. Read the whole flow around each hunk — an allow-list, confirmation step,
   schema check, or scoped credential may sit outside the diff.
4. An injection that reaches an unguarded sink is one finding, classified at the
   sink; report LLM01 alone only when the fix belongs at the input (mixed
   instruction channel, tainted memory).
5. If the diff touches no LLM integration, report `no LLM-integration changes`
   and stop.

## What to look for

### LLM01:2026 Prompt Injection (and LLM05:2026 Data and Model Poisoning)

- Untrusted content — retrieved documents, tickets, emails, web pages, files,
  tool or MCP results — interpolated into the system prompt or instructions
  instead of passed as separate, labeled data.
- Guardrails that exist only as prompt wording — report what the model can
  still reach.
- Model output or untrusted content written to persistent memory or a RAG corpus
  unvalidated (it taints later sessions); unvetted external data fed into
  fine-tuning or a shared index is LLM05.
- Invisible Unicode (tag-block, variation-selector, zero-width) not stripped at
  ingest and render.

### LLM10:2026 Improper Output Handling

Treat model output as untrusted user input:

- Output reaching a shell, `exec`/`eval`, or a code runner; SQL built from it
  without parameterization; file paths; server-fetched URLs (SSRF); HTML,
  Markdown, or email templates rendered unescaped (XSS).
- UIs auto-rendering Markdown images or link previews from output (exfiltration
  through the URL); control characters written to terminals or logs.
- Structured output acted on without strict schema validation in code;
  generated code run or deployed without review.

### LLM03:2026 Excessive Agency (and LLM07:2026 Misinformation)

- Open-ended tools (run a command, fetch any URL, raw SQL) where a narrow one
  would do; tools the feature doesn't need; arguments not validated against a
  strict schema.
- Tool credentials broader than the task — read-write where read suffices, a
  service-wide identity instead of the requesting user's minimal scopes.
- No human approval before high-impact, irreversible, or external actions
  (send, delete, pay, post); the MCP tools spec says a human should be able to
  deny tool invocations.
- Authorization left to the model or system prompt rather than enforced in code
  at the tool or downstream system.
- Model-asserted state ("customer verified") trusted as an action's
  precondition without checking it (LLM07).

### LLM02:2026 Sensitive Information Disclosure and LLM08:2026 Hidden Context Exposure

- Credentials in system prompts, tool descriptions, or other hidden context —
  assume all context is extractable — or authorization rules enforced only there
  (LLM08).
- More data than the task needs sent to the model provider (LLM02).
- Prompts, completions, retrieved chunks, reasoning traces, or tool arguments
  logged or sent to observability unscrubbed (LLM02).

### LLM09:2026 Vector and Embedding Weaknesses

- Retrieval not scoped to the caller: filter by tenant or ACL inside the index
  query, from server-side identity — not a client-supplied scope or a
  post-retrieval filter.
- Mixed-trust content sharing an index; raw similarity scores returned to
  clients; embeddings treated as non-sensitive (they can be inverted).

### MCP servers, clients, and tool configuration

Classify these by what they enable — usually LLM03 or LLM04:

- Unpinned or unvetted MCP servers; tool descriptions and annotations from
  untrusted servers treated as trusted — they can carry hidden instructions
  (tool poisoning, LLM04).
- Local servers launched from config that run unvetted code, are added without
  showing the exact command for consent, or run unsandboxed (LLM04); local HTTP
  servers without an authorization token — prefer `stdio` (LLM03).
- **Token passthrough** — accepting tokens not issued to the server or
  forwarding the client's token downstream (MCP servers MUST NOT); proxies with a
  static upstream client ID skipping per-client consent (confused deputy);
  wildcard scopes (`*`, `full-access`); state handles accepted as authentication
  (LLM03).

### LLM04:2026 Supply Chain

- Models, adapters, or datasets resolved by mutable reference (`latest`, a bare
  `author/name` that can be re-registered) instead of a pinned revision or
  digest.
- `trust_remote_code=True` without a pinned commit `revision` — it runs the
  repository's code.
- Pickle-based model files (`pickle.load`, `torch.load` of untrusted
  checkpoints) run code on load: use a non-pickle format such as safetensors;
  `weights_only=True` is defense-in-depth only (bypassed by CVE-2025-32434).

### LLM06:2026 Unbounded Consumption

- No output cap (`max_tokens`/`max_completion_tokens`), input-size limit, or
  per-user rate, token, or spending limit on a path that calls the model.
- Agent loops without step, recursion-depth, time, or per-run cost limits;
  model or tool calls without a timeout.

## Output

Report each finding as a single list item:

- **[severity] OWASP LLM category** — `file:line`
  **Issue:** the defect and how untrusted content exploits it.
  **Fix:** the concrete change that resolves it.

`severity` reflects who controls the content and what the output reaches:
**critical** — content an outside attacker controls (a customer message, a
retrieved page, a tool or MCP result) reaches code execution, SQL, or an
irreversible or external action with no deterministic gate; **high** — the
same behind a common precondition (an authenticated user, a semi-trusted
source), cross-tenant retrieval, credentials or authorization in hidden
context, a side-effecting tool without approval, token passthrough, unpinned
`trust_remote_code` or pickle loading; **medium** — limited impact: missing
token, step, or cost limits, prompts or PII logged to broad-access sinks;
**low** — hardening (invisible-character stripping, returned similarity
scores). The classifier is the 2026 entry from the headings above, e.g.
`LLM10:2026 Improper Output Handling` — the 2025 edition numbered them
differently. Order findings by severity, highest first, and keep one issue per
finding. For example:

- **[high] LLM09:2026 Vector and Embedding Weaknesses** — `app/rag.py:31`
  **Issue:** `index.query(vector=embedding, top_k=8)` searches every tenant's
  chunks, so any signed-in user's question can pull another tenant's contract
  text into the prompt and the answer.
  **Fix:** filter inside the query on the session's tenant
  (`filter={"tenant_id": session.tenant_id}`) or use a per-tenant namespace.

Verify before reporting: trace each candidate from an untrusted source to the
sink, confirm nothing outside the diff stops it, quote the offending line in the
Issue, and drop anything without a concrete path. Prefer the few findings that
matter — if more than ~10 survive, report the ones worth a human's time and
summarize the rest in a line.

Open the report with one line stating what was reviewed and the outcome, e.g.
`Reviewed main..HEAD (3 files): 2 findings, worst critical.` If the
integration is sound, say so explicitly rather than manufacturing findings.
