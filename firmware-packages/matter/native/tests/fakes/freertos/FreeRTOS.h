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
