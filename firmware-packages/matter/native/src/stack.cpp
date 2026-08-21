// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Bringing the Matter stack up, and the state that survives for as long as it
// runs. Matter calls the complete device a "node"; this bridge creates exactly
// one, hangs every endpoint off it, and then starts CHIP.
//
// The C entry points here are the pre-start half of the API in `bridge.h`. They
// run on the caller's task straight against ESP-Matter, which is safe only
// because nothing else is running against it yet — every one of them refuses to
// act once `started` is true.
#include "stack.h"

#include <cerrno>

#include <app-common/zap-generated/ids/Attributes.h>
#include <app-common/zap-generated/ids/Clusters.h>
#include <esp_matter.h>
#include <esp_matter_core.h>

#include "callbacks.h"
#include "endpoint_schema.h"
#include "event_queue.h"
#include "matter/bridge.h"
#include "value_conversion.h"

namespace OccupancySensing = chip::app::Clusters::OccupancySensing;

using esp_matter::attribute_t;
using esp_matter::endpoint_t;

namespace matter_bridge {

// The endpoint count is capped so the callback code can quickly check whether
// an update belongs to this bridge.
constexpr size_t MAXIMUM_ENDPOINTS = 16;

// Private to this file, but `static` rather than an unnamed namespace because
// the C entry points below reach them through a using-directive. Only the VM
// task writes them, and only before the stack starts.
static esp_matter::node_t *matter_node = nullptr;
static uint16_t endpoint_ids[MAXIMUM_ENDPOINTS]{};
static size_t endpoint_count = 0;
static bool started = false;

bool endpoint_exists(uint16_t endpoint_id)
{
    for (size_t index = 0; index < endpoint_count; ++index) {
        if (endpoint_ids[index] == endpoint_id) {
            return true;
        }
    }
    return false;
}

bool stack_started(void)
{
    return started;
}

} // namespace matter_bridge

using namespace matter_bridge;

// Create the event queue first so that if ESP-Matter produces a callback while
// the node is being created, there is already somewhere safe to store that
// event for MicroPython.
extern "C" int matter_node_create(void)
{
    if (matter_node != nullptr) {
        return EALREADY;
    }
    const int queue_error = create_event_queue();
    if (queue_error != 0) {
        return queue_error;
    }
    esp_matter::node::config_t config;
    matter_node = esp_matter::node::create(&config, attribute_callback, identify_callback);
    if (matter_node == nullptr) {
        destroy_event_queues();
        return EIO;
    }
    return 0;
}

// Add one logical application endpoint to the Matter node before the stack starts.
// ESP-Matter assigns the endpoint a numeric ID. Save that ID so later callbacks
// can distinguish endpoints created by this bridge from internal or unrelated
// endpoints on the same Matter node.
extern "C" int matter_endpoint_create(uint8_t endpoint_type, uint16_t *endpoint_id)
{
    if (endpoint_id == nullptr || matter_node == nullptr || started) {
        return EINVAL;
    }
    if (endpoint_count >= MAXIMUM_ENDPOINTS) {
        return ENOSPC;
    }
    if (endpoint_type > MATTER_ENDPOINT_OCCUPANCY_SENSOR) {
        return EINVAL;
    }
    endpoint_t *endpoint = endpoint_type_to_endpoint(matter_node, endpoint_type);
    if (endpoint == nullptr) {
        return EIO;
    }
    *endpoint_id = esp_matter::endpoint::get_id(endpoint);
    endpoint_ids[endpoint_count++] = *endpoint_id;
    return 0;
}

// Set an endpoint attribute's initial value before the Matter stack starts.
// Persistence policy belongs to endpoint construction, so whether an attribute
// is deferred never depends on the caller overriding its initial value.
//
// Occupancy is refused rather than seeded. The cluster object that serves it is
// built during `matter_stack_start()` from the endpoint's feature map alone, so
// a value written into ESP-Matter's attribute store here is never read back out
// — seeding it would report success and change nothing a controller can see.
// Publishing it after the node starts is the supported route.
extern "C" int matter_attribute_set_initial(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                                             uint32_t value, uint8_t value_type)
{
    if (started || !endpoint_exists(endpoint_id)) {
        return EINVAL;
    }
    if (cluster_id == OccupancySensing::Id && attribute_id == OccupancySensing::Attributes::Occupancy::Id) {
        return ENOTSUP;
    }
    attribute_t *handle = esp_matter::attribute::get(endpoint_id, cluster_id, attribute_id);
    if (handle == nullptr) {
        return ENOENT;
    }
    esp_matter_attr_val_t stored{};
    if (esp_matter::attribute::get_val(handle, &stored) != ESP_OK) {
        return EIO;
    }
    AttributeValue decoded = event_value_to_attribute_value(stored, value, value_type);
    if (decoded.error != 0) {
        return decoded.error;
    }
    const esp_err_t result = esp_matter::attribute::set_val(handle, &decoded.value);
    // The endpoint constructor already installed a default value. If MicroPython
    // asks for that exact same initial value, ESP-Matter reports
    // ESP_ERR_NOT_FINISHED to mean "nothing changed" rather than a real failure.
    // Treat both ESP_OK and that no-op result as success.
    if (result != ESP_OK && result != ESP_ERR_NOT_FINISHED) {
        return EIO;
    }
    return 0;
}

// Start ESP-Matter networking and event processing. Once `started` becomes true,
// setup is over: code outside the CHIP task must no longer modify
// ESP-Matter structures directly. Later reads and changes go through the Request
// scheduling in request.cpp instead.
extern "C" int matter_stack_start(void)
{
    if (matter_node == nullptr || started) {
        return EINVAL;
    }
    if (esp_matter::start(device_event_callback) != ESP_OK) {
        return EIO;
    }
    started = true;
    return 0;
}
