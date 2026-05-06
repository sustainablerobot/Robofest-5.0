# Drone Mission Planner

Web-based mission planning tool for minefield-safe drone routing using Flask + Leaflet + A* path planning.

## Features

- Interactive map with **Street/Satellite** layers
- Floating, collapsible **Mission Planner** panel
- Click-based **Area Mode** (polygon loop), no rectangle dependency
- Explicit mode workflow (map acts only after you select a mode)
- **Start/Goal/Mine** placement inside selected area
- Automatic path updates when mines are added (after area + start + goal are set)
- Manual **Compute Safe Path** trigger for full planning confirmation
- Mission upload and auto-execution endpoints for MAVLink-compatible autopilots
- Mobile-friendly responsive UI

## Tech Stack

- Backend: Flask
- Geometry/Planning: Shapely, NumPy, PyProj
- Telemetry/Mission: pymavlink, pyserial
- Frontend: Leaflet (vanilla JS/CSS)

## Project Structure

- `app.py` — Flask routes and API endpoints
- `config.py` — host/port/debug/default altitude settings
- `services/path_service.py` — polygon-aware A* planning
- `services/telemetry_service.py` — MAVLink connection management
- `services/mission_service.py` — mission upload/auto mission start
- `static/js/map.js` — map setup and map controls
- `static/js/planner.js` — planner workflow and UI behavior
- `templates/map.html` — main UI page

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Run

```powershell
python app.py
```

Open:

- `http://127.0.0.1:5000`
- or `http://localhost:5000`

## Configuration

Edit `config.py`:

- `HOST` (default `0.0.0.0`)
- `PORT` (default `5000`)
- `DEBUG` (default `True`)
- `DRONE_ALTITUDE` (default `10`)

## Planner Workflow (Current)

1. Click **Show Planner** (if collapsed).
2. Select **Area Mode** and click map points to create area loop.
3. Click **Close Area**.
4. Select **Start Mode** and place start point.
5. Select **Goal Mode** and place goal point.
6. Select **Mine Mode** and add mines.
   - Path auto-updates as mines are added.
7. Optional: click **Compute Safe Path** for explicit recompute.
8. Optional: **Upload Mission** or enable auto-start behavior and compute.

## API Endpoints

### `GET /`
Loads planner UI.

### `GET /ports`
Returns available COM/UDP/TCP options.

### `GET /connection_status`
Returns current telemetry connection status.

### `POST /connect`
Body:

```json
{ "port": "COM5", "baud": 115200 }
```

### `POST /disconnect`
Disconnects telemetry session.

### `POST /compute_path`
Body (typical):

```json
{
  "start": [lat, lon],
  "goal": [lat, lon],
  "mines": [[lat, lon], [lat, lon]],
  "polygon": [[lat, lon], [lat, lon], [lat, lon]],
  "grid_resolution": 0.5,
  "mine_radius": 1.0
}
```

### `POST /upload`
Uploads mission waypoints.

### `POST /auto_mission`
Uploads, arms, takeoff, and starts mission.

## Notes

- Browser location permission improves local planning UX.
- If MAVLink packages are missing, install from `requirements.txt`.
- Keep start/goal and mines inside the selected area for valid planning.
