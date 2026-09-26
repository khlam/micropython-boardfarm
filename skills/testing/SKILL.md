---
name: testing
description: General guidance for designing clear, reliable tests across languages and test frameworks. Use when writing or improving unit, integration, end-to-end, async, or regression tests, test fixtures, or test doubles.
---

# Writing tests

Before writing or running tests, check the repository's instructions for the test framework, file locations, timing, commands, and execution environment. Follow those rules and the conventions already used by nearby tests.

## Choose and describe the behavior

- Test observable behavior through the public interface. Avoid coupling a test to private implementation details unless those details are themselves a supported contract.
- Choose the smallest test level that exercises the behavior: unit tests for focused logic, integration tests for component boundaries, and end-to-end tests for critical user flows. Use each where it adds confidence; avoid fixed test-count ratios.
- Give each test a name that states the situation and expected outcome. Keep it focused on one behavior or a closely related set of assertions.
- Organize the test as setup, action, and assertion (also called Arrange-Act-Assert or Given-When-Then). Keep setup small enough that the behavior under test is easy to see.

## Make results dependable

- Keep tests isolated: each test should set up the state it needs and should not depend on execution order or shared mutable state.
- Make inputs repeatable. Use fixed values and control time, randomness, environment, and external services when they affect results.
- For async behavior, wait on the operation or a meaningful condition. Avoid timing assumptions and arbitrary sleeps where the framework offers a better wait mechanism.
- Cover relevant success, failure, and boundary cases. Assert the returned result, state change, or error that forms the behavior's contract.
- Prefer assertions that explain what failed. Avoid logging or printing as a substitute for assertions.

## Use data and doubles with care

- Use parameterized or table-driven tests when the same behavior needs several input cases. Use property-based tests when a general invariant matters and the framework supports them.
- Keep fixtures close to the tests that use them. Give defaults clear meaning, and avoid hidden setup that makes individual tests hard to understand.
- Prefer real collaborators when they are fast and predictable. Add a test double only to control an external boundary or observe a meaningful interaction, and keep it as small as the test needs.
- Use double types deliberately: a fake has a working simplified implementation, a stub supplies chosen responses, a spy records calls, and a mock checks programmed expectations. Prefer checking resulting state when it adequately proves the contract.

## Keep the suite useful

- Update tests when behavior changes, while respecting repository rules about when tests may be written.
- Reuse helpers only when they remove meaningful duplication without hiding setup or assertions.
- When a test fails, check whether the behavior, the test setup, or the test's assumptions are wrong. Do not weaken an assertion just to make a failure disappear.
- Run the focused test command first, then any broader checks required by the repository. Use the repository's supported environment and commands.
