# The CHIP stack shim as an ordinary IDF component.
#
# matter_module.c is deliberately absent: ports/esp32 compiles it into its own main
# component via USER_C_MODULES so MicroPython's QSTR and MP_REGISTER_MODULE
# scanners can see it. The board's mpconfigboard.cmake puts this component on
# that main component's REQUIRES so the two halves link.
#
# There is no hardware-output dependency: product behavior belongs to project
# firmware, not this protocol component.

# Mode Select is an app-config-dependent CHIP cluster. ESP-Matter exposes its
# endpoint factory but does not add the server implementation to its component,
# so the bridge attaches that source to ESP-Matter whenever it offers the endpoint.
set(MATTER_MODE_SELECT_SERVER
    "${MATTER_SDK_PATH}/src/app/clusters/mode-select-server/mode-select-server.cpp"
)

idf_component_register(
    SRCS
        "src/callbacks.cpp"
        "src/chip_operations.cpp"
        "src/endpoint_schema.cpp"
        "src/event_queue.cpp"
        "src/request.cpp"
        "src/stack.cpp"
        "src/value_conversion.cpp"
    INCLUDE_DIRS "include"
    PRIV_INCLUDE_DIRS "src"
    REQUIRES esp_matter
)

idf_component_get_property(ESP_MATTER_LIB esp_matter COMPONENT_LIB)
target_sources(${ESP_MATTER_LIB} PRIVATE "${MATTER_MODE_SELECT_SERVER}")
target_compile_features(${COMPONENT_LIB} PUBLIC cxx_std_17)
