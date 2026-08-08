// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "endpoint_schema.h"

#include "matter/bridge.h"

namespace ColorControl = chip::app::Clusters::ColorControl;

namespace matter_bridge {
namespace {

// Fallback starting values used when a light endpoint is created. Matter
// brightness uses 0-254; color temperature is stored in mireds, and this
// bridge supports 153-500 mireds. MicroPython can replace these defaults
// with application-specific values.
constexpr uint8_t kDefaultLevel = 254;
constexpr uint16_t kDefaultTemperatureMireds = 250;
constexpr uint16_t kMinimumTemperatureMireds = 153;
constexpr uint16_t kMaximumTemperatureMireds = 500;

} // namespace

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
        config.level_control.current_level = kDefaultLevel;
        config.level_control.on_level = kDefaultLevel;
        config.level_control_lighting.start_up_current_level = nullptr;
        return esp_matter::endpoint::dimmable_light::create(node, &config, esp_matter::ENDPOINT_FLAG_NONE,
                                                            nullptr);
    }
    case MATTER_ENDPOINT_EXTENDED_COLOR_LIGHT: {
        esp_matter::endpoint::extended_color_light::config_t config;
        config.on_off.on_off = false;
        config.on_off_lighting.start_up_on_off = nullptr;
        config.level_control.current_level = kDefaultLevel;
        config.level_control.on_level = kDefaultLevel;
        config.level_control_lighting.start_up_current_level = nullptr;
        config.color_control.color_mode = static_cast<uint8_t>(ColorControl::ColorMode::kColorTemperature);
        config.color_control.enhanced_color_mode =
            static_cast<uint8_t>(ColorControl::ColorMode::kColorTemperature);
        config.color_control_color_temperature.color_temperature_mireds = kDefaultTemperatureMireds;
        config.color_control_color_temperature.color_temp_physical_min_mireds = kMinimumTemperatureMireds;
        config.color_control_color_temperature.color_temp_physical_max_mireds = kMaximumTemperatureMireds;
        config.color_control_color_temperature.start_up_color_temperature_mireds = nullptr;
        esp_matter::endpoint_t *endpoint = esp_matter::endpoint::extended_color_light::create(
            node, &config, esp_matter::ENDPOINT_FLAG_NONE, nullptr);
        if (endpoint == nullptr) {
            return nullptr;
        }
        esp_matter::cluster_t *color_cluster = esp_matter::cluster::get(endpoint, ColorControl::Id);
        if (color_cluster == nullptr) {
            return nullptr;
        }
        esp_matter::cluster::color_control::feature::hue_saturation::config_t hue_saturation;
        hue_saturation.current_hue = 0;
        hue_saturation.current_saturation = 0;
        if (esp_matter::cluster::color_control::feature::hue_saturation::add(color_cluster,
                                                                            &hue_saturation) != ESP_OK) {
            return nullptr;
        }
        return endpoint;
    }
    default:
        return nullptr;
    }
}

} // namespace matter_bridge
