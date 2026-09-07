// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include <array>
#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstdint>

#include "matter/bridge.h"
#include "state_snapshot.h"

using namespace matter_bridge;

namespace {

struct Snapshot {
    std::array<matter_snapshot_record, MATTER_MAX_SNAPSHOT_RECORDS> records{};
    size_t count = 0;
    uint32_t generation = 0;
};

Snapshot snapshot()
{
    Snapshot result;
    assert(copy_state_snapshot(result.records.data(), result.records.size(), &result.count,
                               &result.generation) == 0);
    return result;
}

void test_repeated_path_coalesces()
{
    reset_state_snapshot();
    assert(record_remote_attribute(1, 6, 0, 10, MATTER_VALUE_UINT8));
    assert(record_remote_attribute(1, 6, 0, 20, MATTER_VALUE_UINT8));

    const Snapshot result = snapshot();
    assert(result.count == 1);
    assert(result.generation == 2);
    assert(result.records[0].revision == 2);
    assert(result.records[0].value == 20);
}

void test_paths_retain_independent_revisions()
{
    reset_state_snapshot();
    assert(record_remote_attribute(1, 6, 0, 1, MATTER_VALUE_BOOL));
    assert(record_remote_attribute(1, 8, 0, 42, MATTER_VALUE_UINT8));

    const Snapshot result = snapshot();
    assert(result.count == 2);
    assert(result.records[0].revision == 1);
    assert(result.records[1].revision == 2);
}

void test_commissioning_lifecycles_are_independent()
{
    reset_state_snapshot();
    record_commissioning_state(MATTER_COMMISSIONING_STARTED);
    record_commissioning_state(MATTER_COMMISSIONING_WINDOW_CLOSED);
    record_commissioning_state(MATTER_COMMISSIONING_COMPLETE);

    const Snapshot result = snapshot();
    assert(result.count == 2);
    assert(result.generation == 3);
    assert(result.records[0].value == MATTER_COMMISSIONING_COMPLETE);
    assert(result.records[0].revision == 3);
    assert(result.records[1].value == MATTER_COMMISSIONING_WINDOW_CLOSED);
    assert(result.records[1].revision == 2);
}

void test_local_publication_clears_pending_remote_state()
{
    reset_state_snapshot();
    assert(record_remote_attribute(1, 6, 0, 1, MATTER_VALUE_BOOL));
    assert(clear_remote_attribute(1, 6, 0));
    assert(!clear_remote_attribute(1, 6, 0));

    const Snapshot result = snapshot();
    assert(result.count == 0);
    assert(result.generation == 2);
}

void test_attribute_capacity_is_fixed()
{
    reset_state_snapshot();
    for (size_t index = 0; index < MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS; ++index) {
        assert(record_remote_attribute(static_cast<uint16_t>(index / 10 + 1), 6,
                                       static_cast<uint32_t>(index % 10),
                                       static_cast<uint32_t>(index), MATTER_VALUE_UINT16));
    }
    assert(!record_remote_attribute(99, 99, 99, 99, MATTER_VALUE_UINT8));
    assert(snapshot().count == MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS);
}

void test_invalid_copy_arguments_and_capacity_are_rejected()
{
    reset_state_snapshot();
    assert(record_remote_attribute(1, 6, 0, 1, MATTER_VALUE_BOOL));
    std::array<matter_snapshot_record, 1> records{};
    size_t count = 0;
    uint32_t generation = 0;
    assert(copy_state_snapshot(nullptr, records.size(), &count, &generation) == EINVAL);
    assert(copy_state_snapshot(records.data(), 0, &count, &generation) == ENOSPC);
}

void test_revision_sequence_wraps_naturally()
{
    reset_state_snapshot();
    set_state_generation_for_test(UINT32_MAX - 1U);
    assert(record_remote_attribute(1, 6, 0, 1, MATTER_VALUE_BOOL));
    assert(record_remote_attribute(1, 8, 0, 2, MATTER_VALUE_UINT8));

    const Snapshot result = snapshot();
    assert(result.generation == 0U);
    assert(result.records[0].revision == UINT32_MAX);
    assert(result.records[1].revision == 0U);
}

} // namespace

int main()
{
    test_repeated_path_coalesces();
    test_paths_retain_independent_revisions();
    test_commissioning_lifecycles_are_independent();
    test_local_publication_clears_pending_remote_state();
    test_attribute_capacity_is_fixed();
    test_invalid_copy_arguments_and_capacity_are_rejected();
    test_revision_sequence_wraps_naturally();
    return 0;
}
