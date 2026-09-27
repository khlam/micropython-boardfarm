---
name: testing
description: Use when writing table-driven tests, and at most 3 end-to-end smoke tests per project or package.
---

# Writing tests

Write tests only after the user confirms the feature is final.

Test observable behavior through the public interface. Every test is one of three kinds,
named and tagged as such:

- **Unit.** One table-driven test per public entry point, one row per input class:
  typical, each boundary, each error path.
- **Behavioral fuzz.** Asserts an invariant (round-trip, bounds, no undocumented errors) given inputs.
- **Smoke.** At most 3 per project or package. Runs the real caller path end-to-end mocking at hardware or network boundary, and asserts a result known independently of the code (spec test vector, datasheet example), naming its source.

Extend an existing case table or generator before adding a new test.

Don't write tests that:

- assert on private internals or on test doubles;
- repeat another case's input class and outcome;
- exist only for coverage or exercise dead code;
- depend on timing, test order, or shared state.

Run the smallest relevant set, then the full suite (AGENTS.md § Run tests). When a test
fails, decide whether it is a real bug, a wrong assumption, or a brittle test; never
weaken an assertion before confirming the intended behavior with the user.
