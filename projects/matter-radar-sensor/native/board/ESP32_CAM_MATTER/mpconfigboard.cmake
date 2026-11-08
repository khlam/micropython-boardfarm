# AI-Thinker ESP32-CAM (classic ESP32) running MicroPython with native
# ESP-Matter. The camera and microSD slot are unused.

set(IDF_TARGET esp32)

set(ESP_MATTER_PATH $ENV{ESP_MATTER_PATH})
if(NOT ESP_MATTER_PATH)
    message(FATAL_ERROR "ESP_MATTER_PATH must name the pinned ESP-Matter checkout")
endif()
if(NOT DEFINED ENV{MATTER_NATIVE_PATH})
    message(FATAL_ERROR "MATTER_NATIVE_PATH must name firmware-packages/matter/native")
endif()

set(MATTER_SDK_PATH "${ESP_MATTER_PATH}/connectedhomeip/connectedhomeip")
set(ENV{ESP_MATTER_DEVICE_PATH} "${ESP_MATTER_PATH}/device_hal/device/esp32_devkit_c")

include($ENV{ESP_MATTER_DEVICE_PATH}/esp_matter_device.cmake)

file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.partitions
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"${CMAKE_CURRENT_LIST_DIR}/partitions.csv\"\n")

# sdkconfig.spiram is the classic-ESP32 PSRAM fragment: it carries the PSRAM
# cache-bug workaround and the options that keep the result inside IRAM.
set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.spiram
    ${ESP_MATTER_PATH}/examples/light/sdkconfig.defaults
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
    ${CMAKE_BINARY_DIR}/sdkconfig.partitions
)

list(APPEND EXTRA_COMPONENT_DIRS
    "${ESP_MATTER_PATH}/examples/common"
    "${MATTER_SDK_PATH}/config/esp32/components"
    "${ESP_MATTER_PATH}/components"
    "${ESP_MATTER_PATH}/device_hal/device"
    "${CMAKE_CURRENT_LIST_DIR}/../station_only_compat"
    "$ENV{MATTER_NATIVE_PATH}"
    ${extra_components_dirs_append}
)

list(APPEND IDF_COMPONENTS matter-native station-only-compat)
