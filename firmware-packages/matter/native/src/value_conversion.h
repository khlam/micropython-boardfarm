// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
//
// Conversion between ESP-Matter's tagged attribute values and the flat
// integer-plus-tag pair that every value crossing into MicroPython travels in.
//
// Both directions are pure: nothing here reads or writes the running stack, so
// a caller fetches the stored value first and applies the result afterwards.
// That is what keeps the type rules exercisable without a CHIP stack.
#pragma once

#include <cstdint>

#include <esp_matter.h>

#include "matter/bridge.h"

namespace matter_bridge {

// One attribute value on its way up to MicroPython.
struct EventValue {
    bool supported;      // false when the Matter type cannot cross this bridge
    uint32_t value;      // meaningful only when supported
    uint8_t value_type;  // one of the matter_value_type codes
};

// One attribute value on its way down into ESP-Matter.
struct AttributeValue {
    int error;                    // 0, or the errno describing the refusal
    esp_matter_attr_val_t value;  // meaningful only when error is 0
};

// Flatten an ESP-Matter attribute value into the integer plus type tag that the
// event queue and the C API carry.
//
// Boolean, 8-bit, and 16-bit integer-like values are supported. Matter enums
// and bitmaps come across as ordinary integers. More complex Matter types such
// as strings, structures, and lists do not: `supported` comes back false, which
// is safer than truncating them and sending Python an incorrect value.
EventValue attribute_value_to_event_value(const esp_matter_attr_val_t &input);

// Rebuild a value from MicroPython as the exact ESP-Matter type that `stored`
// already holds, so the attribute keeps its precise type and its nullability.
//
// `error` is EINVAL or ERANGE for an input the stored type cannot hold, and
// ENOTSUP for a Matter type this bridge does not carry. A value too large is
// refused rather than silently wrapped.
AttributeValue event_value_to_attribute_value(const esp_matter_attr_val_t &stored, uint32_t input,
                                              uint8_t input_type);

} // namespace matter_bridge
