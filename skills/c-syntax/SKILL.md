---
name: c-syntax
description: C and C++ conventions for native and performance-sensitive embedded code — indentation, braces, naming, fixed-width integers, and the MicroPython native boundary. Use when writing or reviewing C/C++ under firmware-packages/*/native/ or any MicroPython native module.
---

# C and C++

Follow MicroPython's native-code conventions unless preserving third-party source style.

Use:

* 4-space indentation;
* K&R braces;
* braces for every control block;
* `snake_case` for functions and variables;
* `UPPER_SNAKE_CASE` for macros/constants/enums;
* `_t` suffixes for typedefs.

Example:

```c
if (ready) {
    sample();
} else {
    recover();
}
```

Use `size_t` for sizes and fixed-width integers such as `uint8_t` or `uint32_t` for hardware registers and wire formats.

At MicroPython boundaries, use appropriate MicroPython integer and allocation APIs.

Keep ownership explicit. Avoid unnecessary dynamic allocation in MCU hot paths.

For C++:

* keep the MicroPython-facing boundary small;
* use `extern "C"` where required;
* do not allow C++ exceptions to cross C or MicroPython boundaries;
* do not assume exceptions, RTTI, or the full STL are available on every target.

Prefer typed functions or `static inline` functions over function-like macros.

Check return codes and translate native failures into meaningful Python/MicroPython exceptions.
