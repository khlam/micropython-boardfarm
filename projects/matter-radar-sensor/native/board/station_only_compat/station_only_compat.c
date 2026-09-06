// Copyright 2026 micropython-boardfarm contributors
// SPDX-License-Identifier: MIT

#include <stddef.h>

#include "esp_wifi_default.h"

#ifdef CONFIG_ESP_WIFI_SOFTAP_SUPPORT
#error "station_only_compat must only be linked when SoftAP is disabled"
#endif

// MicroPython initializes both WLAN objects unconditionally. ESP-IDF removes
// this symbol with SoftAP support, so return no AP netif while preserving its
// station initialization path. Product firmware never requests the AP object.
esp_netif_t *esp_netif_create_default_wifi_ap(void)
{
    return NULL;
}
