# Keep the pinned MicroPython WLAN module linkable when ESP-IDF omits SoftAP.

idf_component_register(
    SRCS "station_only_compat.c"
    REQUIRES esp_wifi
)
