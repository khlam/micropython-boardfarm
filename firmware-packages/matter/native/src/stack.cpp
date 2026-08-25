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
#include <esp_netif.h>

#include "callbacks.h"
#include "endpoint_schema.h"
#include "matter/bridge.h"
#include "state_snapshot.h"
#include "value_conversion.h"

namespace OccupancySensing = chip::app::Clusters::OccupancySensing;

using esp_matter::attribute_t;
using esp_matter::endpoint_t;

namespace matter_bridge {

// The endpoint count is capped so the callback code can quickly check whether
// an update belongs to this bridge.
constexpr size_t MAXIMUM_ENDPOINTS = 16;

// The key ESP-IDF gives the default Wi-Fi station interface. CHIP creates that
// interface during commissioning; nothing in this bridge creates one.
constexpr const char *STATION_INTERFACE_KEY = "WIFI_STA_DEF";

// Private to this file, but `static` rather than an unnamed namespace because
// the C entry points below reach them through a using-directive. Only the VM
// task writes them, and only before the stack starts.
static esp_matter::node_t *matter_node = nullptr;
static uint16_t endpoint_ids[MAXIMUM_ENDPOINTS]{};
static uint8_t endpoint_types[MAXIMUM_ENDPOINTS]{};
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

bool endpoint_tracks_attribute(uint16_t endpoint_id, uint32_t cluster_id, uint32_t attribute_id)
{
    for (size_t index = 0; index < endpoint_count; ++index) {
        if (endpoint_ids[index] == endpoint_id) {
            return endpoint_type_tracks_attribute(endpoint_types[index], cluster_id, attribute_id);
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

// Reset the static snapshot before creating the one supported node.
extern "C" int matter_node_create(void)
{
    if (matter_node != nullptr) {
        return EALREADY;
    }
    reset_state_snapshot();
    esp_matter::node::config_t config;
    matter_node = esp_matter::node::create(&config, attribute_callback, identify_callback);
    if (matter_node == nullptr) {
        reset_state_snapshot();
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
    if (endpoint_type > MATTER_ENDPOINT_ON_OFF_PLUG_IN_UNIT) {
        return EINVAL;
    }
    endpoint_t *endpoint = endpoint_type_to_endpoint(matter_node, endpoint_type);
    if (endpoint == nullptr) {
        return EIO;
    }
    *endpoint_id = esp_matter::endpoint::get_id(endpoint);
    endpoint_ids[endpoint_count] = *endpoint_id;
    endpoint_types[endpoint_count++] = endpoint_type;
    return 0;
}

// Set an endpoint attribute's initial value before the Matter stack starts.
// Persistence policy belongs to endpoint construction, so whether an attribute
// is deferred never depends on the caller overriding its initial value.
// Occupancy cannot be seeded because its serving cluster is built at start;
// writing the generic store beforehand would have no controller-visible effect.
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

// Read back the address commissioning obtained for the station interface.
//
// This is the one post-start call that does not go through request.cpp. The
// esp_netif getters below marshal themselves onto the lwIP task through
// ESP-IDF's own IPC, so they are already safe to call from the VM task, and
// wrapping them in a second hop would only add a timeout that can fail. Nothing
// here touches esp_matter, so the `started` barrier does not apply either: an
// uncommissioned device simply has no interface yet and says so.
extern "C" int matter_network_address(char *address, size_t capacity)
{
    if (address == nullptr || capacity < MATTER_ADDRESS_SIZE) {
        return EINVAL;
    }
    esp_netif_t *station = esp_netif_get_handle_from_ifkey(STATION_INTERFACE_KEY);
    if (station == nullptr) {
        return ENOTCONN;
    }
    esp_netif_ip_info_t info{};
    if (esp_netif_get_ip_info(station, &info) != ESP_OK) {
        return EIO;
    }
    // The interface exists from the moment CHIP creates it, but stays at 0.0.0.0
    // until DHCP answers. Both are "not on the network yet" to a caller.
    if (info.ip.addr == 0) {
        return ENOTCONN;
    }
    esp_ip4addr_ntoa(&info.ip, address, capacity);
    return 0;
}
