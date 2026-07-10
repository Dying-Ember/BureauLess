# Runtime Harness Milestone 5 Task List

Status: completed. RM5-01 through RM5-06 are complete. This milestone follows the completed Runtime
Harness Milestone 4 replay/history delivery and the completed Workbench
Milestone 7 guided runtime surface.

This is the planned runtime/harness milestone for BureauLess. It adds
provider-side telemetry capture, usage attribution, and backtest-ready metrics
for the maintained OpenAI-compatible execution path without pretending the
harness can infer LLM billing data from filesystem or process evidence alone.

The project-level sequencing lives in
[`../roadmap/development_roadmap.md`](../roadmap/development_roadmap.md). The
execution-spine baseline comes from
[`runtime_harness_milestone_3_5_tasklist.md`](runtime_harness_milestone_3_5_tasklist.md)
and [`runtime_harness_milestone_4_tasklist.md`](runtime_harness_milestone_4_tasklist.md).
Existing runtime metrics and inspection surfaces may consume this milestone
later, but this milestone itself is backend/debug-first.

Milestone 5 is a telemetry-boundary milestone. It does not add generic
multi-provider accounting, universal agent wrappers, token guessing heuristics,
or canonical replay semantics based on inferred usage. The harness remains the
consumer and validator of metering evidence, not the original meter.

## Goals

1. Capture per-session model, provider, token, cost, and cache-related usage
   on the maintained OpenAI-compatible path even when agent-native telemetry is
   partial or absent.
2. Attribute that usage to the correct assignment/session/result boundary so
   later backtests and policy analysis can rely on runtime-owned evidence.
3. Keep unsupported telemetry explicit with confidence fields instead of
   inventing precise usage or cost numbers.

## Principles

- Prefer one provider-side telemetry boundary over per-agent special cases.
- Start with the maintained OpenAI-compatible path before expanding to other
  providers or adapters.
- Treat provider usage as evidence artifacts that the harness validates and
  merges into session/result metrics.
- Preserve `usage_confidence: none` when no trusted usage evidence exists.
- Keep ledger replay, gatekeeper, and acceptance semantics independent from
  telemetry availability.
- Make cache-related counters additive telemetry, not dispatch or acceptance
  gates.
- Land a backend/debuggable path before adding any workbench compatibility
  surface.

## Non-Goals

- No universal telemetry support for every registered agent in this milestone.
- No provider-agnostic proxy mesh or long-running gateway control plane.
- No retroactive token estimation from prompts, patches, or file diffs.
- No workbench milestone or frontend compatibility work in this milestone.
- No canonical replay or acceptance decisions based on token/cost thresholds
  beyond existing explicit policy hooks.

## Workstream 1: Provider Telemetry Boundary

Goal: create one authoritative usage evidence path for the maintained
OpenAI-compatible execution flow.

### [x] RM5-01: Usage Capture Artifact Contract

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: Runtime Harness Milestone 4 complete; existing session/result
  metrics contract
- Target files:
  - `docs/protocol/harness_protocol.md`
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/runtime/metrics.py`
- Work:
  - Define a provider-usage artifact shape for model, provider, input tokens,
    output tokens, total tokens, cost, cost source/confidence, cached input
    tokens, and any reasoning-output counters already exposed by the provider.
  - Record explicit provenance and assignment/session/result linkage so later
    backtests can consume the artifact without guessing attribution.
  - Keep missing or unsupported fields explicit instead of inventing values.
- Acceptance criteria:
  - One validated artifact shape exists for provider-side usage evidence.
  - Unsupported fields remain explicit and do not masquerade as zeros.
- Notes:
  - Added a `provider_usage_capture` artifact contract to the harness protocol
    docs and backed it with a validated backend dataclass/load/write helper in
    `runtime.sessions`.
  - The usage object is now closed to known accounting fields, derives
    `total_tokens` from input/output when both are present, and rejects unknown
    or inconsistent usage fields.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "provider_usage_capture or codex_session_extracts_usage_from_jsonl"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics or runtime_demo"`

### [x] RM5-02: OpenAI-Compatible Capture Hook

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: RM5-01
- Target files:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/agents/registry.py`
- Work:
  - Capture usage evidence on the maintained OpenAI-compatible execution path.
  - Bind captured usage to the active assignment/session boundary before
    packaging the session result.
  - Preserve current behavior for agents/providers that do not expose trusted
    usage evidence.
- Acceptance criteria:
  - Maintained OpenAI-compatible runs can produce trusted usage evidence
    without relying on agent-native token reporting.
  - Unsupported providers continue to work and remain explicit about missing
    telemetry.
- Notes:
  - Added a lightweight local OpenAI-compatible telemetry proxy on the
    maintained `codex-cli` path. The proxy forwards requests to the configured
    upstream base URL, captures trusted provider usage from response payloads,
    and keeps current behavior unchanged for runs that do not expose that
    evidence.
  - Session extraction now carries a validated `provider_usage_capture` payload
    when trusted provider usage is observed, and `package_session_result()`
    persists it as an immutable harness-created artifact under
    `artifacts/provider-usage/`.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "provider_usage_capture or openai_compatible_session_captures_provider_usage_artifact"`
    `python -m pytest tests/test_harness.py -q -k "package_session_result"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics or runtime_demo"`

## Workstream 2: Runtime Metrics Integration

Goal: merge trusted provider usage into the existing runtime metrics and result
surfaces without rewriting acceptance or replay logic.

### [x] RM5-03: Session And Result Metrics Merge

- Status: completed
- Priority: high
- Recommended model: gpt-5.4
- Risk: medium
- Dependencies: RM5-01, RM5-02
- Target files:
  - `src/bureauless/runtime/sessions.py`
  - `src/bureauless/protocol/results.py`
  - `src/bureauless/runtime/metrics.py`
- Work:
  - Merge trusted usage artifacts into `outcome_metrics`, preserving existing
    confidence/source fields.
  - Promote cached-input and reasoning-output counters into the shared runtime
    metrics summary when present.
  - Keep agent-native telemetry as additive evidence when both sources exist,
    with deterministic precedence rules.
- Acceptance criteria:
  - Result/session metrics expose provider-attributed usage where available.
  - Aggregate metrics summaries can include cache-related counters without
    breaking existing readers.
- Notes:
  - Provider usage capture now merges directly into session `outcome_metrics`
    on the maintained OpenAI-compatible path, with provider-attributed fields
    taking precedence over agent-native token usage when both are present.
  - `package_session_result()` re-applies the same merge as a compatibility
    backstop for session records loaded from disk, then persists the immutable
    provider-usage artifact alongside the packaged result.
  - Runtime metrics summaries now expose `cached_input_tokens` and
    `reasoning_output_tokens` per entry and as grouped totals.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "provider_usage_capture or openai_compatible_session_captures_provider_usage_artifact or package_session_result_merges_provider_usage_capture_into_result_metrics or metrics_summarize_includes_cache_related_provider_usage_fields or metrics_summarize_includes_observed_budget_snapshot"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics or runtime_demo"`

### [x] RM5-04: CLI And API Debug Inspection Surface

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: RM5-03
- Target files:
  - `src/bureauless/api/server.py`
  - `src/bureauless/cli/main.py`
- Work:
  - Expose the merged usage evidence through existing runtime inspection APIs
    and summaries.
  - Show when a run is provider-attributed versus agent-reported versus
    unavailable.
  - Keep the surface inspection-only and backend-focused; no new policy writes
    depend on it.
- Acceptance criteria:
  - Operators can inspect per-step model/provider/token/cost/cache telemetry on
    the maintained OpenAI-compatible path through CLI or API debugging
    surfaces.
  - Missing usage remains visible as missing, not as synthetic zeroes.
- Notes:
  - Reused the existing `metrics summarize` CLI command and `/api/metrics`
    inspection endpoint instead of adding a new telemetry surface.
  - Metrics entries now expose explicit `usage_source`
    (`provider_attributed`, `agent_reported`, or `unavailable`) alongside
    cache-related counters so operators can distinguish trusted provider
    attribution from agent-native reporting and true absence.
  - Existing runtime-demo and manifest inspection flows inherit the same
    metrics payload without additional API wrappers.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "metrics_summarize or cli_metrics_summarize or provider_usage_capture or package_session_result_merges_provider_usage_capture_into_result_metrics or openai_compatible_session_captures_provider_usage_artifact"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics_api_endpoint or runtime_demo_api_creates_reviewable_workspace"`

## Workstream 3: Backtest Readiness And Verification

Goal: make the new telemetry path trustworthy enough for later policy analysis
and replay-adjacent backtests.

### [x] RM5-05: Historical Attribution And Backtest Fixtures

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: medium
- Dependencies: RM5-03
- Target files:
  - `src/bureauless/runtime/metrics.py`
  - `tests/test_harness.py`
  - `tests/test_server.py`
- Work:
  - Add fixtures that prove usage attribution survives normal session/result
    packaging and later metrics summarization.
  - Verify that backtests can distinguish trusted provider telemetry, native
    agent telemetry, and missing evidence.
  - Keep replay correctness independent from telemetry presence.
- Acceptance criteria:
  - Maintained tests prove per-step usage attribution and missing-evidence
    handling.
  - Backtest inputs can be built from runtime-owned metrics artifacts without
    log scraping.
- Notes:
  - Added fixtures that prove provider-attributed usage survives the normal
    `session -> packaged result -> imported ledger -> summarize_metrics`
    path without scraping native logs.
  - Added side-by-side session fixtures for `provider_attributed`,
    `agent_reported`, and `unavailable` usage so backtest readers can
    distinguish trusted provider telemetry from agent-native reporting and
    true absence.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "metrics_summarize or cli_metrics_summarize or preserves_provider_attribution_after_result_import or distinguishes_provider_agent_and_missing_usage_sources"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics_api_endpoint or runtime_demo_api_creates_reviewable_workspace"`

### [x] RM5-06: Documentation And Boundary Closure

- Status: completed
- Priority: medium
- Recommended model: gpt-5.4-mini
- Risk: low
- Dependencies: RM5-01 through RM5-05
- Target files:
  - `docs/README.md`
  - `docs/roadmap/development_roadmap.md`
  - `docs/tasks/runtime_harness_tasklist.md`
- Work:
  - Update roadmap, protocol, and milestone indexes to describe the selected
    telemetry boundary and the still-open non-goals.
  - Record what remains unsupported after the OpenAI-compatible path is landed.
- Acceptance criteria:
  - The docs state clearly that provider-side metering is the source of truth
    for this milestone and that generic multi-agent telemetry remains out of
    scope.
- Notes:
  - Runtime Harness M5 is now complete as a backend/debug-first telemetry
    milestone.
  - The maintained `codex-cli + openai-compatible` path now has one selected
    telemetry boundary: trusted provider-side usage captured by the local
    proxy, merged into session/result metrics, and exposed through the
    existing metrics inspection surfaces.
  - Still out of scope after M5: generic multi-agent telemetry, provider
    meshes, token guessing heuristics, replay semantics derived from billing
    data, and any workbench-specific telemetry UI beyond the existing metrics
    readers.
  - Verification:
    `python -m pytest tests/test_harness.py -q -k "metrics_summarize or cli_metrics_summarize or preserves_provider_attribution_after_result_import or distinguishes_provider_agent_and_missing_usage_sources"`
    `uv run python -m pytest tests/test_server.py -q -k "metrics_api_endpoint or runtime_demo_api_creates_reviewable_workspace"`
