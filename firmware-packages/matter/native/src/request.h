// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// One unit of work handed from the MicroPython VM task to the CHIP task.
// After the stack starts, only that task may touch live Matter state, so every
// public call that reads or changes it is packaged here and scheduled across.
#pragma once

#include <atomic>
#include <cerrno>
#include <cstddef>
#include <cstdint>

#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>

#include "matter/bridge.h"

namespace matter_bridge {

// These values describe the kinds of work that MicroPython can ask the
// CHIP task to perform. Callers use normal C functions such as
// `matter_attribute_get()`; those functions create the appropriate internal
// request rather than exposing this request format directly.
enum class RequestKind : uint8_t {
    kRead,
    kPublishBatch,
    kSnapshot,
    kOpenCommissioningWindow,
    kGetFabrics,
    kRemoveFabric,
    kFactoryReset,
};

// A Request carries one operation from the MicroPython VM task to the
// CHIP task and carries the result back. It contains the common fields
// needed for attribute reads/writes plus optional fields for commissioning and
// snapshot and fabric-management operations.
//
// The request owns a semaphore named `done`. The caller waits on this semaphore
// while the CHIP task performs the work. Large result storage is allocated only
// for fabric and state snapshots so ordinary attribute updates stay small.
//
// The reference count starts at two because two tasks may still use the same
// request: the caller and the CHIP task. If the caller times out, the CHIP task
// may still be finishing the operation. Reference counting prevents either side
// from deleting the request while the other side is still using it.
struct Request {
    std::atomic<unsigned int> references{2};
    SemaphoreHandle_t done = nullptr;
    StaticSemaphore_t done_storage{};
    RequestKind kind = RequestKind::kRead;
    int result = EIO;
    uint16_t endpoint_id = 0;
    uint32_t cluster_id = 0;
    uint32_t attribute_id = 0;
    uint32_t value = 0;
    uint8_t value_type = 0;
    matter_attribute_update attribute_updates[MATTER_MAX_ATTRIBUTE_BATCH]{};
    size_t attribute_update_count = 0;
    uint16_t timeout_s = 0;
    uint8_t fabric_index = 0;
    matter_fabric *fabrics = nullptr;
    size_t fabric_count = 0;
    matter_snapshot_record *snapshot_records = nullptr;
    size_t snapshot_count = 0;
    uint32_t snapshot_generation = 0;
};

// Allocate and initialize a Request without throwing a C++ exception. Embedded
// devices can run short on memory, so allocation failure is returned as nullptr
// and later reported to the caller. Fabric-list and state-snapshot requests
// allocate their respective bounded result arrays.
Request *new_request(RequestKind kind);

// Send a Request to the CHIP task and wait for its answer, for at most
// `timeout_ms`. Returns the operation's own result, EBUSY when the request could
// not be scheduled, or ETIMEDOUT. The caller still owns a reference either way,
// so it must call `release()` once it has read whatever it needs.
int schedule_and_wait(Request *request, uint32_t timeout_ms);

// Release one task's ownership of a Request. The Request and any attached
// resources are deleted only when both the caller and the CHIP task have
// released their references.
void release(Request *request);

} // namespace matter_bridge
