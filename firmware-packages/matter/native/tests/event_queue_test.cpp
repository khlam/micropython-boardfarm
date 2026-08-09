// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
// Host unit tests for the native Matter event-queue policy.
#include <cassert>
#include <cerrno>
#include <cstddef>
#include <cstdint>
#include <cstring>
#include <deque>
#include <vector>

#include <freertos/queue.h>

#include "event_queue.h"
#include "matter/bridge.h"

struct FakeQueue {
    UBaseType_t capacity;
    UBaseType_t item_size;
    std::deque<std::vector<std::byte>> items;
};

namespace {

size_t notification_count = 0;
size_t queue_creation_attempts = 0;
size_t queue_deletion_count = 0;
size_t failed_creation_attempt = 0;

matter_event attribute_event(uint32_t value)
{
    matter_event event{};
    event.kind = MATTER_EVENT_ATTRIBUTE;
    event.endpoint_id = 1;
    event.cluster_id = 6U;
    event.attribute_id = 0U;
    event.value = value;
    event.value_type = MATTER_VALUE_UINT8;
    event.origin = MATTER_ORIGIN_REMOTE;
    return event;
}

matter_event next_event(void)
{
    matter_event event{};
    assert(matter_next_event(&event));
    return event;
}

void assert_queue_empty(void)
{
    matter_event event{};
    assert(!matter_next_event(&event));
}

void test_partial_creation_failure_releases_the_first_queue(void)
{
    failed_creation_attempt = 2;
    assert(matter_bridge::create_event_queue() == ENOMEM);
    assert(queue_deletion_count == 1U);
    assert_queue_empty();

    failed_creation_attempt = 0;
    assert(matter_bridge::create_event_queue() == 0);
    assert(matter_bridge::create_event_queue() == EALREADY);
}

void test_cross_kind_arrival_order_is_preserved(void)
{
    matter_bridge::publish_attribute_event(attribute_event(10U));
    matter_bridge::publish_commissioning(MATTER_COMMISSIONING_WINDOW_OPENED);
    matter_bridge::publish_attribute_event(attribute_event(11U));

    assert(next_event().value == 10U);
    assert(next_event().value == MATTER_COMMISSIONING_WINDOW_OPENED);
    assert(next_event().value == 11U);
    assert_queue_empty();
}

void test_commissioning_is_protected_from_a_full_attribute_queue(void)
{
    for (uint32_t value = 0; value < 32U; ++value) {
        matter_bridge::publish_attribute_event(attribute_event(value));
    }
    matter_bridge::publish_commissioning(MATTER_COMMISSIONING_COMPLETE);

    for (uint32_t value = 0; value < 32U; ++value) {
        const matter_event attribute = next_event();
        assert(attribute.kind == MATTER_EVENT_ATTRIBUTE);
        assert(attribute.value == value);
    }
    const matter_event commissioning = next_event();
    assert(commissioning.kind == MATTER_EVENT_COMMISSIONING);
    assert(commissioning.value == MATTER_COMMISSIONING_COMPLETE);
    assert_queue_empty();
    assert(matter_overflow_generation() == 0U);
}

void test_attribute_overflow_cannot_evict_commissioning(void)
{
    matter_bridge::publish_commissioning(MATTER_COMMISSIONING_WINDOW_OPENED);
    for (uint32_t value = 100U; value < 133U; ++value) {
        matter_bridge::publish_attribute_event(attribute_event(value));
    }

    const matter_event commissioning = next_event();
    assert(commissioning.kind == MATTER_EVENT_COMMISSIONING);
    assert(commissioning.value == MATTER_COMMISSIONING_WINDOW_OPENED);
    for (uint32_t value = 101U; value < 133U; ++value) {
        const matter_event attribute = next_event();
        assert(attribute.kind == MATTER_EVENT_ATTRIBUTE);
        assert(attribute.value == value);
    }
    assert_queue_empty();
    assert(matter_overflow_generation() == 1U);
    assert(matter_overflow_generation() == 1U);
}

void test_overflow_generation_is_monotonic(void)
{
    for (uint32_t value = 200U; value < 234U; ++value) {
        matter_bridge::publish_attribute_event(attribute_event(value));
    }

    assert(matter_overflow_generation() == 3U);
    for (uint32_t value = 202U; value < 234U; ++value) {
        assert(next_event().value == value);
    }
    assert_queue_empty();
}

void test_commissioning_overflow_keeps_newest_without_advancing_attribute_generation(void)
{
    const uint32_t attribute_generation = matter_overflow_generation();
    for (uint32_t index = 0; index < 33U; ++index) {
        const auto state = static_cast<matter_commissioning_state>(index % 5U);
        matter_bridge::publish_commissioning(state);
    }

    for (uint32_t index = 1; index < 33U; ++index) {
        const matter_event commissioning = next_event();
        assert(commissioning.kind == MATTER_EVENT_COMMISSIONING);
        assert(commissioning.value == index % 5U);
    }
    assert_queue_empty();
    assert(matter_overflow_generation() == attribute_generation);
}

} // namespace

QueueHandle_t xQueueCreate(UBaseType_t queue_length, UBaseType_t item_size)
{
    ++queue_creation_attempts;
    if (queue_creation_attempts == failed_creation_attempt) {
        return nullptr;
    }
    return new FakeQueue{queue_length, item_size, {}};
}

BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t ticks_to_wait)
{
    assert(ticks_to_wait == 0U);
    if (queue == nullptr || queue->items.size() >= queue->capacity) {
        return pdFALSE;
    }
    std::vector<std::byte> copy(queue->item_size);
    std::memcpy(copy.data(), item, queue->item_size);
    queue->items.push_back(copy);
    return pdTRUE;
}

BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t ticks_to_wait)
{
    assert(ticks_to_wait == 0U);
    if (queue == nullptr || queue->items.empty()) {
        return pdFALSE;
    }
    std::memcpy(item, queue->items.front().data(), queue->item_size);
    queue->items.pop_front();
    return pdTRUE;
}

BaseType_t xQueuePeek(QueueHandle_t queue, void *item, TickType_t ticks_to_wait)
{
    assert(ticks_to_wait == 0U);
    if (queue == nullptr || queue->items.empty()) {
        return pdFALSE;
    }
    std::memcpy(item, queue->items.front().data(), queue->item_size);
    return pdTRUE;
}

void vQueueDelete(QueueHandle_t queue)
{
    ++queue_deletion_count;
    delete queue;
}

void matter_bridge_notify_event(void)
{
    ++notification_count;
}

int main(void)
{
    test_partial_creation_failure_releases_the_first_queue();
    assert(!matter_next_event(nullptr));
    assert(matter_overflow_generation() == 0U);

    test_cross_kind_arrival_order_is_preserved();
    test_commissioning_is_protected_from_a_full_attribute_queue();
    test_attribute_overflow_cannot_evict_commissioning();
    test_overflow_generation_is_monotonic();
    test_commissioning_overflow_keeps_newest_without_advancing_attribute_generation();
    assert(notification_count == 137U);

    matter_bridge::destroy_event_queues();
    assert(queue_deletion_count == 3U);
    assert(matter_bridge::create_event_queue() == 0);
    matter_bridge::destroy_event_queues();
    assert(queue_deletion_count == 5U);
}
