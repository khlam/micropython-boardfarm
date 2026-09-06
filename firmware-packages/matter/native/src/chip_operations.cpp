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
#include "endpoint_schema.h"
#include "matter/bridge.h"
#include "request.h"
#include "state_snapshot.h"
#include "value_conversion.h"

using chip::app::ConcreteClusterPath;
using chip::app::ServerClusterInterface;
using chip::app::Clusters::OccupancySensingCluster;
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

// Return the code-driven Occupancy Sensing cluster serving this endpoint.
OccupancySensingCluster *get_occupancy_cluster(uint16_t endpoint_id)
{
    ServerClusterInterface *served = esp_matter::data_model::provider::get_instance().registry().Get(
        ConcreteClusterPath(endpoint_id, chip::app::Clusters::OccupancySensing::Id));
    // ESP-Matter registers this concrete type for OccupancySensing; CHIP has no RTTI.
    return static_cast<OccupancySensingCluster *>(served);
}

// Occupancy lives in the serving cluster rather than ESP-Matter's generic
// attribute store, so reads must use the same authoritative state controllers see.
int read_occupancy(Request *request)
{
    OccupancySensingCluster *served = get_occupancy_cluster(request->endpoint_id);
    if (served == nullptr) {
        return ENOENT;
    }
    request->value = served->IsOccupied() ? 1U : 0U;
    request->value_type = MATTER_VALUE_UINT8;
    return 0;
}

// Read one Matter attribute into the Request. Return ENOENT if the attribute
// does not exist and EIO if its value cannot cross this bridge.
int read_attribute(Request *request)
{
    if (is_occupancy_attribute(request->cluster_id, request->attribute_id)) {
        return read_occupancy(request);
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
    const EventValue encoded = attribute_value_to_event_value(stored);
    if (!encoded.supported) {
        return EIO;
    }
    request->value = encoded.value;
    request->value_type = encoded.value_type;
    return 0;
}

// Occupancy is served by a code-driven cluster, not ESP-Matter's generic
// attribute store. Its setter updates the controller-visible value and reports
// it without producing a local attribute-callback echo.
int publish_occupancy(uint16_t endpoint_id, uint32_t value)
{
    OccupancySensingCluster *served = get_occupancy_cluster(endpoint_id);
    if (served == nullptr) {
        return ENOENT;
    }
    served->SetOccupancy(value != 0U);
    return 0;
}

// Publish a value chosen by MicroPython into ESP-Matter. ESP-Matter updates the
// attribute and then handles the normal Matter reporting needed to inform
// subscribed controllers.
//
// ESP-Matter also calls `attribute_callback()` for this local change, so the
// update is bracketed as local for exactly as long as `attribute::update()`
// runs and the echo is dropped there.
int publish_attributes(Request *request)
{
    esp_matter_attr_val_t values[MATTER_MAX_ATTRIBUTE_BATCH]{};

    // Resolve and convert the whole batch before the first mutation. That makes
    // path and range failures all-or-nothing even though ESP-Matter cannot roll
    // back an unexpected failure from attribute::update().
    for (size_t index = 0; index < request->attribute_update_count; ++index) {
        const matter_attribute_update &update = request->attribute_updates[index];
        if (is_occupancy_attribute(update.cluster_id, update.attribute_id)) {
            if (get_occupancy_cluster(request->endpoint_id) == nullptr) {
                return ENOENT;
            }
            if (update.value_type != MATTER_VALUE_UINT8 || update.value > 1U) {
                return ERANGE;
            }
            continue;
        }
        attribute_t *handle = esp_matter::attribute::get(request->endpoint_id, update.cluster_id,
                                                         update.attribute_id);
        if (handle == nullptr) {
            return ENOENT;
        }
        esp_matter_attr_val_t stored{};
        if (esp_matter::attribute::get_val(handle, &stored) != ESP_OK) {
            return EIO;
        }
        const AttributeValue decoded =
            event_value_to_attribute_value(stored, update.value, update.value_type);
        if (decoded.error != 0) {
            return decoded.error;
        }
        values[index] = decoded.value;
    }

    int error = 0;
    begin_local_update();
    for (size_t index = 0; index < request->attribute_update_count; ++index) {
        const matter_attribute_update &update = request->attribute_updates[index];
        if (is_occupancy_attribute(update.cluster_id, update.attribute_id)) {
            error = publish_occupancy(request->endpoint_id, update.value);
        } else if (esp_matter::attribute::update(request->endpoint_id, update.cluster_id,
                                                update.attribute_id, &values[index]) != ESP_OK) {
            error = EIO;
        }
        if (error != 0) {
            break;
        }
        clear_remote_attribute(request->endpoint_id, update.cluster_id, update.attribute_id);
    }
    end_local_update();
    return error;
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
    case RequestKind::kPublishBatch:
        result = publish_attributes(request);
        break;
    case RequestKind::kSnapshot:
        result = copy_state_snapshot(request->snapshot_records, MATTER_MAX_SNAPSHOT_RECORDS,
                                     &request->snapshot_count, &request->snapshot_generation);
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
