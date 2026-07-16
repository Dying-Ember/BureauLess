# Engineering Audits

Audits are dated evidence, not stable capability contracts. They record what a
named implementation, Agent version, route, or endpoint instance actually did
and link any resulting remediation to its owner.

The current contract belongs in `docs/protocol/`; current machine-readable
Agent×Provider state comes from:

```bash
uv run bureauless agent matrix --evidence
```

## Audit Types

### Gap analysis

Use a gap analysis when a documented or completed capability claim differs
from shipped behavior and the first task is establishing the real ownership
gap. Name it:

```text
YYYY-MM-DD-<scope>-gap-analysis.md
```

Every finding needs a stable ID, severity, claimed behavior, reproducible
evidence, operational impact, disposition, owner, and closure evidence.

### Compatibility or verification record

Use a verification record when the goal is to preserve a dated probe, version,
route, endpoint-instance result, or telemetry boundary without asserting a
project defect. Name it:

```text
YYYY-MM-DD-<scope>.md
```

These records must distinguish Agent capability, adapter support, and tested
endpoint-instance availability. An unavailable endpoint must not be rewritten
as an Agent incompatibility.

A local implementation bug with an obvious fix normally needs only an issue or
task. A proposed semantic change normally needs an RFC.

## Required Metadata

Every audit starts with:

```markdown
# <Scope>

- Status: draft | recorded | confirmed | remediating | closed
- Audited baseline: <commit, release, versions, or run set>
- Audit date: YYYY-MM-DD
- Scope: <packages, runtime path, agents, routes, or endpoint families>
- Canonical contract: <protocol link>
```

Gap analyses also declare related milestones and owners. Compatibility records
declare tested versions and the exact evidence boundary.

## Evidence Rules

- Native output remains evidence; normalized facts retain provenance.
- Workspace state and independent acceptance determine mutation success, not a
  tool event or final prose claim.
- Requested, CLI-reported, provider-reported, and independently attested model
  identities remain separate.
- Missing token or currency evidence stays missing.
- Provider brand, endpoint family, wire API, and concrete endpoint instance are
  different claims.
- Never record credential values or depend on local Agent configuration that a
  clean child session cannot reproduce.
- A fixture proves parsing or validation, not live runtime integration.

## Severity for Gap Analyses

| Severity | Meaning |
| --- | --- |
| critical | Canonical state, approval, replay, or safety can be incorrect. |
| high | A claimed live control path is absent or materially non-authoritative. |
| medium | The path works only through fixtures, post-hoc synthesis, or a narrow demo. |
| low | Documentation, ergonomics, or observability is incomplete without changing runtime correctness. |

## Completion Vocabulary

Do not let one `completed` label imply every delivery layer:

1. `schema`: the data shape exists.
2. `validation`: malformed or unauthorized data is rejected.
3. `runtime integration`: the maintained path produces and consumes it.
4. `operator surface`: CLI, API, or Workbench can inspect or operate it.
5. `end-to-end evidence`: a maintained test or live probe proves the complete
   behavior without fabricated artifacts.

When route compatibility is involved, separately record:

- `runtime_contract_support`
- `adapter_support`
- `tested_route_support`
- `verification_levels`

## Processing Workflow

1. Reproduce against a named baseline.
2. Separate implementation defects, missing integration, endpoint
   unavailability, design ambiguity, and documentation drift.
3. Record native evidence and normalized conclusions with provenance.
4. For a confirmed gap, update the roadmap/task owner in the same change.
5. Create an RFC only when behavior or ownership still needs a decision.
6. Close a gap only after maintained verification exists.
7. Preserve historical records; add a dated correction instead of silently
   rewriting old evidence.

## Audit Index

- [`2026-07-15-agent-endpoint-capability-matrix.md`](2026-07-15-agent-endpoint-capability-matrix.md):
  current endpoint-instance compatibility and telemetry evidence.
- [`2026-07-13-agent-provider-compatibility.md`](2026-07-13-agent-provider-compatibility.md):
  initial five-Agent compatibility record; current state comes from the
  registry.
- [`2026-07-11-live-demo-control-plane-bootstrap-gap.md`](2026-07-11-live-demo-control-plane-bootstrap-gap.md):
  verified control-plane bootstrap remediation.
- [`2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md`](2026-07-10-control-runtime-boundary-follow-up-gap-analysis.md):
  confirmed RFC-007 implementation-debt audit.
- [`2026-07-02-runtime-execution-gap-analysis.md`](2026-07-02-runtime-execution-gap-analysis.md):
  closed execution-spine gap analysis.
