#define MICROPY_HW_BOARD_NAME               "ESP32-S3-Zero MicroPython Matter LED Strip"

// os.uname().machine is built from this, and every BOARD dispatch in this repo
// matches on the "ESP32S3" substring.
#define MICROPY_HW_MCU_NAME                 "ESP32S3"

// The S3-Zero exposes native USB only, so the REPL rides the USB serial/JTAG
// console rather than an external USB-UART bridge.
#define MICROPY_HW_ENABLE_UART_REPL         (0)

// Node.start() brings CHIP up from main.py, so esp_matter::start() runs on
// mp_task rather than a dedicated init task. 16 KB is not enough for that call
// chain.
#define MICROPY_TASK_STACK_SIZE             (32 * 1024)

// NimBLE is on because Matter commissions over BLE, but CHIP owns that host.
// Exposing MicroPython's `bluetooth` module would give it a second owner, and
// its glue does not build against this IDF's NimBLE headers anyway.
#define MICROPY_PY_BLUETOOTH                (0)
