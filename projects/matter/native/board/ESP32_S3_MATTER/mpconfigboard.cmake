# ESP32-S3-Zero (FH4R2) running MicroPython with native ESP-Matter.
#
# ports/esp32/CMakeLists.txt includes this file before project.cmake, which is
# the only window in which EXTRA_COMPONENT_DIRS and the main component's
# REQUIRES can still be extended. IDF functions are not available yet, so
# anything needing idf_build_set_property lives in the matter-native
# component's project_include.cmake instead.

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

# Sets extra_components_dirs_append (led_driver, button_driver). Pure variable
# assignment, so it is safe this early.
include($ENV{ESP_MATTER_DEVICE_PATH}/esp_matter_device.cmake)

# The IDF project directory is MicroPython's ports/esp32, not this board
# directory, so the partition table has to be named by absolute path.
file(WRITE ${CMAKE_BINARY_DIR}/sdkconfig.partitions
    "CONFIG_PARTITION_TABLE_CUSTOM_FILENAME=\"${CMAKE_CURRENT_LIST_DIR}/partitions.csv\"\n")

# Concatenated in order by the port; later files win on conflicting keys.
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

# esp32_common.cmake feeds IDF_COMPONENTS straight into the main component's
# REQUIRES. This is what lets the frozen-in matter_module.c reach the bridge
# symbols without patching upstream MicroPython.
list(APPEND IDF_COMPONENTS matter-native)
