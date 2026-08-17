// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Construction of the endpoint schemas this bridge knows how to build.
#pragma once

#include <cstdint>

#include <esp_matter.h>

namespace matter_bridge {

// Build the endpoint that `endpoint_type` names on `node`, or return
// nullptr when the type is unknown or ESP-Matter refuses the schema. The caller
// owns the decision of which types are accepted; this only builds them.
esp_matter::endpoint_t *endpoint_type_to_endpoint(esp_matter::node_t *node, uint8_t endpoint_type);

} // namespace matter_bridge
