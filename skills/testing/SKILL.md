---
name: testing
description: Use to plan, write, review, and iteratively fuzz-test focused unit behavior until it is sufficiently covered without creating redundant tests or preserving dead code.
---

## Workflow

1. **Define the behavior**
   - State the feature’s observable behavior, invariants, important side effects, and existing behavior that must remain unchanged.
   - Identify the real entry points and code paths currently reachable by the feature.
   - Explicitly exclude dead, unreachable, deprecated, or unused code unless the task is to revive it.

2. **Build the behavior map**
   - For each relevant function, enumerate meaningful input classes or parameter ranges.
   - For each class, record expected outputs, state changes, errors/throws, and important boundary conditions.
   - Include interactions between inputs when they can change behavior.
   - Mark assumptions that are unclear; resolve the contract before inventing tests.

3. **Audit the existing tests**
   - Locate tests covering the same behavior or nearby logic.
   - Map each test to one or more behavior-map cases.
   - Identify gaps, redundant tests, brittle implementation-coupled assertions, and tests that only exercise unreachable/dead code.
   - Preserve existing tests that provide distinct behavioral value; do not duplicate coverage just to increase test count.

4. **Choose the next test target**
   - Select the highest-value uncovered behavior: prioritize boundaries, error paths, state transitions, combinations, invariants, and regression-prone logic.
   - Prefer a small number of representative cases over exhaustive enumeration when behavior is equivalent.
   - Add a test only when it distinguishes a meaningful behavior, catches a plausible regression, or validates an important invariant.
   - Before adding it, state **what failure the test would catch** and why existing tests would not catch it.

5. **Write focused tests**
   - Keep tests black-box where practical; assert observable behavior rather than implementation details.
   - Use parameterization/property-based generation where many inputs share the same contract.
   - For fuzzing, generate inputs from the behavior map and include explicit boundary, malformed, adversarial, and representative cases.
   - Avoid tests whose only purpose is line/branch coverage.

6. **Run and interpret**
   - Run the smallest relevant test set, then the broader suite.
   - For failures, determine whether the cause is a real behavior bug, an invalid assumption, a brittle test, or dead/unreachable code.
   - Fix the smallest justified thing. Never weaken a test merely to make it pass without first validating the intended contract.

7. **Repeat**
   - Rebuild the gap list after every meaningful change.
   - Repeat Steps 4–6 until the remaining uncovered cases are either:
     - unreachable/dead,
     - equivalent to already-covered behavior,
     - protected by stronger higher-level tests, or
     - too speculative to justify a test.

8. **Stop with evidence**
   - Stop when additional tests have no clear behavioral value.
   - Report:
     - behaviors covered,
     - meaningful cases intentionally left untested and why,
     - bugs/regressions found,
     - redundant/dead tests or code removed,
     - and why further testing is unlikely to add useful signal.
   - Prefer removing obsolete tests over keeping tests solely because they already exist.