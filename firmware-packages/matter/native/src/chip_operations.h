// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// The far side of a Request: everything that runs on the CHIP task.
// After the Matter stack starts, this is the only task allowed to directly
// manipulate ESP-Matter state and the fabric table. Nothing reached from here
// may block, because blocking the CHIP task would also block Matter's
// networking and event processing.
#pragma once

#include <cstdint>

namespace matter_bridge {

// The dispatcher executed by the CHIP task. `ScheduleWork()` passes it a
// Request as `argument`, the matching operation runs, and the result is always
// recorded and the waiting caller woken — including for a request kind that
// somehow carries no operation, which reports EINVAL.
void apply_request(intptr_t argument);

} // namespace matter_bridge
