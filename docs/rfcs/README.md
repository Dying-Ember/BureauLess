# RFCs

RFCs preserve design proposals and their decision history. An accepted RFC is
not the canonical runtime contract; implemented behavior moves into
`docs/protocol/` while the RFC remains for provenance.

When a proposal becomes a decision record, archive the resulting ADR under
`docs/adrs/<nnn>-<slug>/` and keep both documents cross-linked.

Use this directory for candidate changes that need review before they move into
`docs/protocol/`, `docs/tasks/`, or the roadmap.

- [`001-controlled-workflow-mutation.md`](001-controlled-workflow-mutation.md):
  RFC-001, controlled runtime workflow mutation design implemented in
  Milestone 2.5. Tracked by
  [GitHub issue #1](https://github.com/Dying-Ember/BureauLess/issues/1).
- [`002-ledger-evidence-and-progressive-context.md`](002-ledger-evidence-and-progressive-context.md):
  RFC-002, accepted design for minimum-sufficient ledger facts, immutable
  native evidence, node-outcome boundaries, progressive context disclosure,
  and feedback-driven context policy. The Runtime Milestone 3 scope is
  implemented.
- [`003-engineering-boundary-refactor.md`](003-engineering-boundary-refactor.md):
  RFC-003, implemented engineering-boundary refactor for shared errors, CLI
  split, application services, and narrower protocol exports.
- [`004-temporal-replay-mutation-intake-and-retry-control.md`](004-temporal-replay-mutation-intake-and-retry-control.md):
  RFC-004, draft design for universal inert worker mutation intents, trusted
  proposal intake, bounded retry control, workflow versions, and linear temporal
  replay in Runtime Milestone 4.
