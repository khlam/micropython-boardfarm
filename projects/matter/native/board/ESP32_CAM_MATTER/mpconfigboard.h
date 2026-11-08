#define MICROPY_HW_BOARD_NAME               "ESP32-CAM MicroPython Matter"

// os.uname().machine is built from this. BOARD dispatch in this repo matches
// "ESP32S3" first, so the classic chip's "ESP32" reaches the ESP32-CAM branch.
#define MICROPY_HW_MCU_NAME                 "ESP32"

// The ESP32-CAM has no native USB; the REPL rides UART0 through the
// ESP32-CAM-MB's USB-serial bridge.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// Node.start() brings CHIP up from main.py, so esp_matter::start() runs on
// mp_task rather than a dedicated init task. 16 KB is not enough for that call
// chain.
#define MICROPY_TASK_STACK_SIZE             (32 * 1024)

// NimBLE is on because Matter commissions over BLE, but CHIP owns that host.
// Exposing MicroPython's `bluetooth` module would give it a second owner, and
// its glue does not build against this IDF's NimBLE headers anyway.
#define MICROPY_PY_BLUETOOTH                (0)
