// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// The bounded queues carrying Matter events from the CHIP tasks up to the
// MicroPython VM task. Producers live in this bridge's callbacks; the consumer
// is the queue-drain half of the C API, `matter_next_event()`, defined here
// alongside the queues it reads.
#pragma once

#include "matter/bridge.h"

namespace matter_bridge {

// Create both queues. Returns 0, EALREADY when they already exist, or ENOMEM
// when FreeRTOS cannot allocate them.
// Called before the node exists so that if ESP-Matter produces a callback while
// the node is being created, there is already somewhere safe to store that
// event for MicroPython.
int create_event_queue(void);

// Delete both queues and reset their ordering and overflow counters. This is a
// pre-start rollback operation for a node creation that failed after allocating
// the queues; no callback may still be publishing when it is called.
void destroy_event_queues(void);

// Put one attribute event into its lossy queue for MicroPython to process
// later, then notify the MicroPython side that work is waiting. This function
// never waits, because it may be called from the CHIP task and blocking that
// task would stall Matter networking.
//
// If the queue is full, discard the oldest event and keep the newest one. For
// device state, a recent value is usually more useful than an older value. The
// overflow generation tells MicroPython that at least one event was lost, so it
// can re-read the authoritative attributes. Commissioning transitions use a
// separate queue and cannot be displaced by attribute traffic. Both queues use
// a shared sequence so their consumer still observes cross-kind arrival order.
void publish_attribute_event(const matter_event &event);

// Queue a commissioning-status transition for MicroPython. "Commissioning" is
// Matter's pairing/setup process, where a controller securely adds the device
// to a Matter fabric. This event is not tied to a normal endpoint/cluster/
// attribute path, so the commissioning state is stored in the event's `value`
// field. Its dedicated queue is also bounded and keeps the newest transition
// if commissioning itself produces more than 32 undrained events.
void publish_commissioning(matter_commissioning_state state);

} // namespace matter_bridge
