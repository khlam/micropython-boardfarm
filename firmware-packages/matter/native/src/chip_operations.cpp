// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "chip_operations.h"

#include <algorithm>
#include <cerrno>
#include <cstring>

#include <app/clusters/occupancy-sensor-server/OccupancySensingCluster.h>
#include <app/server/CommissioningWindowManager.h>
#include <app/server/Server.h>
#include <data_model_provider/esp_matter_data_model_provider.h>
#include <esp_matter.h>
#include <platform/CHIPDeviceLayer.h>
#include <platform/ConfigurationManager.h>

#include "callbacks.h"
#include "matter/bridge.h"
#include "request.h"
#include "value_conversion.h"

namespace OccupancySensing = chip::app::Clusters::OccupancySensing;

using esp_matter::attribute_t;

namespace matter_bridge {
namespace {

// Finish a request on the CHIP task. Store the result first, then signal the
// semaphore so the waiting caller can wake up and read it. After signaling, the
// caller may immediately continue, so this task only releases its reference.
void finish(Request *request, int result)
{
    request->result = result;
    xSemaphoreGive(request->done);
    release(request);
}

// Each operation below returns 0 on success or an errno-style error code.

// Read one Matter attribute into the Request. Return ENOENT if the attribute
// does not exist and EIO if its value cannot cross this bridge.
int read_attribute(Request *request)
{
    attribute_t *handle = esp_matter::attribute::get(request->endpoint_id, request->cluster_id,
                                                     request->attribute_id);
    if (handle == nullptr) {
        return ENOENT;
    }
    esp_matter_attr_val_t stored{};
    if (esp_matter::attribute::get_val(handle, &stored) != ESP_OK) {
        return EIO;
    }
    const EventValue encoded = attribute_value_to_event_value(stored);
    if (!encoded.supported) {
        return EIO;
    }
    request->value = encoded.value;
    request->value_type = encoded.value_type;
    return 0;
}

// Publish Occupancy through the cluster object that actually serves it.
//
// ESP-Matter hands OccupancySensing to a code-driven ServerCluster registered
// with the data-model provider, and that object — not ESP-Matter's own
// attribute store — answers every read and every report. `attribute::update()`
// reaches the two only for a controller-writable attribute, which ESP-Matter
// routes through the provider; Occupancy is read-only, so an update there
// writes the unserved store, returns ESP_OK, and leaves controllers reading the
// value the endpoint was built with. The cluster's setter updates the served
// value and reports it, which is what a sensed attribute needs.
//
// No local-update bracket: the setter reports through CHIP rather than
// ESP-Matter's attribute callback, so there is no echo for `attribute_callback()`
// to drop.
int publish_occupancy(const Request *request)
{
    chip::app::ServerClusterInterface *served =
        esp_matter::data_model::provider::get_instance().registry().Get(
            chip::app::ConcreteClusterPath(request->endpoint_id, request->cluster_id));
    if (served == nullptr) {
        return ENOENT;
    }
    // The registry keys on the cluster ID and ESP-Matter registers exactly this
    // type for OccupancySensing, so the cast is sound; CHIP builds without RTTI,
    // which rules out checking it at runtime.
    static_cast<chip::app::Clusters::OccupancySensingCluster *>(served)->SetOccupancy(request->value != 0U);
    return 0;
}

// Publish a value chosen by MicroPython into ESP-Matter. ESP-Matter updates the
// attribute and then handles the normal Matter reporting needed to inform
// subscribed controllers.
//
// ESP-Matter also calls `attribute_callback()` for this local change, so the
// update is bracketed as local for exactly as long as `attribute::update()`
// runs and the echo is dropped there.
int publish_attribute(Request *request)
{
    if (request->cluster_id == OccupancySensing::Id &&
        request->attribute_id == OccupancySensing::Attributes::Occupancy::Id) {
        return publish_occupancy(request);
    }
    attribute_t *handle = esp_matter::attribute::get(request->endpoint_id, request->cluster_id,
                                                     request->attribute_id);
    if (handle == nullptr) {
        return ENOENT;
    }
    esp_matter_attr_val_t stored{};
    if (esp_matter::attribute::get_val(handle, &stored) != ESP_OK) {
        return EIO;
    }
    AttributeValue decoded = event_value_to_attribute_value(stored, request->value, request->value_type);
    if (decoded.error != 0) {
        return decoded.error;
    }
    begin_local_update();
    const esp_err_t result = esp_matter::attribute::update(request->endpoint_id, request->cluster_id,
                                                          request->attribute_id, &decoded.value);
    end_local_update();
    return result == ESP_OK ? 0 : EIO;
}

// Make the already-running device temporarily available for Matter pairing.
// Return EALREADY if a commissioning window is open already. This re-pairing
// window is advertised over DNS-SD on the IP network; Bluetooth LE is used for
// the device's initial commissioning flow, not this basic reopening.
int open_commissioning_window(Request *request)
{
    auto &manager = chip::Server::GetInstance().GetCommissioningWindowManager();
    if (manager.IsCommissioningWindowOpen()) {
        return EALREADY;
    }
    const CHIP_ERROR error = manager.OpenBasicCommissioningWindow(
        chip::System::Clock::Seconds16(request->timeout_s),
        chip::CommissioningWindowAdvertisement::kDnssdOnly);
    return error == CHIP_NO_ERROR ? 0 : EIO;
}

// Copy the current Matter fabric table into memory owned by the Request, since
// it may only be safely iterated on the CHIP task; this gives MicroPython a
// stable snapshot. Fabric labels are shortened if necessary and are always
// terminated with a null character for safe C-string use.
int get_fabrics(Request *request)
{
    const auto &table = chip::Server::GetInstance().GetFabricTable();
    for (const auto &fabric : table) {
        if (request->fabric_count >= MATTER_MAX_FABRICS) {
            return EOVERFLOW;
        }
        matter_fabric &output = request->fabrics[request->fabric_count++];
        output.index = fabric.GetFabricIndex();
        output.fabric_id = fabric.GetFabricId();
        output.node_id = fabric.GetNodeId();
        output.vendor_id = fabric.GetVendorId();
        const chip::CharSpan label = fabric.GetFabricLabel();
        const size_t length = std::min(label.size(), static_cast<size_t>(MATTER_FABRIC_LABEL_SIZE - 1));
        std::memcpy(output.label, label.data(), length);
        output.label[length] = '\0';
    }
    return 0;
}

// Remove this device's membership in one Matter fabric. If the supplied fabric
// index no longer exists, return ENOENT so the caller can distinguish "already
// gone" from a more general ESP-Matter failure.
int remove_fabric(Request *request)
{
    const CHIP_ERROR error = chip::Server::GetInstance().GetFabricTable().Delete(request->fabric_index);
    return error == CHIP_NO_ERROR ? 0 : (error == CHIP_ERROR_NOT_FOUND ? ENOENT : EIO);
}

} // namespace

void apply_request(intptr_t argument)
{
    auto *request = reinterpret_cast<Request *>(argument);
    int result = EINVAL;
    switch (request->kind) {
    case RequestKind::kRead:
        result = read_attribute(request);
        break;
    case RequestKind::kPublish:
        result = publish_attribute(request);
        break;
    case RequestKind::kOpenCommissioningWindow:
        result = open_commissioning_window(request);
        break;
    case RequestKind::kGetFabrics:
        result = get_fabrics(request);
        break;
    case RequestKind::kRemoveFabric:
        result = remove_fabric(request);
        break;
    case RequestKind::kFactoryReset:
        chip::DeviceLayer::ConfigurationMgr().InitiateFactoryReset();
        result = 0;
        break;
    }
    finish(request, result);
}

} // namespace matter_bridge
