// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// The state the whole bridge shares: which endpoints belong to it, and whether
// the Matter stack is running yet. Owned by stack.cpp, which builds the node.
#pragma once

#include <cstdint>

namespace matter_bridge {

// Return true only for endpoints created through this bridge. A Matter node can
// contain other endpoints, including endpoint 0 and endpoints owned internally
// by ESP-Matter. Filtering them here prevents unrelated updates from being sent
// to MicroPython.
bool endpoint_exists(uint16_t endpoint_id);

// Return true once `matter_stack_start()` has brought CHIP up. Before that,
// setup code may modify ESP-Matter directly from the caller's task; afterwards
// every mutation must be marshalled onto the CHIP task instead.
bool stack_started(void);

} // namespace matter_bridge
