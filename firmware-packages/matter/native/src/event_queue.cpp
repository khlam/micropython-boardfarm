// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "event_queue.h"

#include <atomic>
#include <cerrno>

#include <freertos/FreeRTOS.h>
#include <freertos/queue.h>

namespace matter_bridge {

// Matter updates can arrive faster than MicroPython can process them, so this
// bridge keeps fixed-size queues instead of allowing memory use to grow without
// limit. Attribute updates are recoverable from native state and therefore use
// a lossy queue. Commissioning transitions have their own queue so attribute
// traffic cannot displace lifecycle events.
constexpr UBaseType_t EVENT_QUEUE_DEPTH = 32;
constexpr uint32_t HALF_SEQUENCE_RANGE = UINT32_MAX / 2U + 1U;

// Sequence stays native-only: FreeRTOS copies this envelope, while the public C
// boundary continues to expose the stable matter_event payload. At most 64
// events can be retained, so modular comparison remains unambiguous across
// uint32 wrap.
struct QueuedEvent {
    uint32_t sequence;
    matter_event event;
};

// The queues and overflow generation stay private to this file; `static` rather
// than an unnamed namespace because the C entry points below reach them through
// a using-directive. The generation is touched from the CHIP tasks and the VM
// task, so it is atomic. It is never consumed: Python records a generation only
// after a successful resynchronization, leaving a failed pass retryable.
static QueueHandle_t attribute_events = nullptr;
static QueueHandle_t commissioning_events = nullptr;
static std::atomic<uint32_t> overflow_generation{0U};
static std::atomic<uint32_t> next_sequence{0U};

// Guards the two composite queue sequences that must not interleave;
// A spinlock (rather than a mutex) is used because these sections are
// short, non-blocking, and may run from either CHIP-task or VM-task context on
// either core.
static portMUX_TYPE event_queue_lock = portMUX_INITIALIZER_UNLOCKED;

// Send `event` into `queue`, dropping the oldest queued event and retrying if
// full, then notify MicroPython.
static void enqueue_event(QueueHandle_t queue, const matter_event &event, bool count_overflow)
{
    if (queue == nullptr) {
        return;
    }
    const QueuedEvent queued{next_sequence.fetch_add(1U), event};
    if (xQueueSend(queue, &queued, 0) != pdTRUE) {
        portENTER_CRITICAL(&event_queue_lock);
        QueuedEvent discarded;
        xQueueReceive(queue, &discarded, 0);
        xQueueSend(queue, &queued, 0);
        if (count_overflow) {
            overflow_generation.fetch_add(1U);
        }
        portEXIT_CRITICAL(&event_queue_lock);
    }
    matter_bridge_notify_event();
}

bool sequence_precedes(uint32_t left, uint32_t right)
{
    return right - left < HALF_SEQUENCE_RANGE;
}

int create_event_queue(void)
{
    if (attribute_events != nullptr || commissioning_events != nullptr) {
        return EALREADY;
    }
    overflow_generation.store(0U);
    next_sequence.store(0U);
    attribute_events = xQueueCreate(EVENT_QUEUE_DEPTH, sizeof(QueuedEvent));
    if (attribute_events == nullptr) {
        return ENOMEM;
    }
    commissioning_events = xQueueCreate(EVENT_QUEUE_DEPTH, sizeof(QueuedEvent));
    if (commissioning_events == nullptr) {
        destroy_event_queues();
        return ENOMEM;
    }
    return 0;
}

void destroy_event_queues(void)
{
    if (attribute_events != nullptr) {
        vQueueDelete(attribute_events);
        attribute_events = nullptr;
    }
    if (commissioning_events != nullptr) {
        vQueueDelete(commissioning_events);
        commissioning_events = nullptr;
    }
    overflow_generation.store(0U);
    next_sequence.store(0U);
}

void publish_attribute_event(const matter_event &event)
{
    enqueue_event(attribute_events, event, true);
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
    enqueue_event(commissioning_events, event, false);
}

} // namespace matter_bridge

using namespace matter_bridge;

// Try to take the next event waiting for MicroPython. This is non-blocking:
// return true and fill `event` when an event is available, or return false
// immediately when the queue is empty.
extern "C" bool matter_next_event(matter_event *event)
{
    if (event == nullptr) {
        return false;
    }
    QueuedEvent attribute{};
    QueuedEvent commissioning{};
    QueuedEvent queued{};
    
    // Peeking both heads, deciding which queue is globally next, and receiving
    // from it must happen as one atomic step
    portENTER_CRITICAL(&event_queue_lock);
    
    const bool has_attribute =
        attribute_events != nullptr && xQueuePeek(attribute_events, &attribute, 0) == pdTRUE;
    const bool has_commissioning =
        commissioning_events != nullptr && xQueuePeek(commissioning_events, &commissioning, 0) == pdTRUE;
    bool received = false;
    if (has_attribute || has_commissioning) {
        QueueHandle_t selected = attribute_events;
        if (!has_attribute ||
            (has_commissioning && sequence_precedes(commissioning.sequence, attribute.sequence))) {
            selected = commissioning_events;
        }
        received = xQueueReceive(selected, &queued, 0) == pdTRUE;
    }
    portEXIT_CRITICAL(&event_queue_lock);
    if (!received) {
        return false;
    }
    *event = queued.event;
    return true;
}

// Return the attribute queue's current overflow generation without consuming
// it. Python commits a seen generation only after a successful resynchronization.
extern "C" uint32_t matter_overflow_generation(void)
{
    return overflow_generation.load();
}
