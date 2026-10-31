# 8BitDo Ultimate 2C Wireless: Native Xbox Controller Firmware (Windows 11 & macOS)

This project makes the **8BitDo Ultimate 2C Wireless** (Bluetooth mode, model `0x301B`, Telink B80 SoC) work as a **100% native Xbox Wireless Controller** over Bluetooth on both **Windows 11** and **macOS**, with **zero drivers, zero background tools, and zero latency overhead**.

Designed specifically for **wireless couch gaming** (e.g. playing on a TV without cables when the original 2.4GHz USB dongle is lost).

---

## What the Firmware Patch Accomplishes

A custom Telink TC32 firmware patch transforms the controller's Bluetooth presentation:

1. **Native Windows 11 XInput (`xinputhid.sys`)**:
   - Presents as a genuine **Microsoft Xbox Wireless Controller (`045E:0B13`)**.
   - Serves an exact **116-byte HID Report Descriptor** crafted to satisfy Windows `xinputhid.sys` with **Code 0** (no Code 10 / "cannot start" errors).
   - Eliminates the need for Steam Input, DS4Windows, or third-party wrappers.

2. **Full Wireless Force-Feedback Rumble (Vibration)**:
   - Repairs 8BitDo's dead Bluetooth output characteristic (which was shipped with an unpopulated RAM pointer and 1-byte length).
   - Implements full Xbox Output Report 3 containing all 5 PID force-feedback usages required by Windows: `0x97` (enable mask), `0x70` (magnitudes), `0x50` (duration), `0xA7` (delay), `0x7C` (loop count).
   - **$2.5\times$ Power Scaling (2.4G Matched)**: Automatically scales incoming Windows magnitude (`0..100`) to 8BitDo hardware PWM levels (`0..250`), restoring full bone-shaking 2.4G-matched rumble force across the entire dynamic range.
   - **2.55-Second Continuous Hardware Timer (`r2 = 255`)**: Sets the motor scheduler countdown timer to 255 ticks (2.55s) so sustained in-game rumble, continuous weapon fire, and engine revs play smoothly without dropouts, while cutting power instantly when the game commands `(0, 0)`.

3. **Wire-Format Report Rewriting**:
   - Injected TC32 code translates stock 10-byte DirectInput reports into standard 19-byte Xbox reports on every packet frame.
   - Fixes swapped LT/RT triggers and analog stick axes.
   - Provides full 16-bit high-resolution stick and trigger precision.

4. **macOS Support**:
   - Fully recognized by Apple's `GameController.framework` and `CoreHaptics` on Apple Silicon and Intel macOS.

---

## Disclaimer

**This project was developed with AI assistance**, including the firmware reverse engineering, opcode disassembly, patch tooling, and flashing scripts.

Flashing modified firmware is done entirely at your own risk. The author is not responsible for a bricked controller, damaged hardware, or lost data. The official 8BitDo updater can always restore stock firmware over USB, and the flashing scripts take automated backups before writing, but proceed with care.

---

## Requirements

- **8BitDo Ultimate 2C Wireless controller** (Model `0x301B`)
- The official **v1.06 beta firmware** as input (`8bitdo-ultimate-2c-wireless_v1.06-beta_model-0x301B.dat`)
- **Windows 11 / 10** with Python 3.10+ (or **macOS** with clang)
- USB-C cable (for the one-time flash in bootloader mode)

---

## Quick Start (Windows)

### 1. Flash the Firmware
1. Turn off the controller (hold Home button until the light turns off).
2. Put the controller in **Bootloader Mode**: hold **`LB` + `RB`**, then plug the USB-C cable into your PC. The LED ring will stay off and the device enumerates as `8BitDo Boot` (`2DC8:3208`).
3. Double-click [`flash-firmware.bat`](flash-firmware.bat) (or run `py -3.12 flash_ultimate2c.py ultimate2c-xbox-windows-rumble.dat`).
4. Wait for flashing and verification to reach 100%. Unplug the USB cable.

### 2. Pair Over Bluetooth
1. In Windows Settings -> **Bluetooth & devices**:
   - If previously paired, click `...` on the controller -> **Remove device** (clears cached descriptors).
2. Hold the pairing button on top of the controller until the indicator blinks rapidly.
3. Click **Add device** -> **Bluetooth** -> select **Xbox Wireless Controller**.

### 3. Verify Inputs and Rumble
- **Test vibration**:
  ```powershell
  py -3.12 test_rumble.py
  ```
  Tests Left heavy motor, Right light motor, 100% full rumble, and a 4-step dynamic speed staircase.
- **Test buttons & sticks**:
  ```powershell
  py -3.12 test_inputs.py
  ```
- **Benchmark Latency & Polling Rate**:
  ```powershell
  py -3.12 benchmark_latency.py
  ```
  *(Or double-click [`benchmark-latency.bat`](benchmark-latency.bat))*. Supports **XInput**, **DirectInput**, and **Raw HID** with side-by-side Bluetooth vs. Cable comparison and live Hz monitoring.

---

## Quick Start (macOS)

1. Put controller in BOOT mode (`LB + RB` + USB cable).
2. Flash using the macOS shell script:
   ```sh
   I_UNDERSTAND_BRICK_RISK=1 ./flash-firmware.sh ultimate2c-1.06beta-xbox-full.dat
   ```
3. Forget and re-pair the controller in macOS System Settings -> Bluetooth.

---

## Feature Support Matrix

| Feature | Windows 11 (XInput Bluetooth) | macOS (GameController Bluetooth) |
|---|:---:|:---:|
| Left / Right Sticks (16-bit analog) | **Yes** | **Yes** |
| LT / RT Triggers (16-bit analog) | **Yes** | **Yes** |
| A / B / X / Y | **Yes** | **Yes** |
| LB / RB Bumpers | **Yes** | **Yes** |
| View / Menu (Back / Start) | **Yes** | **Yes** |
| Home (Xbox Guide Button) | **Yes** | **Yes** |
| L3 / R3 (Stick clicks) | **Yes** | **Yes** |
| D-pad (all 8 directions) | **Yes** | **Yes** |
| **Wireless Force-Feedback Rumble** | **Yes (Full $2.5\times$ Scaled, 2.55s continuous)** | **Yes (CoreHaptics)** |
| L4 / R4 Extra Bumpers | Stock DirectInput bits (Standard XInput 16-button profile) | Wire-only (Apple Elite limitation) |
| USB Wired Mode | **Stock (Untouched)** | **Stock (Untouched)** |
| 2.4GHz Dongle Radio | **Stock (Untouched)** | **Stock (Untouched)** |

---

## Checksums

| File | SHA-256 |
|---|---|
| Input: Official v1.06 beta (`0x301B`) | `11c8d195d3ca76da24a33ba92ad9d7ae8ad6f455244864bed4c66898e9074bfb` |
| Output: Windows Rumble Build (`ultimate2c-xbox-windows-rumble.dat`) | `d4d2d7f7209487623a2b28cdbbd8e15a4506a2256065cff1b357d780969d15ef` |
| Output: macOS Full Wire Build (`ultimate2c-1.06beta-xbox-full.dat`) | `18e2c710def1832177b17dbade1f81b9f2aa8c11bf7e5ce71567d0e6d05f34c1` |

---

## Documentation

- **[docs/firmware-patch.md](docs/firmware-patch.md)** - In-depth breakdown of the patch, exact memory offsets, GATT table layout, Report Descriptors, wire formats, and rumble scaling mechanics.
- **[docs/developing-patches.md](docs/developing-patches.md)** - Complete technical guide on reverse engineering the Telink B80 SoC: disassembly with Ghidra/TC32, kernel tracing (`xinputhid.sys`), opcode encodings, code cave injection, and safe flashing practices.
