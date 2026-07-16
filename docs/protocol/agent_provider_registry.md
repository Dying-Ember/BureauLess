# Agent, Provider, and Endpoint Registry

This document is the compatibility contract for launching a coding agent from
BureauLess. It deliberately separates concepts that are often conflated:

- an **agent** is the executable that plans and edits a workspace;
- a **provider** is the configured delivery route for a model request;
- an **endpoint family** is the HTTP request/response contract that route
  accepts;
- a **wire API** is the particular operation within that contract;
- a **model identifier** selects a model (or a gateway alias) within that
  route;
- an **adapter** turns one agent CLI's invocation and output into a
  BureauLess `SessionRecord`.

There is therefore no useful single, universal "provider type". The registry
classifies every integration along the axes below. The tables are exhaustive
relative to the current registry schema and execution contract, not exhaustive
relative to the agent ecosystem.

The registry stores IDs, capability declarations, and names of environment
variables only. It never stores a credential and it never edits an agent's
local configuration file.

Use `bureauless audit archive <session.yaml> --workspace <path>` to preserve a
versioned session snapshot, rendered report, and manifest containing SHA-256
digests for both artifacts under `.bureauless/audits/<day>/<session-id>/`. The
command refuses to overwrite an existing snapshot. Use `bureauless audit
verify <manifest.yaml>` to verify the stored artifacts against that manifest;
this is evidence preservation, not a signed or tamper-proof storage system.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| **Implemented** | A session adapter exists for the stated agent/route pair. It does not itself claim live-endpoint verification. |
| **Registered only** | The runtime is known and can be inspected, but cannot be dispatched by BureauLess. |
| **Unsupported** | The shape is intentionally rejected because no adapter and evidence contract exist. |
| **Out of scope** | Plausible future shape, but it is not a registered capability or product promise. |

`bureauless agent route <agent-id>` reports whether an agent is
`dispatchable` or `registration_only`. Dispatchability is not readiness:
always run `bureauless agent doctor <agent-id>` and
`bureauless agent readiness <agent-id> --workdir <path>` before a live run.
Those checks cover the installed binary and isolated workspace; they do not
prove that a remote endpoint accepts a selected model or credential.

### Evidence axes

Registry state and test evidence are separate fields. A route reports:

| Field | Meaning | Values used today |
| --- | --- | --- |
| `runtime_contract_support` | What the upstream CLI/runtime can express. | `supported`, `observed`, `unknown` |
| `adapter_support` | What this BureauLess release can launch and normalize. | `implemented`, `not_implemented` |
| `tested_route_support` | Latest recorded result for a specifically named endpoint route, not every route of that family. | `verified`, `unavailable`, `not_tested`, `not_applicable` |
| `verification_levels` | Strength of the evidence behind the declaration. | `static_contract`, `fixture_tested`, `live_text_probe`, `live_workspace_mutation`, `telemetry_verified` |
| `audit_ref` / `verified_at` | Dated evidence record supporting a tested-route declaration. | repository-relative audit path and ISO date, or absent |
| `verified_runtime_version` | CLI version used for that recorded route result. | exact recorded version, or absent |

`bureauless agent route <agent> --provider <provider>` renders those fields.
For example, Pi's observed Responses-shaped runtime support is not reported as
an adapter capability: its adapter is `not_implemented` and the tested route
was `unavailable`. A successful session separately records structured
`session_route_support` dimensions for launch, request completion, workspace
mutation, telemetry, model identity, cost attribution, permission boundary,
and native events. No scalar `verified` value claims that every dimension or
every endpoint in the family was verified.

`bureauless agent matrix --evidence` renders the complete machine-readable
Agent×Provider evidence matrix. Without `--evidence`, `agent matrix` remains
the installed-binary control-surface/doctor view and must not be interpreted
as endpoint compatibility evidence.

Every `audit run` also emits an append-only `route-observation.yaml` beside
the session. It records the runtime version, stable route contract, opaque
route-instance label, terminal outcome, evidence provenance, and hashes of the
session and report. `audit observations --workspace <path>` rebuilds each
observation from those artifacts and rejects drift. To inspect stable registry
claims beside accumulated observations:

```bash
bureauless agent matrix --evidence \
  --observations .bureauless/runs
```

Use `--route-instance-id` on `audit run` to correlate repeated tests of the
same endpoint instance. It is an operator-chosen 1–128 character opaque label
using letters, digits, `.`, `_`, or `-`; URLs, paths, whitespace, and common
credential shapes are rejected. Syntax validation is not general secret
detection, so the operator remains responsible for using a non-sensitive
label rather than a provider name, account identifier, or credential.

## 1. Agent runtime types

An agent runtime is classified by how BureauLess obtains the work result.

| Runtime type | Definition | Registry state | Notes |
| --- | --- | --- | --- |
| Local native CLI | A local executable receives a prompt, operates in a workspace, and terminates as a child process. | **Implemented** for `codex-cli`, `claude-code`, `gemini`, `opencode`, and `pi`. | Current product boundary. Timeout and cancellation are process control. |
| Direct HTTP agent client | BureauLess itself sends a task to a provider's agent API. | **Out of scope**. | This would make BureauLess an agent client, not a CLI adapter, and requires a distinct result/evidence contract. |
| Local wrapper or gateway CLI | A local command forwards work to another agent or provider. | **Unsupported**. | Register it only after its flags, output, credential isolation, and permission semantics are independently verified. |
| Remote job API | A task is submitted, then polled or receives callbacks. | **Out of scope**. | Requires job identity, retry/idempotency, callback authentication, and remote cancellation evidence. |
| Interactive-only desktop/UI agent | Work can only be driven through a human session. | **Unsupported**. | It may be audited manually, but is not dispatchable. |
| Shell fixture | A deterministic command used to test the runtime harness. | **Implemented internally** as `shell-dummy`. | Not an external-agent registration target. |
| Synthetic fixture | A fabricated result used to test protocol flows. | **Implemented internally** as `fake`. | Not an external-agent registration target. |

### Registered local CLIs

| Agent ID | Executable | Adapter | Launch/output contract | Permission boundary | State |
| --- | --- | --- | --- | --- | --- |
| `codex-cli` | `codex` | `codex_exec_v1` | `codex exec` with JSONL native events | Codex native sandbox | **Implemented** |
| `claude-code` | `claude` | `claude_stream_json_v1` | `claude --print --output-format stream-json --verbose` | Claude permission mode | **Implemented** |
| `gemini` | `gemini` | `gemini_stream_json_v1` | `gemini --prompt --output-format stream-json` | Gemini approval mode | **Implemented** |
| `opencode` | `opencode` | `opencode_run_json_v1` | `opencode run --format json` | temporary OpenCode permission policy | **Implemented** |
| `pi` | `pi` | `pi_json_v1` | `pi --print --mode json` | Pi tool allow/deny list | **Implemented** |

The adapter, not the agent name, is the execution boundary. Two CLIs that can
call the same endpoint still need separate adapters because their command-line
flags, workspace controls, output shape, session-termination behavior, and reported
usage differ.

The adapter contracts are separate in the registry, but their current Python
runners/parsers remain co-located in `runtime/sessions.py`. Splitting that file
is maintenance work, not a missing audit capability; it should happen when
independent adapter ownership or change frequency justifies the churn.

## 2. Provider route and endpoint-family types

A `target_provider` is a BureauLess route category. It is not a claim about
the company that bills for the request. For example, a gateway, a cloud-hosted
deployment, and a local server can all expose the same endpoint family but
have different model IDs and credential policies.

| Provider ID | Route kind | Endpoint family | Current wire API | Base URL | Credential delivery | Eligible agent | State |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `openai` | `agent_native` | OpenAI | owned by Codex CLI | optional override | environment variable named by the binding, default `OPENAI_API_KEY` | `codex-cli` | **Implemented** |
| `openai-compatible` | `custom_http` | OpenAI | **Responses** only | required | caller-selected environment-variable name | `codex-cli` | **Implemented** |
| `openai-chat-compatible` | `custom_http` | OpenAI | **Chat Completions** only | required | caller-selected environment-variable name | `opencode`, `pi` | **Implemented** |
| `anthropic-compatible` | `custom_http` | Anthropic | **Messages** | required | caller-selected environment-variable name, default `ANTHROPIC_API_KEY` | `claude-code`, `pi` | **Implemented** |
| `gemini-compatible` | `custom_http` | Gemini | **GenerateContent** | required | child environment `GEMINI_API_KEY` | `gemini` | **Implemented** |

`anthropic-compatible` means “a route an eligible adapter can call through the
Anthropic Messages contract.” It does not mean that the upstream must be the
Anthropic service, nor does it imply that a compatible route accepts OpenAI
Chat Completions or Responses requests.

### Complete endpoint-family decision table

| Endpoint family | Typical operation paths beneath a `/v1` base | Compatible with current adapter? | Reason |
| --- | --- | --- | --- |
| OpenAI Responses | `/responses`, usually `/models` | `codex-cli` through `openai-compatible` | **Implemented.** The current custom Codex route explicitly selects `responses`. |
| OpenAI Chat Completions | `/chat/completions`, usually `/models` | `opencode` and `pi` through `openai-chat-compatible` | **Implemented.** It remains incompatible with the Codex Responses adapter. |
| OpenAI legacy Completions | `/completions` | No | **Unsupported.** Different request and tool/result semantics. |
| OpenAI embeddings, images, audio, files, batches, fine-tuning, assistants | endpoint-specific paths | No | **Out of scope.** These are not coding-agent execution routes. |
| Anthropic Messages | `/messages`, usually `/models` | `claude-code` and `pi` through `anthropic-compatible` | **Implemented.** Each adapter supplies child-only route and credential state using its own native provider shape. |
| Anthropic Messages streaming | `/messages` with server-sent events | No additional BureauLess transport mode | **Not separately integrated.** The CLI owns provider streaming; the adapter consumes Claude Code's JSONL lifecycle stream, not the raw provider SSE. |
| Anthropic legacy Complete | `/complete` | No | **Unsupported.** It is a different contract from Messages. |
| Gemini GenerateContent | `/v1beta/models/{model}:generateContent` | `gemini` through `gemini-compatible` | **Implemented.** `gemini_stream_json_v1` owns child configuration, native JSONL, workspace diff, and terminal status. |
| Cloud-provider model facades | vendor- or deployment-specific paths | No | **Out of scope.** A facade becomes eligible only if it can be verified as an implemented wire contract without modifying local agent configuration. |
| Local/self-hosted endpoint | implementation-specific host, but an implemented compatible path | Conditionally yes | **Implemented only by contract**, not by vendor name: it must implement the selected wire API. |
| Arbitrary HTTP, RPC, WebSocket, or browser automation endpoint | arbitrary | No | **Out of scope.** No request, cancellation, or audit contract exists. |

### “OpenAI-compatible” is not “Responses API”

They name different layers:

| Term | What it says | What it does *not* say |
| --- | --- | --- |
| OpenAI-compatible endpoint | The endpoint claims compatibility with some OpenAI-shaped APIs. | Which operations, streaming details, tool schema, usage fields, or authentication variants it supports. |
| Responses API | The request/response operation expected at `/responses`. | That the endpoint also accepts Chat Completions, or that every OpenAI-compatible gateway implements it. |
| Chat Completions API | The distinct request/response operation expected at `/chat/completions`. | That it is interchangeable with Responses. It is not in the current Codex binding. |
| Anthropic Messages API | The distinct request/response operation expected at `/messages`. | That it is OpenAI-compatible. It is the current Claude Code binding. |
| Gemini GenerateContent API | The distinct request/response operation expected at `models/{model}:generateContent`. | That it is OpenAI- or Anthropic-compatible. It is registered for Gemini CLI only. |

The registry therefore records both `target_provider=openai-compatible` and
`provider_wire_api=responses`. The latter is a concrete compatibility
requirement, not redundant decoration. `anthropic-compatible` defaults to the
one supported wire contract, Messages; the binding records `messages` but
exposes no separate CLI wire-API selector.

## 3. Exact URL boundary

`--provider-base-url` is a **base**, not an operation URL. Its exact level is
adapter-specific: give a `/v1` base to the OpenAI-compatible adapters, while
Claude Code and Pi Messages bindings take the gateway root and append `/v1`
themselves.

| Binding | Value passed as `--provider-base-url` | Endpoint that must work | Discovery endpoint, if offered |
| --- | --- | --- | --- |
| `codex-cli` + `openai-compatible` + `responses` | `https://gateway.example/v1` | `POST /v1/responses` | `GET /v1/models` |
| `claude-code` + `anthropic-compatible` | `https://gateway.example` | `POST /v1/messages` | `GET /v1/models` |
| `pi` + `anthropic-compatible` | `https://gateway.example` | `POST /v1/messages` | endpoint-specific |
| `opencode` or `pi` + `openai-chat-compatible` | `https://gateway.example/v1` | `POST /v1/chat/completions` | `GET /v1/models` |
| `gemini` + `gemini-compatible` | `https://gateway.example/gemini` | `POST /gemini/v1beta/models/{model}:generateContent` | `GET /gemini/v1beta/models` |

Do not pass `https://gateway.example/v1/messages` as the base URL unless the
particular CLI explicitly documents that nonstandard convention. Doing so
normally produces a doubled path such as `/v1/messages/messages`.

Model discovery is endpoint-specific. A `GET /v1/models` response can confirm
which literal IDs an endpoint advertises, but BureauLess does not currently
maintain a persistent global model catalogue or infer that a model available
at one route is available at another.

## 4. Model-addressing types

| Model-addressing type | Meaning | Current handling |
| --- | --- | --- |
| Literal model ID | The exact ID accepted by the route. | **Implemented.** Pass it via `--target-model`. |
| Gateway alias | A route-defined alias mapped by that route to a concrete model. | **Implemented as pass-through.** BureauLess records the requested alias; the endpoint decides whether it resolves. |
| Version-pinned model ID | A literal model ID containing a version/date/revision. | **Implemented as pass-through.** Recommended when reproducibility matters. |
| Provider default | No model is sent and the provider selects one. | **Unsupported.** Real adapters require `--target-model`; audit records must identify the intended model. |
| Deployment ID | A cloud deployment name standing in for a model ID. | **Out of scope.** It can be used only if the selected compatible endpoint treats it as a literal model field. |
| Region/project-qualified model reference | A routing reference requiring cloud SDK metadata. | **Out of scope.** No cloud-credential or project-selection adapter exists. |

`effective_model` remains a legacy compatibility field and currently carries
the requested model string. New session results also record
`model_identity.requested`, plus `cli_reported`, `provider_reported`, and
`independently_attested` only when that evidence exists. If a gateway silently
reroutes an alias, the requested string is not proof of the underlying model.

## 5. Credential-delivery types

Credentials are classified by *how they reach the child process*, not by their
issuer or pricing plan.

| Credential type | Current state | Handling |
| --- | --- | --- |
| Explicit API-key environment-variable name | **Implemented.** | The command receives `--provider-api-key-env NAME`; BureauLess reads `NAME` only to construct the child environment. |
| Provider-profile default environment-variable name | **Implemented.** | Used when a profile defines one and no override is supplied. |
| Native CLI login/OAuth/session configuration | **Not used by these bindings.** | The registry does not read, write, or mutate local agent auth/config files. |
| Cloud SDK credential chain, instance/role identity, workload identity | **Unsupported.** | No profile or audit semantics exist yet. |
| Credential helper, keychain, command substitution, secret manager | **Unsupported.** | The wrapper must not execute a secret-fetch command on its own. Export an environment variable outside BureauLess instead. |
| Credential supplied as a CLI argument, YAML field, report field, or ledger event | **Prohibited.** | It risks persistence in shell history and audit artifacts. |

For a Claude-compatible binding, BureauLess creates a child-process environment
with `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY`, copied from the environment
variable named by `--provider-api-key-env`. It removes an inherited
`ANTHROPIC_AUTH_TOKEN` and assigns a session-local `HOME`,
`XDG_CONFIG_HOME`, and `CLAUDE_CONFIG_DIR`; `--bare` prevents user/project
configuration from selecting a different route. The credential is not written
to the session specification, native logs, result proposal, report, or ledger.
The Codex binding likewise gives Codex only the child environment and its
ephemeral invocation configuration.

Before native output is parsed or persisted, the adapter replaces every exact
occurrence of the selected binding credential with `<redacted>`. This covers
accidental literal echoing in stdout, stderr, extraction warnings, and parsed
assistant text. It cannot detect transformed, encoded, or independently
retrieved secrets, so native logs remain sensitive audit artifacts.

If a credential has been pasted into chat, terminal history, or a committed
file, rotate it. Documentation and examples must show variable *names* only.

## 6. Invocation and configuration-isolation types

| Concern | `codex-cli` | `claude-code` | `gemini` | `opencode` | `pi` |
| --- | --- | --- | --- |
| Non-interactive entry | `exec` | `--print` | `--prompt` | declared `run` | `--print` |
| Model selection | `--model` | `--model` | `--model` | declared `--model` | `--model` |
| Provider selection | ephemeral Codex config overrides | child-only Messages base URL/API-key environment | child-only `GOOGLE_GEMINI_BASE_URL` / `GEMINI_API_KEY` | child-only `OPENCODE_CONFIG_CONTENT` for Chat Completions | temporary `PI_CODING_AGENT_DIR/models.json` for Messages or Chat Completions |
| Persistent local config mutation | never | never; session-local home/config | never; temporary `HOME` | never; temporary HOME/config directory | never; temporary agent/session directories |
| Config isolation signal | `--ignore-user-config` capability is doctor-checked | `--bare`, cleared inherited auth token, session-local `HOME` / Claude config | temporary `HOME`, `--skip-trust`; the clean HOME has no user extensions | `--pure`, temporary HOME/config, and disabled Claude Code loading | temporary agent/session directories; `--no-extensions --no-skills --no-context-files --offline` |
| Session persistence | `--ephemeral` capability is doctor-checked | `--no-session-persistence` | `--session-id`, `--resume`, `--session-file` | adapter uses a fresh local session | adapter uses `--no-session` |
| Working directory control | `--cd` plus isolated workspace | process working directory plus isolated workspace | process working directory plus isolated workspace | declared `--dir` | process working directory plus isolated workspace |
| Cancellation | process-group termination | process-group termination | process-group termination | declared process termination | process-group termination |

The table records the runtime's advertised controls and the current adapter's
chosen path. A successful `agent doctor` means the installed binary exposed
the expected flags; it does not mean every flag is used by every invocation.

Claude Code's selected API-key path is now verified as a clean, stateless
startup: `child_only_route_injection=verified`,
`clean_stateless_startup=verified`, and
`depends_on_existing_global_state=not_observed`. This is evidence for the
explicit `--bare` API-key binding only; it does not assert equivalent isolation
for native login, OAuth, or a user-managed Claude configuration.

## 7. Workspace and permission types

BureauLess isolates a run in a copy or Git worktree before launching an agent.
That isolation is distinct from an agent's own permission system.

| Permission / isolation type | Meaning | Current handling |
| --- | --- | --- |
| `read-only` sandbox mode | BureauLess requests no workspace writes. | Session option; its exact enforcement depends on the adapter/runtime. |
| `workspace-write` sandbox mode | Writes are confined to the isolated workspace. | Session default. Codex uses its native sandbox; Claude Code uses its permission mode. |
| `danger-full-access` sandbox mode | Broad local access is requested. | Session option; use only with explicit operator intent. |
| Codex native sandbox | Codex's sandbox implementation enforces the selected mode. | **Implemented** for `codex-cli`. |
| Claude permission mode | Claude Code's own permission policy governs actions. | **Implemented** for `claude-code` with `--permission-mode acceptEdits`; it is not asserted to be equivalent to Codex sandboxing. |
| Gemini approval mode | `plan`, `auto_edit`, or `yolo` determines Gemini CLI's tool approval behavior. | **Implemented** for `gemini`; BureauLess maps read-only, workspace-write, and danger-full-access respectively. |
| OpenCode permission policy | Child config permits only read/list/search and, when requested, edit; shell remains denied unless danger-full-access is selected. | **Implemented** for `opencode`. |
| Pi tool allow-list | Child command enables only read/list/search and, when requested, edit/write; shell is enabled only for danger-full-access. | **Implemented** for `pi`. |
| No isolated workspace | The agent acts directly in the source tree. | **Unsupported** for normal real-agent sessions. |

The audit record captures a before/after workspace baseline and changed-file
references. A clean diff is evidence about files, not proof that the external
agent made no network, shell, or other side effect. Permission claims must be
interpreted through the concrete agent adapter.

## 8. Output, telemetry, and audit-evidence types

Every real adapter normalizes native output into a `SessionRecord` with status,
start/finish time, exit result, stdout/stderr references, workspace delta, and
an optional structured result proposal. Native output remains evidence; a
normalized field is never a replacement for it.

This `SessionRecord` is the common observation contract, not an agent runtime.
The actual Codex, Claude Code, Gemini, OpenCode, or Pi process still plans,
invokes tools, and edits files. BureauLess stays outside that process and
records the same outer facts for every adapter: binding intent, process
terminal state, wall time, native evidence, isolated workspace delta, model
identity evidence, metric provenance, and comparison eligibility. Adapter-only
facts remain extraction evidence instead of being promoted into false
cross-agent equivalence.

### Decision, side-effect, and contribution evidence

`SessionRecord.audit_evidence` reserves three evidence lists:

```yaml
audit_evidence:
  decision_points:
    - evidence_available_at_time: [artifact-or-event-ref]
      action_selected: dispatch_agent:codex-cli
      alternatives_visible: [routing_mode:small_dag]
      candidate_set:
        - {action: dispatch_agent:codex-cli, disposition: selected, reason: bounded_run}
        - {action: routing_mode:small_dag, disposition: rejected, reason: no_dependencies}
      selection_basis: {budget_confidence: low, triggered_rules: [bounded_single_agent_audit]}
      later_outcome: {session_status: completed}
  side_effects:
    - type: workspace # workspace | process | network | credential | payment
      source: harness # harness | agent | provider
      verified: true  # true | false | unknown
  capability_contributions:
    - capability_id: edit
      invoked: true
      result_used: true # true | false | unknown
      measurable_delta: {changed_files: 1}
```

The harness automatically records only side effects it can support with its
own evidence: launched processes, observed workspace deltas, credential
delivery, and transparent-proxy network evidence. Reported monetary cost stays
telemetry; it is not payment evidence. A payment side effect requires
independent charge evidence, which current adapters do not provide.
The parallel `side_effect_coverage` map declares all five effect classes as
`full`, `partial`, `none`, or `not_applicable`, with a machine-readable `scope`
and `blind_spots` list. Current automatic observations are deliberately
`partial`: for example, provider-proxy traffic does not prove that direct Agent
egress or child-process traffic was absent. An empty side-effect list therefore
never implies that network, credential, or payment activity was absent.

Every canonical dispatch records one Harness-owned decision point with the
selected action, candidate set, rejection reasons, budget/risk basis, selection
scope, evidence references available at dispatch, and later session outcome.
The quickstart fixes Agent/model/route from operator input; it does not pretend
those were policy-selected alternatives. It also does not infer Agent-internal
decisions from final prose or claim that a tool caused an outcome.

`audit run --verify-command '<argv>'` adds Harness-owned independent
verification after the Agent exits. The command is parsed as argv without a
shell, runs against a temporary copy of the Agent's final workspace, excludes
VCS metadata, uses a temporary home, and receives no environment variables
whose names identify keys, tokens, secrets, passwords, or credentials. Its
command hash, exit code, stdout/stderr hashes, status, and timing are stored in
`verification.yaml`; the session contains only the evidence reference and
digest. Agent-reported verification remains a separate field.

For comparable benchmark trials, pass an opaque `--cohort-id`. Benchmark
identity v2 records separate task, delivered-context, and execution-contract
digests, the Harness-observed pre-run workspace state, and the independent
acceptance-contract digest (command, timeout, workspace mode, and environment
policy). The execution contract retains safe comparison
fields including Agent/adapter/runtime version, requested model and provider,
opaque route instance, wire API, sandbox/isolation/timeout/cleanup policy,
permission boundary, key environment-variable name, tool allow-list, and
assignment renderer version. It does not retain the base URL or credential
value. Without `--cohort-id`, BureauLess assigns a session-local
`uncontrolled-<session-id>` cohort that is ineligible for paired comparison.
Transport-only assignment and context-capsule IDs are removed before hashing
the delivered-context contract so repeated trials do not differ solely because
their envelope IDs are unique.

After producing a baseline and candidate with the same declared cohort, task,
delivered context, workspace baseline, and independent acceptance contract,
generate a bounded capability comparison with:

```bash
uv run bureauless audit contribution baseline/session.yaml candidate/session.yaml \
  --capability-id workspace-edit --invoked true
```

The v2 artifact reports controlled identity fields, execution `treatment_diff`,
known `uncontrolled_confounders`, Harness-comparable latency/file delta and
independent-verification outcomes. Token and monetary deltas remain conditional
on matching native provenance. Invocation and result-use are explicit operator
attestations, and the artifact always states `causal_claim: not_established`.

| Evidence type | `codex_exec_v1` | `claude_stream_json_v1` | `gemini` | `opencode` | `pi` |
| --- | --- | --- | --- |
| Native output contract | JSONL event stream | one JSON result object | JSONL event stream | JSONL event stream | JSONL event stream |
| Final status / exit code | captured | captured | captured | captured | captured |
| stdout and stderr | persisted as native logs | persisted as native logs | persisted as native logs | persisted as native logs | persisted as native logs |
| Workspace diff | captured from isolated workspace | captured from isolated workspace | captured from isolated workspace | captured from isolated workspace | captured from isolated workspace |
| Input/output tokens | parsed when native output exposes them | parsed from CLI-reported `usage` when present | parsed from terminal `result.stats` when present | parsed from JSON events when present | parsed from terminal assistant-message usage when present |
| Cost | parsed when native output/proxy exposes it | parsed from CLI-reported total cost when present | missing unless Gemini emits it | missing: observed cost has no stable currency provenance | parsed from assistant-message cost when present |
| Progress/tool events | native JSONL events | native JSONL assistant/tool-result events | native JSONL events | native JSONL events | native JSONL events |
| Provider-side usage attribution | local transparent proxy on the `openai-compatible` route | not implemented | not implemented | not implemented | not implemented |
| Structured result proposal | extracted from structured agent output when present | extracted from structured text inside the final JSON result when present | extracted from assembled assistant message events when structured | extracted from assembled text events when structured | extracted from assistant text content when structured |

Telemetry confidence is source-specific:

- a Codex `openai-compatible` run can capture provider responses through the
  local transparent proxy and attach provider-usage evidence when the upstream
  returns it;
- a Claude Code run records CLI-reported usage/cost as `agent_reported`; it
  does not currently add an independent provider-side proxy capture;
- a Gemini run records terminal `result.stats` as `agent_reported`; it retains
  provider-reported model labels but does not claim independent route-level
  attribution or cost when the stream omits it;
- absent usage is recorded as missing rather than guessed.

No adapter should infer token count, cost, model revision, tool call, or
verification success from natural-language output alone.

### Cross-run comparison eligibility

The session result records `metric_provenance` beside normalized metrics. The
current baseline is deliberately conservative:

| Metric | Eligibility | Reason |
| --- | --- | --- |
| Wall time | comparable | Harness-clock measurement. |
| File delta | comparable | Harness workspace diff. |
| Token usage | conditional | Agent/provider reporting shape and cache accounting differ. |
| Monetary cost | conditional or not comparable | Currency and billing attribution are often missing. OpenCode's observed numeric cost is intentionally not normalized as USD. |
| Tool timeline | comparable when native events exist | All five adapters normalize their CLI-owned native event streams; this does not expose raw provider SSE. |

The report prints the source for each session (`harness`, `agent_reported`,
`provider_reported`, or unavailable) and the selected Agent×Provider route's
declared comparison eligibility. Route evidence is authoritative for telemetry
and comparability; Agent-level values remain only a compatibility fallback for
unbound registry views. A normalized value never upgrades its evidence source.

`bureauless metrics summarize .bureauless/runs` recursively discovers the
`session.yaml` artifacts emitted by `audit run`. Its `comparison` section
reports the least-comparable eligibility, observed/missing counts, and distinct
evidence sources for latency, file delta, tokens, monetary cost, and tool
timeline. Totals remain observations; the command does not turn conditional or
mixed telemetry into a scientifically valid ranking.


### Historical audit records

The dated CLI probes, endpoint outcomes, model labels, and telemetry observations
are preserved in [`../audits/2026-07-13-agent-provider-compatibility.md`](../audits/2026-07-13-agent-provider-compatibility.md).
They are evidence for the tested versions and routes, not mutable registry state.
Each tested route links back to this record through `audit_ref`, `verified_at`,
and `verified_runtime_version`; a newer installed CLI version does not silently
inherit that historical verification.

The latest dated endpoint-instance results, including the isolated Claude Code
correction and the current unavailable Gemini route, are in
[`../audits/2026-07-15-agent-endpoint-capability-matrix.md`](../audits/2026-07-15-agent-endpoint-capability-matrix.md).

## 9. Current capability matrix

This is the primary human-readable Agent×endpoint matrix. It is exhaustive
relative to the current registry schema and execution contract, not to every
possible future agent or endpoint. `Latest route result` is always scoped to a
dated endpoint instance: it never downgrades the general endpoint-family or
agent contract.

| Agent | Route category | Endpoint family / wire API | Runtime contract | BureauLess adapter | Child-only route injection / isolation | Observable normalized evidence | Latest route result |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Codex CLI | `openai` | native OpenAI route | supported | implemented | ephemeral Codex configuration; native sandbox | JSONL tools, workspace diff, CLI/provider usage when exposed | not tested by the current dated route audit |
| Codex CLI | `openai-compatible` | OpenAI / Responses | supported | implemented | selected key environment and `/v1` base | JSONL tools, workspace diff, provider usage through local proxy when available | verified live workspace mutation |
| Claude Code | `anthropic-compatible` | Anthropic / Messages | supported | implemented | selected key, gateway root, cleared inherited token, session-local home/config, `--bare` | JSONL lifecycle/tool events, workspace diff, CLI usage/cost | verified live workspace mutation in an isolated API-key session; stream parser fixture-tested |
| Gemini CLI | `gemini-compatible` | Gemini / GenerateContent | supported | implemented | selected child API key/base URL and temporary home | JSONL tools, workspace diff, terminal usage/model labels; cost may be absent | adapter verified historically; current tested CLI route unavailable (model discovery is not generation proof) |
| OpenCode | `openai-chat-compatible` | OpenAI / Chat Completions | supported | implemented | temporary home/config and selected key | JSONL tools, workspace diff, agent usage; cost is unpriced without currency provenance | verified live workspace mutation |
| OpenCode | `anthropic-compatible` | Anthropic / Messages | observed | not implemented | no BureauLess binding | no session evidence | runtime shape observed; adapter not implemented |
| OpenCode | `openai-compatible` | OpenAI / Responses | observed | not implemented | no BureauLess binding | no session evidence | tested route unavailable; not an OpenCode-wide incompatibility claim |
| Pi | `anthropic-compatible` | Anthropic / Messages | supported | implemented | temporary Pi model registry and selected key | JSONL tools, workspace diff, agent usage/cost | verified live workspace mutation |
| Pi | `openai-chat-compatible` | OpenAI / Chat Completions | supported | implemented | temporary Pi model registry and selected key | JSONL tools, workspace diff, agent usage/cost | verified live workspace mutation |
| Pi | `openai-compatible` | OpenAI / Responses | observed | not implemented | no BureauLess binding | no session evidence | tested route unavailable; runtime observation is not adapter support |

The registry, rather than this rendered table, is the executable source of
truth. Render the corresponding machine-readable rows with:

```bash
bureauless agent matrix --evidence
```

The output distinguishes runtime contract support, BureauLess adapter support, and
the latest recorded result for a tested route, alongside `route_kind`,
`endpoint_family`, and `wire_api`. `agent matrix` without
`--evidence` remains the local doctor/control-surface view.

## 10. Canonical commands

The commands below are one-shot invocations. They do not edit the local Codex,
Claude Code, or gateway configuration.

### Codex CLI through a Responses-compatible endpoint

```bash
export OPENAI_GATEWAY_API_KEY='…'

bureauless session run MISSION WORKFLOW DISPATCH \
  --ledger LEDGER \
  --agent codex-cli \
  --target-model model-id-from-this-endpoint \
  --target-provider openai-compatible \
  --provider-base-url https://gateway.example/v1 \
  --provider-api-key-env OPENAI_GATEWAY_API_KEY \
  --provider-wire-api responses
```

### Claude Code through a Messages-compatible endpoint

```bash
export CLAUDE_GATEWAY_API_KEY='…'

bureauless session run MISSION WORKFLOW DISPATCH \
  --ledger LEDGER \
  --agent claude-code \
  --target-model model-id-from-this-endpoint \
  --target-provider anthropic-compatible \
  --provider-base-url https://gateway.example \
  --provider-api-key-env CLAUDE_GATEWAY_API_KEY
```

Before either live command, check the route and runtime:

```bash
bureauless agent route claude-code --provider anthropic-compatible
bureauless agent doctor claude-code
bureauless agent readiness claude-code --workdir . --isolation-mode copy
```

For the smallest end-to-end path, initialize once and let `audit run` reuse the
same assignment, routing, registration snapshot, dispatch, session, report,
and archive contracts. A live run records the installed binary/version doctor
result and classifies its route evidence as `matching`, `version_drift`,
`route_unverified`, or `installed_version_unknown`; `--dry-run` intentionally
leaves that probe `not_checked`:

```bash
bureauless audit init --workspace . --task "Fix one bounded bug and add tests"
bureauless audit run --workspace . \
  --agent claude-code \
  --target-model model-id-from-this-endpoint \
  --target-provider anthropic-compatible \
  --provider-base-url https://gateway.example \
  --provider-api-key-env CLAUDE_GATEWAY_API_KEY
```

## 11. Registration checklist for a new agent or provider route

Do not add a row merely because a CLI can be installed or a gateway advertises
compatibility. A new registration needs all applicable evidence below.

1. Identify the exact runtime type and non-interactive executable entrypoint.
2. Record command flags for model selection, working directory, persistence,
   output capture, and cancellation; verify them with `agent doctor`.
3. Classify the endpoint family and operation path separately. State whether
   it is Responses, Chat Completions, Messages, or something else.
4. Test a minimal authenticated request against the operation path and a
   model-discovery request if the endpoint provides one.
5. Define credential injection as a child-only environment mapping. Never
   write keys or provider settings into local agent configuration.
6. State the permission semantics honestly; do not call two unrelated
   permission systems equivalent without a verified mapping.
7. Implement a session adapter that persists native stdout/stderr, captures
   workspace changes, normalizes exit/timeout/cancellation, and records which
   fields were parsed versus missing.
8. Add a compatibility-matrix row and tests for accepted and rejected
   bindings. Registration remains **registered only** until the adapter exists.
9. Document the telemetry source and confidence. If provider-side usage is
   absent, say so rather than manufacturing a cost figure.

This checklist is deliberately operational: it prevents a provider label from
becoming an unverified promise and keeps the audit layer independent of any
one model vendor or agent configuration tool.
