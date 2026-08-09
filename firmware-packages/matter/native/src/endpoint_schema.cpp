// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "endpoint_schema.h"

#include <cstring>

#include <app/clusters/mode-select-server/supported-modes-manager.h>

#include "matter/bridge.h"

namespace ColorControl = chip::app::Clusters::ColorControl;
namespace LevelControl = chip::app::Clusters::LevelControl;
namespace ModeSelect = chip::app::Clusters::ModeSelect;

namespace matter_bridge {
namespace {

// Fallback starting values used when a light endpoint is created. Matter
// brightness uses 0-254; color temperature is stored in mireds, and this
// bridge supports 153-500 mireds. MicroPython can replace these defaults
// with application-specific values.
constexpr uint8_t DEFAULT_LEVEL = 254;
constexpr uint16_t DEFAULT_TEMPERATURE_MIREDS = 250;
constexpr uint16_t MINIMUM_TEMPERATURE_MIREDS = 153;
constexpr uint16_t MAXIMUM_TEMPERATURE_MIREDS = 500;

class ModeOptionsManager final : public ModeSelect::SupportedModesManager {
public:
    void configure(const matter_mode_option *options, size_t option_count)
    {
        count = option_count;
        for (size_t index = 0; index < option_count; ++index) {
            const size_t length = std::strlen(options[index].label);
            std::memcpy(labels[index], options[index].label, length + 1);
            mode_options[index].label = chip::CharSpan(labels[index], length);
            mode_options[index].mode = options[index].mode;
            mode_options[index].semanticTags = {};
        }
    }

    void bind(uint16_t endpoint)
    {
        endpoint_id = endpoint;
    }

    ModeOptionsProvider getModeOptionsProvider(chip::EndpointId endpoint) const override
    {
        if (endpoint != endpoint_id) {
            return {};
        }
        return ModeOptionsProvider(mode_options, mode_options + count);
    }

    chip::Protocols::InteractionModel::Status
    getModeOptionByMode(chip::EndpointId endpoint, uint8_t mode,
                        const ModeSelect::Structs::ModeOptionStruct::Type **option) const override
    {
        using chip::Protocols::InteractionModel::Status;
        if (endpoint != endpoint_id || option == nullptr) {
            return Status::InvalidCommand;
        }
        for (size_t index = 0; index < count; ++index) {
            if (mode_options[index].mode == mode) {
                *option = &mode_options[index];
                return Status::Success;
            }
        }
        return Status::InvalidCommand;
    }

private:
    char labels[MATTER_MAX_MODE_OPTIONS][MATTER_MODE_TEXT_SIZE]{};
    ModeSelect::Structs::ModeOptionStruct::Type mode_options[MATTER_MAX_MODE_OPTIONS]{};
    size_t count = 0;
    uint16_t endpoint_id = 0;
};

ModeOptionsManager mode_options_manager;

bool defer_persistence(esp_matter::endpoint_t *endpoint, uint32_t cluster_id, uint32_t attribute_id)
{
    const uint16_t endpoint_id = esp_matter::endpoint::get_id(endpoint);
    esp_matter::attribute_t *attribute = esp_matter::attribute::get(endpoint_id, cluster_id, attribute_id);
    return attribute != nullptr && esp_matter::attribute::set_deferred_persistence(attribute) == ESP_OK;
}

bool defer_dimmable_attributes(esp_matter::endpoint_t *endpoint)
{
    return defer_persistence(endpoint, LevelControl::Id, LevelControl::Attributes::CurrentLevel::Id);
}

bool defer_extended_color_attributes(esp_matter::endpoint_t *endpoint)
{
    return defer_dimmable_attributes(endpoint) &&
           defer_persistence(endpoint, ColorControl::Id, ColorControl::Attributes::CurrentHue::Id) &&
           defer_persistence(endpoint, ColorControl::Id, ColorControl::Attributes::CurrentSaturation::Id) &&
           defer_persistence(endpoint, ColorControl::Id, ColorControl::Attributes::CurrentX::Id) &&
           defer_persistence(endpoint, ColorControl::Id, ColorControl::Attributes::CurrentY::Id) &&
           defer_persistence(endpoint, ColorControl::Id,
                             ColorControl::Attributes::ColorTemperatureMireds::Id);
}

// Every post-create failure path funnels through here so a half-configured
// endpoint is torn down rather than left attached to the node with no
// Python-side ID ever recorded.
esp_matter::endpoint_t *destroy_and_fail(esp_matter::node_t *node, esp_matter::endpoint_t *endpoint)
{
    esp_matter::endpoint::destroy(node, endpoint);
    return nullptr;
}

} // namespace

esp_matter::endpoint_t *mode_select_endpoint(esp_matter::node_t *node, const char *description,
                                             const matter_mode_option *options, size_t option_count)
{
    mode_options_manager.configure(options, option_count);
    esp_matter::endpoint::mode_select::config_t config;
    const size_t description_length = std::strlen(description);
    std::memcpy(config.mode_select.description, description, description_length + 1);
    config.mode_select.current_mode = options[0].mode;
    config.mode_select.delegate = &mode_options_manager;
    esp_matter::endpoint_t *endpoint = esp_matter::endpoint::mode_select::create(
        node, &config, esp_matter::ENDPOINT_FLAG_NONE, nullptr);
    if (endpoint != nullptr) {
        mode_options_manager.bind(esp_matter::endpoint::get_id(endpoint));
    }
    return endpoint;
}

// The `start_up_*` fields are left null so ESP-Matter can restore values saved
// from an earlier boot instead of forcing these constructor defaults every
// time. MicroPython's initial-value API is therefore the one place an
// application intentionally pins startup state. The extended-color endpoint
// supports both color temperature and hue/saturation on the same endpoint.
esp_matter::endpoint_t *endpoint_type_to_endpoint(esp_matter::node_t *node, uint8_t endpoint_type)
{
    switch (endpoint_type) {
    case MATTER_ENDPOINT_ON_OFF_LIGHT: {
        esp_matter::endpoint::on_off_light::config_t config;
        config.on_off.on_off = false;
        config.on_off_lighting.start_up_on_off = nullptr;
        return esp_matter::endpoint::on_off_light::create(node, &config, esp_matter::ENDPOINT_FLAG_NONE,
                                                          nullptr);
    }
    case MATTER_ENDPOINT_DIMMABLE_LIGHT: {
        esp_matter::endpoint::dimmable_light::config_t config;
        config.on_off.on_off = false;
        config.on_off_lighting.start_up_on_off = nullptr;
        config.level_control.current_level = DEFAULT_LEVEL;
        config.level_control.on_level = DEFAULT_LEVEL;
        config.level_control_lighting.start_up_current_level = nullptr;
        esp_matter::endpoint_t *endpoint = esp_matter::endpoint::dimmable_light::create(
            node, &config, esp_matter::ENDPOINT_FLAG_NONE, nullptr);
        if (endpoint == nullptr) {
            return nullptr;
        }
        if (!defer_dimmable_attributes(endpoint)) {
            return destroy_and_fail(node, endpoint);
        }
        return endpoint;
    }
    case MATTER_ENDPOINT_EXTENDED_COLOR_LIGHT: {
        esp_matter::endpoint::extended_color_light::config_t config;
        config.on_off.on_off = false;
        config.on_off_lighting.start_up_on_off = nullptr;
        config.level_control.current_level = DEFAULT_LEVEL;
        config.level_control.on_level = DEFAULT_LEVEL;
        config.level_control_lighting.start_up_current_level = nullptr;
        config.color_control.color_mode = static_cast<uint8_t>(ColorControl::ColorMode::kColorTemperature);
        config.color_control.enhanced_color_mode =
            static_cast<uint8_t>(ColorControl::ColorMode::kColorTemperature);
        config.color_control_color_temperature.color_temperature_mireds = DEFAULT_TEMPERATURE_MIREDS;
        config.color_control_color_temperature.color_temp_physical_min_mireds = MINIMUM_TEMPERATURE_MIREDS;
        config.color_control_color_temperature.color_temp_physical_max_mireds = MAXIMUM_TEMPERATURE_MIREDS;
        config.color_control_color_temperature.start_up_color_temperature_mireds = nullptr;
        esp_matter::endpoint_t *endpoint = esp_matter::endpoint::extended_color_light::create(
            node, &config, esp_matter::ENDPOINT_FLAG_NONE, nullptr);
        if (endpoint == nullptr) {
            return nullptr;
        }
        esp_matter::cluster_t *color_cluster = esp_matter::cluster::get(endpoint, ColorControl::Id);
        if (color_cluster == nullptr) {
            return destroy_and_fail(node, endpoint);
        }
        esp_matter::cluster::color_control::feature::hue_saturation::config_t hue_saturation;
        hue_saturation.current_hue = 0;
        hue_saturation.current_saturation = 0;
        if (esp_matter::cluster::color_control::feature::hue_saturation::add(color_cluster,
                                                                            &hue_saturation) != ESP_OK) {
            return destroy_and_fail(node, endpoint);
        }
        if (!defer_extended_color_attributes(endpoint)) {
            return destroy_and_fail(node, endpoint);
        }
        return endpoint;
    }
    default:
        return nullptr;
    }
}

} // namespace matter_bridge
