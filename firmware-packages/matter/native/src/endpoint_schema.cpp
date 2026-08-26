// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT
#include "endpoint_schema.h"

#include "matter/bridge.h"

namespace ColorControl = chip::app::Clusters::ColorControl;
namespace Identify = chip::app::Clusters::Identify;
namespace LevelControl = chip::app::Clusters::LevelControl;
namespace OnOff = chip::app::Clusters::OnOff;
namespace OccupancySensing = chip::app::Clusters::OccupancySensing;

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

// Matter has no radar modality, so the required type metadata declares PIR.
constexpr uint8_t OCCUPANCY_SENSOR_TYPE_PIR =
    static_cast<uint8_t>(OccupancySensing::OccupancySensorTypeEnum::kPir);
constexpr uint8_t OCCUPANCY_SENSOR_TYPE_BITMAP_PIR =
    static_cast<uint8_t>(OccupancySensing::OccupancySensorTypeBitmap::kPir);

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

// Occupancy is republished after boot rather than persisted. ESP-Matter can
// return an endpoint without its required sensing cluster, so verify it here.
esp_matter::endpoint_t *create_occupancy_sensor(esp_matter::node_t *node)
{
    esp_matter::endpoint::occupancy_sensor::config_t config;
    config.occupancy_sensing.occupancy = 0;
    config.occupancy_sensing.occupancy_sensor_type = OCCUPANCY_SENSOR_TYPE_PIR;
    config.occupancy_sensing.occupancy_sensor_type_bitmap = OCCUPANCY_SENSOR_TYPE_BITMAP_PIR;
    config.occupancy_sensing.feature_flags =
        esp_matter::cluster::occupancy_sensing::feature::passive_infrared::get_id();
    esp_matter::endpoint_t *endpoint = esp_matter::endpoint::occupancy_sensor::create(
        node, &config, esp_matter::ENDPOINT_FLAG_NONE, nullptr);
    if (endpoint == nullptr) {
        return nullptr;
    }
    if (esp_matter::cluster::get(endpoint, OccupancySensing::Id) == nullptr) {
        return destroy_and_fail(node, endpoint);
    }
    return endpoint;
}

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
    case MATTER_ENDPOINT_OCCUPANCY_SENSOR:
        return create_occupancy_sensor(node);
    case MATTER_ENDPOINT_ON_OFF_PLUG_IN_UNIT: {
        esp_matter::endpoint::on_off_plug_in_unit::config_t config;
        config.on_off.on_off = false;
        config.on_off_lighting.start_up_on_off = nullptr;
        return esp_matter::endpoint::on_off_plug_in_unit::create(node, &config, esp_matter::ENDPOINT_FLAG_NONE,
                                                                nullptr);
    }
    default:
        return nullptr;
    }
}

bool is_occupancy_attribute(uint32_t cluster_id, uint32_t attribute_id)
{
    return cluster_id == OccupancySensing::Id && attribute_id == OccupancySensing::Attributes::Occupancy::Id;
}

bool endpoint_type_tracks_attribute(uint8_t endpoint_type, uint32_t cluster_id, uint32_t attribute_id)
{
    if (cluster_id == Identify::Id && attribute_id == Identify::Attributes::IdentifyTime::Id) {
        return true;
    }
    if (endpoint_type == MATTER_ENDPOINT_OCCUPANCY_SENSOR) {
        return is_occupancy_attribute(cluster_id, attribute_id);
    }
    if (cluster_id == OnOff::Id && attribute_id == OnOff::Attributes::OnOff::Id) {
        return true;
    }
    if (endpoint_type == MATTER_ENDPOINT_ON_OFF_LIGHT ||
        endpoint_type == MATTER_ENDPOINT_ON_OFF_PLUG_IN_UNIT) {
        return false;
    }
    if (cluster_id == LevelControl::Id &&
        attribute_id == LevelControl::Attributes::CurrentLevel::Id) {
        return true;
    }
    if (endpoint_type != MATTER_ENDPOINT_EXTENDED_COLOR_LIGHT || cluster_id != ColorControl::Id) {
        return false;
    }
    return attribute_id == ColorControl::Attributes::CurrentHue::Id ||
           attribute_id == ColorControl::Attributes::CurrentSaturation::Id ||
           attribute_id == ColorControl::Attributes::CurrentX::Id ||
           attribute_id == ColorControl::Attributes::CurrentY::Id ||
           attribute_id == ColorControl::Attributes::ColorTemperatureMireds::Id ||
           attribute_id == ColorControl::Attributes::ColorMode::Id ||
           attribute_id == ColorControl::Attributes::EnhancedColorMode::Id;
}

} // namespace matter_bridge
