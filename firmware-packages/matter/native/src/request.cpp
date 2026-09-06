// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// The VM-task side of a Request, and the C entry points built on it. Each one
// checks its arguments, fills in a Request, and blocks on the CHIP task for at
// most the caller's timeout — so a stalled stack surfaces as ETIMEDOUT rather
// than a hung MicroPython VM.
#include "request.h"

#include <algorithm>
#include <cerrno>
#include <new>

#include <platform/CHIPDeviceLayer.h>

#include "chip_operations.h"
#include "matter/bridge.h"
#include "stack.h"
#include "state_snapshot.h"

namespace matter_bridge {

Request *new_request(RequestKind kind)
{
    auto *request = new (std::nothrow) Request;
    if (request == nullptr) {
        return nullptr;
    }
    request->done = xSemaphoreCreateBinaryStatic(&request->done_storage);
    request->kind = kind;
    if (kind == RequestKind::kGetFabrics) {
        request->fabrics = new (std::nothrow) matter_fabric[MATTER_MAX_FABRICS]{};
        if (request->fabrics == nullptr) {
            vSemaphoreDelete(request->done);
            delete request;
            return nullptr;
        }
    }
    else if (kind == RequestKind::kSnapshot) {
        request->snapshot_records =
            new (std::nothrow) matter_snapshot_record[MATTER_MAX_SNAPSHOT_RECORDS]{};
        if (request->snapshot_records == nullptr) {
            vSemaphoreDelete(request->done);
            delete request;
            return nullptr;
        }
    }
    return request;
}

// `ScheduleWork` arranges for `apply_request()` to run on the correct task; the
// caller then waits on the Request's semaphore.
//
// If scheduling fails, the CHIP task will never receive the Request, so its
// reference is released immediately here. If waiting times out instead, the
// CHIP task's reference is left alone — see the refcount note on `Request` in
// request.h for why.
int schedule_and_wait(Request *request, uint32_t timeout_ms)
{
    if (chip::DeviceLayer::PlatformMgr().ScheduleWork(apply_request, reinterpret_cast<intptr_t>(request)) !=
        CHIP_NO_ERROR) {
        release(request);
        return EBUSY;
    }
    if (xSemaphoreTake(request->done, pdMS_TO_TICKS(timeout_ms)) != pdTRUE) {
        return ETIMEDOUT;
    }
    return request->result;
}

void release(Request *request)
{
    if (request->references.fetch_sub(1) == 1) {
        vSemaphoreDelete(request->done);
        delete[] request->fabrics;
        delete[] request->snapshot_records;
        delete request;
    }
}

namespace {

// Owns the VM-task side release() call for the seven wrappers below, so each one
// states only its precondition and its own fields rather than repeating
// allocate/null-check/release around them. `get()` is nullptr exactly when
// allocation failed; the wrapper still has to turn that into ENOMEM itself,
// since there is no exception to carry it out.
class RequestGuard {
public:
    explicit RequestGuard(RequestKind kind) : request_(new_request(kind)) {}
    ~RequestGuard()
    {
        if (request_ != nullptr) {
            release(request_);
        }
    }
    RequestGuard(const RequestGuard &) = delete;
    RequestGuard &operator=(const RequestGuard &) = delete;

    Request *get() const { return request_; }

private:
    Request *request_;
};

} // namespace

} // namespace matter_bridge

using namespace matter_bridge;

// Read one live Matter attribute after the stack has started. This public wrapper
// creates a read Request, sends it to the CHIP task, waits for completion,
// and copies the returned value and type back to the caller.
extern "C" int matter_attribute_get(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                                     uint32_t *value, uint8_t *value_type, uint32_t timeout_ms)
{
    if (!stack_started() || value == nullptr || value_type == nullptr || !endpoint_exists(endpoint_id)) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kRead);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    request->endpoint_id = endpoint_id;
    request->cluster_id = cluster_id;
    request->attribute_id = attribute_id;
    const int result = schedule_and_wait(request, timeout_ms);
    if (result == 0) {
        *value = request->value;
        *value_type = request->value_type;
    }
    return result;
}

// Publish one local attribute batch after the stack has started. The fixed
// request storage survives a caller timeout while the CHIP task finishes.
extern "C" int matter_attributes_publish(uint16_t endpoint_id,
                                          const matter_attribute_update *updates, size_t count,
                                          uint32_t timeout_ms)
{
    if (!stack_started() || !endpoint_exists(endpoint_id) || updates == nullptr || count == 0 ||
        count > MATTER_MAX_ATTRIBUTE_BATCH) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kPublishBatch);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    request->endpoint_id = endpoint_id;
    std::copy_n(updates, count, request->attribute_updates);
    request->attribute_update_count = count;
    return schedule_and_wait(request, timeout_ms);
}

extern "C" uint32_t matter_state_generation(void)
{
    return state_generation();
}

// Ask the CHIP task for one coherent copy of all retained remote and
// commissioning state. The request owns its buffer across a caller timeout;
// only a completed request is copied into caller-owned memory.
extern "C" int matter_get_state_snapshot(matter_snapshot_record *records, size_t capacity,
                                          size_t *count, uint32_t *generation, uint32_t timeout_ms)
{
    if (!stack_started() || records == nullptr || count == nullptr || generation == nullptr) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kSnapshot);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    int result = schedule_and_wait(request, timeout_ms);
    if (result == 0) {
        if (request->snapshot_count > capacity) {
            result = ENOSPC;
        } else {
            std::copy_n(request->snapshot_records, request->snapshot_count, records);
            *count = request->snapshot_count;
            *generation = request->snapshot_generation;
        }
    }
    return result;
}

// Ask the running Matter stack to reopen pairing for `timeout_s` seconds.
// `timeout_ms` is separate: it controls only how long this C caller is willing
// to wait for the CHIP task to accept and complete the request.
extern "C" int matter_open_commissioning_window(uint16_t timeout_s, uint32_t timeout_ms)
{
    if (!stack_started()) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kOpenCommissioningWindow);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    request->timeout_s = timeout_s;
    return schedule_and_wait(request, timeout_ms);
}

// Ask the CHIP task for a snapshot of every Matter fabric this device belongs
// to. We cannot know the required array size safely until the CHIP task has read
// the fabric table. If the caller's output array is too small, return ENOSPC and
// copy nothing rather than returning an incomplete fabric list.
extern "C" int matter_get_fabrics(matter_fabric *fabrics, size_t capacity, size_t *count, uint32_t timeout_ms)
{
    if (!stack_started() || fabrics == nullptr || count == nullptr) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kGetFabrics);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    int result = schedule_and_wait(request, timeout_ms);
    if (result == 0) {
        if (request->fabric_count > capacity) {
            result = ENOSPC;
        } else {
            std::copy_n(request->fabrics, request->fabric_count, fabrics);
            *count = request->fabric_count;
        }
    }
    return result;
}

// Remove this device from one Matter fabric identified by its fabric index.
// This is similar to removing one smart-home administrator/controller domain
// from the device; other fabrics, if any, remain intact.
extern "C" int matter_remove_fabric(uint8_t fabric_index, uint32_t timeout_ms)
{
    if (!stack_started()) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kRemoveFabric);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    request->fabric_index = fabric_index;
    return schedule_and_wait(request, timeout_ms);
}

// Request a full Matter factory reset. CHIP's configuration manager performs
// the reset, which is expected to erase Matter configuration such as
// commissioning/fabric state according to the platform's factory-reset logic.
extern "C" int matter_factory_reset(uint32_t timeout_ms)
{
    if (!stack_started()) {
        return EINVAL;
    }
    RequestGuard guard(RequestKind::kFactoryReset);
    Request *request = guard.get();
    if (request == nullptr) {
        return ENOMEM;
    }
    return schedule_and_wait(request, timeout_ms);
}
