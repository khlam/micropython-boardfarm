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

// Return whether one path belongs to the Python mirror for `endpoint_type`.
// Native callbacks use this to exclude protocol metadata Python cannot consume.
bool endpoint_type_tracks_attribute(uint8_t endpoint_type, uint32_t cluster_id, uint32_t attribute_id);

// Return whether one path is the Occupancy attribute, which is served by a
// code-driven cluster instead of ESP-Matter's generic attribute store and so
// needs its own read/write path everywhere a caller resolves an attribute.
bool is_occupancy_attribute(uint32_t cluster_id, uint32_t attribute_id);

} // namespace matter_bridge
