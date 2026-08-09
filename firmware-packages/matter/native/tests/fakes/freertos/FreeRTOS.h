// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
// Minimal FreeRTOS types for the host event-queue unit test.
#pragma once

#include <cstdint>

using BaseType_t = int;
using UBaseType_t = unsigned int;
using TickType_t = uint32_t;

constexpr BaseType_t pdFALSE = 0;
constexpr BaseType_t pdTRUE = 1;

// Minimal FreeRTOS SMP spinlock for the host event-queue unit test
struct portMUX_TYPE {
    int unused;
};
constexpr portMUX_TYPE portMUX_INITIALIZER_UNLOCKED{0};
inline void portENTER_CRITICAL(portMUX_TYPE *) {}
inline void portEXIT_CRITICAL(portMUX_TYPE *) {}
