// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Host tests for the retained state snapshot: one case table per entry point of
// state_snapshot.h, then a model-based fuzz. The header promises no output order
// (Python sorts by revision), so every check finds a record by its path or its
// commissioning state, never by its index.
#include <array>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <map>
#include <random>
#include <set>
#include <string>
#include <tuple>
#include <vector>

#include "matter/bridge.h"
#include "state_snapshot.h"

using namespace matter_bridge;

namespace {

int failure_count = 0;

// Report a failure under its case name and keep going, so one run lists every
// broken row.
void fail(const std::string &case_name, const std::string &what)
{
    ++failure_count;
    std::fprintf(stderr, "FAIL %s: %s\n", case_name.c_str(), what.c_str());
}

void check_equal(uint64_t actual, uint64_t expected, const std::string &case_name,
                 const std::string &what)
{
    if (actual != expected) {
        fail(case_name,
             what + " is " + std::to_string(actual) + ", want " + std::to_string(expected));
    }
}

struct Path {
    uint16_t endpoint_id;
    uint32_t cluster_id;
    uint32_t attribute_id;
};

bool operator==(const Path &left, const Path &right)
{
    return left.endpoint_id == right.endpoint_id && left.cluster_id == right.cluster_id &&
           left.attribute_id == right.attribute_id;
}

bool operator<(const Path &left, const Path &right)
{
    return std::tie(left.endpoint_id, left.cluster_id, left.attribute_id) <
           std::tie(right.endpoint_id, right.cluster_id, right.attribute_id);
}

Path path_of(const matter_snapshot_record &copied)
{
    return {copied.endpoint_id, copied.cluster_id, copied.attribute_id};
}

std::string describe(const Path &path)
{
    char text[40];
    std::snprintf(text, sizeof(text), "path %u/0x%04x/0x%04x", unsigned(path.endpoint_id),
                  unsigned(path.cluster_id), unsigned(path.attribute_id));
    return text;
}

constexpr uint32_t ON_OFF_CLUSTER = 0x0006;
constexpr uint32_t LEVEL_CONTROL_CLUSTER = 0x0008;
constexpr uint32_t COLOR_CONTROL_CLUSTER = 0x0300;

// Each path below differs from ON_OFF in exactly one component.
constexpr Path ON_OFF = {1, ON_OFF_CLUSTER, 0x0000};
constexpr Path ON_OFF_ENDPOINT_2 = {2, ON_OFF_CLUSTER, 0x0000};
constexpr Path LEVEL = {1, LEVEL_CONTROL_CLUSTER, 0x0000};
constexpr Path ON_TIME = {1, ON_OFF_CLUSTER, 0x4001};

// The distinct paths fill_attribute_table() records, one per attribute slot, on
// a cluster the paths above never use.
constexpr Path table_path(size_t index)
{
    return {static_cast<uint16_t>(index / MATTER_MAX_ATTRIBUTE_BATCH + 1), COLOR_CONTROL_CLUSTER,
            static_cast<uint32_t>(index % MATTER_MAX_ATTRIBUTE_BATCH)};
}

constexpr Path LAST_TABLE_PATH = table_path(MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS - 1);

struct Snapshot {
    std::array<matter_snapshot_record, MATTER_MAX_SNAPSHOT_RECORDS> records{};
    size_t count = 0;
    uint32_t generation = 0;
};

enum class Op { RESET, POSITION_GENERATION, FILL_ATTRIBUTE_TABLE, RECORD, CLEAR, COMMISSION };

// One call a scripted case makes. `accepted` is the result expected from
// record_remote_attribute or clear_remote_attribute.
struct Step {
    Op op;
    Path path;
    uint32_t value; // RECORD's value, POSITION_GENERATION's target, or COMMISSION's state
    uint8_t value_type;
    bool accepted;
};

Step reset()
{
    return {Op::RESET, {}, 0, 0, true};
}

Step position_generation(uint32_t generation)
{
    return {Op::POSITION_GENERATION, {}, generation, 0, true};
}

Step fill_attribute_table()
{
    return {Op::FILL_ATTRIBUTE_TABLE, {}, 0, 0, true};
}

Step record(Path path, uint32_t value, uint8_t value_type)
{
    return {Op::RECORD, path, value, value_type, true};
}

Step refused_record(Path path, uint32_t value, uint8_t value_type)
{
    return {Op::RECORD, path, value, value_type, false};
}

Step clear(Path path)
{
    return {Op::CLEAR, path, 0, 0, true};
}

Step refused_clear(Path path)
{
    return {Op::CLEAR, path, 0, 0, false};
}

Step commission(matter_commissioning_state state)
{
    return {Op::COMMISSION, {}, static_cast<uint32_t>(state), 0, true};
}

// A record the copied snapshot must hold exactly once. Attributes are found by
// path; a commissioning record carries nothing but its state, so it is found by
// that.
struct Expected {
    uint8_t kind;
    Path path;
    uint32_t value;
    uint8_t value_type;
    uint32_t revision;
};

Expected attribute(Path path, uint32_t value, uint8_t value_type, uint32_t revision)
{
    return {MATTER_SNAPSHOT_ATTRIBUTE, path, value, value_type, revision};
}

Expected commissioning(matter_commissioning_state state, uint32_t revision)
{
    return {MATTER_SNAPSHOT_COMMISSIONING, {}, static_cast<uint32_t>(state), 0, revision};
}

struct ScriptCase {
    const char *name;
    std::vector<Step> steps;
    std::vector<Expected> expected;
    size_t count; // every retained record, including the ones fill_attribute_table() wrote
};

const std::vector<ScriptCase> RESET_CASES = {
    {"reset drops a full snapshot and restarts revisions",
     {commission(MATTER_COMMISSIONING_STARTED), fill_attribute_table(),
      commission(MATTER_COMMISSIONING_WINDOW_OPENED), reset(),
      record(ON_OFF, 1, MATTER_VALUE_BOOL)},
     {attribute(ON_OFF, 1, MATTER_VALUE_BOOL, 1)},
     1},
};

const std::vector<ScriptCase> RECORD_CASES = {
    {"repeated path coalesces to the newest value",
     {record(LEVEL, 10, MATTER_VALUE_UINT8), record(LEVEL, 20, MATTER_VALUE_UINT8)},
     {attribute(LEVEL, 20, MATTER_VALUE_UINT8, 2)},
     1},
    {"paths differing in one component keep independent revisions",
     {record(ON_OFF, 1, MATTER_VALUE_BOOL), record(ON_OFF_ENDPOINT_2, 0, MATTER_VALUE_BOOL),
      record(LEVEL, 42, MATTER_VALUE_UINT8), record(ON_TIME, 300, MATTER_VALUE_UINT16)},
     {attribute(ON_OFF, 1, MATTER_VALUE_BOOL, 1),
      attribute(ON_OFF_ENDPOINT_2, 0, MATTER_VALUE_BOOL, 2),
      attribute(LEVEL, 42, MATTER_VALUE_UINT8, 3), attribute(ON_TIME, 300, MATTER_VALUE_UINT16, 4)},
     4},
    {"full table refuses a new path",
     {fill_attribute_table(), refused_record(ON_OFF, 1, MATTER_VALUE_BOOL)},
     {},
     MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS},
    {"full table still coalesces a retained path",
     {fill_attribute_table(), record(LAST_TABLE_PATH, 7, MATTER_VALUE_UINT16)},
     {attribute(LAST_TABLE_PATH, 7, MATTER_VALUE_UINT16,
                MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS + 1)},
     MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS},
    {"revision sequence wraps naturally",
     {position_generation(UINT32_MAX - 1U), record(ON_OFF, 1, MATTER_VALUE_BOOL),
      record(LEVEL, 2, MATTER_VALUE_UINT8)},
     {attribute(ON_OFF, 1, MATTER_VALUE_BOOL, UINT32_MAX),
      attribute(LEVEL, 2, MATTER_VALUE_UINT8, 0)},
     2},
};

const std::vector<ScriptCase> CLEAR_CASES = {
    {"local publication clears pending remote state once",
     {record(ON_OFF, 1, MATTER_VALUE_BOOL), clear(ON_OFF), refused_clear(ON_OFF)},
     {},
     0},
    {"clear refuses a path differing in one component",
     {record(ON_OFF, 1, MATTER_VALUE_BOOL), refused_clear(ON_OFF_ENDPOINT_2),
      refused_clear(LEVEL), refused_clear(ON_TIME)},
     {attribute(ON_OFF, 1, MATTER_VALUE_BOOL, 1)},
     1},
    {"clear refuses an unknown path on a full table",
     {fill_attribute_table(), refused_clear(ON_OFF)},
     {},
     MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS},
    {"clear frees a slot on a full table",
     {fill_attribute_table(), clear(table_path(0)), record(ON_OFF, 1, MATTER_VALUE_BOOL)},
     {attribute(ON_OFF, 1, MATTER_VALUE_BOOL, MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS + 2)},
     MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS},
};

// One row per state: each replaces its own lifecycle's earlier record and leaves
// the other lifecycle's record alone.
const std::vector<ScriptCase> COMMISSIONING_CASES = {
    {"STARTED replaces only the session record",
     {commission(MATTER_COMMISSIONING_COMPLETE), commission(MATTER_COMMISSIONING_WINDOW_OPENED),
      commission(MATTER_COMMISSIONING_STARTED)},
     {commissioning(MATTER_COMMISSIONING_STARTED, 3),
      commissioning(MATTER_COMMISSIONING_WINDOW_OPENED, 2)},
     2},
    {"COMPLETE replaces only the session record",
     {commission(MATTER_COMMISSIONING_STARTED), commission(MATTER_COMMISSIONING_WINDOW_CLOSED),
      commission(MATTER_COMMISSIONING_COMPLETE)},
     {commissioning(MATTER_COMMISSIONING_COMPLETE, 3),
      commissioning(MATTER_COMMISSIONING_WINDOW_CLOSED, 2)},
     2},
    {"FAILED, the last session state, replaces only the session record",
     {commission(MATTER_COMMISSIONING_STARTED), commission(MATTER_COMMISSIONING_WINDOW_OPENED),
      commission(MATTER_COMMISSIONING_FAILED)},
     {commissioning(MATTER_COMMISSIONING_FAILED, 3),
      commissioning(MATTER_COMMISSIONING_WINDOW_OPENED, 2)},
     2},
    {"WINDOW_OPENED, the first window state, replaces only the window record",
     {commission(MATTER_COMMISSIONING_STARTED), commission(MATTER_COMMISSIONING_WINDOW_CLOSED),
      commission(MATTER_COMMISSIONING_WINDOW_OPENED)},
     {commissioning(MATTER_COMMISSIONING_STARTED, 1),
      commissioning(MATTER_COMMISSIONING_WINDOW_OPENED, 3)},
     2},
    {"WINDOW_CLOSED replaces only the window record",
     {commission(MATTER_COMMISSIONING_STARTED), commission(MATTER_COMMISSIONING_WINDOW_OPENED),
      commission(MATTER_COMMISSIONING_WINDOW_CLOSED)},
     {commissioning(MATTER_COMMISSIONING_STARTED, 1),
      commissioning(MATTER_COMMISSIONING_WINDOW_CLOSED, 3)},
     2},
    {"reserved slots keep both lifecycles beside a full attribute table",
     {commission(MATTER_COMMISSIONING_STARTED), fill_attribute_table(),
      commission(MATTER_COMMISSIONING_WINDOW_OPENED)},
     {commissioning(MATTER_COMMISSIONING_STARTED, 1),
      commissioning(MATTER_COMMISSIONING_WINDOW_OPENED,
                    MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS + 2)},
     MATTER_MAX_SNAPSHOT_RECORDS},
};

enum class NullArgument { NONE, RECORDS, COUNT, GENERATION };

struct CopyCase {
    const char *name;
    size_t retained; // distinct attribute paths recorded before the copy
    size_t capacity;
    NullArgument null_argument;
    int result;
};

const std::vector<CopyCase> COPY_CASES = {
    {"empty state copies nothing at generation zero", 0, MATTER_MAX_SNAPSHOT_RECORDS,
     NullArgument::NONE, 0},
    {"capacity equal to the retained count", 1, 1, NullArgument::NONE, 0},
    {"capacity below the retained count", 1, 0, NullArgument::NONE, ENOSPC},
    {"null records", 1, 1, NullArgument::RECORDS, EINVAL},
    {"null count", 1, 1, NullArgument::COUNT, EINVAL},
    {"null generation", 1, 1, NullArgument::GENERATION, EINVAL},
};

// Record the first `count` table paths, each holding its own index.
void record_table_paths(size_t count, const std::string &case_name, const std::string &label)
{
    for (size_t index = 0; index < count; ++index) {
        const Path path = table_path(index);
        if (!record_remote_attribute(path.endpoint_id, path.cluster_id, path.attribute_id,
                                     static_cast<uint32_t>(index), MATTER_VALUE_UINT16)) {
            fail(case_name, label + " refused " + describe(path));
        }
    }
}

// Apply one step and return the generation it must leave behind: one step per
// accepted mutation, none for a refused record or clear.
uint32_t apply_step(const Step &step, uint32_t generation, const std::string &case_name,
                    const std::string &label)
{
    switch (step.op) {
    case Op::RESET:
        reset_state_snapshot();
        return 0;
    case Op::POSITION_GENERATION:
        set_state_generation_for_test(step.value);
        return step.value;
    case Op::FILL_ATTRIBUTE_TABLE:
        record_table_paths(MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS, case_name, label + " fill");
        return generation + MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS;
    case Op::RECORD:
        check_equal(record_remote_attribute(step.path.endpoint_id, step.path.cluster_id,
                                            step.path.attribute_id, step.value, step.value_type),
                    step.accepted, case_name,
                    label + " record " + describe(step.path) + " accepted");
        break;
    case Op::CLEAR:
        check_equal(clear_remote_attribute(step.path.endpoint_id, step.path.cluster_id,
                                           step.path.attribute_id),
                    step.accepted, case_name,
                    label + " clear " + describe(step.path) + " accepted");
        break;
    case Op::COMMISSION:
        record_commissioning_state(static_cast<matter_commissioning_state>(step.value));
        break;
    }
    return generation + (step.accepted ? 1U : 0U);
}

std::string describe(const Expected &expected)
{
    if (expected.kind == MATTER_SNAPSHOT_COMMISSIONING) {
        return "commissioning state " + std::to_string(expected.value);
    }
    return describe(expected.path);
}

bool identifies(const Expected &expected, const matter_snapshot_record &copied)
{
    if (copied.kind != expected.kind) {
        return false;
    }
    if (expected.kind == MATTER_SNAPSHOT_COMMISSIONING) {
        return copied.value == expected.value;
    }
    return path_of(copied) == expected.path;
}

void check_expected_record(const Snapshot &snapshot, const Expected &expected,
                           const std::string &case_name)
{
    const std::string what = describe(expected);
    const matter_snapshot_record *found = nullptr;
    size_t occurrences = 0;
    for (size_t index = 0; index < snapshot.count; ++index) {
        if (identifies(expected, snapshot.records[index])) {
            found = &snapshot.records[index];
            ++occurrences;
        }
    }
    check_equal(occurrences, 1, case_name, what + " occurrences");
    if (found == nullptr) {
        return;
    }
    check_equal(found->revision, expected.revision, case_name, what + " revision");
    if (expected.kind == MATTER_SNAPSHOT_ATTRIBUTE) {
        check_equal(found->value, expected.value, case_name, what + " value");
        check_equal(found->value_type, expected.value_type, case_name, what + " value_type");
    }
}

// state_generation() is checked after every step and against the copied
// generation, so every row of every scripted table covers its contract.
void run_script_case(const char *table, const ScriptCase &test_case)
{
    const std::string case_name = std::string(table) + " / " + test_case.name;
    reset_state_snapshot();
    uint32_t generation = 0;
    for (size_t index = 0; index < test_case.steps.size(); ++index) {
        const std::string label = "step " + std::to_string(index + 1);
        generation = apply_step(test_case.steps[index], generation, case_name, label);
        check_equal(state_generation(), generation, case_name, label + " state_generation()");
    }

    Snapshot snapshot;
    const int result = copy_state_snapshot(snapshot.records.data(), snapshot.records.size(),
                                           &snapshot.count, &snapshot.generation);
    check_equal(result, 0, case_name, "copy_state_snapshot() result");
    if (result != 0) {
        return;
    }
    check_equal(snapshot.count, test_case.count, case_name, "record count");
    check_equal(snapshot.generation, generation, case_name, "copied generation");
    for (const Expected &expected : test_case.expected) {
        check_expected_record(snapshot, expected, case_name);
    }
}

void run_script_table(const char *table, const std::vector<ScriptCase> &cases)
{
    for (const ScriptCase &test_case : cases) {
        run_script_case(table, test_case);
    }
}

void run_copy_case(const CopyCase &test_case)
{
    const std::string case_name = std::string("copy_state_snapshot / ") + test_case.name;
    reset_state_snapshot();
    record_table_paths(test_case.retained, case_name, "setup");

    Snapshot snapshot;
    const int result = copy_state_snapshot(
        test_case.null_argument == NullArgument::RECORDS ? nullptr : snapshot.records.data(),
        test_case.capacity,
        test_case.null_argument == NullArgument::COUNT ? nullptr : &snapshot.count,
        test_case.null_argument == NullArgument::GENERATION ? nullptr : &snapshot.generation);
    check_equal(result, test_case.result, case_name, "result");
    if (result != 0 || test_case.result != 0) {
        return;
    }
    check_equal(snapshot.count, test_case.retained, case_name, "record count");
    check_equal(snapshot.generation, test_case.retained, case_name, "copied generation");
    for (size_t index = 0; index < test_case.retained; ++index) {
        check_expected_record(snapshot,
                              attribute(table_path(index), static_cast<uint32_t>(index),
                                        MATTER_VALUE_UINT16, static_cast<uint32_t>(index + 1)),
                              case_name);
    }
}

// The contract restated independently of the implementation: the newest value
// per path within a fixed attribute capacity, one record per commissioning
// lifecycle, and one generation step per successful mutation.
struct ModelAttribute {
    uint32_t value;
    uint8_t value_type;
    uint32_t revision;
};

struct ModelLifecycle {
    bool present;
    uint32_t state;
    uint32_t revision;
};

struct Model {
    std::map<Path, ModelAttribute> attributes;
    ModelLifecycle session{};
    ModelLifecycle window{};
    uint32_t generation = 0;
};

// Which outcomes the generated sequence reached, so a change to the operation
// mix cannot quietly stop exercising one.
struct FuzzTally {
    size_t coalesced = 0;
    size_t refused = 0;
    size_t cleared = 0;
    size_t clear_missed = 0;
};

// 200 paths against 160 attribute slots, so the table fills and refuses while
// repeated paths still coalesce.
constexpr size_t FUZZ_ENDPOINTS = 10;
constexpr std::array<uint32_t, 2> FUZZ_CLUSTERS = {ON_OFF_CLUSTER, LEVEL_CONTROL_CLUSTER};
constexpr size_t FUZZ_ATTRIBUTES = 10;
static_assert(FUZZ_ENDPOINTS * FUZZ_CLUSTERS.size() * FUZZ_ATTRIBUTES >
                  MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS,
              "the fuzz path space must overflow the attribute table");

bool is_window_state(uint32_t state)
{
    return state == MATTER_COMMISSIONING_WINDOW_OPENED ||
           state == MATTER_COMMISSIONING_WINDOW_CLOSED;
}

// std::mt19937's output is fixed by the standard but the distributions' is not,
// so drawing with `%` keeps the sequence identical on every standard library.
uint32_t draw(std::mt19937 &generator, size_t bound)
{
    return static_cast<uint32_t>(generator() % bound);
}

Path draw_path(std::mt19937 &generator)
{
    const uint16_t endpoint_id = static_cast<uint16_t>(1 + draw(generator, FUZZ_ENDPOINTS));
    const uint32_t cluster_id = FUZZ_CLUSTERS[draw(generator, FUZZ_CLUSTERS.size())];
    const uint32_t attribute_id = draw(generator, FUZZ_ATTRIBUTES);
    return {endpoint_id, cluster_id, attribute_id};
}

void fuzz_record(std::mt19937 &generator, Model &model, FuzzTally &tally,
                 const std::string &case_name)
{
    static constexpr std::array<uint8_t, 3> VALUE_TYPES = {
        MATTER_VALUE_BOOL, MATTER_VALUE_UINT8, MATTER_VALUE_UINT16};
    const Path path = draw_path(generator);
    const uint32_t value = static_cast<uint32_t>(generator());
    const uint8_t value_type = VALUE_TYPES[draw(generator, VALUE_TYPES.size())];
    const bool retained = model.attributes.count(path) == 1;
    const bool fits = retained || model.attributes.size() < MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS;
    check_equal(record_remote_attribute(path.endpoint_id, path.cluster_id, path.attribute_id,
                                        value, value_type),
                fits, case_name, "record " + describe(path) + " accepted");
    if (!fits) {
        ++tally.refused;
        return;
    }
    tally.coalesced += retained ? 1U : 0U;
    model.generation += 1U;
    model.attributes[path] = {value, value_type, model.generation};
}

void fuzz_clear(std::mt19937 &generator, Model &model, FuzzTally &tally,
                const std::string &case_name)
{
    const Path path = draw_path(generator);
    const bool retained = model.attributes.erase(path) == 1;
    check_equal(clear_remote_attribute(path.endpoint_id, path.cluster_id, path.attribute_id),
                retained, case_name, "clear " + describe(path) + " accepted");
    if (!retained) {
        ++tally.clear_missed;
        return;
    }
    ++tally.cleared;
    model.generation += 1U;
}

void fuzz_commission(std::mt19937 &generator, Model &model)
{
    static constexpr std::array<matter_commissioning_state, 5> STATES = {
        MATTER_COMMISSIONING_STARTED, MATTER_COMMISSIONING_COMPLETE, MATTER_COMMISSIONING_FAILED,
        MATTER_COMMISSIONING_WINDOW_OPENED, MATTER_COMMISSIONING_WINDOW_CLOSED};
    const matter_commissioning_state state = STATES[draw(generator, STATES.size())];
    record_commissioning_state(state);
    model.generation += 1U;
    ModelLifecycle &lifecycle = is_window_state(state) ? model.window : model.session;
    lifecycle = {true, static_cast<uint32_t>(state), model.generation};
}

std::string describe_fields(uint32_t value, uint8_t value_type, uint32_t revision)
{
    return "value " + std::to_string(value) + " type " + std::to_string(value_type) +
           " revision " + std::to_string(revision);
}

void check_model_attribute(const Model &model, const matter_snapshot_record &copied,
                           std::set<Path> &seen, const std::string &case_name)
{
    const Path path = path_of(copied);
    if (!seen.insert(path).second) {
        fail(case_name, describe(path) + " appears more than once");
    }
    const auto retained = model.attributes.find(path);
    if (retained == model.attributes.end()) {
        fail(case_name, describe(path) + " is copied but not retained by the model");
        return;
    }
    // Compared before formatting: this runs for every record after every operation.
    const ModelAttribute &want = retained->second;
    if (copied.value != want.value || copied.value_type != want.value_type ||
        copied.revision != want.revision) {
        const std::string held = describe_fields(copied.value, copied.value_type, copied.revision);
        const std::string wanted = describe_fields(want.value, want.value_type, want.revision);
        fail(case_name, describe(path) + " holds " + held + ", want " + wanted);
    }
}

void check_model_lifecycle(const Model &model, const matter_snapshot_record &copied,
                           std::array<bool, 2> &seen, const std::string &case_name)
{
    const bool window = is_window_state(copied.value);
    const std::string what = window ? "window record" : "session record";
    if (seen[window ? 1 : 0]) {
        fail(case_name, what + " appears more than once");
    }
    seen[window ? 1 : 0] = true;
    const ModelLifecycle &lifecycle = window ? model.window : model.session;
    if (!lifecycle.present) {
        fail(case_name, what + " is copied but not retained by the model");
        return;
    }
    check_equal(copied.value, lifecycle.state, case_name, what + " state");
    check_equal(copied.revision, lifecycle.revision, case_name, what + " revision");
}

void check_against_model(const Model &model, const std::string &case_name)
{
    Snapshot snapshot;
    const int result = copy_state_snapshot(snapshot.records.data(), snapshot.records.size(),
                                           &snapshot.count, &snapshot.generation);
    check_equal(result, 0, case_name, "copy_state_snapshot() result");
    if (result != 0) {
        return;
    }
    if (snapshot.count > MATTER_MAX_SNAPSHOT_RECORDS) {
        fail(case_name, "record count exceeds MATTER_MAX_SNAPSHOT_RECORDS");
        return;
    }
    const size_t lifecycles = (model.session.present ? 1U : 0U) + (model.window.present ? 1U : 0U);
    check_equal(snapshot.count, model.attributes.size() + lifecycles, case_name, "record count");
    check_equal(snapshot.generation, model.generation, case_name, "copied generation");
    check_equal(state_generation(), model.generation, case_name, "state_generation()");

    std::set<uint32_t> revisions;
    std::set<Path> paths;
    std::array<bool, 2> lifecycles_seen{};
    for (size_t index = 0; index < snapshot.count; ++index) {
        const matter_snapshot_record &copied = snapshot.records[index];
        if (!revisions.insert(copied.revision).second) {
            fail(case_name, "revision " + std::to_string(copied.revision) + " repeats");
        }
        if (copied.kind == MATTER_SNAPSHOT_ATTRIBUTE) {
            check_model_attribute(model, copied, paths, case_name);
        } else if (copied.kind == MATTER_SNAPSHOT_COMMISSIONING) {
            check_model_lifecycle(model, copied, lifecycles_seen, case_name);
        } else {
            fail(case_name, "unknown record kind " + std::to_string(copied.kind));
        }
    }
}

void fuzz_against_model()
{
    constexpr uint32_t SEED = 20260927U;
    constexpr size_t OPERATION_COUNT = 10000;
    // Start near the top of the range so the sequence wraps early in the run.
    constexpr uint32_t START_GENERATION = UINT32_MAX - 1000U;

    std::mt19937 generator(SEED);
    Model model;
    FuzzTally tally;
    reset_state_snapshot();
    set_state_generation_for_test(START_GENERATION);
    model.generation = START_GENERATION;
    for (size_t index = 0; index < OPERATION_COUNT; ++index) {
        const std::string case_name = "fuzz / operation " + std::to_string(index + 1);
        const int failures_before = failure_count;
        const uint32_t roll = draw(generator, 100);
        if (roll < 70) {
            fuzz_record(generator, model, tally, case_name);
        } else if (roll < 85) {
            fuzz_clear(generator, model, tally, case_name);
        } else {
            fuzz_commission(generator, model);
        }
        check_against_model(model, case_name);
        if (failure_count != failures_before) {
            // The model no longer describes the unit, so every later operation
            // would only repeat this failure.
            return;
        }
    }

    const std::string case_name = "fuzz / generated sequence";
    if (tally.coalesced == 0) {
        fail(case_name, "no record coalesced a retained path");
    }
    if (tally.refused == 0) {
        fail(case_name, "no record met a full attribute table");
    }
    if (tally.cleared == 0) {
        fail(case_name, "no clear removed a retained path");
    }
    if (tally.clear_missed == 0) {
        fail(case_name, "no clear missed");
    }
    if (model.generation >= START_GENERATION) {
        fail(case_name, "the revision sequence never wrapped");
    }
}

} // namespace

int main()
{
    run_script_table("reset_state_snapshot", RESET_CASES);
    run_script_table("record_remote_attribute", RECORD_CASES);
    run_script_table("clear_remote_attribute", CLEAR_CASES);
    run_script_table("record_commissioning_state", COMMISSIONING_CASES);
    for (const CopyCase &test_case : COPY_CASES) {
        run_copy_case(test_case);
    }
    fuzz_against_model();

    if (failure_count != 0) {
        std::fprintf(stderr, "%d state snapshot check(s) failed\n", failure_count);
        return 1;
    }
    std::printf("state snapshot tests passed\n");
    return 0;
}
