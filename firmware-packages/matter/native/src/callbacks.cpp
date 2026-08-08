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

// If the device loses its last Matter fabric, this bridge reopens pairing for
// five minutes so the device does not become unreachable.
constexpr uint32_t kCommissioningWindowSeconds = 300;

// Written by the task publishing a local update and read by the callback that
// would otherwise queue the echo, so it crosses tasks and must be atomic.
std::atomic<uint8_t> update_origin{MATTER_ORIGIN_REMOTE};

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
    publish_event(event);
    return ESP_OK;
}

esp_err_t identify_callback(esp_matter::identification::callback_type_t type, uint16_t endpoint_id, uint8_t,
                            uint8_t, void *)
{
    (void)type;
    (void)endpoint_id;
    return ESP_OK;
}

// If the final fabric is removed, no controller owns the device anymore, so
// automatically reopen a commissioning window so a user can pair it again.
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
        publish_commissioning(MATTER_COMMISSIONING_FAILED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowOpened:
        publish_commissioning(MATTER_COMMISSIONING_WINDOW_OPENED);
        break;
    case chip::DeviceLayer::DeviceEventType::kCommissioningWindowClosed:
        publish_commissioning(MATTER_COMMISSIONING_WINDOW_CLOSED);
        break;
    case chip::DeviceLayer::DeviceEventType::kFabricRemoved:
        if (chip::Server::GetInstance().GetFabricTable().FabricCount() == 0) {
            auto &manager = chip::Server::GetInstance().GetCommissioningWindowManager();
            if (!manager.IsCommissioningWindowOpen()) {
                manager.OpenBasicCommissioningWindow(chip::System::Clock::Seconds16(kCommissioningWindowSeconds),
                                                     chip::CommissioningWindowAdvertisement::kDnssdOnly);
            }
        }
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
