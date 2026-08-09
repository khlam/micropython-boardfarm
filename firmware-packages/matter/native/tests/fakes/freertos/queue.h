// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
// Minimal FreeRTOS queue API for the host event-queue unit test.
#pragma once

#include <freertos/FreeRTOS.h>

struct FakeQueue;
using QueueHandle_t = FakeQueue *;

QueueHandle_t xQueueCreate(UBaseType_t queue_length, UBaseType_t item_size);
BaseType_t xQueueSend(QueueHandle_t queue, const void *item, TickType_t ticks_to_wait);
BaseType_t xQueueReceive(QueueHandle_t queue, void *item, TickType_t ticks_to_wait);
BaseType_t xQueuePeek(QueueHandle_t queue, void *item, TickType_t ticks_to_wait);
void vQueueDelete(QueueHandle_t queue);
