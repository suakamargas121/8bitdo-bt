import ctypes
from ctypes import wintypes
import time

print('=' * 60)
print(' 8BitDo Controller Input Test (XInput)')
print('=' * 60)

xinput_dll = None
for dll_name in ['xinput1_4.dll', 'xinput1_3.dll', 'xinput9_1_0.dll']:
    try:
        xinput_dll = ctypes.windll.LoadLibrary(dll_name)
        print(f'[+] Loaded {dll_name}')
        break
    except Exception:
        pass

if not xinput_dll:
    print('[-] Failed to load XInput DLL.')
    exit(1)

class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ('wButtons', wintypes.WORD),
        ('bLeftTrigger', wintypes.BYTE),
        ('bRightTrigger', wintypes.BYTE),
        ('sThumbLX', wintypes.SHORT),
        ('sThumbLY', wintypes.SHORT),
        ('sThumbRX', wintypes.SHORT),
        ('sThumbRY', wintypes.SHORT),
    ]

class XINPUT_STATE(ctypes.Structure):
    _fields_ = [
        ('dwPacketNumber', wintypes.DWORD),
        ('Gamepad', XINPUT_GAMEPAD),
    ]

XInputGetState = xinput_dll.XInputGetState
XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
XInputGetState.restype = wintypes.DWORD

BUTTON_NAMES = {
    0x0001: 'DPAD_UP',
    0x0002: 'DPAD_DOWN',
    0x0004: 'DPAD_LEFT',
    0x0008: 'DPAD_RIGHT',
    0x0010: 'START',
    0x0020: 'BACK',
    0x0040: 'LEFT_THUMB',
    0x0080: 'RIGHT_THUMB',
    0x0100: 'LB',
    0x0200: 'RB',
    0x1000: 'A',
    0x2000: 'B',
    0x4000: 'X',
    0x8000: 'Y',
}

print("\nScanning for active XInput controller...")
connected_idx = None
for idx in range(4):
    state = XINPUT_STATE()
    if XInputGetState(idx, ctypes.byref(state)) == 0:
        connected_idx = idx
        print(f'[+] Controller {idx} is CONNECTED!')
        break

if connected_idx is None:
    print('[-] No XInput controller connected.')
    print('    Check Windows Device Manager to ensure the device has started without errors.')
else:
    print(f'Streaming live input data from Controller {connected_idx} (Press Ctrl+C to stop)...')
    print('Move sticks, squeeze triggers, and press buttons:\n')
    last_packet = -1
    try:
        while True:
            state = XINPUT_STATE()
            if XInputGetState(connected_idx, ctypes.byref(state)) == 0:
                if state.dwPacketNumber != last_packet:
                    last_packet = state.dwPacketNumber
                    gp = state.Gamepad
                    pressed = [name for mask, name in BUTTON_NAMES.items() if (gp.wButtons & mask)]
                    btns = ','.join(pressed) if pressed else 'None'
                    print(
                        f'LX:{gp.sThumbLX:6d} LY:{gp.sThumbLY:6d} | '
                        f'RX:{gp.sThumbRX:6d} RY:{gp.sThumbRY:6d} | '
                        f'LT:{gp.bLeftTrigger:3d} RT:{gp.bRightTrigger:3d} | '
                        f'Buttons: {btns}'
                    )
            time.sleep(0.015)
    except KeyboardInterrupt:
        print('\n[+] Test stopped by user.')
