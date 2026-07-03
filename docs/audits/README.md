# Engineering Audits

Engineering audits record verified differences between documented capability
claims and shipped behavior. They preserve evidence and remediation ownership;
they are not substitutes for protocols, RFCs, ADRs, roadmaps, or task lists.

## When To Create An Audit

Create an audit when one or more of these conditions hold:

- a milestone is marked complete but a maintained execution path does not meet
  its acceptance claim;
- a schema, validator, fixture, API, or UI exists without a corresponding live
  runtime integration;
- two authoritative documents disagree about delivered behavior;
- an incident or integration test reveals a cross-milestone design gap;
- a capability needs coordinated remediation across protocol, runtime, API, and
  operator surfaces.

A local implementation bug with an obvious fix normally needs only an issue or
task. A proposed semantic change normally needs an RFC. Use an audit when the
first problem is establishing what is actually implemented and where the
ownership gap belongs.

## File Naming And Required Metadata

Use `YYYY-MM-DD-<scope>-gap-analysis.md`. Every audit starts with:

```markdown
# <Scope> Gap Analysis

- Status: draft | confirmed | remediating | closed
- Audited baseline: <commit or release>
- Audit date: YYYY-MM-DD
- Scope: <packages, runtime path, or capability>
- Related milestones: <links>
- Owners: <team, workstream, or task list>
```

Each finding must include:

- a stable finding ID;
- severity;
- the documented capability claim;
- observed implementation and reproducible code or test evidence;
- operational impact;
- disposition and owning task;
- whether an RFC or ADR is required;
- closure evidence when resolved.

Use these severities:

| Severity | Meaning |
| --- | --- |
| critical | Canonical state, approval, replay, or safety can be incorrect. |
| high | A claimed live control path is absent or materially non-authoritative. |
| medium | The supported path works only through fixtures, post-hoc synthesis, or a narrow demo. |
| low | Documentation, ergonomics, or observability is incomplete without changing runtime correctness. |

## Capability Completion Vocabulary

Do not use one `completed` label to imply all delivery layers. Audits and
roadmaps should distinguish these layers when the difference matters:

1. `schema`: data shape exists.
2. `validation`: malformed or unauthorized data is rejected.
3. `runtime integration`: the maintained execution path produces and consumes
   the shape as an authoritative control input.
4. `operator surface`: CLI, API, or Workbench can inspect or operate the path.
5. `end-to-end evidence`: a maintained test or smoke path proves the complete
   behavior without manual artifact fabrication.

A capability is end-to-end complete only when every required layer is complete.

## Processing Workflow

1. **Verify**: reproduce the gap against a named commit and cite code/tests.
2. **Classify**: separate implementation defects, missing integration, design
   ambiguity, and documentation drift.
3. **Record**: create or update one audit with stable finding IDs.
4. **Route**: update the roadmap and task indexes in the same change. Assign
   every confirmed finding to a milestone task or explicitly defer it.
5. **Decide**: create an RFC only when behavior, ownership, compatibility, or
   architecture still requires a decision. Record the accepted choice in an ADR.
6. **Implement**: land code, tests, protocol changes, and operator changes under
   the owning task.
7. **Close**: add verification evidence, mark the finding closed, and update the
   roadmap/task status. An issue or pull request closing is not sufficient by
   itself.

## History And Status Rules

- Do not delete or silently rewrite a completed milestone's historical task
  evidence. Add a dated post-completion correction and link the remediation.
- A completed milestone may remain historically complete for its declared
  delivery scope while the roadmap states that broader integration is partial.
- Critical and high findings cannot be left without an owner or an explicit
  deferral rationale.
- A UI that renders a fixture does not prove runtime integration.
- A validator that accepts an artifact does not prove that the artifact controls
  execution.
- An audit becomes `closed` only when all non-deferred findings have maintained
  verification evidence.

## Audit Index

- [`2026-07-02-runtime-execution-gap-analysis.md`](2026-07-02-runtime-execution-gap-analysis.md):
  closed audit of the real-agent execution spine from dispatch through
  acceptance, progressive context, lifecycle control, and Workbench discovery;
  mutation intake remains explicitly deferred to Runtime M4.
