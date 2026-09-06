#define MICROPY_HW_BOARD_NAME               "ESP32-S3-Zero Matter LD2450"

// os.uname().machine is built from this, and BOARD dispatch matches on the
// "ESP32S3" substring.
#define MICROPY_HW_MCU_NAME                 "ESP32S3"

// The USB-C connector uses the ESP32-S3's USB Serial/JTAG peripheral. Disable
// TinyUSB CDC so MicroPython does not switch that port away before main.py.
#define MICROPY_HW_ENABLE_USBDEV            (0)
#define MICROPY_HW_ESP_USB_SERIAL_JTAG      (1)
#define MICROPY_HW_ENABLE_UART_REPL         (0)

// Node.start() brings CHIP up from MicroPython and needs a larger task stack.
#define MICROPY_TASK_STACK_SIZE             (32 * 1024)

// CHIP owns the NimBLE host used for Matter commissioning.
#define MICROPY_PY_BLUETOOTH                (0)
