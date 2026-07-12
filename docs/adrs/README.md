# ADR Archive

This directory stores Architecture Decision Records.

RFCs capture proposals and discussion history. ADRs capture the final decision
made from one RFC or a bounded set of RFC-derived decisions. The two document
types must stay cross-linked so future work can move from proposal to decision
without reconstructing the thread.

## Directory Model

Use one numbered subdirectory per RFC topic:

```text
docs/
  rfcs/
    001-controlled-workflow-mutation.md
    002-ledger-evidence-and-progressive-context.md
  adrs/
    001-controlled-workflow-mutation/
      README.md
      001-accepted-design.md
    002-ledger-evidence-and-progressive-context/
      README.md
      001-accepted-design.md
    003-engineering-boundary-refactor/
      README.md
      2026-06-30-shared-errors.md
      2026-06-30-cli-boundary.md
```

Rules:

1. The RFC numeric prefix and the ADR topic numeric prefix must match.
2. Every ADR file must declare the RFC it came from.
3. Every RFC that reaches a decision should list the ADR files that resolved it.
4. Superseded ADRs stay in place; they are never rewritten into a different topic.

## File Roles

- `docs/rfcs/<nnn>-<slug>.md`: proposal, alternatives, open questions, and
  decision history before acceptance.
- `docs/adrs/<nnn>-<slug>/README.md`: index for the decision archive tied to
  the RFC.
- `docs/adrs/<nnn>-<slug>/<nnn>-<decision-slug>.md`: one decision record.

## Required Cross-References

Each ADR should include:

- `RFC:` canonical path to the source RFC.
- `Related RFC sections:` optional pointers to the exact RFC sections that
  triggered the decision.
- `Supersedes:` optional list of earlier ADRs from the same topic.
- `Implementation:` the code paths, docs, or tasks that will absorb the
  decision.
- `Status:` `proposed`, `accepted`, `superseded`, or `rejected`.

Each RFC should include:

- `ADR:` canonical path to the decision record or archive index.
- `Decision:` accepted / rejected / deferred outcome.
- `Implementation tracking:` task list, roadmap item, or PR reference.

## Recommended Workflow

1. Write or update the RFC in `docs/rfcs/`.
2. Draft the ADR under `docs/adrs/<nnn>-<slug>/`.
3. Link the ADR back to the RFC and the RFC back to the ADR.
4. When implementation starts, link the ADR to the task list or code path.
5. When the behavior is promoted into `docs/protocol/`, keep the ADR as the
   archived decision record and the RFC as provenance.

## Current Topics

- `001-controlled-workflow-mutation/`: archived decision record for GitHub
  issue #1 and the controlled workflow mutation RFC.
- `002-ledger-evidence-and-progressive-context/`: archived decision record for
  the ledger evidence and progressive context RFC.
- `003-engineering-boundary-refactor/`: archive path for the engineering
  boundary refactor RFC, implemented through its accepted ADRs.
- `004-temporal-replay-mutation-intake-and-retry-control/`: implemented
  version-bound mutation intake, bounded retry, ledger v3, and inclusive replay
  design for Runtime Milestone 4.
- `005-authoritative-result-acceptance-spine/`: accepted staged-result and
  strict outcome-acceptance design for Runtime Milestone 3.5.
- `006-bounded-context-continuation/`: accepted bounded progressive-context
  continuation design for Runtime Milestone 3.5.
- `007-control-runtime-boundary/`: accepted control runtime
  boundary RFC.
