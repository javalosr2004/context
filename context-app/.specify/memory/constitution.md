<!--
SYNC IMPACT REPORT
==================
Version change: 3.0.0 → 3.1.0
Bump rationale: MINOR. Principle II is relaxed but not redefined: instead
of "Apple first-party only" on the frontend with all third-party Swift
packages requiring per-feature amendment, lightweight third-party Swift
packages are now permitted under defined criteria. The rule still requires
explicit listing in `plan.md` (no covert dependencies) and still
non-negotiates against heavy frameworks. The principle's name and
non-negotiable status are preserved. Adding the criteria is a material
expansion, hence MINOR rather than PATCH.

Modified principles:
  - II. Minimum-Viable Dependencies (NON-NEGOTIABLE) — text refined to
        introduce the "lightweight" criterion explicitly. Same intent,
        clearer bounds.

Added sections:
  - Additional Constraints → "Lightweight Library Criteria" — concrete
    heuristics for what counts as "not heavy".
  - Approved Dependencies → "Frontend tier" — Apple frameworks remain
    pre-approved; lightweight Swift packages may be added per-feature in
    `plan.md` without a constitution amendment, provided the criteria are
    met.

Removed sections: none.

Templates requiring updates:
  ✅ .specify/templates/plan-template.md — placeholder Constitution Check;
     consumes this file at plan time. No edit required.
  ✅ .specify/templates/spec-template.md — stack-agnostic. No edit required.
  ✅ .specify/templates/tasks-template.md — language-agnostic. No edit
     required.
  ✅ .specify/templates/checklist-template.md — generic. No edit required.

Plan impact:
  ✅ specs/001-overlay-tutorial/plan.md — Constitution Check Principle II
     row will be updated in lockstep with this amendment to reflect the
     relaxed (but still bounded) policy. The current plan uses zero
     third-party Swift packages; that remains compliant.

Spec impact: none.

Follow-up TODOs: none.
-->

# Context-App Constitution

This is a full-stack project. These principles are written to be neutral
across tiers and languages. They are stated once and apply to every layer
they reach, from the user-facing client to the persistence layer and any
external service the project integrates with.

## Core Principles

### I. Clear Code, Layer-Agnostic

Code MUST be clear before it is clever, in every tier of the stack.
Functions and modules MUST have a single responsibility. Names MUST reveal
intent: the right name beats the right comment. Avoid catch-all "utils"
modules, deep nesting, long parameter lists, oversized classes, and
flag-driven branching. Prefer composition over inheritance and pure
functions over hidden state. If a reasonable engineer cannot understand a
unit on first read in its native ecosystem, rewrite it — do not paper over
it with comments.

**Rationale**: Cleanliness is the cheapest form of correctness review.
Across a multi-tier stack, where a single change often crosses runtimes,
unclear code at any layer compounds: the reader pays the comprehension
cost once per tier instead of once.

### II. Minimum-Viable Dependencies (NON-NEGOTIABLE)

Each tier of the project MUST keep its dependency graph as small as the
requirement allows. Heavy frameworks and grab-bag utility libraries are
prohibited. Lightweight, single-purpose libraries are permitted under the
following workflow:

1. **Pre-approved packages**: Packages on the Approved Dependencies list
   (see *Additional Constraints*) MAY be used freely.
2. **Lightweight additions per feature**: New third-party packages that
   meet the *Lightweight Library Criteria* (see *Additional Constraints*)
   MAY be added in a feature's `plan.md` under a "Dependencies for this
   feature" subsection that lists the package, its version constraint, the
   precise feature it provides, and a one-line justification for why
   first-party tooling is insufficient. No constitution amendment is
   required for lightweight additions.
3. **Heavy or framework-class additions**: Anything that does NOT meet the
   Lightweight Library Criteria — heavy frameworks, packages with large
   transitive trees, anything that "owns" a tier — requires a constitution
   amendment that adds the package to the Approved Dependencies list.

Approval is per-package, per-version-range, and per-purpose; previous
approval does NOT extend to other packages or other uses of the same
package. The rule is non-negotiable in two specific senses: (a) covert
dependencies (used in code but not declared in `plan.md` / Approved
Dependencies) are forbidden, and (b) heavy frameworks may not be slipped
in via the lightweight pathway.

**Rationale**: External dependencies bring transitive risk — supply chain,
licensing, version drift, unbounded API surface. The previous version of
this principle was overly absolute on the frontend ("Apple first-party
only"), which made legitimate small libraries (a 200-line crypto helper, a
focused parser) require an amendment for no real gain. The lightweight
pathway lets small focused libraries through, while the heavy-framework
guard preserves the original intent: keep the dependency graph
auditable and small.

### III. Test-Driven Development for Domain Logic (NON-NEGOTIABLE)

Every domain logic unit MUST be developed test-first. The cycle is: write
a failing test → confirm it fails for the right reason → implement the
minimum code to make it pass → refactor with the test green. Tests MUST
be committed with (or before) the implementation they cover.

A "domain logic unit" is any unit that contains branching, state
transitions, validation, calculation, or orchestration of side effects. It
applies regardless of tier: a Swift class on the frontend, a Python
function on the backend, a database migration's rollback path.

The following are EXEMPT: pure presentation code (SwiftUI views, view
modifiers, AppKit wiring, HTML templates), trivial serializers/
deserializers driven entirely by a schema, and generated code. Business
logic embedded in UI or glue MUST be extracted into a testable unit.

**Rationale**: TDD on real logic catches design problems before they
ossify and produces a regression net that survives refactors. The
exemption keeps the rule honest — pretending UI tests have the same
cost/flake profile as unit tests leads to silent erosion.

### IV. Contract-First Tier Boundaries (NON-NEGOTIABLE)

Every boundary between tiers (client ↔ server, server ↔ external service,
service ↔ persistence) MUST be defined by an explicit, versioned contract
before either side implements it. The contract is the source of truth for
field names, types, error shapes, and semantics. No internal type, raw
file path, or implementation detail of one tier may leak into the wire
format of another. Each tier owns its own domain types and translates at
the boundary.

Contract changes MUST be described in the PR (added fields, deprecated
fields, breaking changes called out explicitly). When a change is
breaking, both sides MUST be updated atomically in the same PR or behind
a coordinated rollout plan documented in the feature's `plan.md`.
Contract artifacts MUST live in the feature's `specs/<feature>/contracts/`
directory.

**Rationale**: A clear cross-tier contract is the single most important
piece of architecture in a full-stack app. Without it, the tiers couple
informally and every change becomes a cross-team archaeology project.
With it, each tier evolves independently as long as the contract holds.

### V. Separation of Concerns by Layer (NON-NEGOTIABLE)

Each layer of the stack MUST own one concern and MUST NOT reach across
layer boundaries. Concretely:

- **Presentation** layers (UI views, components, screens) MUST NOT
  contain domain logic, persistence calls, or direct calls to external
  services. They consume domain results through an explicit interface.
- **Application/Service** layers orchestrate domain logic; they MUST NOT
  embed presentation decisions or persistence/IO details.
- **Domain** layers express the project's business rules in pure terms;
  they MUST NOT depend on transport, persistence, or framework specifics.
- **Infrastructure** layers (HTTP clients, database adapters, file IO,
  external SDK wrappers) MUST be thin, replaceable, and depended on
  through interfaces — not consumed directly from presentation or domain
  code.
- **Secrets and credentials** live exclusively at the infrastructure
  boundary (environment, secret manager, keychain). They MUST NOT appear
  in presentation, application, or domain code, and MUST NOT be logged.

**Rationale**: This is the practice that makes full-stack projects
maintainable. Without it, a UI tweak silently breaks a database query, a
domain refactor leaks framework types into the contract, and secrets end
up in client logs. With it, each layer can be tested, replaced, and
reasoned about in isolation.

## Additional Constraints

### Lightweight Library Criteria

A third-party library is "lightweight" — and therefore eligible for the
per-feature pathway in Principle II — if **all** of the following hold:

1. **Single, focused purpose**: the library does one thing and exposes a
   small public surface area. A library that aspires to "own" the
   architecture of a tier (e.g., its own dependency injection,
   networking, persistence, and view layer) is not lightweight.
2. **Small transitive footprint**: ≤ 3 transitive runtime dependencies for
   Swift packages; ≤ 5 for Python packages (FastAPI, Pydantic, etc. count
   as already-on-the-list and do not push other libraries over the
   threshold). Transitive dev/test-only dependencies do not count.
3. **Modest binary footprint**: a Swift package adds ≤ ~1 MB to the
   compiled app binary; a Python package's wheel is ≤ ~10 MB unpacked.
   Numbers are guidelines, not hard cutoffs — a slightly larger library
   that obviously belongs (e.g., a battle-tested cryptography primitive)
   is acceptable with a note.
4. **Permissive license**: MIT, Apache 2.0, BSD, ISC, or equivalent. GPL
   and AGPL are NOT permissible without an explicit Approved-Dependencies
   amendment.
5. **Active maintenance**: a release in the past 18 months OR a stable
   final release explicitly marked "feature complete" by maintainers.
6. **Ecosystem-native**: a Swift Package Manager package (no CocoaPods or
   Carthage), or a normal `pip`-installable Python package on PyPI.
7. **No precompiled native binaries on the Swift side** unless the
   package is from Apple or a very-well-known vendor (e.g., Sentry,
   Firebase) AND the binary is signed and notarized. Source builds are
   preferred.

Anything that fails any of these criteria is "heavy" and requires a
constitution amendment to be added to the Approved Dependencies list.

### Stack and Approved Dependencies

The project's tiers and the third-party packages explicitly approved for
each are listed below. Lightweight additions per-feature (per Principle
II) do not require updating this list, but MUST be declared in the
feature's `plan.md`.

**Frontend tier**:

- Runtime: Swift, Apple platform frameworks (Foundation, SwiftUI, AppKit,
  Combine where required by an Apple API). These are always permitted.
- Pre-approved third-party packages: *(none yet)*
- Lightweight additions: permitted per-feature under Principle II.
- Test runner: XCTest (or Swift Testing where applicable).

**Backend tier**:

- Runtime: Python 3.11+.
- Pre-approved packages:
  - `fastapi` — ASGI web framework.
  - `uvicorn` — ASGI server.
  - `pydantic` — schema and validation models.
  - `google-generativeai` — Google's official Gemini SDK; used
    exclusively for Gemini API calls.
  - `httpx` — HTTP client; permitted only if `google-generativeai`
    cannot meet a specific need (record the reason in the calling
    module's docstring).
  - `pytest` — test runner; test-only.
  - `ruff` — linter/formatter; dev-only.
- Lightweight additions: permitted per-feature under Principle II.

### Stack Norms

These are stylistic norms, not principles. Violations do not require an
amendment, but reviewers MAY request changes citing them.

- **Swift**: prefer value types over reference types unless identity or
  shared mutable state is required; use Swift Concurrency
  (`async/await`, `Task`, actors) for new asynchronous code; avoid `!`
  force-unwraps and `as!` outside of test fixtures with documented
  justification; respect Swift API Design Guidelines for naming.
- **Python**: follow PEP 8 layout; type-hint public function signatures;
  prefer `dataclass` or Pydantic models over bare dicts for structured
  payloads; use `async def`/`await` for I/O exposed to the ASGI server;
  raise specific exceptions, never bare `Exception`; never swallow
  exceptions silently.

### Other Constraints

- **UI testing scope**: UI layers are exempt from Principle III. They MAY
  be tested via snapshot or end-to-end tooling at the team's discretion;
  absence of such tests MUST NOT block a merge.
- **Observability**: Every backend handler and every long-running
  frontend operation MUST emit a structured log entry on entry, exit
  (with outcome), and error. Logs MUST NOT contain secrets, full request
  bodies with PII, or third-party API keys.
- **Input validation**: Every tier MUST validate input received from
  another tier or from the user against the contract before passing it
  to domain code. Validation failures MUST surface a typed error, not a
  silent default.
- **Idempotency**: Backend handlers that perform writes SHOULD be
  idempotent (safe to retry) where the domain allows; non-idempotent
  handlers MUST document the constraint at the contract.

## Development Workflow

- **Red-Green-Refactor**: For every domain logic unit (Principle III),
  the first commit on a branch that introduces it SHOULD contain a
  failing test. Reviewers MAY request evidence of the red phase.
- **Constitution Check gate**: `/speckit-plan` MUST run a Constitution
  Check that fails if a plan:
  1. introduces a third-party package that is neither on the Approved
     Dependencies list nor declared as a lightweight per-feature addition
     in `plan.md` (Principle II); OR introduces a per-feature addition
     that does not meet the Lightweight Library Criteria;
  2. proposes implementing a non-exempt logic unit without a
     corresponding test task ordered before its implementation task
     (Principle III);
  3. proposes a cross-tier feature without a `contracts/` artifact
     (Principle IV);
  4. proposes presentation code that calls persistence or external SDKs
     directly, or any other layer-violation (Principle V).
- **Code review**: Every change MUST be reviewed against these
  principles. Reviewer comments citing a principle by number ("violates
  III") block merge until resolved or the principle is amended.
- **Refactoring discipline**: Refactors that change behavior MUST be
  split from refactors that do not. Behavior-preserving refactors MUST
  keep the test suite green at every commit.
- **Justifying complexity**: Any complexity added beyond the simplest
  solution that satisfies the requirement MUST be justified in the PR
  description with the concrete invariant or failure mode it prevents.

## Governance

This constitution supersedes ad-hoc practices, individual style
preferences, and prior conventions inherited from other projects. When
this document and another guideline conflict, this document wins until
it is amended.

**Amendment procedure**: Amendments are proposed via PR that edits this
file. The PR MUST (a) describe the change in plain language, (b)
classify the version bump per the policy below, (c) update `Last
Amended` to the merge date, and (d) include a Sync Impact Report at the
top of the file listing affected templates and follow-ups. Amendments
require explicit approval from the project owner.

**Versioning policy** (semantic):

- **MAJOR**: A principle is removed, replaced, or redefined in a way
  that invalidates prior compliance, or the framing of the constitution
  changes (e.g., language scope, tier scope).
- **MINOR**: A new principle or section is added, an existing principle
  is materially expanded or relaxed, or new packages are added to the
  Approved Dependencies list.
- **PATCH**: Wording clarifications, typo fixes, non-semantic
  refinements.

**Compliance review**: Every PR review MUST verify constitution
compliance. Violations that ship anyway MUST be tracked as follow-up
issues with remediation owners; they MUST NOT be silently normalized.

**Runtime guidance**: Implementation-level guidance (build commands,
repo layout, day-to-day conventions) lives in `CLAUDE.md` files and
feature plans. This constitution governs only the non-negotiable
principles above.

**Version**: 3.1.0 | **Ratified**: 2026-05-05 | **Last Amended**: 2026-05-05
