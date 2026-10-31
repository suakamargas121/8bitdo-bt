#!/usr/bin/env python3
"""8BitDo Ultimate 2C Wireless: Windows/Cross-Platform USB Boot Flasher & Backup Tool.

Replicates the protocol of ultimate2c_boot_flash.c and ultimate2c_boot_backup.c
using python-hidapi.

Device:
  VID: 0x2DC8 (8BitDo)
  PID: 0x3208 (8BitDo Boot)
  Model: 0x301B (Ultimate 2C Wireless)

Boot Mode:
  Hold LB + RB while plugging the controller into a USB-C cable.
  The controller enumerates as "8BitDo Boot" (2DC8:3208).
"""

import argparse
import datetime
import hashlib
import os
import struct
import sys
import time
from pathlib import Path

try:
    import hid
except ImportError:
    sys.exit(
        "ERROR: 'hidapi' is required. Install it using:\n"
        "  py -3.12 -m pip install hidapi  (or pip install hidapi)"
    )

VENDOR_8BITDO = 0x2DC8
PID_ULTIMATE_2C_BOOT = 0x3208
EXPECTED_CONTROLLER_PID = 0x301B

REPORT_ID_PREFIX = 5
BUFFER_SIZE = 65                                    # 1 dummy byte + 64 data bytes
BOOT_PAYLOAD_OFFSET = 18                            # payload offset in received report
BOOT_MAX_READ = 46                                  # 46 bytes
BOOT_MAX_WRITE = 46                                 # 46 bytes
DAT_WRAPPER_SIZE = 0x1C                             # 28 bytes

DEFAULT_FLASH_ADDR = 0x6000
DEFAULT_FLASH_LEN = 0x12400                         # 74,752 bytes

KNOWN_PATCHED_SHA256 = "18e2c710def1832177b17dbade1f81b9f2aa8c11bf7e5ce71567d0e6d05f34c1"


def crc16_modbus(data: bytes) -> int:
    """Calculate Modbus CRC16 matching the Telink / 8BitDo bootloader."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return crc & 0xFFFF


class Ultimate2cBootDevice:
    def __init__(self, device_handle):
        self.dev = device_handle

    @classmethod
    def open(cls):
        """Locate and open the 8BitDo Boot device (2DC8:3208)."""
        devices = hid.enumerate(VENDOR_8BITDO, PID_ULTIMATE_2C_BOOT)
        if not devices:
            return None
        dev_info = devices[0]
        h = hid.device()
        h.open_path(dev_info["path"])
        h.set_nonblocking(False)
        return cls(h)

    def close(self):
        try:
            self.dev.close()
        except Exception:
            pass

    def send_boot_command(
        self,
        cmd: int,
        cmd_params: int = 0,
        length: int = 0,
        crc: int = 0,
        total_len: int = 0,
        offset: int = 0,
        payload: bytes = b"",
        wait_response: bool = True,
        timeout_ms: int = 2000,
    ) -> bytes:
        """Send a 65-byte Output Report (0x00 dummy + 0x05 prefix + 63 bytes) and read response."""
        report = bytearray(BUFFER_SIZE)
        report[0] = 0                       # Windows dummy report ID (device has no report ID)
        report[1] = REPORT_ID_PREFIX       # 8BitDo prefix byte (0x05)
        struct.pack_into("<H", report, 2, cmd)
        struct.pack_into("<H", report, 4, cmd_params)
        struct.pack_into("<H", report, 6, length)
        struct.pack_into("<H", report, 8, crc)
        struct.pack_into("<I", report, 10, total_len)
        struct.pack_into("<I", report, 14, offset)

        if payload:
            if len(payload) > BOOT_MAX_WRITE:
                raise ValueError(f"Payload too large: {len(payload)} > {BOOT_MAX_WRITE}")
            report[18 : 18 + len(payload)] = payload

        res = self.dev.write(bytes(report))
        if res < 0:
            raise IOError("hid_write failed while sending boot command")

        if not wait_response:
            return b""

        # Read response report
        start_time = time.time()
        while (time.time() - start_time) * 1000 < timeout_ms:
            resp = self.dev.read(64, 100)
            if resp:
                resp_bytes = bytes(resp)
                if len(resp_bytes) >= BOOT_PAYLOAD_OFFSET:
                    return resp_bytes
            time.sleep(0.002)

        raise TimeoutError(f"Timeout waiting for response to command {cmd}")

    def identify(self) -> int:
        """Command 8: returns controller model PID (0x301B)."""
        resp = self.send_boot_command(cmd=8, cmd_params=0, length=4, total_len=4, offset=0)
        pid = struct.unpack_from("<H", resp, BOOT_PAYLOAD_OFFSET)[0]
        return pid

    def read_version(self) -> tuple[int, int, bytes]:
        """Read 8 bytes at 0x01017040 (version string)."""
        ver_bytes = self.boot_read(0x01017040, 8)
        main_ver = struct.unpack_from("<H", ver_bytes, 0)[0]
        beta_ver = struct.unpack_from("<H", ver_bytes, 4)[0]
        return main_ver, beta_ver, ver_bytes

    def boot_read(self, address: int, length: int) -> bytes:
        """Command 5: Read flash chunk (up to 46 bytes)."""
        if length > BOOT_MAX_READ:
            length = BOOT_MAX_READ
        resp = self.send_boot_command(
            cmd=5, cmd_params=0, length=length, total_len=length, offset=address
        )
        resp_param = struct.unpack_from("<H", resp, 4)[0]
        if resp_param != 5:
            raise RuntimeError(f"Unexpected read ACK at 0x{address:x}: param={resp_param}")
        return resp[BOOT_PAYLOAD_OFFSET : BOOT_PAYLOAD_OFFSET + length]

    def boot_erase(self, address: int, length: int):
        """Command 4: Erase flash region."""
        resp = self.send_boot_command(
            cmd=4, cmd_params=0, length=0, crc=0, total_len=length, offset=address
        )
        resp_param = struct.unpack_from("<H", resp, 4)[0]
        if resp_param != 4:
            raise RuntimeError(f"Erase failed: param={resp_param}")

    def boot_write_chunk(self, address: int, chunk: bytes, total_len: int):
        """Command 3: Write flash chunk (up to 46 bytes) with Modbus CRC."""
        crc = crc16_modbus(chunk)
        resp = self.send_boot_command(
            cmd=3,
            cmd_params=0,
            length=len(chunk),
            crc=crc,
            total_len=total_len,
            offset=address,
            payload=chunk,
        )
        resp_param = struct.unpack_from("<H", resp, 4)[0]
        if resp_param != 3:
            raise RuntimeError(f"Write chunk failed at 0x{address:x}: param={resp_param}")

    def boot_reset(self):
        """Command 7: Reset controller back into runtime firmware."""
        self.send_boot_command(cmd=7, wait_response=False)

    def dump_flash(self, address: int, length: int, progress_cb=None) -> bytes:
        """Read flash memory sequentially in 46-byte chunks."""
        data = bytearray()
        done = 0
        while done < length:
            chunk_len = min(length - done, BOOT_MAX_READ)
            chunk = self.boot_read(address + done, chunk_len)
            data.extend(chunk)
            done += len(chunk)
            if progress_cb:
                progress_cb(done, length)
        return bytes(data)

    def write_flash(self, address: int, payload: bytes, progress_cb=None):
        """Erase and write flash memory sequentially."""
        total_len = len(payload)
        self.boot_erase(address, total_len)

        done = 0
        while done < total_len:
            chunk_len = min(total_len - done, BOOT_MAX_WRITE)
            chunk = payload[done : done + chunk_len]
            self.boot_write_chunk(address + done, chunk, total_len)
            done += chunk_len
            if progress_cb:
                progress_cb(done, total_len)

    def verify_flash(self, address: int, expected: bytes, progress_cb=None):
        """Read back and verify byte-for-byte."""
        total_len = len(expected)
        done = 0
        while done < total_len:
            chunk_len = min(total_len - done, BOOT_MAX_READ)
            chunk = self.boot_read(address + done, chunk_len)
            expected_chunk = expected[done : done + chunk_len]
            if chunk != expected_chunk:
                for i, (b_got, b_exp) in enumerate(zip(chunk, expected_chunk)):
                    if b_got != b_exp:
                        offset = address + done + i
                        raise ValueError(
                            f"Verification mismatch at offset 0x{offset:x}: "
                            f"got 0x{b_got:02x}, expected 0x{b_exp:02x}"
                        )
            done += len(chunk)
            if progress_cb:
                progress_cb(done, total_len)


def progress_printer(label: str):
    last_print = [0]
    def cb(done, total):
        pct = (done / total) * 100
        now = time.time()
        if now - last_print[0] > 0.08 or done == total:
            bar_len = 30
            filled = int(bar_len * done // total)
            bar = "#" * filled + "-" * (bar_len - filled)
            sys.stdout.write(f"\r  {label}: [{bar}] {pct:5.1f}% ({done}/{total} bytes)")
            sys.stdout.flush()
            last_print[0] = now
        if done == total:
            sys.stdout.write("\n")
    return cb


def parse_firmware_file(path: Path) -> tuple[int, int, bytes]:
    """Parse a .dat firmware or raw .bin file."""
    raw = path.read_bytes()
    if len(raw) < 74752:
        raise ValueError(f"Firmware file too small ({len(raw)} bytes)")

    # Check for 8BitDo .dat wrapper (28 bytes)
    if len(raw) >= DAT_WRAPPER_SIZE + DEFAULT_FLASH_LEN:
        version, addr, length, pid = struct.unpack_from("<IIII", raw, 0)
        if addr == DEFAULT_FLASH_ADDR and length == DEFAULT_FLASH_LEN and pid == EXPECTED_CONTROLLER_PID:
            payload = raw[DAT_WRAPPER_SIZE : DAT_WRAPPER_SIZE + length]
            return addr, length, payload

    # If raw flash dump (74,752 bytes)
    if len(raw) == DEFAULT_FLASH_LEN:
        return DEFAULT_FLASH_ADDR, DEFAULT_FLASH_LEN, raw

    raise ValueError(
        f"Unrecognized firmware format in {path.name}: size {len(raw)} bytes"
    )


def perform_backup(boot_dev: Ultimate2cBootDevice, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Reading flash 0x{DEFAULT_FLASH_ADDR:x}..0x{DEFAULT_FLASH_ADDR + DEFAULT_FLASH_LEN:x} ...")
    data = boot_dev.dump_flash(
        DEFAULT_FLASH_ADDR, DEFAULT_FLASH_LEN, progress_printer("Backing up")
    )
    out_path.write_bytes(data)
    print(f"Backup saved to: {out_path} ({len(data)} bytes)")
    return data


def main():
    parser = argparse.ArgumentParser(
        description="8BitDo Ultimate 2C Wireless Windows USB Boot Flasher & Backup Tool"
    )
    parser.add_argument(
        "firmware",
        nargs="?",
        default="ultimate2c-xbox-windows-rumble.dat",
        help="Path to .dat firmware or .bin flash dump to write.",
    )
    parser.add_argument(
        "--backup",
        metavar="FILE",
        nargs="?",
        const="",
        help="Backup current controller flash and exit without flashing.",
    )
    parser.add_argument(
        "--info",
        action="store_true",
        help="Detect device in BOOT mode and display info without modifying flash.",
    )
    parser.add_argument(
        "--confirm",
        "--yes",
        "-y",
        action="store_true",
        help="Acknowledge flash risk and skip interactive prompt.",
    )
    args = parser.parse_args()

    print("==================================================================")
    print(" 8BitDo Ultimate 2C Wireless - USB Bootloader Tool (Windows/Cross)")
    print("==================================================================")

    # Locate boot device
    print("\nScanning for 8BitDo controller in BOOT mode (2DC8:3208)...")
    boot_dev = Ultimate2cBootDevice.open()
    if not boot_dev:
        print("\n[!] Controller not found in BOOT mode.")
        print("To enter BOOT mode:")
        print("  1. Disconnect the USB cable and turn off the controller.")
        print("  2. Hold down LB + RB on the controller.")
        print("  3. While holding LB + RB, plug the USB cable into your PC.")
        print("  4. The controller will enumerate as '8BitDo Boot' (2DC8:3208).")
        print("  5. Run this command again.")
        sys.exit(1)

    try:
        pid = boot_dev.identify()
        print(f"[+] Connected! Bootloader identify PID: 0x{pid:04X}")
        if pid != EXPECTED_CONTROLLER_PID:
            sys.exit(
                f"[-] ERROR: Controller PID is 0x{pid:04X}, expected 0x{EXPECTED_CONTROLLER_PID:04X} "
                f"(Ultimate 2C Wireless). Refusing to operate on unknown hardware."
            )

        try:
            main_v, beta_v, ver_bytes = boot_dev.read_version()
            print(f"[+] Version info: Main={main_v} Beta={beta_v} Raw={ver_bytes.hex(' ')}")
        except Exception as e:
            print(f"[*] Note: Could not read version string ({e})")

        # Info mode
        if args.info:
            print("[+] Device check complete.")
            return

        # Backup-only mode
        if args.backup is not None:
            if args.backup:
                b_path = Path(args.backup)
            else:
                timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                b_path = Path("backups") / f"controller-flash-{timestamp}.bin"
            perform_backup(boot_dev, b_path)
            return

        # Flash mode
        fw_path = Path(args.firmware)
        if not fw_path.exists():
            sys.exit(f"[-] Firmware file not found: {fw_path}")

        print(f"\nFirmware to flash: {fw_path}")
        fw_bytes = fw_path.read_bytes()
        fw_sha = hashlib.sha256(fw_bytes).hexdigest()
        print(f"Firmware SHA-256: {fw_sha}")

        if fw_sha == KNOWN_PATCHED_SHA256:
            print("[+] Verified: Matches known-good Xbox Elite XInput patched firmware!")
        else:
            print("[*] Note: File SHA-256 differs from stock patched image.")

        addr, length, payload = parse_firmware_file(fw_path)
        print(f"Target memory: 0x{addr:04X}..0x{addr+length:04X} ({length} bytes)")

        # Risk confirmation
        env_risk = os.environ.get("I_UNDERSTAND_BRICK_RISK") == "1"
        if not (args.confirm or env_risk):
            print("\n" + "=" * 66)
            print(" WARNING: Flashing firmware carries risk of bricking.")
            print(" A backup of your current flash will be automatically saved.")
            print("=" * 66)
            ans = input("Proceed with flashing? [y/N]: ").strip().lower()
            if ans not in ("y", "yes"):
                print("Aborted by user.")
                sys.exit(0)

        # 1. Mandatory pre-flash backup
        timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_file = Path("backups") / f"pre-flash-{timestamp}.bin"
        print(f"\n[Step 1/4] Taking mandatory pre-flash backup...")
        try:
            perform_backup(boot_dev, backup_file)
        except Exception as e:
            sys.exit(f"[-] FATAL: Backup failed ({e}). Aborting flash for safety.")

        # 2. Erase & Write
        print(f"\n[Step 2/4] Erasing flash and writing new firmware ({length} bytes)...")
        boot_dev.write_flash(addr, payload, progress_printer("Writing"))

        # 3. Readback verify
        print(f"\n[Step 3/4] Reading back flash for byte-for-byte verification...")
        try:
            boot_dev.verify_flash(addr, payload, progress_printer("Verifying"))
            print("[+] Verification SUCCESS: Readback matches payload byte-for-byte!")
        except Exception as e:
            print(f"\n[-] ERROR: Verification failed! {e}")
            print("Controller has been left in BOOT mode for recovery.")
            sys.exit(2)

        # 4. Reboot
        print(f"\n[Step 4/4] Resetting controller into runtime firmware...")
        boot_dev.boot_reset()
        print("\n" + "=" * 66)
        print(" FLASH COMPLETE!")
        print(" The controller will automatically reboot.")
        print(" Bluetooth instructions:")
        print("   1. If previously paired on your PC, go to Windows Settings ->")
        print("      Bluetooth & devices -> select your controller and click 'Remove'.")
        print("   2. Turn on the controller, press the Bluetooth pair button,")
        print("      and pair with your PC.")
        print("   3. It will now connect as an official Xbox Controller with native XInput!")
        print("=" * 66)

    finally:
        boot_dev.close()


if __name__ == "__main__":
    main()
