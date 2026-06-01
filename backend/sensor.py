"""
sensor.py — HC-SR04 ultrasonic cup-presence detector. PROTOTYPE.

This module is intentionally kept thin and backend-agnostic.  The public
interface (connect_sensor, read_distance, check_cup_present) is stable; only
the transport layer underneath needs to change when the Arduino Nano is
replaced.

Current backend: Arduino Nano running a NewPing sketch that continuously
prints distance readings (in cm) over UART at 9600 baud in the format:
    "42\n"   — distance in cm
    "0\n"    — sensor timeout / out of range (NewPing returns 0 on no echo)

Possible future backends (drop-in replacements for _read_from_serial):
    - Raspberry Pi GPIO via gpiozero.DistanceSensor
    - ESP32 ADC over WiFi/MQTT
    - Direct USB-connected ranging module (VL53L0X via I2C-to-USB bridge)

To swap backends: implement a function matching the signature
    _read_raw() -> float | None
and replace the call in read_distance().

In DRY_RUN mode (config.DRY_RUN=True) the sensor is never opened and
read_distance() returns a simulated "cup present" value so recipes run
end-to-end on the bench without hardware.
"""

import time
import serial  # pyserial

import config

# ── Module-level state ────────────────────────────────────────────────────────

_serial: serial.Serial | None = None  # Arduino Nano serial port, None = disconnected

# Distance threshold (cm) below which a cup is considered present.
# A cup at the holder reflects at ~8–12 cm; empty holder reflects at >40 cm.
# TODO: calibrate after physical mounting of the sensor is finalised.
CUP_PRESENT_THRESHOLD_CM: float = 20.0

# How many consecutive reads must agree before cup presence is confirmed.
# Filters single-sample noise from vibration or ambient IR interference.
STABLE_READS_REQUIRED: int = 3

# Seconds to wait between polling reads inside check_cup_present().
READ_INTERVAL_S: float = 0.1


# ── Connection ────────────────────────────────────────────────────────────────

def connect_sensor() -> bool:
    """
    Open the serial connection to the Arduino Nano sensor board.

    Opens SENSOR_PORT at SENSOR_BAUD (9600).  After the port opens the
    function sleeps for SENSOR_BOOT_DELAY seconds to let the Arduino Nano
    bootloader finish its reset cycle — commands or reads attempted before the
    bootloader hands off to the sketch return garbage.

    In DRY_RUN mode the function prints a notice and returns True immediately
    without touching any hardware.

    Algorithm: pyserial Serial() with a 1 s read timeout so that readline()
    inside read_distance() never blocks forever if the sketch stops sending.

    Returns:
        True if port opened successfully (or DRY_RUN), False on error.
    """
    global _serial

    if config.DRY_RUN:
        print("[DRY RUN] connect_sensor() — skipping serial open")
        return True

    try:
        _serial = serial.Serial(
            port=config.SENSOR_PORT,
            baudrate=config.SENSOR_BAUD,
            timeout=1,  # 1 s read timeout — prevents readline() from blocking forever
        )
        # Wait for the Arduino bootloader to finish before reading any data.
        # DTR toggle on port-open triggers a MCU reset; the bootloader takes
        # ~1-2 s before the sketch begins executing and sending distance values.
        time.sleep(config.SENSOR_BOOT_DELAY)
        print(f"[sensor] Connected on {config.SENSOR_PORT} @ {config.SENSOR_BAUD} baud")
        return True
    except (serial.SerialException, OSError) as exc:
        print(f"[sensor] connect_sensor() failed: {exc}")
        _serial = None
        return False


def disconnect_sensor() -> None:
    """
    Close the sensor serial port and release the resource.

    Safe to call even if the port is already closed.  Should be paired with
    connect_sensor() and called from main.py's atexit handler.
    """
    global _serial
    if _serial and _serial.is_open:
        _serial.close()
        print("[sensor] Serial port closed")
    _serial = None


# ── Backend read (swap this function to change hardware) ───────────────────────

def _read_from_serial() -> float | None:
    """
    Read one distance sample from the Arduino Nano over UART.

    The NewPing sketch on the Nano continuously prints one integer per line:
        "42\n"  — distance in cm
        "0\n"   — no echo / out of range (NewPing timeout)

    Algorithm:
      - Call readline() which blocks up to the 1 s port timeout.
      - Decode the bytes, strip whitespace, attempt int conversion.
      - Return None on any parse or IO error so the caller can skip the sample.

    Returns:
        distance in cm as a float, or None if the read failed / timed out.
    """
    if _serial is None or not _serial.is_open:
        return None

    try:
        raw = _serial.readline().decode('ascii', errors='replace').strip()
        if not raw:
            return None  # readline() timed out — no data within 1 s
        return float(raw)
    except (ValueError, serial.SerialException):
        return None  # Malformed line or IO error — skip this sample


# ── Public interface ───────────────────────────────────────────────────────────

def read_distance() -> float | None:
    """
    Return the current distance reading from the ultrasonic sensor in cm.

    Dispatches to _read_from_serial() in live mode.  In DRY_RUN mode returns
    a simulated value of 10.0 cm (cup present) so the recipe pipeline can
    exercise the full code path without hardware.

    This is the function to replace the body of when swapping backends:
    keep the signature and return type, change only the implementation.

    Returns:
        distance in cm (float), or None if the read failed.
    """
    if config.DRY_RUN:
        # Simulate a cup sitting at 10 cm — well inside CUP_PRESENT_THRESHOLD_CM
        return 10.0

    return _read_from_serial()


def check_cup_present() -> bool:
    """
    Return True if a cup is detected in the holder, False otherwise.

    Uses a simple majority-vote debounce: takes STABLE_READS_REQUIRED
    consecutive samples and returns True only if all of them report a
    distance below CUP_PRESENT_THRESHOLD_CM.  This rejects single-sample
    spikes caused by vibration or reflections from nearby surfaces.

    Algorithm:
      1. Collect STABLE_READS_REQUIRED samples spaced READ_INTERVAL_S apart.
      2. Skip None samples (failed reads) — they do not count for or against.
      3. If all valid samples are below the threshold, cup is present.
      4. If any valid sample is above the threshold, cup is absent.
      5. If all samples returned None (sensor offline), return False to be
         safe — do not allow a recipe to run with no sensor feedback.

    Returns:
        True if a cup is consistently detected, False otherwise.
    """
    valid_readings: list[float] = []

    for _ in range(STABLE_READS_REQUIRED):
        dist = read_distance()
        if dist is not None:
            valid_readings.append(dist)
        time.sleep(READ_INTERVAL_S)

    if not valid_readings:
        # All reads failed — sensor may be offline; block recipe for safety
        print("[sensor] check_cup_present(): no valid readings, assuming no cup")
        return False

    cup_present = all(d < CUP_PRESENT_THRESHOLD_CM for d in valid_readings)

    if not cup_present:
        avg = sum(valid_readings) / len(valid_readings)
        print(f"[sensor] No cup detected — avg distance {avg:.1f} cm "
              f"(threshold {CUP_PRESENT_THRESHOLD_CM} cm)")

    return cup_present
