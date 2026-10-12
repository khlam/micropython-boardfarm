---
name: testing
description: Use when writing or changing tests, and before changing firmware behavior. Test-first, table-driven tests that a reader understands without opening the code.
---

# Writing tests

## Test first

1. Confirm the intended behavior with the user.
2. Add or extend a test that states it, or that reproduces the bug. Run it and show
   that it fails for the expected reason.
3. Write the least code that makes it pass, then run the full suite.

## Readable tests

A reader understands each case without opening a helper or the code under test.

- Every test is a case table, even with one row. Extend an existing table before
  adding a new test.
- Each row is a `namedtuple` with named fields, never a bare positional tuple. Its
  `id` reads as given-when-then: `vacant-empty-report-stays-vacant`.
- A row gives the starting state, the inputs in order, and the expected outputs.
  Inputs are values the firmware receives (targets, Matter writes, clock ticks),
  never callables, step names, or a mini-language.
- Fake only the hardware and network boundary: UART, `matter_native`, the pixel,
  the clock. Never patch firmware code.
- Assert only on what leaves the code: return values, Matter attributes, pixel
  colour, JSON lines. Never read a private attribute.

## Kinds

- **Unit.** One test per public entry point, one row per input class: typical, each
  boundary, each error path. For a state machine, one row per edge in its README
  diagram plus one per input that keeps the state.
- **Scenario.** Runs the project's real `main()` loops through the boundary fakes,
  one row per line of the README's contract. These catch wiring regressions that
  unit tests miss.
- **Behavioral fuzz.** Asserts an invariant (round-trip, bounds, no undocumented
  errors) across generated inputs.
- **Smoke.** At most 3 per project or package. Asserts a result known independently
  of the code (spec test vector, datasheet example), naming its source.

Don't write tests that:

- repeat another row's input class and outcome;
- exist only for coverage or exercise dead code;
- depend on wall time, test order, or shared state.

## Run

Run the smallest relevant set, then the full suite. When a test fails, decide whether it is a real bug, a wrong assumption, or a brittle test;
never weaken an assertion before confirming the intended behavior with the user.
