# Agent/Provider Compatibility Audit

- Status: recorded
- Audited baseline: installed CLI probes and live child-only runs on 2026-07-13
- Audit date: 2026-07-13
- Scope: Codex CLI, Claude Code, Gemini CLI, OpenCode, Pi, and the tested endpoint contracts
- Canonical contract: [`../protocol/agent_provider_registry.md`](../protocol/agent_provider_registry.md)

This is a dated evidence record, not a claim about every endpoint of a
provider family. Native logs and workspace diffs are authoritative for the
individual runs; normalized facts below retain their stated provenance.

Recorded runtime versions used by the registry evidence are Claude Code
`2.1.202`, Gemini CLI `0.50.0`, OpenCode `1.17.18`, and Pi `0.80.6`. Codex route
rows remain `not_tested` by this audit and therefore carry no verified runtime
version. These values are historical evidence, not minimum-version promises.

## Findings

### Codex CLI

| Finding | Result | Boundary |
| --- | --- | --- |
| Native OpenAI and custom Responses adapter | implemented | `codex_exec_v1` launches isolated child sessions and the custom route explicitly selects Responses. |
| Provider-side usage capture | supported when the route exposes it | The local transparent proxy preserves upstream usage evidence; absence remains missing. |
| Fresh route probe in this audit | not recorded | This audit does not upgrade an unrecorded endpoint/model combination to `verified`. |

### Claude Code

| Finding | Result | Boundary |
| --- | --- | --- |
| Messages route and non-interactive final JSON | verified | `--print --output-format json` worked through child-only base URL and credential injection. |
| Native stream shape | observed | `stream-json --verbose` emitted lifecycle, incremental, tool, and final events; `claude_print_json_v1` currently consumes final JSON only. |
| Clean stateless startup | unverified | A fresh `CLAUDE_CONFIG_DIR` failed locally with `model_not_found` before provider usage. This is not endpoint incompatibility. |
| Local configuration mutation | not performed | Successful calls used only child environment variables. |
| Telemetry | CLI/provider reported | Final JSON exposed input/output/cache usage and USD cost when present. Tool timeline and partial thinking are not currently normalized. |

The registry records this as `child_only_route_injection=verified`,
`clean_stateless_startup=unverified`, and
`depends_on_existing_global_state=observed`.

### Pi

| Finding | Result | Boundary |
| --- | --- | --- |
| Anthropic Messages | verified | Temporary `PI_CODING_AGENT_DIR` provider using `anthropic-messages` completed a read/edit JSON run. |
| OpenAI Chat Completions | verified | Temporary `openai-completions` provider and `/v1` base completed a JSON run. |
| OpenAI Responses | unavailable at tested route | The route returned HTTP 500 `convert_request_failed: not implemented`; Pi surfaced failure and retry events. |
| Permission and workspace evidence | verified | Read/edit allow-list emitted tool events and the isolated workspace diff confirmed the requested change. |
| Telemetry | agent reported | Final assistant usage exposed input/output/cache read/cache write/total tokens and cost fields. |
| Local configuration mutation | not performed | Provider, session, and credential state remained in temporary child directories. |

The successful Messages edit reported input `222`, output `46`, cache read
`2,198`, cache write `9`, and total `2,475` tokens. The workspace diff, not a
tool event, remains the file-change fact.

### Gemini CLI

| Finding | Result | Boundary |
| --- | --- | --- |
| Model discovery and non-interactive edit | verified | Temporary `HOME`, child API key/base URL, and stream JSON run completed an edit. |
| Native telemetry | verified | Terminal `result.stats` exposed input/output/total/cached tokens, duration, model counters, and tool-call count. No cost was observed. |
| Requested versus reported model | differs | Requested `gemini-3-pro-preview`; provider reported `gemini-3.1-pro-preview` initially and `gemini-pro-default` on resume. |
| Local configuration mutation | not performed | The temporary child `HOME` was removed after the probe. |

The live adapter edit reported input `20,861`, output `205`, total `21,750`,
and two tool calls. Requested and provider-reported model labels must remain
separate.

### OpenCode

| Finding | Result | Boundary |
| --- | --- | --- |
| OpenAI Chat Completions | verified | Child-only `@ai-sdk/openai-compatible` configuration completed a JSON-mode edit. |
| Anthropic Messages | runtime observed; adapter not implemented | Child-only built-in Anthropic provider completed probes, but BureauLess does not bind its OpenCode adapter to this shape. |
| OpenAI Responses | unavailable at tested route | Direct route probe returned HTTP 500 `convert_request_failed: not implemented`; it is not registered as Responses-ready. |
| OpenCode Go subscription | verified separately | A first-party subscription model completed; it is not evidence for caller-supplied endpoints and has no adapter binding. |
| Permission and file evidence | verified | Child policy denied shell/web, allowed the requested edit, and the workspace diff confirmed the file fact. |
| Telemetry | agent reported, cost unpriced | Events exposed input/output/reasoning/cache fields. Numeric cost had no stable currency provenance and was not normalized as USD. |
| Local configuration mutation | not performed | Child-only config/home directories were used. |

The successful Chat edit reported input `129`, output `26`, cache read `7,185`,
and total `7,340` tokens. OpenCode's exported file summary was observed as
`0` despite the edit, so it is not accepted as file-change evidence.

### Cross-cutting conclusions

1. Agent, adapter, and endpoint results are separate facts. A failed
   Responses route does not make Pi or OpenCode generally incompatible.
2. Tool events are claims of action; the harness workspace diff is the final
   file-state fact.
3. Token fields are conditionally comparable. Cost is never inferred; OpenCode
   cost remains unpriced without currency provenance.
4. Credentials were injected into child environments or temporary child
   configuration only. No tested adapter changed user agent configuration.

The current machine-readable view is generated with:

```bash
bureauless agent matrix --evidence
```

Future live runs should be preserved with `bureauless audit archive`; the
stored session snapshot, manifest hash, and report supersede prose updates to
this historical record.
