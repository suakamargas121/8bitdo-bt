import struct
import zlib
from pathlib import Path

SRC = Path("8bitdo-ultimate-2c-wireless_v1.06-beta_model-0x301B.dat")
DST = Path("ultimate2c-xbox-windows-rumble.dat")

WRAPPER_SIZE = 0x1C
IMAGE_BASE = 0x6000
PNP_VALUE_FILE = 0x11488
REPORT_MAP_FILE = 0x11414
STOCK_MAP_LEN = 0x74
GATT_MAP_ENTRY = 0x11864
HOOK_FILE = 0x5B38
CAVE_FILE = 0x12340

# Windows Xbox BLE Clean HID Report Descriptor with Full Force-Feedback Rumble (116 bytes == 116 byte slot)
# Satisfies xinputhid.sys!0x140003ed4 and eliminates Code 10:
#   - Report 1 (Input, 19 bytes payload):
#       * Left Stick X/Y, Right Stick Rx/Ry (4x 16-bit)
#       * Triggers: Brake LT (0xC5), Accelerator RT (0xC4) (2x 16-bit)
#       * D-Pad: Hat switch (0x39) (4-bit + 4-bit pad)
#       * Buttons: 1..16 (16-bit)
#       * Elite tail padding (32-bit const)
#   - Report 3 (Output, 8 bytes payload):
#       * Usage 0x97: Motor enable mask (4-bit + 4-bit pad)
#       * Usage 0x70: Motor magnitudes (4x 8-bit array for 4 rumble motors)
#       * Usage 0x50: Duration (8-bit)
#       * Usage 0xA7: Delay (8-bit)
#       * Usage 0x7C: Loop count (8-bit)
NEW_MAP = bytes.fromhex(
    "05010905a1018501"
    "150026ffff751019302932093595048102"
    "050209c509c495028102"
    "050109391501250875049501814275048103"
    "05091901291015002501750195108102"
    "752095018103"
    "050f09218503a102"
    "0997750491029103"
    "09702564750895049102"
    "095009a7097c26ff0095039102"
    "c0c0"
)

assert len(NEW_MAP) <= STOCK_MAP_LEN, f"Map too big: {len(NEW_MAP)} > {STOCK_MAP_LEN}"

HOOK_HEX = "0c90029cc006c006c006c006"
# Proven Stable Windows Input Code Cave:
# Translates stock reports into 19-byte Xbox reports with verified 16-bit stick & trigger axes
CAVE_HEX = "88606c066d0620b5684820406040a848a040e040e848204160412849a041e041a84981f0214281f96142684981f0a14281f9e142284808a801c400a0008001b02043e849dba108006043284a7ca10800a04300a0e84902ec04a10a0092f803ec20a10b001bf91a03e243224400a06044a04440a01da122ec13a3fc974b990860f397c09b"
# 2.4G-Matched Full Power Motor Scheduler Handler (0x9B30):
# Restores the 8BitDo motor scheduler (0x9B30) which drives the background 10ms PWM tick (0x9B68).
# Scales Windows 0..100 to exact 2.4G range 0..250 (2.5x: (val<<1) + (val>>1)):
#   - 100% vibration -> 250 (Full 98% 2.4G Power)
#   - 50% vibration  -> 125 (Strong 2.4G Rumble)
#   - 25% vibration  -> 62  (Distinct 2.4G Buzz)
# r2 = 255 (ffa2): 2.55s continuous hold timer
HANDLER_HEX = "106504ec204b43f840f0c0e8614b4bf849f0c9e8ffa2f797a99b00a0106d"
STATIC_REF = bytes.fromhex("03 02")

HOOK = bytes.fromhex(HOOK_HEX)
CAVE = bytes.fromhex(CAVE_HEX)
HANDLER = bytes.fromhex(HANDLER_HEX)
HANDLER_FILE = CAVE_FILE + len(CAVE)
STATIC_REF_FILE = HANDLER_FILE + len(HANDLER)

ENTRY_VALUE_OUTPUT = 0x1181C
ENTRY_REF_OUTPUT = 0x11834

def fw_addr(file_off):
    return file_off - WRAPPER_SIZE + IMAGE_BASE

def main():
    data = bytearray(SRC.read_bytes())

    # 1. PnP ID: Microsoft Xbox Series X|S Wireless Controller (045E:0B13)
    STOCK_PNP = bytes.fromhex("02 c8 2d 02 60 01 00")
    pnp = bytearray(STOCK_PNP)
    struct.pack_into("<H", pnp, 1, 0x045E)
    struct.pack_into("<H", pnp, 3, 0x0B13)
    data[PNP_VALUE_FILE:PNP_VALUE_FILE + len(pnp)] = pnp

    # 2. Report Map in place
    data[REPORT_MAP_FILE:REPORT_MAP_FILE + STOCK_MAP_LEN] = NEW_MAP + bytes(STOCK_MAP_LEN - len(NEW_MAP))
    struct.pack_into("<I", data, GATT_MAP_ENTRY + 4, len(NEW_MAP))

    # 3. Hook + Cave + Handler + Static Ref
    data[HOOK_FILE:HOOK_FILE + len(HOOK)] = HOOK
    data[CAVE_FILE:CAVE_FILE + len(CAVE)] = CAVE
    data[HANDLER_FILE:HANDLER_FILE + len(HANDLER)] = HANDLER
    data[STATIC_REF_FILE:STATIC_REF_FILE + len(STATIC_REF)] = STATIC_REF

    # 4. Output report
    struct.pack_into("<I", data, ENTRY_VALUE_OUTPUT + 4, 8)
    struct.pack_into("<I", data, ENTRY_VALUE_OUTPUT + 16, fw_addr(HANDLER_FILE) | 1)
    struct.pack_into("<I", data, ENTRY_REF_OUTPUT + 12, fw_addr(STATIC_REF_FILE))

    # 5. Telink CRC
    payload = memoryview(data)[WRAPPER_SIZE:]
    hsize = struct.unpack_from("<I", payload, 0x18)[0]
    crc_without_word = zlib.crc32(payload[: hsize - 4]) & 0xFFFFFFFF
    stored_crc = (~crc_without_word) & 0xFFFFFFFF
    struct.pack_into("<I", data, WRAPPER_SIZE + hsize - 4, stored_crc)

    DST.write_bytes(data)
    print(f"Generated {DST.name} ({len(data)} bytes, CRC 0x{stored_crc:08x})")
    print(f"  PnP ID: VID=0x045E PID=0x0B13 (Xbox Wireless Controller)")
    print(f"  Report Map: {len(NEW_MAP)} bytes (Full Input + 5-usage Force-Feedback Output Report 3)")

if __name__ == "__main__":
    main()
