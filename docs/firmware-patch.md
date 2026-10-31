# The Firmware Patch: macOS GameController & Windows 11 Native XInput

This document describes exactly what the firmware patches change in the 8BitDo Ultimate 2C Wireless (`0x301B`, Telink B80 SoC) firmware, why each change exists, and the technical evidence behind each decision.

Two build scripts are provided:
1. `build_fixed_firmware.py` $\rightarrow$ [`ultimate2c-xbox-windows-rumble.dat`](../ultimate2c-xbox-windows-rumble.dat): Tailored for Windows 11 / 10 native XInput (`xinputhid.sys`) with full force-feedback rumble, $2.5\times$ PWM scaling, and verified stick/trigger axes. Also compatible with macOS and Linux.
2. `patch_ultimate2c_xbox_full.py` $\rightarrow$ `ultimate2c-1.06beta-xbox-full.dat`: The original macOS Apple Silicon target with Elite V2 identity (`045E:0B22`).

---

## 1. Problem Statement & Host Drivers

Gamepads operate differently across operating systems over Bluetooth Low Energy (BLE):

### macOS
- **GameController.framework** matches devices against an internal kernel allowlist (`AppleGameControllerPersonality.kext`).
- Only allowlisted Vendor/Product IDs are claimed.
- For Xbox controllers, the driver **strictly parses input reports with the fixed 19-byte Xbox Bluetooth layout**, ignoring arbitrary third-party report maps. Stock 8BitDo 10-byte DirectInput reports result in dead or misaligned buttons.

### Windows 11
- Windows uses the kernel-mode driver **`xinputhid.sys`** (`C:\Windows\System32\drivers\xinputhid.sys`) to bind BLE gamepads into the standard XInput subsystem (Controllers 0..3).
- **Code 10 ("Device Cannot Start")**: If the Bluetooth HID Report Descriptor does not adhere to Microsoft's precise Xbox layout specifications or is missing mandatory Force Feedback (rumble) Usages in Output Report 3, `xinputhid.sys` fails during driver initialization (`DriverEntry` / `0x140003ed4`) and leaves a yellow exclamation mark in Device Manager.
- **Dead Rumble in Stock Firmware**: The stock 8BitDo firmware ships with a broken 1-byte Output Characteristic pointing to unpopulated RAM (`0x842E14`), making wireless rumble impossible out of the box on all operating systems.

---

## 2. The Base Firmware Image

The stock 1.06 beta firmware is a 74,780-byte `.dat` file:

| Region | File Offset | Notes |
|---|---|---|
| Wrapper | `0x00..0x1C` | 28-byte header |
| Payload | `0x1C..0x12400` | 74,752 bytes; `KNLT` tag at payload + 8 |
| Covered by CRC | payload start to `0x1233C` | `hsize` (payload + 0x18) is `0x12324`; CRC32 stored at `hsize - 4` |
| Trailer | `0x12340..0x1241C` | 220 zero bytes, **not** covered by the CRC |

Firmware memory addresses in disassembly map to file offsets as:
$$\text{file} = \text{fw} - 0x6000 + 0x1C$$

---

## 3. Summary of Firmware Changes (Windows Rumble Build)

| # | Change | File Offset | Stock Firmware | Patched Firmware |
|---|---|---|---|---|
| 1 | Bluetooth PnP ID | `0x11488` | `02 c8 2d 02 60 01 00` (8BitDo) | `02 5e 04 13 0b 01 00` (Xbox Wireless Controller `045E:0B13`) |
| 2 | HID Report Map | `0x11414` | 116-byte stock DInput map | 116-byte Xbox Map (Full Input + 5-Usage Output Report 3) |
| 3 | GATT Map Length | `0x11868` | `0x74` (116) | `0x74` (116, exact in-place fit) |
| 4 | Input Notify Hook | `0x5B38` | `notify(0x40, 0x1D, sp, 10)` call | `tjl 0x12340` + 4 nops |
| 5 | Code Cave (Input Remapper) | `0x12340` | All zeros (padding) | 132 bytes of TC32 (axis & button remapper) |
| 6 | Motor Handler (Rumble) | `0x123C4` | All zeros (padding) | 30 bytes of TC32 ($2.5\times$ PWM scaling + scheduler call) |
| 7 | Static Report Reference | `0x123E2` | All zeros (padding) | `03 02` (Report ID 3, Type Output) |
| 8 | Output Attr Length | `0x11820` | `1` byte | `8` bytes |
| 9 | Output Write Callback | `0x1182C` | `0` (null / no handler) | `0x183A9` (`fw_addr(0x123C4) \| 1`) |
| 10 | Output Report Reference | `0x11840` | `0x842E14` (unpopulated RAM) | `0x183C6` (points to static `[03 02]`) |
| 11 | Telink CRC32 | `0x1233C` | `0x2638C6C6` (stock) | Recomputed and verified |

---

## 4. Deep-Dive: Windows 11 `xinputhid.sys` & The 116-Byte Report Map

### Why the Original Draft Failed with Code 10
Reverse engineering `C:\Windows\System32\drivers\xinputhid.sys` revealed that when an Xbox BLE controller enumerates, the driver inspects the parsed HID collections:
1. It validates the 19-byte Input Report 1 (X, Y, Z/Rx, Rz/Ry, Hat, Buttons).
2. At `0x140003ed4`, it calls `HidP_GetSpecificValueCaps` on Output Report 3, checking for **five mandatory PID Force Feedback Usages**:
   - `0x97`: Actuator Enable Mask (4-bit)
   - `0x70`: Actuator Magnitudes (4x 8-bit array for 4 rumble motors)
   - `0x50`: Pulse Duration (8-bit)
   - `0xA7`: Pulse Start Delay (8-bit)
   - `0x7C`: Loop Count (8-bit)
3. If any of these usages are absent, the driver aborts with `STATUS_UNSUCCESSFUL`, causing **Code 10**.

### The 116-Byte Compact Descriptor
The stock firmware reserves an exact 116-byte slot at `0x11414` for the descriptor. Extending beyond 116 bytes would push into GATT attribute tables and corrupt Bluetooth functionality.

We crafted an exact 116-byte descriptor combining the full 19-byte input report and all 5 rumble usages:
```
05 01        Usage Page (Generic Desktop)
09 05        Usage (Gamepad)
A1 01        Collection (Application)
85 01          Report ID (1)
15 00          Logical Minimum (0)
26 FF FF       Logical Maximum (65535)
75 10          Report Size (16)
19 30 29 32    Usage Minimum (X), Usage Maximum (Z/Rx)
09 35          Usage (Rz/Ry)
95 04          Report Count (4)
81 02          Input (Data, Var, Abs) - Sticks LX, LY, RX, RY (4x 16-bit)
05 02          Usage Page (Simulation Controls)
09 C5 09 C4    Usage (Brake / LT), Usage (Accelerator / RT)
95 02          Report Count (2)
81 02          Input (Data, Var, Abs) - Triggers LT, RT (2x 16-bit)
05 01          Usage Page (Generic Desktop)
09 39          Usage (Hat switch)
15 01          Logical Minimum (1)
25 08          Logical Maximum (8)
75 04 95 01    Report Size (4), Report Count (1)
81 42          Input (Data, Var, Abs, Null) - D-Pad (4-bit)
75 04 81 03    Report Size (4), Input (Const) - Padding (4-bit)
05 09          Usage Page (Button)
19 01 29 10    Usage Minimum (Button 1), Usage Maximum (Button 16)
15 00 25 01    Logical Min (0), Logical Max (1)
75 01 95 10    Report Size (1), Report Count (16)
81 02          Input (Data, Var, Abs) - 16 Buttons
75 20 95 01    Report Size (32), Report Count (1)
81 03          Input (Const) - Elite tail padding (32-bit)
05 0F          Usage Page (Physical Interface Device)
09 21          Usage (Set Effect Report)
85 03          Report ID (3)
A1 02          Collection (Logical)
09 97            Usage (DC Enable Actuators)
75 04 91 02      Output (Data, Var, Abs) - Enable mask (4-bit)
91 03            Output (Const) - Padding (4-bit)
09 70            Usage (Magnitude)
25 64            Logical Maximum (100)
75 08 95 04      Report Size (8), Report Count (4)
91 02            Output (Data, Var, Abs) - 4 Motor Magnitudes (LeftTrigger, RightTrigger, LeftHeavy, RightLight)
09 50            Usage (Duration)
09 A7            Usage (Start Delay)
09 7C            Usage (Loop Count)
26 FF 00         Logical Maximum (255)
95 03 91 02      Report Count (3), Output (Data, Var, Abs)
C0             End Collection
C0           End Collection
```
*(Exact size: 116 bytes. Eliminates Code 10 completely).*

---

## 5. Input Report Rewriting (Code Cave)

The stock firmware constructs a 10-byte input report at `sp` inside `0x59CC`:
```
[0] Hat (0..7 clockwise, 15 = center)
[1] Left Stick X    [2] Left Stick Y
[3] Right Stick X   [4] Right Stick Y
[5] RT (Right Trigger) [6] LT (Left Trigger)
[7] Buttons low:  bit0: A, bit1: B, bit2: L4, bit3: X, bit4: Y, bit5: R4, bit6: LB, bit7: RB
[8] Buttons high: bit2: Minus, bit3: Plus, bit4: Home, bit5: L3, bit6: R3
[9] Battery level
```

The hook at `0x5B38` intercepts the notification call and branches to the code cave at `0x12340`. The cave constructs the 19-byte Xbox payload:
- **Stick Axes [0..7]**: Duplicates 8-bit stick bytes into 16-bit LE words.
- **Triggers [8..11]**: Maps `stock[6]` to LT (`wire[8..9]`) and `stock[5]` to RT (`wire[10..11]`) shifted left by 2 (10-bit value in 16-bit field), correcting swapped triggers.
- **Hat [12]**: Maps stock 0..7 (center 15) to Xbox 1..8 (center 0).
- **Buttons [13..14]**: Masks buttons low (`& 0xDB`) and buttons high (`& 0x7C`), aligning them with the Xbox button bitmask.
- **Tail [15..18]**: Writes paddles to 15/16 and zeros to 17/18.

---

## 6. Force-Feedback Rumble: Scaling & Scheduling (2.4G Matched)

### The Scale Mismatch Problem
- Windows `xinputhid.sys!0x1400064b5` processes XInput rumble packets (`0..65535`). It passes each motor speed byte through a 256-entry lookup table at `0x140001020` that divides the value down to percent: **`0..100` (`0x00..0x64`)**.
- 8BitDo's internal hardware motor scheduler (`0x9B30`) and PWM controller (`0x9A04`) expect **`0..255`**.
- In the initial unscaled handler, passing raw `0..100` resulted in:
  - 100% in-game vibration $\rightarrow 100 / 255 =$ **only 39% power**.
  - 50% in-game vibration $\rightarrow 50 / 255 =$ **only 19% power**.
  - Speeds below 30% stalled below the motor deadzones (+13 and +20).

### The $2.5\times$ PWM Scaling Solution
In stock 2.4G mode, the USB dongle directly receives `0..255` from XInput over USB. Windows over Bluetooth Low Energy normalizes values down to `0..100`.
To match the exact 2.4G physical power curve, the handler scales Windows `0..100` by **$2.5\times$** via high-speed TC32 bit shifts, mapping $100 \rightarrow 250$ (matching the 255 peak of 2.4G mode), $50 \rightarrow 125$ (matching 128), and $25 \rightarrow 62$ (matching 64):

$$\text{speed} = (\text{val} \ll 1) + (\text{val} \gg 1) = 2.5 \times \text{val} \quad (\max 250 \approx 98\% \text{ PWM})$$

```asm
; Verified 2.4G-Matched Full Power Motor Handler (30 bytes at 0x123C4)
tpush   {r4, lr}        ; 10 65  Save host r4 & lr
tadds   r4, r0, #0      ; 04 ec  Save buffer pointer to r4

; Scale Left Motor (0..100 -> 0..250):
tloadrb r0, [r4, #12]   ; 20 4b  Load Left magnitude (0..100)
tshftr  r3, r0, #1      ; 43 f8  r3 = r0 >> 1
tshftl  r0, r0, #1      ; 40 f0  r0 = r0 << 1
tadds   r0, r0, r3      ; c0 e8  r0 = (r0 << 1) + (r0 >> 1) = 2.5x (max 250)

; Scale Right Motor (0..100 -> 0..250):
tloadrb r1, [r4, #13]   ; 61 4b  Load Right magnitude (0..100)
tshftr  r3, r1, #1      ; 4b f8  r3 = r1 >> 1
tshftl  r1, r1, #1      ; 49 f0  r1 = r1 << 1
tadds   r1, r1, r3      ; c9 e8  r1 = (r1 << 1) + (r1 >> 1) = 2.5x (max 250)

; Scheduler call:
tmovs   r2, #255        ; ff a2  r2 = 255 (2.55s continuous hardware timer)
tjl     0x9B30          ; f7 97 a9 9b  Call 8BitDo motor scheduler (arms 10ms tick 0x9B68)

; Return:
tmovs   r0, #0          ; 00 a0  Return 0
tpop    {r4, pc}        ; 10 6d  Return to caller
```

### Continuous Vibration & The Hardware Timer (`r2 = 255`)
In `0x9B30`, `r2` sets the countdown timer in RAM (`0x8434F9`). The controller's background loop (`0x9B68`) decrements this byte every 10ms until it reaches zero, at which point it cuts motor PWM to 0.

- **The Limitation of `r2 = 30` (300ms)**: Windows XInput is **state-based** (`XInputSetState`). Over Bluetooth Low Energy, Windows only transmits an Output Report packet when vibration values change—it does *not* pump redundant packets every 10ms. When `r2 = 30` was used, any requested vibration longer than 300ms would abruptly cut off after 0.3s, feeling like intermittent pulses ("in phase") rather than a continuous rumble.
- **The Zero-Risk Fix (`r2 = 255`)**: We changed the single immediate operand from `0x1E` (30) to `0xFF` (255) (`ffa2`). This expands the hold duration to **2,550ms (2.55 seconds)**—over $8.5\times$ longer. Long in-game rumbles, damage effects, and continuous engine revs play smoothly without dropouts, while remaining 100% responsive: whenever the game commands `(0, 0)`, the motor stops instantly.
