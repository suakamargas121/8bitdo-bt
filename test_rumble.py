import ctypes
import sys
import time

# Load Windows XInput DLL
try:
    xinput = ctypes.windll.xinput1_4
except Exception:
    try:
        xinput = ctypes.windll.xinput1_3
    except Exception:
        sys.exit("[-] Could not load xinput1_4.dll or xinput1_3.dll")

class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ("wLeftMotorSpeed", ctypes.c_ushort),
        ("wRightMotorSpeed", ctypes.c_ushort)
    ]
def set_vibration(user_index: int, left_speed: int, right_speed: int):
    vib = XINPUT_VIBRATION(left_speed, right_speed)
    return xinput.XInputSetState(user_index, ctypes.byref(vib))

def rumble_continuous(user_index: int, left_speed: int, right_speed: int, duration_sec: float):
    """Continuously stream vibration state at 25Hz (every 40ms), exactly how PC games do."""
    start = time.time()
    while time.time() - start < duration_sec:
        set_vibration(user_index, left_speed, right_speed)
        time.sleep(0.04)
    set_vibration(user_index, 0, 0)

def main():
    print("=" * 60)
    print(" 8BitDo Ultimate 2C Wireless: XInput Force-Feedback Rumble Test")
    print("=" * 60)
    
    # Test controller 0..3
    target = None
    for i in range(4):
        res = set_vibration(i, 0, 0)
        if res == 0:  # ERROR_SUCCESS
            target = i
            print(f"[+] Found active XInput device at Controller {i}!")
            break
            
    if target is None:
        sys.exit("[!] No connected XInput controller found. Ensure controller is turned on and paired over Bluetooth.")
        
    print(f"\nTesting vibration on Controller {target}:")
    
    try:
        print("[1/4] Continuous Left (Heavy) motor (50% speed, 1.0s)...")
        rumble_continuous(target, 32767, 0, 1.0)
        time.sleep(0.5)

        print("[2/4] Continuous Right (Light) motor (50% speed, 1.0s)...")
        rumble_continuous(target, 0, 32767, 1.0)
        time.sleep(0.5)

        print("[3/4] Continuous Both motors (100% full rumble, 1.2s)...")
        rumble_continuous(target, 65535, 65535, 1.2)
        time.sleep(0.5)

        print("[4/5] Gentle heartbeat buzz...")
        for _ in range(3):
            rumble_continuous(target, 20000, 20000, 0.15)
            time.sleep(0.1)
            rumble_continuous(target, 35000, 35000, 0.15)
            time.sleep(0.5)

        print("[5/5] Continuous Dynamic Speed Staircase (25% -> 50% -> 75% -> 100%)...")
        for pct in [25, 50, 75, 100]:
            spd = int(65535 * pct / 100)
            print(f"      -> {pct}% speed ({spd})...")
            rumble_continuous(target, spd, spd, 0.8)
        set_vibration(target, 0, 0)

        print("\n[+] Vibration test completed successfully!")
    finally:
        set_vibration(target, 0, 0)

if __name__ == "__main__":
    main()
