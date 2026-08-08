# MicroPython user C module manifest for the _matter bridge.
#
# ports/esp32 compiles these sources into its main component so the QSTR and
# MP_REGISTER_MODULE scanners see them. The bridge symbols themselves live in
# the matter-native IDF component, which the board's mpconfigboard.cmake adds
# to the main component's REQUIRES.

add_library(usermod_matter INTERFACE)

target_sources(usermod_matter INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/matter_module.c
)

target_include_directories(usermod_matter INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/../include
)

target_link_libraries(usermod INTERFACE usermod_matter)
