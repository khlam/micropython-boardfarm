// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "state_snapshot.h"

#include <array>
#include <atomic>
#include <cerrno>

namespace matter_bridge {
namespace {

struct SnapshotSlot {
    bool present = false;
    matter_snapshot_record record{};
};

// The final two slots are reserved for the session and window lifecycles, so
// attribute traffic cannot evict either commissioning record.
std::array<SnapshotSlot, MATTER_MAX_SNAPSHOT_RECORDS> slots{};
std::atomic<uint32_t> generation{0U};

uint32_t next_revision()
{
    return generation.fetch_add(1U) + 1U;
}

SnapshotSlot *find_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    SnapshotSlot *empty = nullptr;
    for (size_t index = 0; index < MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS; ++index) {
        SnapshotSlot &slot = slots[index];
        if (!slot.present) {
            if (empty == nullptr) {
                empty = &slot;
            }
            continue;
        }
        const matter_snapshot_record &record = slot.record;
        if (record.endpoint_id == endpoint_id && record.cluster_id == cluster_id &&
            record.attribute_id == attribute_id) {
            return &slot;
        }
    }
    return empty;
}

} // namespace

void reset_state_snapshot(void)
{
    slots.fill({});
    generation.store(0U);
}

uint32_t state_generation(void)
{
    return generation.load();
}

bool record_remote_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                             uint32_t value, uint8_t value_type)
{
    SnapshotSlot *slot = find_attribute(endpoint_id, cluster_id, attribute_id);
    if (slot == nullptr) {
        return false;
    }
    slot->present = true;
    slot->record.revision = next_revision();
    slot->record.kind = MATTER_SNAPSHOT_ATTRIBUTE;
    slot->record.endpoint_id = endpoint_id;
    slot->record.cluster_id = cluster_id;
    slot->record.attribute_id = attribute_id;
    slot->record.value = value;
    slot->record.value_type = value_type;
    return true;
}

bool clear_remote_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    // find_attribute() answers with a free slot when the path is not retained,
    // so `present` is what separates a hit from an empty one.
    SnapshotSlot *slot = find_attribute(endpoint_id, cluster_id, attribute_id);
    if (slot == nullptr || !slot->present) {
        return false;
    }
    slot->present = false;
    next_revision();
    return true;
}

void record_commissioning_state(matter_commissioning_state state)
{
    const size_t index = MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS +
                         (state > MATTER_COMMISSIONING_FAILED ? 1U : 0U);
    SnapshotSlot &slot = slots[index];
    slot.present = true;
    slot.record.revision = next_revision();
    slot.record.kind = MATTER_SNAPSHOT_COMMISSIONING;
    slot.record.value = static_cast<uint32_t>(state);
    slot.record.value_type = MATTER_VALUE_UINT8;
}

int copy_state_snapshot(matter_snapshot_record *records, size_t capacity, size_t *count,
                        uint32_t *captured_generation)
{
    if (records == nullptr || count == nullptr || captured_generation == nullptr) {
        return EINVAL;
    }
    size_t required = 0;
    for (const SnapshotSlot &slot : slots) {
        required += slot.present ? 1U : 0U;
    }
    if (required > capacity) {
        return ENOSPC;
    }
    size_t output_count = 0;
    for (const SnapshotSlot &slot : slots) {
        if (slot.present) {
            records[output_count++] = slot.record;
        }
    }
    *count = output_count;
    *captured_generation = generation.load();
    return 0;
}

#ifdef MATTER_STATE_SNAPSHOT_TEST
void set_state_generation_for_test(uint32_t value)
{
    generation.store(value);
}
#endif

} // namespace matter_bridge
