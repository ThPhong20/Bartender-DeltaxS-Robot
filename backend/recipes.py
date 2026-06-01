"""
recipes.py — High-level drink recipe orchestration.

Translates a (drink, size) order into an ordered sequence of robot motions by
calling the primitives in robot.py.  No G-Code is built here — this module
only decides *what* to do and *in what order*.

Standard recipe sequence:
    1. home()          — move to safe start position
    2. check_cup()     — abort if no cup detected in holder
    3. dispense_ice()  — optional; skipped if recipe.ice is False
    4. rotate_disc()   — align the correct bottle over the cup
    5. pour()          — move nozzle to cup and dwell for pour time
    6. home()          — return to safe position when done

All robot calls are wrapped in try/except so a single failed motion does not
crash the Flask server — errors are returned as strings and surfaced to the
/order route.
"""

import time

import config
import robot
import sensor


def _get_cup_z(size: str) -> float:
    """
    Return the Z height (mm) for the fill opening of the given cup size.

    Looks up CUP_S_Z or CUP_M_Z from config based on size key.  Defaults to
    CUP_S_Z for unknown sizes so an unrecognised value does not crash the
    recipe.

    Args:
        size: cup size key, expected 'S' or 'M'
    Returns:
        Z coordinate in mm for that cup's fill opening
    """
    # TODO: extend when more cup sizes are added
    return config.CUP_S_Z if size == 'S' else config.CUP_M_Z


def check_cup(size: str) -> bool:
    """
    Verify a cup is present in the holder before starting the recipe.

    Delegates to sensor.check_cup_present().  The size parameter is accepted
    for future use (e.g. detecting which size cup is seated) but is unused in
    the current prototype.

    Args:
        size: cup size key ('S' or 'M') — reserved for future use
    Returns:
        True if a cup is detected, False otherwise
    """
    # TODO: use size to select the correct sensor threshold when two holders
    #       are added for S and M cups separately
    return sensor.check_cup_present()


def dispense_ice() -> None:
    """
    Trigger the ice gate to drop ice into the cup.

    Moves the end-effector to the ice module approach position then calls
    robot.press_button() to perform the horizontal press-hold-retract sequence.
    After retracting, moves back to home so the arm clears the ice chute.

    Algorithm: see robot.press_button() for the 4-step press sequence.
    ICE_HOLD_MS controls how long the gate stays open; set to 0 in config
    until ice volume is calibrated.

    Returns:
        None — errors are printed by robot.press_button() internally
    """
    # TODO: implement once ice module is physically mounted and positions are
    #       calibrated in config.py (ICE_APPROACH_X/Y/Z, ICE_PRESS_X, ICE_HOLD_MS)
    pass


def rotate_to_bottle(bottle: int) -> None:
    """
    Rotate the dispensing disc to align the specified bottle over the cup.

    Looks up the target angle for the given bottle number from
    config.BOTTLE_ANGLES and calls robot.rotate_disc().

    Args:
        bottle: bottle slot number (1, 2, or 3) as defined in config.BOTTLE_ANGLES
    Returns:
        None
    Raises:
        Does not raise — logs a warning if the bottle number is not in
        BOTTLE_ANGLES and skips the rotation.
    """
    # TODO: implement once disc motor is wired and angles are calibrated
    pass


def pour(size: str) -> None:
    """
    Move the nozzle over the cup and dwell for the configured pour duration.

    Positions the end-effector at (POUR_X, POUR_Y, cup_z) where cup_z is
    determined by the cup size, then issues a G04 dwell for POUR_TIME_MS.
    After the dwell, lifts back to home Z before returning.

    Algorithm:
      1. move_to(POUR_X, POUR_Y, cup_z) — align nozzle with cup opening.
      2. G04 P{POUR_TIME_MS}            — hold while liquid flows by gravity.
      3. move_to(HOME_X, HOME_Y, HOME_Z)— lift clear before next step.

    Args:
        size: cup size key ('S' or 'M') used to select the correct Z height
    Returns:
        None
    """
    # TODO: implement once pour position and flow rate are calibrated
    #       (POUR_X, POUR_Y, POUR_Z, CUP_S_Z, CUP_M_Z, POUR_TIME_MS in config)
    pass


def run_recipe(drink: str, size: str) -> dict:
    """
    Execute the full drink recipe for the given drink ID and cup size.

    This is the sole entry point called by routes.py.  It sets robot.is_busy,
    runs the recipe sequence, then clears the flag regardless of outcome so
    the robot never gets permanently locked.

    Sequence:
        home → check_cup → [dispense_ice] → rotate_to_bottle → pour → home

    Args:
        drink: drink ID string matching a key in config.RECIPES
               (e.g. 'nuoc_chanh', 'nuoc_dau', 'nuoc_cam')
        size:  cup size key ('S' or 'M')
    Returns:
        dict with keys:
            'ok'     (bool)   — True if recipe completed without error
            'error'  (str)    — error message if ok=False, empty string otherwise
            'drink'  (str)    — echo of the drink parameter
            'size'   (str)    — echo of the size parameter
    """
    if drink not in config.RECIPES:
        return {'ok': False, 'error': f'Unknown drink: {drink}', 'drink': drink, 'size': size}

    recipe = config.RECIPES[drink]
    robot.is_busy = True

    try:
        # Step 1: move to safe home position before any other motion
        robot.home()  # G28 — home all axes via endstops

        # Step 2: confirm a cup is seated before dispensing anything
        if not check_cup(size):
            return {'ok': False, 'error': 'No cup detected', 'drink': drink, 'size': size}

        # Step 3: dispense ice if the recipe requires it
        if recipe['ice']:
            dispense_ice()

        # Step 4: rotate disc to align the correct bottle
        rotate_to_bottle(recipe['bottle'])

        # Step 5: pour the drink
        pour(size)

        # Step 6: return to safe home position
        robot.home()  # G28 — home all axes after dispensing

        # Brief pause so the robot settles before accepting the next order
        time.sleep(config.POST_HOME_DELAY_MS / 1000)

        return {'ok': True, 'error': '', 'drink': drink, 'size': size}

    except Exception as exc:  # noqa: BLE001
        return {'ok': False, 'error': str(exc), 'drink': drink, 'size': size}

    finally:
        # Always release the busy flag — even if an exception occurred above
        robot.is_busy = False
