"""
main.py — Application entry point for the DeltaX Barista Robot.

Responsibilities:
    - Create and configure the Flask application.
    - Register the API Blueprint from routes.py under the '/api' prefix.
    - Serve the tablet frontend (frontend/index.html + assets) as static files.
    - Connect to the robot and sensor on startup.
    - Register an atexit handler to close serial ports cleanly on shutdown.
    - Start the Flask development server.

Directory layout assumed (relative to this file):
    backend/main.py        ← this file
    frontend/index.html    ← tablet UI entry point
    frontend/assets/       ← CSS, JS, images

Run with:
    cd backend
    python main.py

The server listens on 0.0.0.0:5000 so any device on the LAN can reach the
tablet UI at http://<host-ip>:5000.  Set HOST/PORT constants below to change.
"""

import atexit
import os

from flask import Flask

import config
import robot
import sensor
from routes import bp as api_bp

# ── Server binding ─────────────────────────────────────────────────────────────

HOST: str = '0.0.0.0'  # Listen on all interfaces so tablets on the LAN can connect
PORT: int = 5000

# ── Flask app factory ─────────────────────────────────────────────────────────

# Resolve the frontend directory relative to this file so the app works
# regardless of the working directory from which python main.py is invoked.
_HERE = os.path.dirname(os.path.abspath(__file__))
_FRONTEND_DIR = os.path.join(_HERE, '..', 'frontend')

app = Flask(
    __name__,
    static_folder=_FRONTEND_DIR,   # Serve frontend/ as the static root
    static_url_path='',            # Map static root to '/' (no /static prefix)
)


# ── Frontend route ─────────────────────────────────────────────────────────────

@app.route('/')
def index():
    """
    Serve the tablet UI entry point.

    Flask's send_static_file() locates index.html inside static_folder
    (frontend/) and returns it with the correct Content-Type header.
    All asset paths in index.html are relative (assets/css/..., assets/js/...)
    so they resolve correctly once the document root is '/'.

    Returns:
        HTTP 200 with frontend/index.html content
    """
    return app.send_static_file('index.html')


# ── Blueprint registration ────────────────────────────────────────────────────

# All routes defined in routes.py become /api/order, /api/status, /api/health
app.register_blueprint(api_bp, url_prefix='/api')


# ── Hardware initialisation ───────────────────────────────────────────────────

def _init_hardware() -> None:
    """
    Open serial connections to the robot and sensor at server startup.

    Called once before the Flask server starts accepting requests.  Failures
    are logged but do not abort startup — in DRY_RUN mode both calls succeed
    trivially, and in live mode a failed connection means the robot is
    unavailable but the UI can still load and show an error state.

    Algorithm: call connect() on each hardware module; each returns a bool
    indicating success.  Warnings are printed so the operator knows which
    hardware is offline without reading a traceback.
    """
    robot_ok  = robot.connect()
    sensor_ok = sensor.connect_sensor()

    if not robot_ok:
        print('[main] WARNING: robot serial connection failed — '
              'check ROBOT_PORT in config.py')
    if not sensor_ok:
        print('[main] WARNING: sensor serial connection failed — '
              'check SENSOR_PORT in config.py')


def _shutdown_hardware() -> None:
    """
    Close all serial ports when the Flask process exits.

    Registered with atexit so it runs on both clean exit (Ctrl-C) and
    when the process is terminated normally.  Releasing the COM ports
    prevents 'port in use' errors the next time the server starts.
    """
    robot.disconnect()
    sensor.disconnect_sensor()
    print('[main] Hardware connections closed')


# Register shutdown handler before starting so it always runs on exit
atexit.register(_shutdown_hardware)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == '__main__':
    _init_hardware()

    print(f'[main] DRY_RUN = {config.DRY_RUN}')
    print(f'[main] Starting server on http://{HOST}:{PORT}')

    # debug=False in production; use=reloader=False so atexit fires exactly
    # once and hardware init does not run twice (Flask reloader forks the process)
    app.run(host=HOST, port=PORT, debug=config.DRY_RUN, use_reloader=False)
