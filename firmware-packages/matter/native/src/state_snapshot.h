// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Coalesced controller and commissioning state retained on the CHIP task.
#pragma once

#include <cstddef>
#include <cstdint>

#include "matter/bridge.h"

namespace matter_bridge {

// Reset every retained record and restart the shared revision sequence.
void reset_state_snapshot(void);

// Return the current revision without entering the CHIP task.
uint32_t state_generation(void);

// Retain the newest remote value for one mirrored endpoint path.
bool record_remote_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                             uint32_t value, uint8_t value_type);

// Remove an older remote value after Python successfully publishes the same
// path locally. Returns whether a retained record was removed.
bool clear_remote_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id);

// Retain the latest state for the commissioning session or window lifecycle.
void record_commissioning_state(matter_commissioning_state state);

// Copy all retained records and the coherent generation. Called on the CHIP
// task, which is the sole writer of record contents.
int copy_state_snapshot(matter_snapshot_record *records, size_t capacity, size_t *count,
                        uint32_t *generation);

#ifdef MATTER_STATE_SNAPSHOT_TEST
// Position the revision sequence so host tests can exercise natural wrap.
void set_state_generation_for_test(uint32_t value);
#endif

} // namespace matter_bridge
