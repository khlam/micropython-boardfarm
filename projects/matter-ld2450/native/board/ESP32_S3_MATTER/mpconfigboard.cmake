# ESP32-S3-Zero running MicroPython with native ESP-Matter.

set(IDF_TARGET esp32s3)

set(ESP_MATTER_PATH $ENV{ESP_MATTER_PATH})
if(NOT ESP_MATTER_PATH)
    message(FATAL_ERROR "ESP_MATTER_PATH must name the pinned ESP-Matter checkout")
endif()
if(NOT DEFINED ENV{MATTER_NATIVE_PATH})
    message(FATAL_ERROR "MATTER_NATIVE_PATH must name firmware-packages/matter/native")
endif()

set(MATTER_SDK_PATH "${ESP_MATTER_PATH}/connectedhomeip/connectedhomeip")
set(ENV{ESP_MATTER_DEVICE_PATH} "${ESP_MATTER_PATH}/device_hal/device/esp32s3_devkit_c")

include($ENV{ESP_MATTER_DEVICE_PATH}/esp_matter_device.cmake)

file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.partitions
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"${CMAKE_CURRENT_LIST_DIR}/partitions.csv\"\n")

set(SDKCONFIG_DEFAULTS
    boards/sdkconfig.base
    boards/sdkconfig.ble
    boards/sdkconfig.spiram_sx
    ${ESP_MATTER_PATH}/examples/light/sdkconfig.defaults
    ${CMAKE_CURRENT_LIST_DIR}/sdkconfig.board
    ${CMAKE_BINARY_DIR}/sdkconfig.partitions
)

list(APPEND EXTRA_COMPONENT_DIRS
    "${ESP_MATTER_PATH}/examples/common"
    "${MATTER_SDK_PATH}/config/esp32/components"
    "${ESP_MATTER_PATH}/components"
    "${ESP_MATTER_PATH}/device_hal/device"
    "$ENV{MATTER_NATIVE_PATH}"
    ${extra_components_dirs_append}
)

list(APPEND IDF_COMPONENTS matter-native)
