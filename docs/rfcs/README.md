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
  and feedback-driven context policy. Implementation is tracked in Milestone 3.
- [`003-engineering-boundary-refactor.md`](003-engineering-boundary-refactor.md):
  RFC-003, draft engineering-boundary refactor for shared errors, CLI split,
  application services, and narrower protocol exports.
