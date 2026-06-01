"""
config.py — Central configuration for the DeltaX Barista Robot.

All hardware constants, COM port assignments, G-Code position targets,
cup-size parameters, recipe definitions, and timing values live here.
No other module should hard-code these values; import from config instead.

DRY_RUN=True disables serial transmission so the system runs safely on a
bench without a connected robot (robot.py prints G-Code to stdout instead).
Set DRY_RUN=False only after the robot is physically assembled and COM ports
are confirmed with Device Manager.
"""

# ── Development mode ────────────────────────────────────────────────────────

# Master safety switch: True = no serial writes, G-Code is printed to stdout.
# Must remain True until robot is physically assembled and wired.
DRY_RUN: bool = True

# ── Serial ports ────────────────────────────────────────────────────────────

# USB serial port for the DeltaX XS D600 controller board.
# Verify with Device Manager → Ports (COM & LPT) after connecting USB cable.
ROBOT_PORT: str = "COM3"

# USB serial port for the Arduino Nano running the HC-SR04 sensor firmware.
# Typically assigned a different COM number than the robot by Windows.
SENSOR_PORT: str = "COM4"

# DeltaX XS D600 factory default baud rate — do not change.
ROBOT_BAUD: int = 115_200

# Arduino Nano sketch uses Serial.begin(9600) — must match exactly.
SENSOR_BAUD: int = 9_600

# Seconds to wait after opening the serial port before sending commands.
# The Arduino Nano bootloader resets the MCU on DTR toggle; commands sent
# before the bootloader finishes will be silently dropped.
SENSOR_BOOT_DELAY: float = 2.0

# ── Workspace constraint ─────────────────────────────────────────────────────

# The DeltaX XS D600 workspace bottom boundary on the Z axis (mm).
# Firmware will refuse moves below this value; always keep target Z above it
# by a small clearance margin to avoid limit-switch collisions.
Z_MIN: float = -625.0

# Safety clearance above Z_MIN added to every move (mm).
# Keeps end-effector from bottoming out on the workspace boundary.
Z_CLEARANCE: float = 5.0

# ── Home position ────────────────────────────────────────────────────────────

# XYZ coordinates of the robot's home/safe position (mm).
# Robot returns here between tasks and on error recovery.
HOME_X: float = 0.0   # TODO: calibrate
HOME_Y: float = 0.0   # TODO: calibrate
HOME_Z: float = 0.0   # TODO: calibrate

# ── Cup holder positions ─────────────────────────────────────────────────────

# The cup holder is a fixed platform.  Both cup sizes share the same XY
# centre; Z differs because a larger cup sits lower in the holder cradle.

CUP_X: float = 0.0    # TODO: calibrate — XY centre of the cup holder
CUP_Y: float = 0.0    # TODO: calibrate

# Z height for a Small (250 ml) cup's fill opening (mm).
CUP_S_Z: float = 0.0  # TODO: calibrate

# Z height for a Medium (350 ml) cup's fill opening (mm).
CUP_M_Z: float = 0.0  # TODO: calibrate

# Nominal cup capacities in millilitres — used for logging/UI only.
CUP_SIZES: dict = {
    "S": 250,  # Small cup
    "M": 350,  # Medium cup
}

# ── Water dispensing module ──────────────────────────────────────────────────

# The water module is a 3-bottle rotating disc driven by Axis 4 (E axis).
# Bottles are spaced 120° apart; rotating to the correct angle aligns the
# chosen bottle's nozzle over the cup.

# Disc rotation feedrate (degrees/min) for the E axis stepper.
DISC_FEEDRATE: int = 200  # G01 E[angle] F200 — matches hardware tuning

# Angular position (degrees) of each bottle on the rotating disc.
# Bottle 1 is the reference (0°); bottles 2 and 3 are offset by 120° each.
BOTTLE_ANGLES: dict = {
    1: 0.0,    # TODO: calibrate — reference position, nuoc_chanh
    2: 120.0,  # TODO: calibrate — nuoc_dau
    3: 240.0,  # TODO: calibrate — nuoc_cam
}

# XYZ position of the dispenser nozzle when disc is at the pour position (mm).
POUR_X: float = 0.0   # TODO: calibrate
POUR_Y: float = 0.0   # TODO: calibrate
POUR_Z: float = 0.0   # TODO: calibrate

# ── Ice module ───────────────────────────────────────────────────────────────

# The ice module uses a gravity slide: ice waits in a tube and a horizontal
# gate/piston on the X axis pushes a measured quantity into the cup.

# XYZ of the end-effector press tool when aligned with the ice gate (mm).
ICE_APPROACH_X: float = 0.0   # TODO: calibrate — X retracted (safe)
ICE_APPROACH_Y: float = 0.0   # TODO: calibrate
ICE_APPROACH_Z: float = 0.0   # TODO: calibrate

# X coordinate of the fully extended press position.
# Moving from ICE_APPROACH_X to ICE_PRESS_X physically pushes the ice gate.
ICE_PRESS_X: float = 0.0      # TODO: calibrate — X extended (pressed)

# How long (ms) to hold the press position so ice falls into the cup.
# G04 Pxx dwell command is used; set to 0 until ice volume is calibrated.
ICE_HOLD_MS: int = 0          # TODO: calibrate

# Feedrate for the horizontal ice-gate press move (mm/min).
ICE_PRESS_FEEDRATE: int = 1_500  # Slow enough for controlled mechanical contact

# ── Timing constants ─────────────────────────────────────────────────────────

# Duration (ms) to keep the pour nozzle open / robot stationary over cup.
# Calculated from flow-rate measurements; 0 until calibration.
POUR_TIME_MS: int = 0         # TODO: calibrate — measure ml/s at operating pressure

# How long to wait after homing before accepting the next order (ms).
POST_HOME_DELAY_MS: int = 500

# Polling interval (ms) the Flask /status route uses to detect recipe completion.
STATUS_POLL_MS: int = 500

# ── Travel feedrate ──────────────────────────────────────────────────────────

# Default XYZ travel speed used in G01 move commands (mm/min).
# Conservative value safe for early-stage testing; increase after tuning.
TRAVEL_FEEDRATE: int = 3_000

# ── Recipe definitions ────────────────────────────────────────────────────────

# Each recipe maps a drink ID (used by the frontend and /order endpoint) to:
#   bottle  — which disc slot (1-3) to rotate to
#   ice     — whether to dispense ice before pouring
#   name    — human-readable drink name for logging / UI display
#   emoji   — displayed in the tablet UI drink menu
#   desc    — short description shown under the drink name in the UI
#
# Sizes S / M affect CUP_S_Z vs CUP_M_Z but not the recipe logic itself.

RECIPES: dict = {
    "nuoc_chanh": {
        "name":   "Nước Chanh",
        "emoji":  "🍋",
        "desc":   "Fresh lemon juice, sugar syrup, ice",
        "bottle": 1,    # Bottle 1 on rotating disc (0°)
        "ice":    True,
    },
    "nuoc_dau": {
        "name":   "Nước Dâu",
        "emoji":  "🍓",
        "desc":   "Strawberry syrup, milk, ice",
        "bottle": 2,    # Bottle 2 on rotating disc (120°)
        "ice":    True,
    },
    "nuoc_cam": {
        "name":   "Nước Cam",
        "emoji":  "🍊",
        "desc":   "Fresh orange juice, sugar, ice",
        "bottle": 3,    # Bottle 3 on rotating disc (240°)
        "ice":    True,
    },
}
