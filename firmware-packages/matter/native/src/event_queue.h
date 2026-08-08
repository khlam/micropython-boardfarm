// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// The bounded queue carrying Matter events from the CHIP tasks up to the
// MicroPython VM task. Producers live in this bridge's callbacks; the consumer
// is the queue-drain half of the C API, `matter_next_event()`, defined here
// alongside the queue it reads.
#pragma once

#include "matter/bridge.h"

namespace matter_bridge {

// Create the queue. Returns 0, or ENOMEM when FreeRTOS cannot allocate it.
// Called before the node exists so that if ESP-Matter produces a callback while
// the node is being created, there is already somewhere safe to store that
// event for MicroPython.
int create_event_queue(void);

// Put one Matter event into the queue for MicroPython to process later, then
// notify the MicroPython side that work is waiting. This function never waits,
// because it may be called from the CHIP task and blocking that task
// would stall Matter networking.
//
// If the queue is full, discard the oldest event and keep the newest one. For
// device state, a recent value is usually more useful than an older value. The
// overflow flag tells MicroPython that at least one event was lost, so it can
// re-read the authoritative attributes.
void publish_event(const matter_event &event);

// Queue a commissioning-status transition for MicroPython. "Commissioning" is
// Matter's pairing/setup process, where a controller securely adds the device
// to a Matter fabric. This event is not tied to a normal endpoint/cluster/
// attribute path, so the commissioning state is stored in the event's `value`
// field.
void publish_commissioning(matter_commissioning_state state);

} // namespace matter_bridge
