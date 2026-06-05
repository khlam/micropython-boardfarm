## macOS: serial bridge
Docker Desktop runs containers inside a Linux VM, and neither it nor Apple's Virtualization.framework can pass a USB-serial device into that VM — so the `/dev:/dev` mount the `viz` and `esp32-flash` services rely on sees nothing on macOS. [`tools/serial-bridge.sh`](serial-bridge.sh) works around this with a full-duplex serial↔TCP relay built from stock tools (`stty`/`cat`/`nc`) — nothing is installed on the host. Set it up **once**, then every project's commands match Linux.

1. In its own terminal, start the bridge and leave it running. It auto-detects the board (`/dev/cu.usbmodem*`) and serves it on TCP `5555`:
   ```sh
   tools/serial-bridge.sh
   ```
2. In your shell profile (`~/.zshrc`), point `SERIAL_PORT` at the bridge so every project picks it up:
   ```sh
   export SERIAL_PORT=socket://host.docker.internal:5555
   ```
   Open a new terminal (or `source ~/.zshrc`) so the variable is set.
3. Run the dashboard or flash exactly as on Linux — both read `SERIAL_PORT`:
   ```sh
   docker compose up --build viz                # reads the board over the bridge
   docker compose run --rm --build esp32-flash  # compiles + flashes over the bridge
   ```
   The bridge carries no DTR/RTS reset line, so flashing requires the board to **already** be in bootloader mode (hold **BOOT**, tap **RESET**); the `esp32-flash` stage passes `--before/--after no_reset` automatically for `socket://` ports.
