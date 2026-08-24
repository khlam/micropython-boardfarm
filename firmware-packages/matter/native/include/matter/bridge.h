// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// C boundary between MicroPython and the native ESP-Matter protocol bridge.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Every code below is part of the Python-facing contract: the frozen `matter`
// package mirrors these numbers as its own constants and indexes tables with
// them, so a value may be appended but never renumbered.

// Endpoint schemas the bridge knows how to build. Mirrors matter.EndpointType.
enum matter_endpoint_type {
    MATTER_ENDPOINT_ON_OFF_LIGHT = 0,
    MATTER_ENDPOINT_DIMMABLE_LIGHT = 1,
    MATTER_ENDPOINT_EXTENDED_COLOR_LIGHT = 2,
    MATTER_ENDPOINT_OCCUPANCY_SENSOR = 3,
};

// Which fields of a queued event carry meaning. An attribute event fills the
// whole path; a commissioning event carries its state in `value` alone.
enum matter_event_kind {
    MATTER_EVENT_ATTRIBUTE = 0,
    MATTER_EVENT_COMMISSIONING = 1,
};

// What caused an attribute update. Only remote updates are ever enqueued — the
// bridge drops its own echo at the source — but the codes stay aligned with
// the Python `Origin` names, MATTER_ORIGIN_RESTORE included, so the two sides
// describe an update the same way.
enum matter_event_origin {
    MATTER_ORIGIN_REMOTE = 0,
    MATTER_ORIGIN_LOCAL = 1,
    MATTER_ORIGIN_RESTORE = 2,
};

// Pairing transitions reported to Python. Ordered to index the decode table in
// the `matter` package, which pairs each state with its lifecycle name.
enum matter_commissioning_state {
    MATTER_COMMISSIONING_STARTED = 0,
    MATTER_COMMISSIONING_COMPLETE = 1,
    MATTER_COMMISSIONING_FAILED = 2,
    MATTER_COMMISSIONING_WINDOW_OPENED = 3,
    MATTER_COMMISSIONING_WINDOW_CLOSED = 4,
};

// How to read the `uint32_t` an attribute value travels in. The three widths
// cover every attribute the supported schemas expose; anything else is refused
// rather than truncated.
enum matter_value_type {
    MATTER_VALUE_BOOL = 0,
    MATTER_VALUE_UINT8 = 1,
    MATTER_VALUE_UINT16 = 2,
};

// One event crossing the queue. Flat and pointer-free by design, because
// FreeRTOS copies it in and out by value: an event can therefore outlive the
// CHIP task that produced it without referring to anything that task owns.
struct matter_event {
    uint8_t kind;
    uint16_t endpoint_id;
    uint32_t cluster_id;
    uint32_t attribute_id;
    uint32_t value;
    uint8_t value_type;
    uint8_t origin;
};

// The label size is the Matter maximum plus its terminator. The fabric ceiling
// bounds every fabric array in the bridge, so a caller sizes one up front
// instead of asking how many fabrics there are and then asking for them.
enum { MATTER_FABRIC_LABEL_SIZE = 33, MATTER_MAX_FABRICS = 16 };

// Non-secret identity of one commissioned fabric. Keys and certificates stay
// inside CHIP; nothing here is privileged enough to leak into a JSON report.
struct matter_fabric {
    uint8_t index;
    uint64_t fabric_id;
    uint64_t node_id;
    uint16_t vendor_id;
    char label[MATTER_FABRIC_LABEL_SIZE];
};

// Every int-returning call reports 0 or an errno, which matter_module.c raises as
// OSError. The setup calls below run on the caller's task straight against
// esp_matter, which is safe only because nothing is started yet.

// Create the sole node and the queue its callbacks publish into.
// Returns EALREADY when a node exists, ENOMEM, or EIO.
int matter_node_create(void);

// Add one endpoint of `endpoint_type` and write back the ID the stack assigned.
// Returns EINVAL for an unknown type, before a node exists, or after start;
// ENOSPC past the endpoint ceiling; or EIO.
int matter_endpoint_create(uint8_t endpoint_type, uint16_t *endpoint_id);

// Seed one attribute before the stack starts, so the value lands on what the
// stack will restore from flash rather than on a running mirror.
// Returns EINVAL once started, ENOENT for an unknown path, ERANGE or ENOTSUP
// when the value does not fit the attribute's stored type, or EIO.
int matter_attribute_set_initial(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id, uint32_t value,
                                 uint8_t value_type);

// Bring up CHIP. Endpoints are fixed from here on, and every later mutation is
// marshalled onto the CHIP task instead of applied directly.
// Returns EINVAL when no node exists or it already started, or EIO.
int matter_stack_start(void);

// Read one attribute out of the running stack, waiting up to `timeout_ms` for
// the CHIP task to service the request.
// Returns EINVAL, ENOENT, EIO, EBUSY when the request could not be scheduled,
// or ETIMEDOUT — none of which say anything about the attribute itself, so a
// caller may retry.
int matter_attribute_get(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id, uint32_t *value,
                         uint8_t *value_type, uint32_t timeout_ms);

// Publish a locally decided value so Matter subscribers observe it. The echo
// this provokes is suppressed rather than queued.
// Returns the same codes as matter_attribute_get, plus ERANGE or ENOTSUP for a
// value the attribute's stored type cannot hold.
int matter_attribute_publish(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id, uint32_t value,
                             uint8_t value_type, uint32_t timeout_ms);

// Pop one queued event without waiting, returning false when the queue is dry.
bool matter_next_event(struct matter_event *event);

// Return the attribute queue's overflow generation without consuming it.
// Python records a generation only after it successfully re-reads state, so a
// failed resynchronization remains pending. Natural uint32 wrap is allowed.
uint32_t matter_overflow_generation(void);

// Reopen pairing for `timeout_s`. Returns EALREADY when a window is already
// open, or the scheduling errnos matter_attribute_get lists.
int matter_open_commissioning_window(uint16_t timeout_s, uint32_t timeout_ms);

// Copy up to `capacity` fabric records out of the fabric table and write how
// many were written. Returns ENOSPC when `capacity` is too small to hold them
// all — leaving the array untouched rather than partly filled — EOVERFLOW when
// the table itself exceeds MATTER_MAX_FABRICS, or the scheduling errnos
// matter_attribute_get lists.
int matter_get_fabrics(struct matter_fabric *fabrics, size_t capacity, size_t *count, uint32_t timeout_ms);

// Drop one fabric by its operational index. Removing the last one leaves the
// device pairable: the bridge reopens a basic commissioning window itself.
// Returns ENOENT for an unknown index, or the scheduling errnos above.
int matter_remove_fabric(uint8_t fabric_index, uint32_t timeout_ms);

// Ask CHIP to erase its persisted state and reboot. Success means the request
// was accepted, which is before the reboot lands. Returns the scheduling
// errnos above on failure.
int matter_factory_reset(uint32_t timeout_ms);

// Enough for "255.255.255.255" and its terminator.
enum { MATTER_ADDRESS_SIZE = 16 };

// Copy the IPv4 address commissioning obtained for the Wi-Fi station interface.
// Nothing here configures the radio: CHIP owns it, and this only reads back what
// it already brought up, which is the one piece of that state an application
// cannot reach any other way.
// Returns ENOTCONN while the interface has no address, EINVAL for a buffer
// smaller than MATTER_ADDRESS_SIZE, or EIO.
int matter_network_address(char *address, size_t capacity);

// Implemented by matter_module.c. CHIP tasks use it only after enqueueing an
// event; it schedules the registered drain callback onto the VM task.
void matter_bridge_notify_event(void);

#ifdef __cplusplus
}
#endif
