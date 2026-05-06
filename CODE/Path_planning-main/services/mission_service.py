from __future__ import annotations

import bisect
import math
import time
from typing import Any

try:
    from pymavlink import mavutil
except Exception:
    mavutil = None

from pyproj import CRS, Transformer

from services.telemetry_service import get_connection


def _build_local_transformers(origin_lat: float, origin_lon: float) -> tuple[Transformer, Transformer]:
    local_crs = CRS.from_proj4(
        f"+proj=aeqd +lat_0={origin_lat} +lon_0={origin_lon} +x_0=0 +y_0=0 +units=m +datum=WGS84"
    )
    to_local = Transformer.from_crs("EPSG:4326", local_crs, always_xy=True)
    to_geo = Transformer.from_crs(local_crs, "EPSG:4326", always_xy=True)
    return to_local, to_geo


def resample_path_meters(path: list[list[float]], spacing_m: float) -> list[list[float]]:
    if not path or len(path) < 2:
        return path

    spacing_m = float(max(0.2, spacing_m))

    origin_lat, origin_lon = float(path[0][0]), float(path[0][1])
    to_local, to_geo = _build_local_transformers(origin_lat, origin_lon)

    local_points: list[tuple[float, float]] = []
    for lat, lon in path:
        x, y = to_local.transform(float(lon), float(lat))
        local_points.append((float(x), float(y)))

    cumulative = [0.0]
    for idx in range(1, len(local_points)):
        x1, y1 = local_points[idx - 1]
        x2, y2 = local_points[idx]
        cumulative.append(cumulative[-1] + math.hypot(x2 - x1, y2 - y1))

    total_length = cumulative[-1]
    if total_length < spacing_m:
        return path

    targets: list[float] = []
    current = 0.0
    while current < total_length:
        targets.append(current)
        current += spacing_m
    if abs(targets[-1] - total_length) > 1e-6:
        targets.append(total_length)

    sampled_local: list[tuple[float, float]] = []
    for target in targets:
        seg = bisect.bisect_right(cumulative, target) - 1
        seg = max(0, min(seg, len(local_points) - 2))

        seg_start = cumulative[seg]
        seg_end = cumulative[seg + 1]
        x1, y1 = local_points[seg]
        x2, y2 = local_points[seg + 1]

        if seg_end <= seg_start + 1e-9:
            sampled_local.append((x1, y1))
            continue

        t = (target - seg_start) / (seg_end - seg_start)
        sx = x1 + (x2 - x1) * t
        sy = y1 + (y2 - y1) * t
        sampled_local.append((sx, sy))

    mission_path: list[list[float]] = []
    for x, y in sampled_local:
        lon, lat = to_geo.transform(x, y)
        mission_path.append([float(lat), float(lon)])

    return mission_path


def _upload_mission_items(path: list[list[float]], altitude_m: float) -> None:
    master = get_connection()
    if master is None:
        raise RuntimeError("Drone is not connected.")

    master.mav.mission_clear_all_send(master.target_system, master.target_component)
    time.sleep(0.2)

    mission_items: list[dict[str, float | int]] = []

    takeoff_lat = float(path[0][0])
    takeoff_lon = float(path[0][1])
    mission_items.append(
        {
            "command": int(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF),
            "lat": takeoff_lat,
            "lon": takeoff_lon,
            "alt": float(altitude_m),
        }
    )

    for waypoint in path:
        mission_items.append(
            {
                "command": int(mavutil.mavlink.MAV_CMD_NAV_WAYPOINT),
                "lat": float(waypoint[0]),
                "lon": float(waypoint[1]),
                "alt": float(altitude_m),
            }
        )

    master.mav.mission_count_send(master.target_system, master.target_component, len(mission_items))

    sent = 0
    while sent < len(mission_items):
        request = master.recv_match(type=["MISSION_REQUEST", "MISSION_REQUEST_INT"], blocking=True, timeout=6)
        if request is None:
            raise TimeoutError("Mission upload timed out waiting for waypoint request.")

        seq = int(getattr(request, "seq", -1))
        if seq < 0 or seq >= len(mission_items):
            raise RuntimeError(f"Autopilot requested invalid mission seq {seq}.")

        item = mission_items[seq]
        master.mav.mission_item_send(
            master.target_system,
            master.target_component,
            seq,
            mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
            int(item["command"]),
            0,
            1,
            0,
            0,
            0,
            0,
            float(item["lat"]),
            float(item["lon"]),
            float(item["alt"]),
        )
        sent += 1

    ack = master.recv_match(type="MISSION_ACK", blocking=True, timeout=8)
    if ack is None:
        raise TimeoutError("Mission upload did not receive MISSION_ACK.")

    ack_type = int(getattr(ack, "type", -1))
    accepted = int(mavutil.mavlink.MAV_MISSION_ACCEPTED)
    if ack_type != accepted:
        raise RuntimeError(f"Mission rejected by autopilot (ack={ack_type}).")


def _send_command(master, command: int, params: list[float]) -> None:
    full_params = [0.0] * 7
    for idx, value in enumerate(params[:7]):
        full_params[idx] = float(value)

    master.mav.command_long_send(
        master.target_system,
        master.target_component,
        int(command),
        0,
        full_params[0],
        full_params[1],
        full_params[2],
        full_params[3],
        full_params[4],
        full_params[5],
        full_params[6],
    )


def upload_mission(path: list[list[float]], altitude_m: float, spacing_m: float = 1.0) -> dict[str, Any]:
    if not path or len(path) < 2:
        return {"success": False, "message": "No mission path to upload."}

    master = get_connection()
    if master is None:
        return {"success": False, "message": "Drone is not connected."}

    if mavutil is None:
        return {"success": False, "message": "pymavlink not available."}

    try:
        mission_path = resample_path_meters(path, spacing_m)
        _upload_mission_items(mission_path, altitude_m)

        return {
            "success": True,
            "message": f"Mission uploaded with {len(mission_path)} waypoints (~{spacing_m:.1f}m spacing).",
            "mission_waypoints": len(mission_path),
            "mission_path": mission_path,
        }
    except Exception as exc:
        return {"success": False, "message": f"Mission upload failed: {exc}"}


def auto_execute_mission(path: list[list[float]], altitude_m: float, spacing_m: float = 1.0) -> dict[str, Any]:
    if not path or len(path) < 2:
        return {"success": False, "message": "No mission path to execute."}

    master = get_connection()
    if master is None:
        return {"success": False, "message": "Drone is not connected."}

    if mavutil is None:
        return {"success": False, "message": "pymavlink not available."}

    try:
        mission_path = resample_path_meters(path, spacing_m)
        _upload_mission_items(mission_path, altitude_m)

        _send_command(master, mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, [1])
        time.sleep(1.0)

        _send_command(master, mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, [0, 0, 0, 0, 0, 0, float(altitude_m)])
        time.sleep(2.0)

        _send_command(master, mavutil.mavlink.MAV_CMD_MISSION_START, [0, 0])

        return {
            "success": True,
            "message": f"Auto mission started with {len(mission_path)} waypoints at {spacing_m:.1f}m spacing.",
            "mission_waypoints": len(mission_path),
            "mission_path": mission_path,
        }
    except Exception as exc:
        return {"success": False, "message": f"Auto mission failed: {exc}"}