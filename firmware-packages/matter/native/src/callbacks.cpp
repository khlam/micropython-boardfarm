// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "callbacks.h"

#include <atomic>

#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>

#include "matter/bridge.h"
#include "stack.h"
#include "state_snapshot.h"
#include "value_conversion.h"

namespace matter_bridge {
namespace {

// How long a window this bridge opens itself stays up. Five minutes is long
// enough to walk back to the controller and short enough that an unattended
// node is not left advertising a passcode indefinitely.
constexpr uint32_t COMMISSIONING_WINDOW_SECONDS = 300;

// Written by the task publishing a local update and read by the callback that
// would otherwise retain the echo, so it crosses tasks and must be atomic.
std::atomic<uint8_t> update_origin{MATTER_ORIGIN_REMOTE};

// True from the moment a commissioner completes PASE until that attempt ends,
// whichever way it ends. CHIP closes the window as soon as a commissioner
// connects, which is indistinguishable from the window timing out unless the
// session is tracked -- and the two call for opposite responses. Every device
// event is dispatched on the CHIP task, so this needs no synchronisation.
bool session_active = false;

// Put a node that belongs to no fabric back on the air.
//
// The invariant is that an unpaired node always advertises. CHIP defends it only
// part of the way: it retries a failed attempt by itself, but only while the
// window's own timer is still armed. Past that the stack goes quiet for good --
// the discovery window times out, an attempt exhausts its retry budget, or the
// last fabric is removed -- and the node is unreachable until it is power-cycled.
//
// A node that still holds a fabric is left alone: reopening a basic window would
// put its factory passcode back on the air for an accessory its owner can
// already reach.
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
    if (endpoint_tracks_attribute(endpoint_id, cluster_id, attribute_id)) {
        record_remote_attribute(endpoint_id, cluster_id, attribute_id, encoded.value,
                                encoded.value_type);
    }
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
        session_active = true;
        record_commissioning_state(MATTER_COMMISSIONING_STARTED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningComplete:
        session_active = false;
        record_commissioning_state(MATTER_COMMISSIONING_COMPLETE);
        break;
    case chip::DeviceLayer::DeviceEventType::kFailSafeTimerExpired:
        // One attempt failed, whether its timer ran out or a commissioner
        // disarmed the fail-safe on its way out. CHIP starts listening for the
        // next attempt itself, so the node stays pairable and no window is
        // reopened here.
        session_active = false;
        record_commissioning_state(MATTER_COMMISSIONING_FAILED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningSessionStopped:
        // CHIP raises this only once it has given up listening for a
        // commissioner altogether -- its retry budget is spent, or re-arming
        // PASE failed. It never accompanies a successful pairing, whose session
        // is torn down by kCommissioningComplete instead. Reported and recovered
        // from, because it is otherwise the one way a node goes quiet without
        // ever saying that commissioning ended.
        session_active = false;
        record_commissioning_state(MATTER_COMMISSIONING_FAILED);
        reopen_commissioning_window();
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowOpened:
        record_commissioning_state(MATTER_COMMISSIONING_WINDOW_OPENED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowClosed:
        record_commissioning_state(MATTER_COMMISSIONING_WINDOW_CLOSED);
        // A commissioner connecting closes the window too, and that one must be
        // left closed -- reopening it mid-attempt would advertise over the
        // commissioner still working. CHIP reports the session first, so an
        // inactive one here means nobody is on the other end: the discovery
        // window simply ran out, and an unpaired node has gone silent.
        if (!session_active) {
            reopen_commissioning_window();
        }
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
