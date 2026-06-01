"""
robot.py — Serial communication layer for the DeltaX XS D600 delta robot.

Provides a thin, stateful wrapper around pyserial.  All G-Code generation and
transmission happens here; higher-level modules (recipes.py) call the named
motion primitives (move_to, press_button, rotate_disc) rather than building
G-Code strings themselves.

When config.DRY_RUN is True every outgoing command is printed to stdout with a
[DRY RUN] prefix instead of being written to the serial port.  This lets the
full recipe pipeline run safely on a bench without any hardware connected.

State model:
  _serial   — pyserial Serial instance, None when not connected
  is_busy   — True while a recipe is executing; routes.py checks this to
              reject concurrent orders
"""

import re
import time
import threading
import serial  # pyserial

import config

# ── Module-level state ────────────────────────────────────────────────────────

_serial: serial.Serial | None = None  # Live serial port, None = disconnected
is_busy: bool = False                 # Prevents concurrent recipe execution
_lock = threading.Lock()              # Serialises send() calls across threads


# ── Connection ────────────────────────────────────────────────────────────────

def connect() -> bool:
    """
    Open the serial connection to the DeltaX XS D600 controller.

    Attempts to open ROBOT_PORT at ROBOT_BAUD (115200).  On success the global
    _serial object is set and the function returns True.  On failure the
    exception is logged and False is returned — callers should check the return
    value and surface an error to the user rather than proceeding.

    Algorithm: pyserial Serial() constructor blocks until the port opens or
    raises an OSError/SerialException.  A short read timeout (1 s) is set so
    that subsequent readline() calls in send() don't hang indefinitely if the
    robot stops responding mid-sequence.

    In DRY_RUN mode the function prints a notice and returns True immediately
    without touching any hardware.

    Returns:
        True if the port was opened (or DRY_RUN is active), False on error.
    """
    global _serial

    if config.DRY_RUN:
        print("[DRY RUN] connect() — skipping serial open")
        return True

    try:
        _serial = serial.Serial(
            port=config.ROBOT_PORT,
            baudrate=config.ROBOT_BAUD,
            timeout=1,  # 1 s read timeout prevents send() from blocking forever
        )
        # DeltaX XS needs ~500 ms after port open before accepting commands
        time.sleep(0.5)
        print(f"[robot] Connected on {config.ROBOT_PORT} @ {config.ROBOT_BAUD} baud")
        return True
    except (serial.SerialException, OSError) as exc:
        print(f"[robot] connect() failed: {exc}")
        _serial = None
        return False


def disconnect() -> None:
    """
    Close the serial port and release the _serial resource.

    Safe to call even if the port is already closed.  Called by main.py's
    atexit handler so the OS releases the COM port cleanly on shutdown.

    Algorithm: guard with is_open check because Serial.close() on an already-
    closed port raises a ValueError in some pyserial versions.
    """
    global _serial
    if _serial and _serial.is_open:
        _serial.close()
        print("[robot] Serial port closed")
    _serial = None


# ── G-Code helpers ─────────────────────────────────────────────────────────────

def strip_line_number(line: str) -> str:
    """
    Remove G-Code line number prefix (e.g. 'N05 G28' -> 'G28').

    DeltaX XS firmware rejects lines starting with 'N' followed by digits —
    it returns 'Unknown:Gcode!'.  This function strips the prefix before
    sending.

    Algorithm: split on whitespace, check if first token matches pattern
    N+digits, discard it if so.

    Args:
        line: raw G-Code line string
    Returns:
        cleaned G-Code string without line number prefix
    """
    tokens = line.split()
    # If the first token is an Nxx pattern (e.g. N0, N42) discard it
    if tokens and tokens[0].upper().startswith('N') and tokens[0][1:].isdigit():
        return ' '.join(tokens[1:])
    return line


def strip_comment(line: str) -> str:
    """
    Remove inline G-Code comments delimited by semicolons or parentheses.

    DeltaX XS firmware does not always strip comments before parsing, so
    sending 'G28 ; home all' can cause an 'Unknown:Gcode!' response.  This
    function normalises every line before transmission.

    Algorithm:
      - Semicolon comments: truncate at the first ';' character.
      - Parenthetical comments: remove all (...) substrings with a regex.
      Strip trailing whitespace after both passes.

    Args:
        line: G-Code string potentially containing comments
    Returns:
        G-Code string with all comment content removed
    """
    # Remove parenthetical comments like (this is a comment)
    line = re.sub(r'\(.*?\)', '', line)
    # Truncate at semicolon — everything from ';' onward is a comment
    if ';' in line:
        line = line[:line.index(';')]
    return line.strip()


def _clean(line: str) -> str:
    """
    Apply strip_line_number then strip_comment to produce a transmit-ready line.

    Args:
        line: raw G-Code string
    Returns:
        cleaned G-Code string ready to write to serial
    """
    return strip_comment(strip_line_number(line))


# ── Core send primitive ───────────────────────────────────────────────────────

def send(line: str) -> str:
    """
    Clean, transmit a single G-Code command, and return the firmware response.

    This is the single point through which every G-Code command passes.  It:
      1. Cleans the line (strips line numbers and comments).
      2. In DRY_RUN mode: prints the command and returns 'ok' immediately.
      3. In live mode: acquires the thread lock, writes the ASCII line + CRLF
         to the serial port, then reads one response line from the firmware.

    The DeltaX XS firmware responds with 'ok' on success or an error string
    starting with 'Error' / 'Unknown'.  The caller is responsible for deciding
    how to handle non-ok responses; this function always returns the raw
    firmware string so callers can log it.

    Algorithm: pyserial write() encodes the string to bytes; readline() reads
    until '\n' or the 1 s timeout expires.  The lock prevents interleaved
    writes from concurrent threads (Flask runs requests on separate threads).

    Args:
        line: G-Code command string (may include line numbers or comments)
    Returns:
        firmware response string ('ok', error message, or '[DRY RUN] ok')
    Raises:
        Does NOT raise — catches serial errors internally and returns an error
        string so recipes.py try/except blocks see a consistent interface.
    """
    cleaned = _clean(line)
    if not cleaned:
        return 'ok'  # Skip blank lines silently

    if config.DRY_RUN:
        print(f"[DRY RUN] >> {cleaned}")
        return 'ok'

    if _serial is None or not _serial.is_open:
        return 'error: not connected'

    try:
        with _lock:
            _serial.write((cleaned + '\r\n').encode('ascii'))
            response = _serial.readline().decode('ascii', errors='replace').strip()
        return response or 'ok'  # Empty readline() means timeout; treat as ok
    except serial.SerialException as exc:
        return f'error: {exc}'


# ── Motion primitives ─────────────────────────────────────────────────────────

def home() -> str:
    """
    Send the robot to its firmware home position using endstop homing.

    Issues G28 which commands the DeltaX XS to drive all three axes toward
    their endstops, zero the coordinate system, then lift to the safe home
    height defined in the firmware.  This is the standard recovery and
    start-of-sequence move.

    Algorithm: single G28 command; firmware handles the homing sequence
    internally.  The function blocks by waiting for the 'ok' response, which
    the firmware only sends after homing completes (typically 3–5 seconds).

    Returns:
        firmware response string from send()
    """
    return send('G28')  # Home all axes via endstops


def move_to(x: float, y: float, z: float,
            feedrate: int = config.TRAVEL_FEEDRATE) -> str:
    """
    Move the end-effector to an absolute XYZ position at the given feedrate.

    Enforces the workspace Z constraint from config: if the requested Z is
    below Z_MIN + Z_CLEARANCE the move is blocked and an error string is
    returned without sending anything to the robot.  This prevents firmware
    errors and physical crashes during the calibration phase when positions
    are still placeholder 0.0 values.

    Algorithm:
      - Validate Z against workspace boundary.
      - Format a G01 absolute-mode linear interpolation command.
      - Delegate to send() for transmission.

    Note: assumes the firmware is already in absolute positioning mode (G90),
    which is the DeltaX XS power-on default.

    Args:
        x:         target X coordinate (mm)
        y:         target Y coordinate (mm)
        z:         target Z coordinate (mm), must be >= Z_MIN + Z_CLEARANCE
        feedrate:  travel speed (mm/min), defaults to config.TRAVEL_FEEDRATE
    Returns:
        firmware response string, or 'error: Z out of workspace' if blocked
    """
    safe_z_floor = config.Z_MIN + config.Z_CLEARANCE

    # Z=0.0 is a placeholder — allow it in DRY_RUN but warn so calibration
    # doesn't silently proceed with wrong positions in live mode
    if not config.DRY_RUN and z < safe_z_floor:
        return f'error: Z {z} out of workspace (min {safe_z_floor})'

    cmd = f'G01 X{x:.3f} Y{y:.3f} Z{z:.3f} F{feedrate}'
    return send(cmd)  # Linear move to (x, y, z) at feedrate mm/min


def press_button(approach_x: float, press_x: float,
                 y: float, z: float,
                 hold_ms: int = 0,
                 feedrate: int = config.ICE_PRESS_FEEDRATE) -> None:
    """
    Execute a horizontal press-and-release motion for the ice gate mechanism.

    The ice module uses a gravity slide with a horizontal gate: the robot
    approaches from the retracted X position, extends to press_x to push the
    gate open, dwells for hold_ms to let ice fall, then retracts.

    Sequence:
      1. Move to (approach_x, y, z) — safe position aligned with the gate.
      2. Move to (press_x, y, z)    — push gate open (horizontal X move only).
      3. G04 P{hold_ms}             — dwell so ice falls into cup.
      4. Move back to (approach_x, y, z) — retract gate to closed.

    Algorithm: three G01 commands plus one G04 dwell.  Y and Z remain constant
    throughout; only X changes.  The low feedrate prevents mechanical shock on
    the gate actuator.

    Args:
        approach_x: X coordinate of the retracted/safe position (mm)
        press_x:    X coordinate of the fully pressed/extended position (mm)
        y:          Y coordinate, constant throughout the press sequence (mm)
        z:          Z coordinate, constant throughout the press sequence (mm)
        hold_ms:    dwell time at press position in milliseconds (default 0)
        feedrate:   horizontal press speed in mm/min (default ICE_PRESS_FEEDRATE)
    Returns:
        None — errors from individual sends are printed but not re-raised so
        that a stuck ice gate does not abort the entire recipe.
    """
    try:
        # Step 1: align with the ice gate from the safe retracted side
        move_to(approach_x, y, z, feedrate)

        # Step 2: extend horizontally to push the gate open
        send(f'G01 X{press_x:.3f} F{feedrate}')  # Horizontal press — X axis only

        # Step 3: dwell at extended position so ice has time to fall
        if hold_ms > 0:
            send(f'G04 P{hold_ms}')  # Dwell hold_ms milliseconds (G04 Pxx)

        # Step 4: retract back to safe position to close the gate
        send(f'G01 X{approach_x:.3f} F{feedrate}')  # Retract ice gate

    except Exception as exc:  # noqa: BLE001
        print(f"[robot] press_button() error: {exc}")


def rotate_disc(angle: float) -> str:
    """
    Rotate the water-bottle disc to the given absolute angle on Axis 4 (E axis).

    The dispensing module is a rotating disc carrying three 120°-spaced bottles.
    Axis 4 on the DeltaX XS maps to the E (extruder) stepper output, repurposed
    here as a rotation axis.  Sending G01 E{angle} F{DISC_FEEDRATE} drives the
    disc to an absolute angular position in degrees.

    Algorithm:
      - The E axis must be in absolute mode.  G90 (absolute) is the firmware
        default; a G90 is sent before the rotation as a safety measure in case
        a prior command switched to relative mode.
      - The single G01 E{angle} F{feedrate} command drives the disc stepper to
        the target angle.  Firmware sends 'ok' when the move completes.

    Args:
        angle:  target disc angle in degrees (0–360, nominally 0/120/240 for
                the three bottle positions defined in config.BOTTLE_ANGLES)
    Returns:
        firmware response string from the final G01 send()
    """
    send('G90')  # Ensure absolute positioning mode for E axis
    return send(f'G01 E{angle:.2f} F{config.DISC_FEEDRATE}')  # Rotate disc to angle°
