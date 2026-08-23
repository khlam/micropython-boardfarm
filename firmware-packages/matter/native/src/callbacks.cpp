// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "callbacks.h"

#include <atomic>

#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>

#include "event_queue.h"
#include "matter/bridge.h"
#include "stack.h"
#include "value_conversion.h"

namespace matter_bridge {
namespace {

// How long a window this bridge opens itself stays up. Five minutes is long
// enough to walk back to the controller and short enough that an unattended
// node is not left advertising a passcode indefinitely.
constexpr uint32_t COMMISSIONING_WINDOW_SECONDS = 300;

// Written by the task publishing a local update and read by the callback that
// would otherwise queue the echo, so it crosses tasks and must be atomic.
std::atomic<uint8_t> update_origin{MATTER_ORIGIN_REMOTE};

// Put a node that belongs to no fabric back on the air.
//
// CHIP retries a failed commissioning attempt on its own, but only while the
// window's own timer is still armed; the attempt that exhausts its retry budget,
// and the removal of the last fabric, both leave the stack advertising nothing.
// Nothing inside CHIP reopens the window after that, so without this the node is
// unreachable until it is power-cycled. A node that still holds a fabric is left
// alone: reopening a basic window would put its factory passcode back on the air
// for an accessory its owner can already reach.
void reopen_commissioning_window(void)
{
    if (chip::Server::GetInstance().GetFabricTable().FabricCount() != 0) {
        return;
    }
    auto &manager = chip::Server::GetInstance().GetCommissioningWindowManager();
    if (manager.IsCommissioningWindowOpen()) {
        return;
    }
    const chip::System::Clock::Seconds16 timeout(COMMISSIONING_WINDOW_SECONDS);

    // A node that has never been commissioned holds no network credentials, so a
    // DNS-SD-only window would advertise on a network it cannot join and BLE is
    // its only way back. Once a commissioning has succeeded, ESP-Matter reclaims
    // the BLE host (CONFIG_USE_BLE_ONLY_FOR_COMMISSIONING) and asking for it fails
    // outright -- but that node is on the network, so DNS-SD alone reaches it.
    if (manager.OpenBasicCommissioningWindow(timeout, chip::CommissioningWindowAdvertisement::kAllSupported) ==
        CHIP_NO_ERROR) {
        return;
    }
    manager.OpenBasicCommissioningWindow(timeout, chip::CommissioningWindowAdvertisement::kDnssdOnly);
}

} // namespace

esp_err_t attribute_callback(esp_matter::attribute::callback_type_t type, uint16_t endpoint_id,
                             uint32_t cluster_id, uint32_t attribute_id, esp_matter_attr_val_t *value, void *)
{
    // Attribute updates made by MicroPython also trigger this callback. Those are
    // local echoes, not new commands from a phone or hub, so do not send them
    // back to Python.
    if (type != esp_matter::attribute::POST_UPDATE || update_origin.load() != MATTER_ORIGIN_REMOTE ||
        !endpoint_exists(endpoint_id)) {
        return ESP_OK;
    }
    const EventValue encoded = attribute_value_to_event_value(*value);
    if (!encoded.supported) {
        return ESP_OK;
    }
    matter_event event{};
    event.value = encoded.value;
    event.value_type = encoded.value_type;
    event.kind = MATTER_EVENT_ATTRIBUTE;
    event.endpoint_id = endpoint_id;
    event.cluster_id = cluster_id;
    event.attribute_id = attribute_id;
    event.origin = MATTER_ORIGIN_REMOTE;
    publish_attribute_event(event);
    return ESP_OK;
}

esp_err_t identify_callback(esp_matter::identification::callback_type_t type, uint16_t endpoint_id, uint8_t,
                            uint8_t, void *)
{
    (void)type;
    (void)endpoint_id;
    return ESP_OK;
}

// Translate the device-wide events that describe pairing, and keep an unpaired
// node reachable across the two transitions that would otherwise silence it.
void device_event_callback(const chip::DeviceLayer::ChipDeviceEvent *event, intptr_t)
{
    switch (event->Type) {
    case chip::DeviceLayer::DeviceEventType::kCommissioningSessionStarted:
        publish_commissioning(MATTER_COMMISSIONING_STARTED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningComplete:
        publish_commissioning(MATTER_COMMISSIONING_COMPLETE);
        break;
    case chip::DeviceLayer::DeviceEventType::kFailSafeTimerExpired:
        // One attempt failed, whether its timer ran out or a commissioner
        // disarmed the fail-safe on its way out. CHIP starts listening for the
        // next attempt itself, so the node stays pairable and no window is
        // reopened here.
        publish_commissioning(MATTER_COMMISSIONING_FAILED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningSessionStopped:
        // CHIP raises this only once it has given up listening for a
        // commissioner altogether -- its retry budget is spent, or re-arming
        // PASE failed. It never accompanies a successful pairing, whose session
        // is torn down by kCommissioningComplete instead. Reported and recovered
        // from, because it is otherwise the one way a node goes quiet without
        // ever saying that commissioning ended.
        publish_commissioning(MATTER_COMMISSIONING_FAILED);
        reopen_commissioning_window();
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowOpened:
        publish_commissioning(MATTER_COMMISSIONING_WINDOW_OPENED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowClosed:
        publish_commissioning(MATTER_COMMISSIONING_WINDOW_CLOSED);
        break;
    case chip::DeviceLayer::DeviceEventType::kFabricRemoved:
        // Losing the last fabric leaves nobody owning the device.
        reopen_commissioning_window();
        break;
    default:
        break;
    }
}

void begin_local_update(void)
{
    update_origin.store(MATTER_ORIGIN_LOCAL);
}

void end_local_update(void)
{
    update_origin.store(MATTER_ORIGIN_REMOTE);
}

} // namespace matter_bridge
