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
  Milestone 2.5; temporal replay was completed separately by RFC-004. Tracked
  by [GitHub issue #1 (closed)](https://github.com/Dying-Ember/BureauLess/issues/1).
- [`002-ledger-evidence-and-progressive-context.md`](002-ledger-evidence-and-progressive-context.md):
  RFC-002, accepted design for minimum-sufficient ledger facts, immutable
  native evidence, node-outcome boundaries, progressive context disclosure,
  and feedback-driven context policy. Runtime M3 and the M3.5 real-session
  continuation loop are implemented. Tracked by
  [GitHub issue #11 (closed)](https://github.com/Dying-Ember/BureauLess/issues/11).
- [`003-engineering-boundary-refactor.md`](003-engineering-boundary-refactor.md):
  RFC-003, implemented engineering-boundary refactor for shared errors, CLI
  split, application services, and narrower protocol exports. Tracked by
  [GitHub issue #2 (closed)](https://github.com/Dying-Ember/BureauLess/issues/2).
- [`004-temporal-replay-mutation-intake-and-retry-control.md`](004-temporal-replay-mutation-intake-and-retry-control.md):
  RFC-004, accepted design for universal inert worker mutation intents, trusted
  proposal intake, bounded retry control, workflow versions, and linear temporal
  replay in Runtime Milestone 4. Resolved by ADR-004 and implemented; tracked
  by [GitHub issue #3 (closed)](https://github.com/Dying-Ember/BureauLess/issues/3).
- [`005-authoritative-result-acceptance-spine.md`](005-authoritative-result-acceptance-spine.md):
  RFC-005, accepted and implemented Runtime Milestone 3.5 design for staged result intake,
  authoritative node-outcome acceptance, review/verification policy, and
  conservative ledger v2 migration. Resolved by ADR-005 and tracked by
  [GitHub issue #10 (closed)](https://github.com/Dying-Ember/BureauLess/issues/10).
- [`006-bounded-context-continuation.md`](006-bounded-context-continuation.md):
  RFC-006, accepted Runtime Milestone 3.5 design for harness-owned context
  request identity, bounded resolution, resumed agent turns, lifecycle events,
  and continuation telemetry. Resolved and implemented by ADR-006; tracked by
  [GitHub issue #12 (closed)](https://github.com/Dying-Ember/BureauLess/issues/12).
- [`007-control-runtime-boundary.md`](007-control-runtime-boundary.md):
  RFC-007, accepted boundary for what execution control BureauLess must own versus
  what remains owned by external agent runtimes and adapters; implementation
  debt is tracked separately. [GitHub issue #9 (closed)](https://github.com/Dying-Ember/BureauLess/issues/9).
