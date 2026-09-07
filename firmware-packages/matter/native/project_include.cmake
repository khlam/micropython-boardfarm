# Build-wide flags connectedhomeip needs. IDF includes this before any
# component CMakeLists, which is the earliest point idf_build_set_property is
# available — mpconfigboard.cmake runs before project.cmake and cannot call it.

# -Os is scoped to C++ because that is where connectedhomeip and esp_matter
# live, and they are most of the image. These options are appended after the
# level Kconfig chose, so the last -O on the command line wins: adding -Os to
# the C options as well would quietly downgrade every C file in the build —
# the MicroPython VM above all — from the -O2 that
# CONFIG_COMPILER_OPTIMIZATION_PERF asks for in boards/sdkconfig.base.
idf_build_set_property(CXX_COMPILE_OPTIONS "-std=gnu++17;-Os;-DCHIP_HAVE_CONFIG_H;-Wno-overloaded-virtual" APPEND)
idf_build_set_property(COMPILE_OPTIONS "-Wno-format-nonliteral;-Wno-format-security" APPEND)
