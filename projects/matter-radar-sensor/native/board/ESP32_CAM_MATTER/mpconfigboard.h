#define MICROPY_HW_BOARD_NAME               "ESP32-CAM Matter LD2450"

// os.uname().machine is built from this. BOARD dispatch matches "ESP32S3"
// first, so the classic chip's "ESP32" reaches the ESP32-CAM branch.
#define MICROPY_HW_MCU_NAME                 "ESP32"

// No native USB: the REPL rides UART0 through the ESP32-CAM-MB's USB-serial
// bridge.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// Node.start() brings CHIP up from MicroPython and needs a larger task stack.
#define MICROPY_TASK_STACK_SIZE             (32 * 1024)

// CHIP owns the NimBLE host used for Matter commissioning.
#define MICROPY_PY_BLUETOOTH                (0)
