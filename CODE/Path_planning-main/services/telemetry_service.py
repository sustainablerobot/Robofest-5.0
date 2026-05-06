from __future__ import annotations

from typing import Any

try:
    from pymavlink import mavutil
except Exception:
    mavutil = None

try:
    from serial.tools import list_ports
except Exception:
    list_ports = None


_master = None
_connection_string = ""
_is_connected = False


def list_available_ports() -> list[str]:
    ports: list[str] = []

    if list_ports is not None:
        for port in list_ports.comports():
            ports.append(port.device)

    defaults = ["udp:127.0.0.1:14550", "tcp:127.0.0.1:5760", "COM3", "COM4"]
    for item in defaults:
        if item not in ports:
            ports.append(item)

    return ports


def connect_drone(port: str, baud: int) -> dict[str, Any]:
    global _master, _connection_string, _is_connected

    connection_string = (port or "").strip()
    if not connection_string:
        return {"success": False, "message": "Connection string is required."}

    if mavutil is None:
        return {
            "success": False,
            "message": "pymavlink not available. Install dependencies from requirements.txt.",
        }

    try:
        if connection_string.lower().startswith(("udp:", "tcp:")):
            _master = mavutil.mavlink_connection(connection_string)
        else:
            _master = mavutil.mavlink_connection(connection_string, baud=int(baud))

        heartbeat = _master.wait_heartbeat(timeout=8)
        if heartbeat is None:
            raise TimeoutError("No heartbeat received from drone/autopilot.")

        _connection_string = connection_string
        _is_connected = True
        return {
            "success": True,
            "message": f"Connected on {connection_string}",
            "target_system": int(getattr(_master, "target_system", 0) or 0),
            "target_component": int(getattr(_master, "target_component", 0) or 0),
        }
    except Exception as exc:
        _master = None
        _connection_string = ""
        _is_connected = False
        return {"success": False, "message": f"Connection failed: {exc}"}


def disconnect_drone() -> dict[str, Any]:
    global _master, _connection_string, _is_connected

    if _master is not None:
        try:
            _master.close()
        except Exception:
            pass

    _master = None
    _connection_string = ""
    _is_connected = False
    return {"success": True, "message": "Disconnected."}


def get_connection():
    return _master


def connection_status() -> dict[str, Any]:
    return {
        "success": True,
        "connected": _is_connected,
        "connection": _connection_string,
    }