// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "value_conversion.h"

#include <cerrno>

namespace matter_bridge {
namespace {

// Not a matter_value_type code: the classifier's way of saying the bridge
// refuses this Matter type rather than carrying it.
constexpr uint8_t UNSUPPORTED_KIND = 0xFF;

// The one place the carried Matter types are listed. Both directions classify
// through here, so a width can be added without two lists drifting apart.
uint8_t attribute_type_to_value_kind(esp_matter_val_type_t type)
{
    switch (type) {
    case ESP_MATTER_VAL_TYPE_BOOLEAN:
        return MATTER_VALUE_BOOL;
    case ESP_MATTER_VAL_TYPE_UINT8:
    case ESP_MATTER_VAL_TYPE_NULLABLE_UINT8:
    case ESP_MATTER_VAL_TYPE_ENUM8:
    case ESP_MATTER_VAL_TYPE_NULLABLE_ENUM8:
    case ESP_MATTER_VAL_TYPE_BITMAP8:
        return MATTER_VALUE_UINT8;
    case ESP_MATTER_VAL_TYPE_UINT16:
    case ESP_MATTER_VAL_TYPE_NULLABLE_UINT16:
    case ESP_MATTER_VAL_TYPE_BITMAP16:
        return MATTER_VALUE_UINT16;
    default:
        return UNSUPPORTED_KIND;
    }
}

} // namespace

EventValue attribute_value_to_event_value(const esp_matter_attr_val_t &input)
{
    switch (attribute_type_to_value_kind(input.type)) {
    case MATTER_VALUE_BOOL:
        return {true, input.val.b ? 1U : 0U, MATTER_VALUE_BOOL};
    case MATTER_VALUE_UINT8:
        return {true, input.val.u8, MATTER_VALUE_UINT8};
    case MATTER_VALUE_UINT16:
        return {true, input.val.u16, MATTER_VALUE_UINT16};
    default:
        return {false, 0U, 0U};
    }
}

// The stored value is copied and only its data replaced. That is what preserves
// the Matter metadata riding along with it — the precise type, and whether the
// attribute is nullable.
AttributeValue event_value_to_attribute_value(const esp_matter_attr_val_t &stored, uint32_t input,
                                              uint8_t input_type)
{
    AttributeValue output{0, stored};
    switch (attribute_type_to_value_kind(stored.type)) {
    case MATTER_VALUE_BOOL:
        if (input_type != MATTER_VALUE_BOOL) {
            output.error = EINVAL;
            return output;
        }
        output.value.val.b = input != 0U;
        return output;
    case MATTER_VALUE_UINT8:
        if (input_type == MATTER_VALUE_BOOL || input > UINT8_MAX) {
            output.error = ERANGE;
            return output;
        }
        output.value.val.u8 = static_cast<uint8_t>(input);
        return output;
    case MATTER_VALUE_UINT16:
        if (input_type == MATTER_VALUE_BOOL || input > UINT16_MAX) {
            output.error = ERANGE;
            return output;
        }
        output.value.val.u16 = static_cast<uint16_t>(input);
        return output;
    default:
        output.error = ENOTSUP;
        return output;
    }
}

} // namespace matter_bridge
