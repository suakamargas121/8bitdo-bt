"""
8BitDo Ultimate 2C Wireless: Multi-Backend Latency & Polling Benchmark
======================================================================
Comprehensive controller latency and polling rate benchmark supporting:
- Raw HID (Direct hardware packets via hidapi - works on Stock & Custom firmwares)
- DirectInput (DInput via Windows Multimedia Joystick API - joyGetPosEx)
- XInput (Xbox Controller API via xinput1_4.dll)

Measures:
- Polling Rate (Hz): Mean, Median, Min, Max
- Interval / Latency (ms): Mean, Median (p50), p95, p99, Min, Max Spike
- Jitter / Stability (standard deviation σ)
- Continuous Live Monitor & Side-by-Side A/B Comparison (Bluetooth vs. Cable)
"""

import ctypes
from ctypes import wintypes
import math
import os
import sys
import time
from typing import List, Dict, Optional, Tuple, Any

# Enable UTF-8 encoding on Windows consoles
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

# Enable ANSI colors on Windows console
os.system('')

# --- High-Resolution Multimedia Timer Setup ---
try:
    winmm = ctypes.windll.winmm
    winmm.timeBeginPeriod(1)
except Exception:
    winmm = None

# --- HIDAPI Optional Import ---
try:
    import hid
    HAS_HIDAPI = True
except ImportError:
    HAS_HIDAPI = False

# --- XInput Setup ---
xinput = None
for dll_name in ['xinput1_4.dll', 'xinput1_3.dll', 'xinput9_1_0.dll']:
    try:
        xinput = ctypes.windll.LoadLibrary(dll_name)
        break
    except Exception:
        pass

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

class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [
        ('wLeftMotorSpeed', ctypes.c_ushort),
        ('wRightMotorSpeed', ctypes.c_ushort),
    ]

if xinput:
    XInputGetState = xinput.XInputGetState
    XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
    XInputGetState.restype = wintypes.DWORD

    XInputSetState = getattr(xinput, 'XInputSetState', None)
    if XInputSetState:
        XInputSetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]
        XInputSetState.restype = wintypes.DWORD
else:
    XInputGetState = None
    XInputSetState = None

# --- DirectInput / WinMM Joystick Setup ---
class JOYINFOEX(ctypes.Structure):
    _fields_ = [
        ('dwSize', wintypes.DWORD),
        ('dwFlags', wintypes.DWORD),
        ('dwXpos', wintypes.DWORD),
        ('dwYpos', wintypes.DWORD),
        ('dwZpos', wintypes.DWORD),
        ('dwRpos', wintypes.DWORD),
        ('dwUpos', wintypes.DWORD),
        ('dwVpos', wintypes.DWORD),
        ('dwButtons', wintypes.DWORD),
        ('dwButtonNumber', wintypes.DWORD),
        ('dwPOV', wintypes.DWORD),
        ('dwReserved1', wintypes.DWORD),
        ('dwReserved2', wintypes.DWORD),
    ]

JOY_RETURNALL = 0x000000FF

# =====================================================================
# Base Backend Abstraction
# =====================================================================
class ControllerBackend:
    name: str = "Base"
    details: str = ""

    def open(self) -> bool:
        raise NotImplementedError

    def poll(self) -> Tuple[bool, Optional[int]]:
        """Returns (has_new_packet, sequence_or_hash)."""
        raise NotImplementedError

    def close(self):
        pass

    def supports_rumble(self) -> bool:
        return False

    def set_rumble(self, pct: int):
        pass


class XInputBackend(ControllerBackend):
    def __init__(self, index: int = 0):
        self.index = index
        self.name = f"XInput (Controller {index})"
        self.details = "Microsoft Xbox XInput Driver"
        self._last_pkt = None
        self._state = XINPUT_STATE()

    def open(self) -> bool:
        if not XInputGetState:
            return False
        return XInputGetState(self.index, ctypes.byref(self._state)) == 0

    def poll(self) -> Tuple[bool, Optional[int]]:
        if XInputGetState(self.index, ctypes.byref(self._state)) == 0:
            pkt = self._state.dwPacketNumber
            if self._last_pkt is None:
                self._last_pkt = pkt
                return True, pkt
            if pkt != self._last_pkt:
                d = (pkt - self._last_pkt) & 0xFFFFFFFF
                self._last_pkt = pkt
                return True, d
        return False, None

    def supports_rumble(self) -> bool:
        return XInputSetState is not None

    def set_rumble(self, pct: int):
        if not self.supports_rumble():
            return
        val = int(65535 * (pct / 100.0))
        vib = XINPUT_VIBRATION(val, val)
        XInputSetState(self.index, ctypes.byref(vib))


class DirectInputBackend(ControllerBackend):
    def __init__(self, index: int = 0):
        self.index = index
        self.name = f"DirectInput (Joystick {index})"
        self.details = "Windows DirectInput / WinMM Joystick API"
        self._ji = JOYINFOEX()
        self._ji.dwSize = ctypes.sizeof(JOYINFOEX)
        self._ji.dwFlags = JOY_RETURNALL
        self._last_state: Optional[bytes] = None

    def open(self) -> bool:
        if not winmm:
            return False
        return winmm.joyGetPosEx(self.index, ctypes.byref(self._ji)) == 0

    def poll(self) -> Tuple[bool, Optional[int]]:
        if winmm.joyGetPosEx(self.index, ctypes.byref(self._ji)) == 0:
            # Capture state snapshot
            curr_state = bytes(self._ji)
            if self._last_state is None:
                self._last_state = curr_state
                return True, 1
            if curr_state != self._last_state:
                self._last_state = curr_state
                return True, 1
        return False, None


class RawHIDBackend(ControllerBackend):
    def __init__(self, path: bytes, name: str = "8BitDo Controller"):
        self.path = path
        self.name = f"Raw HID ({name})"
        self.details = "Hardware-Direct HID Reports (hidapi)"
        self._dev = None

    def open(self) -> bool:
        if not HAS_HIDAPI:
            return False
        try:
            self._dev = hid.device()
            self._dev.open_path(self.path)
            self._dev.set_nonblocking(True)
            return True
        except Exception:
            return False

    def poll(self) -> Tuple[bool, Optional[int]]:
        if not self._dev:
            return False, None
        try:
            # Non-blocking read of raw hardware report
            data = self._dev.read(64)
            if data:
                return True, 1
        except Exception:
            pass
        return False, None

    def close(self):
        if self._dev:
            try:
                self._dev.close()
            except Exception:
                pass
            self._dev = None


# =====================================================================
# Device Discovery
# =====================================================================
def enumerate_available_backends() -> List[ControllerBackend]:
    backends: List[ControllerBackend] = []

    # 1. Raw HID (Gold standard - hardware level)
    if HAS_HIDAPI:
        try:
            for dev in hid.enumerate():
                prod = dev.get('product_string') or ''
                usage_page = dev.get('usage_page', 0)
                usage = dev.get('usage', 0)
                # Look for 8BitDo or Gamepads (UsagePage 1, Usage 4/5)
                if '8bitdo' in prod.lower() or (usage_page == 1 and usage in (4, 5)):
                    name = prod if prod else f"VID:{dev['vendor_id']:04x} PID:{dev['product_id']:04x}"
                    backends.append(RawHIDBackend(dev['path'], name))
        except Exception:
            pass

    # 2. XInput
    if XInputGetState:
        state = XINPUT_STATE()
        for idx in range(4):
            if XInputGetState(idx, ctypes.byref(state)) == 0:
                backends.append(XInputBackend(idx))

    # 3. DirectInput (WinMM)
    if winmm:
        ji = JOYINFOEX()
        ji.dwSize = ctypes.sizeof(JOYINFOEX)
        ji.dwFlags = JOY_RETURNALL
        for idx in range(8):
            if winmm.joyGetPosEx(idx, ctypes.byref(ji)) == 0:
                backends.append(DirectInputBackend(idx))

    return backends

def auto_select_backend() -> Optional[ControllerBackend]:
    """Auto-detect the most responsive available controller backend."""
    backends = enumerate_available_backends()
    if not backends:
        return None

    # Priority 1: Raw HID if it's 8BitDo (captures ALL reports with zero OS deadzone/filtering)
    for b in backends:
        if isinstance(b, RawHIDBackend) and '8bitdo' in b.name.lower():
            if b.open():
                return b

    # Priority 2: XInput
    for b in backends:
        if isinstance(b, XInputBackend):
            if b.open():
                return b

    # Priority 3: DirectInput
    for b in backends:
        if isinstance(b, DirectInputBackend):
            if b.open():
                return b

    # Fallback to first openable
    for b in backends:
        if b.open():
            return b

    return None

def wait_for_backend(prompt: str = "Scanning for controller...") -> ControllerBackend:
    print(f"\033[93m[*] {prompt}\033[0m")
    print("    Ensure controller is turned on and connected (Bluetooth or Cable)...", end="", flush=True)
    dots = 0
    while True:
        b = auto_select_backend()
        if b:
            print(f"\n\033[92m[+] Connected: {b.name} [{b.details}]\033[0m")
            return b
        time.sleep(0.2)
        dots = (dots + 1) % 4
        print(f"\r    Waiting for connection{'.' * dots}{' ' * (3 - dots)}", end="", flush=True)


# =====================================================================
# Statistics & Session Runner
# =====================================================================
class BenchmarkStats:
    def __init__(self, intervals_ms: List[float], packet_drops: int, total_packets: int, duration_sec: float, backend_name: str = ""):
        self.intervals_ms = intervals_ms
        self.packet_drops = packet_drops
        self.total_packets = total_packets
        self.duration_sec = duration_sec
        self.backend_name = backend_name

        if intervals_ms:
            sorted_intervals = sorted(intervals_ms)
            n = len(sorted_intervals)
            self.count = n
            self.mean_ms = sum(sorted_intervals) / n
            self.median_ms = sorted_intervals[n // 2]
            self.min_ms = sorted_intervals[0]
            self.max_ms = sorted_intervals[-1]
            
            # Standard deviation (Jitter)
            variance = sum((x - self.mean_ms) ** 2 for x in sorted_intervals) / n
            self.jitter_ms = math.sqrt(variance)

            # Percentiles
            self.p50_ms = sorted_intervals[int(n * 0.50)]
            self.p95_ms = sorted_intervals[min(int(n * 0.95), n - 1)]
            self.p99_ms = sorted_intervals[min(int(n * 0.99), n - 1)]

            # Polling rates (Hz)
            self.avg_hz = 1000.0 / self.mean_ms if self.mean_ms > 0 else 0
            self.median_hz = 1000.0 / self.median_ms if self.median_ms > 0 else 0
            self.max_hz = 1000.0 / self.min_ms if self.min_ms > 0 else 0
            self.min_hz = 1000.0 / self.max_ms if self.max_ms > 0 else 0

            # Drop rate percentage
            expected = total_packets + packet_drops
            self.drop_rate = (packet_drops / expected * 100.0) if expected > 0 else 0.0

            # Stability score
            jitter_penalty = min(self.jitter_ms * 12.0, 50.0)
            drop_penalty = min(self.drop_rate * 5.0, 50.0)
            self.stability_score = max(0.0, 100.0 - jitter_penalty - drop_penalty)
        else:
            self.count = 0
            self.mean_ms = self.median_ms = self.min_ms = self.max_ms = 0.0
            self.jitter_ms = self.p50_ms = self.p95_ms = self.p99_ms = 0.0
            self.avg_hz = self.median_hz = self.max_hz = self.min_hz = 0.0
            self.drop_rate = 0.0
            self.stability_score = 0.0


def run_benchmark_session(
    backend: ControllerBackend,
    duration_sec: float = 10.0,
    label: str = "Benchmark",
    rumble_pct: int = 0
) -> BenchmarkStats:
    if not backend.open():
        print(f"\033[91m[-] Failed to open backend: {backend.name}\033[0m")
        return BenchmarkStats([], 0, 0, 0, backend.name)

    if rumble_pct > 0 and backend.supports_rumble():
        backend.set_rumble(rumble_pct)

    print(f"\n\033[1;36m>>> {label} ({duration_sec:.1f}s) <<<\033[0m")
    print(f"    Backend: \033[1;32m{backend.name}\033[0m ({backend.details})")
    if rumble_pct > 0:
        print(f"\033[95m    [Vibration Active: {rumble_pct}% power]\033[0m")
    print("\033[93m[*] INSTRUCTION: Continuously swirl thumbsticks or press buttons rapidly!\033[0m\n")

    intervals_ms: List[float] = []
    dropped_packets = 0
    total_packets = 0
    last_time: Optional[float] = None

    start_time = time.perf_counter()
    next_ui_update = start_time
    ui_interval = 0.08

    try:
        while True:
            now = time.perf_counter()
            elapsed = now - start_time
            if elapsed >= duration_sec:
                break

            # Poll backend
            has_data, delta_info = backend.poll()
            if has_data:
                total_packets += 1
                if delta_info and delta_info > 1 and isinstance(backend, XInputBackend):
                    dropped_packets += (delta_info - 1)

                if last_time is not None:
                    dt_ms = (now - last_time) * 1000.0
                    if dt_ms < 250.0:
                        intervals_ms.append(dt_ms)
                last_time = now

            # Live UI Update
            if now >= next_ui_update:
                progress = min(elapsed / duration_sec, 1.0)
                bar_len = 24
                filled = int(bar_len * progress)
                bar = '█' * filled + '░' * (bar_len - filled)

                if len(intervals_ms) >= 5:
                    recent = intervals_ms[-20:]
                    recent_avg_ms = sum(recent) / len(recent)
                    recent_hz = 1000.0 / recent_avg_ms if recent_avg_ms > 0 else 0
                    stats_str = f"| \033[92m{recent_hz:5.1f} Hz\033[0m | Lat: \033[96m{recent_avg_ms:4.1f} ms\033[0m | Pkts: \033[93m{total_packets}\033[0m"
                else:
                    stats_str = "| \033[93mWaiting for movement...\033[0m"

                print(f"\r  [{bar}] {elapsed:4.1f}s/{duration_sec:4.1f}s {stats_str}   ", end="", flush=True)
                next_ui_update = now + ui_interval

            time.sleep(0.0001)

    finally:
        if rumble_pct > 0 and backend.supports_rumble():
            backend.set_rumble(0)
        backend.close()

    print()
    return BenchmarkStats(intervals_ms, dropped_packets, total_packets, duration_sec, backend.name)


def print_stats_table(stats: BenchmarkStats, title: str = "Benchmark Results"):
    print("\n" + "=" * 65)
    print(f" {title:^63} ")
    print("=" * 65)
    
    if stats.count < 10:
        print("\033[91m[-] Warning: Very few packets recorded!\033[0m")
        print("    Did you move the thumbsticks continuously during the test?")
        print(f"    Total packets captured: {stats.count}")
        print("=" * 65)
        return

    print(f"  Backend Used         : \033[1;32m{stats.backend_name}\033[0m")
    print(f"  Captured Packets     : {stats.count} packets ({stats.duration_sec:.1f}s duration)")
    if stats.packet_drops > 0:
        print(f"  Dropped / Skipped    : {stats.packet_drops} ({stats.drop_rate:.2f}%)")
    print("-" * 65)
    print(f"  \033[1mPOLLING RATE (Hz)\033[0m")
    print(f"    • Average          : \033[1;32m{stats.avg_hz:6.1f} Hz\033[0m")
    print(f"    • Median (p50)     : {stats.median_hz:6.1f} Hz")
    print(f"    • Peak (Max)       : {stats.max_hz:6.1f} Hz")
    print(f"    • Lowest (Min)     : {stats.min_hz:6.1f} Hz")
    print("-" * 65)
    print(f"  \033[1mINTERVAL / LATENCY (ms)\033[0m")
    print(f"    • Average Interval : \033[1;36m{stats.mean_ms:6.2f} ms\033[0m")
    print(f"    • Median (p50)     : {stats.median_ms:6.2f} ms")
    print(f"    • 95th Percentile  : {stats.p95_ms:6.2f} ms")
    print(f"    • 99th Percentile  : \033[93m{stats.p99_ms:6.2f} ms\033[0m")
    print(f"    • Min Interval     : {stats.min_ms:6.2f} ms")
    print(f"    • Max Spike        : \033[91m{stats.max_ms:6.2f} ms\033[0m")
    print(f"    • Jitter (σ stdev) : \033[1;35m±{stats.jitter_ms:5.2f} ms\033[0m")
    print("-" * 65)
    
    score = stats.stability_score
    if score >= 90:
        color = "\033[1;32m"
        rating = "EXCELLENT (Rock solid, minimal jitter)"
    elif score >= 75:
        color = "\033[1;36m"
        rating = "VERY GOOD (Normal wireless variation)"
    elif score >= 50:
        color = "\033[1;33m"
        rating = "FAIR (Occasional spikes or drops)"
    else:
        color = "\033[1;31m"
        rating = "POOR (High jitter or packet loss)"
        
    print(f"  Connection Stability : {color}{score:5.1f} / 100 - {rating}\033[0m")
    print("=" * 65)


def print_comparison_table(bt_stats: BenchmarkStats, cable_stats: BenchmarkStats):
    print("\n" + "╔" + "═" * 72 + "╗")
    print("║" + " 8BitDo Ultimate 2C: BLUETOOTH vs. USB CABLE COMPARISON ".center(72) + "║")
    print("╠" + "═" * 28 + "╦" + "═" * 21 + "╦" + "═" * 21 + "╣")
    print("║ Metric                     ║  Bluetooth LE       ║  USB-C Cable        ║")
    print("╠" + "═" * 28 + "╬" + "═" * 21 + "╬" + "═" * 21 + "╣")

    def row(name: str, bt_val: str, cable_val: str):
        print(f"║ {name:<26} ║ {bt_val:^19} ║ {cable_val:^19} ║")

    row("Average Polling Rate", f"{bt_stats.avg_hz:5.1f} Hz", f"{cable_stats.avg_hz:5.1f} Hz")
    row("Peak Polling Rate", f"{bt_stats.max_hz:5.1f} Hz", f"{cable_stats.max_hz:5.1f} Hz")
    row("Average Interval", f"{bt_stats.mean_ms:5.2f} ms", f"{cable_stats.mean_ms:5.2f} ms")
    row("Median Interval (p50)", f"{bt_stats.median_ms:5.2f} ms", f"{cable_stats.median_ms:5.2f} ms")
    row("99th Percentile Latency", f"{bt_stats.p99_ms:5.2f} ms", f"{cable_stats.p99_ms:5.2f} ms")
    row("Worst Spike (Max)", f"{bt_stats.max_ms:5.2f} ms", f"{cable_stats.max_ms:5.2f} ms")
    row("Jitter (σ standard dev)", f"±{bt_stats.jitter_ms:4.2f} ms", f"±{cable_stats.jitter_ms:4.2f} ms")
    row("Stability Score", f"{bt_stats.stability_score:4.1f}/100", f"{cable_stats.stability_score:4.1f}/100")

    print("╚" + "═" * 28 + "╩" + "═" * 21 + "╩" + "═" * 21 + "╝")

    print("\n\033[1;36m[Detailed Analysis & Findings]\033[0m")
    if cable_stats.avg_hz > 0 and bt_stats.avg_hz > 0:
        rate_mult = cable_stats.avg_hz / bt_stats.avg_hz
        print(f"  • Polling Speed    : USB Cable is \033[1;32m{rate_mult:.1f}x faster\033[0m ({cable_stats.avg_hz:.0f} Hz vs. {bt_stats.avg_hz:.0f} Hz).")

    if bt_stats.mean_ms > cable_stats.mean_ms:
        latency_saved = bt_stats.mean_ms - cable_stats.mean_ms
        pct_saved = (latency_saved / bt_stats.mean_ms) * 100.0
        print(f"  • Input Latency    : USB Cable saves \033[1;32m{latency_saved:.2f} ms\033[0m per packet ({pct_saved:.1f}% lower input lag).")

    if cable_stats.jitter_ms < bt_stats.jitter_ms:
        print(f"  • Consistency      : USB Cable delivers \033[1;32m±{cable_stats.jitter_ms:.2f} ms\033[0m jitter vs Bluetooth's ±{bt_stats.jitter_ms:.2f} ms.")

    print()


def guided_ab_comparison():
    print("\n" + "=" * 65)
    print(" GUIDED COMPARISON: BLUETOOTH vs. USB CABLE ")
    print("=" * 65)

    print("\033[1;33m[STEP 1 of 2: BLUETOOTH BENCHMARK]\033[0m")
    print("Ensure the controller is connected via BLUETOOTH (no cable plugged in yet).")
    input("Press ENTER when ready to start 10s Bluetooth benchmark...")

    bt_backend = wait_for_backend("Detecting Bluetooth controller...")
    bt_stats = run_benchmark_session(bt_backend, duration_sec=10.0, label="Phase 1: Bluetooth LE")
    print_stats_table(bt_stats, "Bluetooth LE Results")

    print("\n\033[1;33m[STEP 2 of 2: USB CABLE BENCHMARK]\033[0m")
    print("Now PLUG IN the USB-C CABLE to your PC.")
    input("Press ENTER when the USB cable is plugged in...")

    print("Re-scanning for controller on USB connection...")
    time.sleep(1.0)
    cable_backend = wait_for_backend("Detecting USB Wired controller...")
    cable_stats = run_benchmark_session(cable_backend, duration_sec=10.0, label="Phase 2: USB-C Cable")
    print_stats_table(cable_stats, "USB-C Cable Results")

    print_comparison_table(bt_stats, cable_stats)


def live_monitor(backend: ControllerBackend):
    print("\n" + "=" * 65)
    print(" CONTINUOUS LIVE POLLING & JITTER MONITOR ")
    print("=" * 65)
    print(f"Active Backend: \033[1;32m{backend.name}\033[0m ({backend.details})")
    print("Move sticks or press buttons to see live polling rate. Press Ctrl+C to return.\n")

    if not backend.open():
        print(f"\033[91m[-] Failed to open backend: {backend.name}\033[0m")
        return

    window: List[float] = []
    last_t = None

    try:
        while True:
            now = time.perf_counter()
            has_data, _ = backend.poll()
            if has_data:
                if last_t is not None:
                    dt = (now - last_t) * 1000.0
                    if dt < 200.0:
                        window.append(dt)
                        if len(window) > 30:
                            window.pop(0)
                last_t = now

            if window and len(window) >= 5:
                avg_dt = sum(window) / len(window)
                hz = 1000.0 / avg_dt if avg_dt > 0 else 0
                variance = sum((x - avg_dt) ** 2 for x in window) / len(window)
                jitter = math.sqrt(variance)

                meter_val = int(min(hz / 1000.0, 1.0) * 20)
                meter = '■' * meter_val + ' ' * (20 - meter_val)
                print(f"\r  [{meter}] \033[1;32m{hz:6.1f} Hz\033[0m | Interval: \033[1;36m{avg_dt:5.2f} ms\033[0m | Jitter: \033[1;35m±{jitter:4.2f} ms\033[0m   ", end="", flush=True)

            time.sleep(0.0005)
    except KeyboardInterrupt:
        print("\n[+] Exited live monitor.")
    finally:
        backend.close()


def select_backend_menu() -> ControllerBackend:
    backends = enumerate_available_backends()
    print("\nAvailable Controller Backends:")
    if not backends:
        print("\033[91m  No active controllers detected! Turn on controller and reconnect.\033[0m")
        return wait_for_backend()

    for i, b in enumerate(backends, 1):
        print(f"  \033[1m[{i}]\033[0m \033[1;32m{b.name}\033[0m - {b.details}")

    print(f"  \033[1m[A]\033[0m \033[1;36mAuto-Detect Recommended Backend\033[0m")

    choice = input("\nSelect backend [1-{}, A]: ".format(len(backends))).strip()
    if choice.isdigit() and 1 <= int(choice) <= len(backends):
        return backends[int(choice) - 1]
    
    # Default to auto
    b = auto_select_backend()
    return b if b else wait_for_backend()


def main():
    try:
        print("\033[1;36m" + "=" * 65)
        print("  8BitDo Controller: Multi-Backend Latency & Stability Benchmark")
        print("  Supports: DirectInput (DInput) • Raw HID • XInput")
        print("=" * 65 + "\033[0m")

        current_backend: Optional[ControllerBackend] = None

        while True:
            print("\nSelect Benchmark Mode:")
            print("  \033[1m[1]\033[0m \033[1;32mGuided A/B Comparison\033[0m (Bluetooth vs. USB Cable)")
            print("  \033[1m[2]\033[0m Quick Benchmark (10-second test on current backend)")
            print("  \033[1m[3]\033[0m Continuous Live Monitor (real-time Hz & jitter meter)")
            print("  \033[1m[4]\033[0m Choose Specific Backend (DirectInput, Raw HID, or XInput)")
            print("  \033[1m[0]\033[0m Exit")
            
            try:
                choice = input("\nEnter choice [1-4, 0]: ").strip()
            except (KeyboardInterrupt, EOFError):
                break

            if choice == '1':
                guided_ab_comparison()
            elif choice == '2':
                if not current_backend:
                    current_backend = auto_select_backend() or wait_for_backend()
                stats = run_benchmark_session(current_backend, duration_sec=10.0, label="Quick 10s Benchmark")
                print_stats_table(stats, "Quick Benchmark Results")
            elif choice == '3':
                if not current_backend:
                    current_backend = auto_select_backend() or wait_for_backend()
                live_monitor(current_backend)
            elif choice == '4':
                current_backend = select_backend_menu()
                print(f"\033[92m[+] Selected: {current_backend.name}\033[0m")
            elif choice == '0' or choice.lower() == 'q':
                break
            else:
                print("\033[91mInvalid choice. Please select 0-4.\033[0m")

    finally:
        if winmm:
            try:
                winmm.timeEndPeriod(1)
            except Exception:
                pass
        print("\n[+] Benchmark finished.")

if __name__ == '__main__':
    main()
