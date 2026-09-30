---
name: testing
description: Use when writing tests. Prefer table-driven tests.
---

# Writing tests

Write tests only after the user confirms the feature is final.

Every test is table-driven, even with a single row. Design towards extending an existing
case table or generator before adding a new test.

Test observable behavior through the public interface. Every test is one of three kinds:

- **Unit.** One test per public entry point, one row per input class: typical, each boundary, each error path.
- **Behavioral fuzz.** Asserts an invariant (round-trip, bounds, no undocumented errors) across generated inputs.
- **Smoke.** At most 3 per project or package. Runs caller path end-to-end mocking only the hardware or network boundary, and asserts a result known independently of the code (spec test vector, datasheet example), naming its source.


Don't write tests that:

- assert on private internals or on test doubles;
- repeat another case's input class and outcome;
- exist only for coverage or exercise dead code;
- depend on timing, test order, or shared state.

Run the smallest relevant set, then the full suite (AGENTS.md § Run tests). When a test
fails, decide whether it is a real bug, a wrong assumption, or a brittle test; never
weaken an assertion before confirming the intended behavior with the user.
