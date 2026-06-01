"""
routes.py — Flask Blueprint exposing the robot's HTTP API.

All routes are registered under the '/api' prefix (set in main.py when the
Blueprint is registered).  The frontend (script.js) talks to three endpoints:

    POST /api/order        — place a new drink order
    GET  /api/status       — poll robot state during recipe execution
    GET  /api/health       — lightweight connectivity check
    POST /api/test/error   — inject a fake error state (demo / dev only)
    POST /api/test/reset   — clear injected error and return to idle

Order execution is intentionally asynchronous: POST /order starts the recipe
on a background thread and returns 202 Accepted immediately.  The frontend
then polls GET /status at ~2 s intervals until the status reaches 'done' or
'error'.  This prevents the HTTP request from timing out during a long recipe.

Module-level _state dict is the single source of truth for robot progress.
It is written by the background recipe thread and read by /status.  A
threading.Lock guards all writes so the dict is never in a torn state when
read mid-update.
"""

import threading

from flask import Blueprint, jsonify, request

import config
import recipes
import robot

bp = Blueprint('api', __name__)

# ── Shared state ──────────────────────────────────────────────────────────────

# _state is read by GET /status and written by _run_recipe_thread().
# All keys must always be present so the frontend never receives a KeyError.
_state: dict = {
    'status': 'idle',   # idle | preparing | dispensing | done | error
    'drink':  None,     # drink ID string currently being made, or None
    'size':   None,     # cup size key currently being made, or None
    'detail': '',       # human-readable status detail for the UI
    'error':  None,     # {'code': int, 'message': str} or None
}

_state_lock = threading.Lock()  # Guards all writes to _state


def _set_state(**kwargs) -> None:
    """
    Thread-safe update of one or more fields in the _state dict.

    Acquires _state_lock, applies all keyword-argument updates atomically,
    then releases the lock.  Callers should never write to _state directly.

    Algorithm: a single with-block ensures the lock is released even if an
    exception is raised inside, avoiding deadlocks.

    Args:
        **kwargs: any subset of _state keys to update
    """
    with _state_lock:
        _state.update(kwargs)


# ── Background recipe runner ───────────────────────────────────────────────────

def _run_recipe_thread(drink: str, size: str) -> None:
    """
    Execute run_recipe() on a background thread and update _state with results.

    This function is the target of the threading.Thread started by POST /order.
    Running the recipe off the request thread means the HTTP response can be
    returned immediately (202) while the robot works, and GET /status can be
    polled for progress.

    Sequence:
        1. Set status → 'preparing' so /status reflects work-in-progress.
        2. Call recipes.run_recipe(drink, size) — blocks until the recipe ends.
        3. On success: set status → 'done'.
        4. On failure: set status → 'error' and populate the error field.

    The 'dispensing' phase can be inserted inside recipes.py once the pour()
    stub is implemented — recipes.py should call a progress callback or update
    _state directly via a setter passed in.

    Args:
        drink: drink ID string (validated before this thread is started)
        size:  cup size key
    Returns:
        None — communicates results through _state
    """
    _set_state(status='preparing', drink=drink, size=size,
               detail=f'Preparing {config.RECIPES[drink]["name"]}…', error=None)

    result = recipes.run_recipe(drink, size)

    if result['ok']:
        _set_state(
            status='done',
            detail=f'{config.RECIPES[drink]["name"]} is ready!',
            error=None,
        )
    else:
        _set_state(
            status='error',
            detail='Robot encountered an error.',
            error={'code': 500, 'message': result['error']},
        )


# ── Routes ────────────────────────────────────────────────────────────────────

@bp.route('/order', methods=['POST'])
def order():
    """
    Accept a new drink order and start recipe execution on a background thread.

    Expects a JSON body with keys:
        drink   (str, required) — drink ID, must exist in config.RECIPES
        size    (str, required) — cup size key, must be in config.CUP_SIZES
        orderId (any, optional) — echoed back for client-side correlation

    Validation:
        - Missing or non-JSON body           → 400
        - Unknown drink ID                   → 400
        - Unknown cup size                   → 400
        - Robot already busy (robot.is_busy) → 409 Conflict

    On success, starts a daemon thread running _run_recipe_thread() and returns
    202 Accepted so the client knows to start polling /status.

    Algorithm: daemon=True ensures the thread does not prevent Flask from
    shutting down cleanly when the process receives SIGTERM.

    Returns:
        202 {'ok': True, 'orderId': ...}       on acceptance
        400 {'ok': False, 'error': '...'}      on validation failure
        409 {'ok': False, 'error': 'busy'}     if robot is already running
    """
    body = request.get_json(silent=True)
    if not body:
        return jsonify({'ok': False, 'error': 'Expected JSON body'}), 400

    drink = body.get('drink', '').strip()
    size  = body.get('size',  '').strip().upper()
    order_id = body.get('orderId')

    # Validate drink against known recipes
    if drink not in config.RECIPES:
        return jsonify({'ok': False,
                        'error': f'Unknown drink "{drink}". '
                                 f'Valid: {list(config.RECIPES)}'}), 400

    # Validate size against known cup sizes
    if size not in config.CUP_SIZES:
        return jsonify({'ok': False,
                        'error': f'Unknown size "{size}". '
                                 f'Valid: {list(config.CUP_SIZES)}'}), 400

    # Reject the order if the robot is already executing a recipe
    if robot.is_busy:
        return jsonify({'ok': False, 'error': 'Robot is busy'}), 409

    # Start the recipe on a background thread — do not block the HTTP response
    thread = threading.Thread(
        target=_run_recipe_thread,
        args=(drink, size),
        daemon=True,  # Thread is killed automatically when Flask process exits
    )
    thread.start()

    return jsonify({'ok': True, 'orderId': order_id}), 202


@bp.route('/status', methods=['GET'])
def status():
    """
    Return the current robot status for the frontend polling loop.

    Reads _state under _state_lock for a consistent snapshot.  The frontend
    polls this endpoint every ~2 s while an order is in progress (see
    startPolling() in script.js) and uses the 'status' field to drive the
    UI state machine.

    Response shape (always 200 OK):
        {
            'status': 'idle' | 'preparing' | 'dispensing' | 'done' | 'error',
            'drink':  str | null,
            'size':   str | null,
            'detail': str,
            'error':  {'code': int, 'message': str} | null
        }

    Returns:
        200 with JSON state snapshot
    """
    with _state_lock:
        snapshot = dict(_state)  # Copy under lock to avoid torn reads
    return jsonify(snapshot), 200


@bp.route('/test/error', methods=['POST'])
def test_error():
    """
    Inject a fake error state for UI demonstration and pipeline testing.

    Forces _state into the 'error' status without running any robot motion.
    Useful for showing stakeholders the error panel behaviour, and for
    verifying that the frontend polling loop and error display work correctly.

    Accepts an optional JSON body:
        { "message": "Custom error description" }
    Falls back to a generic message if the body is absent or missing the key.

    Returns:
        200 {'ok': True} after state is updated
    """
    body = request.get_json(silent=True) or {}
    message = body.get('message', 'Simulated hardware fault — axis limit exceeded')

    # Mark robot as no longer busy so new orders can be placed after clearing
    robot.is_busy = False

    _set_state(
        status='error',
        detail='Robot encountered an error.',
        error={'code': 500, 'message': message},
    )
    return jsonify({'ok': True}), 200


@bp.route('/test/reset', methods=['POST'])
def test_reset():
    """
    Clear any injected or real error state and return the robot to idle.

    Companion to /test/error — lets the operator reset the UI after a
    demonstration without needing to restart the server.

    Returns:
        200 {'ok': True} after state is reset to idle
    """
    robot.is_busy = False
    _set_state(
        status='idle',
        drink=None,
        size=None,
        detail='',
        error=None,
    )
    return jsonify({'ok': True}), 200


@bp.route('/health', methods=['GET'])
def health():
    """
    Lightweight liveness check used by the frontend connection badge.

    The frontend calls this endpoint on load and every 10 s (see
    checkConnection() in script.js) to decide whether to show 'Connected'
    or 'Offline' in the header badge.

    Returns the DRY_RUN flag so the UI can optionally warn that the system
    is running in simulation mode.

    Returns:
        200 {'ok': True, 'dry_run': bool}
    """
    return jsonify({'ok': True, 'dry_run': config.DRY_RUN}), 200
