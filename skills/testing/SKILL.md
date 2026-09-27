---
name: testing
description: Use when writing table-driven unit tests, behavioral fuzz tests, and at most 3 end-to-end smoke tests per project or package.
---

# Writing tests

Write tests only after the user confirms the feature is final (AGENTS.md). The language
skill gives the syntax; for Python, see `cpython-syntax` § Tests.

## What a test should be

Every test is exactly one of three kinds, labeled in its name and with the framework's tag
so readers can tell them apart. Make tests table-driven wherever cases share a contract: one
test with a case table beats several near-identical tests.

**Unit.** Asserts one public entry point's output, state change, or error across a table of
input classes: typical, each boundary, each error path, and the failure classes in
`coding-conventions` § Tests. Two rows with the same input class and outcome are one row.

**Behavioral fuzz.** Asserts an invariant (round-trip, bounds, monotonicity, no errors
beyond the documented ones) over many generated inputs plus explicit boundary, malformed,
and adversarial cases. Generation uses a fixed seed so every run is identical. Many cases
per input class are the point, not redundancy.

**Smoke.** Drives the real caller path end-to-end (a project's entry point, or a package
through the code that calls it) from input at the outer boundary to final output. Only the
hardware or network boundary is replaced with a double; everything between runs for real. It
asserts a result known to be correct independently of the code, such as a spec test vector,
a datasheet example, or a hand-verified output, and names that source. It always runs in CI,
never skipped or conditional. Each project and each package holds at most 3; pick the
results whose breakage would matter most.

A test is **bad** when it:

- asserts on private internals, or on test doubles rather than the behavior;
- repeats another test's input class and outcome;
- exercises dead or unreachable code;
- exists only for line or branch coverage;
- depends on timing, test order, or shared state.

## Workflow

1. **Define the behavior.** State observable behavior, invariants, side effects, and the
   reachable entry points. Skip dead or unreachable code.
2. **Build the behavior map.** For each public entry point, list input classes with their
   expected outputs, state changes, and errors, plus interactions between inputs that change
   behavior. Resolve unclear contracts with the user before inventing expectations.
3. **Map existing tests** onto the behavior map. Extend an existing case table or fuzz
   generator rather than adding a new test for behavior that is already partly covered.
4. **Pick the next gap.** Prioritize boundaries, error paths, state transitions, and
   invariants. State what failure the test would catch that existing tests would not.
5. **Write it** as one of the three kinds, black-box, through the public interface.
6. **Run** the smallest relevant set, then the full suite (AGENTS.md § Run tests). For a
   failure, decide whether it is a real bug, a wrong assumption, or a brittle test. Never
   weaken an assertion before confirming the intended contract.
7. **Repeat** steps 4–6 until every remaining gap is equivalent to covered behavior,
   covered by a higher-level test, or too speculative to justify.

## Report

- behaviors covered, by kind;
- cases deliberately left untested, and why;
- bugs found;
- bad tests and dead code seen (removing them is `simplify-diff-to-main`'s job).
