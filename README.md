# DeltaX Barista Robot

R&D prototype for an automated beverage dispenser built on the **DeltaX XS D600** delta robot platform. A Flask backend translates drink orders from a browser-based tablet UI into G-Code motion sequences executed over USB serial.

---

## Hardware

| Component | Spec |
|---|---|
| Robot | DeltaX XS D600 delta robot, USB serial 115200 baud |
| Frame | 165 × 128 × 75 cm aluminium profile |
| Water module | Rotating 3-bottle disc, Axis 4 (E stepper), 120° spacing |
| Ice module | Gravity slide + horizontal gate, pressed by X axis |
| Cup holder | Fixed platform, 2 sizes: S = 250 ml, M = 350 ml |
| Sensor | HC-SR04 ultrasonic via Arduino Nano, 9600 baud *(prototype — subject to change)* |

---

## Project structure

```
├── backend/
│   ├── main.py       # Flask app factory, hardware init, entry point
│   ├── config.py     # All constants — ports, positions, recipes, timing
│   ├── robot.py      # Serial communication with DeltaX XS (G-Code layer)
│   ├── sensor.py     # Cup-presence detection (prototype, backend-agnostic)
│   ├── recipes.py    # Recipe orchestration: home → ice → rotate → pour → home
│   └── routes.py     # Flask Blueprint: /api/order, /api/status, /api/health
├── frontend/
│   ├── index.html    # Tablet UI (drink → size → order)
│   └── assets/
│       ├── css/styles.css
│       └── js/script.js
├── requirements.txt
└── .gitignore
```

---

## Setup

**1. Clone and create virtual environment**
```bash
python -m venv venv
```

**2. Activate**
```bash
# Windows (PowerShell)
venv\Scripts\Activate.ps1

# Mac / Linux
source venv/bin/activate
```

**3. Install dependencies**
```bash
pip install -r requirements.txt
```

---

## Running

```bash
cd backend
python main.py
```

Open a browser to `http://localhost:5000`.  
Tablets on the same LAN can reach it at `http://<host-ip>:5000`.

---

## API

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/order` | Place a drink order `{drink, size}` |
| `GET` | `/api/status` | Poll robot state during recipe execution |
| `GET` | `/api/health` | Liveness check, returns `dry_run` flag |
| `POST` | `/api/test/error` | Inject a fake error state (dev/demo) |
| `POST` | `/api/test/reset` | Reset to idle (dev/demo) |

### Order request body
```json
{ "drink": "nuoc_chanh", "size": "M", "orderId": 1 }
```

### Status response
```json
{
  "status": "idle | preparing | dispensing | done | error",
  "drink":  "nuoc_chanh",
  "size":   "M",
  "detail": "Nước Chanh is ready!",
  "error":  null
}
```

---

## Recipes

| ID | Name | Bottle | Ice |
|---|---|---|---|
| `nuoc_chanh` | Nước Chanh | 1 (0°) | Yes |
| `nuoc_dau` | Nước Dâu | 2 (120°) | Yes |
| `nuoc_cam` | Nước Cam | 3 (240°) | Yes |

---

## Development mode (DRY_RUN)

`config.DRY_RUN = True` is the default. In this mode:

- No serial ports are opened.
- All G-Code commands are printed to stdout with a `[DRY RUN]` prefix instead of being sent to hardware.
- `sensor.read_distance()` returns a simulated 10 cm (cup present).
- The full HTTP + recipe pipeline runs normally so the UI and API can be tested without any hardware connected.

Set `DRY_RUN = False` only after the robot is physically assembled and COM ports are confirmed in Device Manager.

---

## Calibration checklist

All positions in `config.py` are placeholder `0.0` and marked `# TODO: calibrate`. Complete these before switching `DRY_RUN` off:

- [ ] `HOME_X / Y / Z` — robot safe home position
- [ ] `CUP_X / Y`, `CUP_S_Z`, `CUP_M_Z` — cup holder centre and Z per size
- [ ] `POUR_X / Y / Z` — nozzle position over cup
- [ ] `BOTTLE_ANGLES` — fine-tune 0° / 120° / 240° disc offsets
- [ ] `ICE_APPROACH_X / Y / Z`, `ICE_PRESS_X` — ice gate positions
- [ ] `ICE_HOLD_MS` — gate open dwell time (ms)
- [ ] `POUR_TIME_MS` — pour dwell time derived from flow-rate measurement
- [ ] `CUP_PRESENT_THRESHOLD_CM` in `sensor.py` — mount sensor then measure

---

## Sensor note

`sensor.py` is a prototype. The current backend reads from an Arduino Nano over UART, but the interface is designed to be swapped without changing any other module. To use a different sensor, replace only `_read_from_serial()` in `sensor.py` — the public functions `read_distance()` and `check_cup_present()` stay the same.

---

## Dependencies

| Package | Version | Purpose |
|---|---|---|
| Flask | 3.1.3 | Web framework — serves UI and `/api/*` endpoints |
| pyserial | 3.5 | Serial communication with robot and Arduino Nano |
