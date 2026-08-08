// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Everything ESP-Matter and CHIP call into. These run on the CHIP task:
// they only translate and enqueue, never touching MicroPython directly.
#pragma once

#include <cstdint>

#include <esp_matter.h>
#include <esp_matter_core.h>
#include <esp_matter_identify.h>
#include <platform/CHIPDeviceLayer.h>

namespace matter_bridge {

// ESP-Matter calls this after an attribute changes. For example, a controller
// might change a light's OnOff or CurrentLevel attribute. Converts supported
// remote changes into `matter_event` records and queues them for MicroPython.
//
// Returning ESP_OK tells ESP-Matter that its own update may continue. We still
// return ESP_OK when we intentionally choose not to forward an event to Python.
esp_err_t attribute_callback(esp_matter::attribute::callback_type_t type, uint16_t endpoint_id,
                             uint32_t cluster_id, uint32_t attribute_id, esp_matter_attr_val_t *value,
                             void *private_data);

// Matter has an "Identify" feature that lets a user ask a device to make itself
// obvious, for example by blinking a light during setup. ESP-Matter requires an
// identify callback when the node is created, but this generic bridge does not
// decide how a particular product should identify itself. The application's
// MicroPython code can observe the IdentifyTime attribute and perform the
// product-specific action there.
esp_err_t identify_callback(esp_matter::identification::callback_type_t type, uint16_t endpoint_id,
                            uint8_t effect_id, uint8_t effect_variant, void *private_data);

// CHIP calls this for important device-wide Matter events. Translates
// commissioning events into queue messages that MicroPython can understand, and
// reopens pairing when the device loses its last fabric.
void device_event_callback(const chip::DeviceLayer::ChipDeviceEvent *event, intptr_t argument);

// Bracket an attribute update this bridge makes itself. ESP-Matter reports our
// own write back through `attribute_callback()`; between these two calls that
// echo is recognised and dropped rather than queued to MicroPython, which also
// saves queue space for genuine remote controller updates. A controller write
// outside that window is still treated as a real remote update, so keep the
// window as short as the update call itself.
void begin_local_update(void);
void end_local_update(void);

} // namespace matter_bridge
