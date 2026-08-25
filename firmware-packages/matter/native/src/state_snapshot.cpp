// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "state_snapshot.h"

#include <array>
#include <atomic>
#include <cerrno>

namespace matter_bridge {
namespace {

struct AttributeSlot {
    bool present = false;
    matter_snapshot_record record{};
};

struct CommissioningSlot {
    bool present = false;
    matter_commissioning_state state = MATTER_COMMISSIONING_STARTED;
    uint32_t revision = 0;
};

std::array<AttributeSlot, MATTER_MAX_ATTRIBUTE_SNAPSHOT_RECORDS> attributes{};
CommissioningSlot commissioning_session{};
CommissioningSlot commissioning_window{};
std::atomic<uint32_t> generation{0U};

uint32_t next_revision()
{
    return generation.fetch_add(1U) + 1U;
}

AttributeSlot *find_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    AttributeSlot *empty = nullptr;
    for (AttributeSlot &slot : attributes) {
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

void append_commissioning(matter_snapshot_record *records, size_t *count,
                          const CommissioningSlot &slot)
{
    if (!slot.present) {
        return;
    }
    matter_snapshot_record &record = records[(*count)++];
    record.revision = slot.revision;
    record.kind = MATTER_SNAPSHOT_COMMISSIONING;
    record.value = static_cast<uint32_t>(slot.state);
    record.value_type = MATTER_VALUE_UINT8;
}

} // namespace

void reset_state_snapshot(void)
{
    for (AttributeSlot &slot : attributes) {
        slot = {};
    }
    commissioning_session = {};
    commissioning_window = {};
    generation.store(0U);
}

uint32_t state_generation(void)
{
    return generation.load();
}

bool record_remote_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                             uint32_t value, uint8_t value_type)
{
    AttributeSlot *slot = find_attribute(endpoint_id, cluster_id, attribute_id);
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
    for (AttributeSlot &slot : attributes) {
        if (!slot.present) {
            continue;
        }
        const matter_snapshot_record &record = slot.record;
        if (record.endpoint_id == endpoint_id && record.cluster_id == cluster_id &&
            record.attribute_id == attribute_id) {
            slot.present = false;
            next_revision();
            return true;
        }
    }
    return false;
}

void record_commissioning_state(matter_commissioning_state state)
{
    CommissioningSlot &slot = state <= MATTER_COMMISSIONING_FAILED ? commissioning_session
                                                                   : commissioning_window;
    slot.present = true;
    slot.state = state;
    slot.revision = next_revision();
}

int copy_state_snapshot(matter_snapshot_record *records, size_t capacity, size_t *count,
                        uint32_t *captured_generation)
{
    if (records == nullptr || count == nullptr || captured_generation == nullptr) {
        return EINVAL;
    }
    size_t required = commissioning_session.present ? 1U : 0U;
    required += commissioning_window.present ? 1U : 0U;
    for (const AttributeSlot &slot : attributes) {
        required += slot.present ? 1U : 0U;
    }
    if (required > capacity) {
        return ENOSPC;
    }
    size_t output_count = 0;
    for (const AttributeSlot &slot : attributes) {
        if (slot.present) {
            records[output_count++] = slot.record;
        }
    }
    append_commissioning(records, &output_count, commissioning_session);
    append_commissioning(records, &output_count, commissioning_window);
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
