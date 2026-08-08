// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "event_queue.h"

#include <atomic>
#include <cerrno>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace matter_bridge {

// Matter updates can arrive faster than MicroPython can process them, so this
// bridge keeps a fixed-size event queue instead of allowing memory use to grow
// without limit. If the queue fills, old events may be dropped and Python is
// told to re-read the current state.
constexpr UBaseType_t kEventQueueDepth = 32;

// The queue and its overflow flag stay private to this file; `static` rather
// than an unnamed namespace because the C entry points below reach them through
// a using-directive. Both are touched from the CHIP tasks and the VM task, so
// the flag is atomic.
static QueueHandle_t events = nullptr;
static std::atomic<bool> queue_overflowed{false};

int create_event_queue(void)
{
    events = xQueueCreate(kEventQueueDepth, sizeof(matter_event));
    return events == nullptr ? ENOMEM : 0;
}

void publish_event(const matter_event &event)
{
    if (events == nullptr) {
        return;
    }
    if (xQueueSend(events, &event, 0) != pdTRUE) {
        matter_event discarded;
        xQueueReceive(events, &discarded, 0);
        xQueueSend(events, &event, 0);
        queue_overflowed.store(true);
    }
    matter_bridge_notify_event();
}

void publish_commissioning(matter_commissioning_state state)
{
    const matter_event event{
        MATTER_EVENT_COMMISSIONING,
        0,
        0U,
        0U,
        static_cast<uint32_t>(state),
        MATTER_VALUE_UINT8,
        MATTER_ORIGIN_REMOTE,
    };
    publish_event(event);
}

} // namespace matter_bridge

using namespace matter_bridge;

// Try to take the next event waiting for MicroPython. This is non-blocking:
// return true and fill `event` when an event is available, or return false
// immediately when the queue is empty.
extern "C" bool matter_next_event(matter_event *event)
{
    return event != nullptr && events != nullptr && xQueueReceive(events, event, 0) == pdTRUE;
}

// Tell MicroPython whether the event queue has overflowed since the previous
// check. `exchange(false)` returns the old flag and clears it at the same time.
// A true result means Python should re-read Matter state because some queued
// updates may have been dropped.
extern "C" bool matter_take_overflow(void)
{
    return queue_overflowed.exchange(false);
}
