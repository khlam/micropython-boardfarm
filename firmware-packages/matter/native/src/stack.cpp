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
#include <cstring>

#include <esp_matter.h>
#include <esp_matter_core.h>

#include "callbacks.h"
#include "endpoint_schema.h"
#include "event_queue.h"
#include "matter/bridge.h"
#include "value_conversion.h"

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
static bool mode_select_created = false;

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

// Add one logical light endpoint to the Matter node before the stack starts.
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
    if (endpoint_type > MATTER_ENDPOINT_EXTENDED_COLOR_LIGHT) {
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

extern "C" int matter_mode_select_endpoint_create(const char *description,
                                                   const matter_mode_option *options,
                                                   size_t option_count, uint16_t *endpoint_id)
{
    if (description == nullptr || options == nullptr || endpoint_id == nullptr || matter_node == nullptr ||
        started || option_count == 0 || option_count > MATTER_MAX_MODE_OPTIONS) {
        return EINVAL;
    }
    if (mode_select_created) {
        return EALREADY;
    }
    if (endpoint_count >= MAXIMUM_ENDPOINTS) {
        return ENOSPC;
    }
    const size_t description_length = strnlen(description, MATTER_MODE_TEXT_SIZE);
    if (description_length == 0 || description_length >= MATTER_MODE_TEXT_SIZE) {
        return EINVAL;
    }
    for (size_t index = 0; index < option_count; ++index) {
        const size_t label_length = strnlen(options[index].label, MATTER_MODE_TEXT_SIZE);
        if (options[index].mode != index || label_length == 0 || label_length >= MATTER_MODE_TEXT_SIZE) {
            return EINVAL;
        }
        for (size_t previous = 0; previous < index; ++previous) {
            if (std::strcmp(options[index].label, options[previous].label) == 0) {
                return EINVAL;
            }
        }
    }
    endpoint_t *endpoint = mode_select_endpoint(matter_node, description, options, option_count);
    if (endpoint == nullptr) {
        return EIO;
    }
    *endpoint_id = esp_matter::endpoint::get_id(endpoint);
    endpoint_ids[endpoint_count++] = *endpoint_id;
    mode_select_created = true;
    return 0;
}

// Set an endpoint attribute's initial value before the Matter stack starts.
// Persistence policy belongs to endpoint construction, so whether an attribute
// is deferred never depends on the caller overriding its initial value.
extern "C" int matter_attribute_set_initial(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id,
                                             uint32_t value, uint8_t value_type)
{
    if (started || !endpoint_exists(endpoint_id)) {
        return EINVAL;
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
