# Agent Endpoint Capability Matrix

- Status: recorded
- Audited baseline: live isolated benchmark sessions on 2026-07-15
- Audit date: 2026-07-15
- Scope: Agent×endpoint wire contracts, isolation, workspace mutation, and telemetry
- Canonical contract: [`../protocol/agent_provider_registry.md`](../protocol/agent_provider_registry.md)

This is endpoint-instance evidence for the stable Agent×endpoint capability
matrix. It records no provider brand, URL, credential value, or local agent
configuration. An unavailable endpoint instance does not change an agent's
runtime contract or adapter registration.

## Test contract

Every completed run received the same bounded source edit. Success required an
independent acceptance command to pass and the isolated workspace diff to show
only the allowed source-file change. Native tool events were retained as
evidence, but did not determine file-change success.

## Matrix evidence

| Agent | Route category / wire API | CLI version | Session isolation | Endpoint-instance result | Observed telemetry boundary |
| --- | --- | --- | --- | --- | --- |
| Codex CLI | `openai-compatible` / Responses | `0.144.4` | ephemeral invocation config and isolated workspace | verified: completed and independent acceptance passed | provider-attributed input/output/cache/reasoning usage was available; no price was asserted |
| Claude Code | `anthropic-compatible` / Messages | `2.1.202` | `--bare`, session-local home/config, inherited auth token removed, selected API-key environment | verified: completed and independent acceptance passed without relying on local Claude state | CLI-reported input/output/cache usage and USD cost; `stream-json` captured paired tool-use/tool-result events, including permission denial evidence |
| Gemini CLI | `gemini-compatible` / GenerateContent | `0.50.0` | temporary home and child API-key/base-URL configuration | unavailable for this selected CLI binding: discovery was not sufficient to obtain a generation channel | terminal result was unavailable; this does not invalidate the historical adapter mutation proof |
| OpenCode | `openai-chat-compatible` / Chat Completions | `1.17.20` | temporary home/config and child-only selected key | verified: completed and independent acceptance passed | agent-reported input/output/reasoning/cache usage; numeric cost remained unpriced because currency was not independently attested |
| Pi | `anthropic-compatible` / Messages | `0.80.6` | temporary Pi model registry and child-only selected key | verified: completed and independent acceptance passed | agent-reported input/output/cache usage and cost, plus native tool events |
| Pi | `openai-chat-compatible` / Chat Completions | `0.80.6` | temporary Pi model registry and child-only selected key | verified: completed and independent acceptance passed | agent-reported input/output/cache usage and cost, plus native tool events |

The remaining registered rows have no new live binding in this audit:

| Agent | Route category / wire API | Registry conclusion |
| --- | --- | --- |
| Codex CLI | `openai` / native | adapter implemented; no route-specific live probe in this audit |
| OpenCode | `anthropic-compatible` / Messages | upstream shape observed; BureauLess adapter not implemented |
| OpenCode | `openai-compatible` / Responses | upstream shape observed; BureauLess adapter not implemented; the prior tested endpoint instance was unavailable |
| Pi | `openai-compatible` / Responses | upstream shape observed; BureauLess adapter not implemented; the prior tested endpoint instance was unavailable |

## Corrections and limitations

1. Claude Code now has a verified clean API-key startup path. The binding must
   receive a gateway root (not a `/v1` operation prefix), because Claude Code
   appends the version path. This correction applies only to the explicit
   child-only API-key path, not native login or user-managed configuration.
2. Gemini model listing and successful generation are separate observations.
   The selected current binding returned no generation channel, so it is
   recorded as endpoint-instance unavailable rather than as an adapter defect.
3. Wall time and workspace diff are harness facts and comparable across these
   runs. Tokens are conditionally comparable; cost and tool timelines retain
   their per-agent provenance and must not be ranked as a single economy score.
4. A same-day follow-up upgraded the Claude adapter from final JSON to the
   CLI-owned `stream-json --verbose` lifecycle stream. A live isolated mutation
   produced three tool calls, six paired tool events, complete CLI usage/cache/
   cost fields, and a passing independent acceptance result. This observes the
   Claude CLI stream, not raw provider SSE.

Render the executable registry view with:

```bash
bureauless agent matrix --evidence
```
