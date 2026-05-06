from flask import Flask, render_template, request, jsonify

from services.path_service import compute_path
from services.telemetry_service import (
    connect_drone,
    disconnect_drone,
    list_available_ports,
    connection_status,
)
from services.mission_service import upload_mission, auto_execute_mission

from config import HOST, PORT, DEBUG, DRONE_ALTITUDE

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("map.html")


@app.route("/ports", methods=["GET"])
def ports():
    return jsonify({"success": True, "ports": list_available_ports()})


@app.route("/connection_status", methods=["GET"])
def connection_state():
    return jsonify(connection_status())


@app.route("/connect", methods=["POST"])
def connect():
    data = request.get_json(force=True, silent=True) or {}
    port = (data.get("port") or "").strip()
    baud = int(data.get("baud", 57600))

    result = connect_drone(port, baud)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/disconnect", methods=["POST"])
def disconnect():
    result = disconnect_drone()
    return jsonify(result), 200


@app.route("/compute_path", methods=["POST"])
def compute():
    data = request.get_json(force=True, silent=True) or {}

    start = data.get("start")
    goal = data.get("goal")
    mines = data.get("mines", [])
    polygon = data.get("polygon")
    rectangle = data.get("rectangle")
    grid_resolution = float(data.get("grid_resolution", 0.5))
    mine_radius = float(data.get("mine_radius", 1.0))

    if not start or not goal:
        return jsonify({"success": False, "error": "Start and goal are required."}), 400
    if (not polygon or len(polygon) < 3) and (not rectangle or len(rectangle) < 4):
        return jsonify({"success": False, "error": "Create a closed search area first."}), 400

    try:
        path = compute_path(
            start=start,
            goal=goal,
            mines=mines,
            polygon=polygon,
            rectangle=rectangle,
            grid_resolution=grid_resolution,
            mine_radius=mine_radius,
        )
    except ValueError as exc:
        return jsonify({"success": False, "error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"success": False, "error": f"Path planning failed: {exc}"}), 500

    return jsonify({"success": True, "path": path})


@app.route("/upload", methods=["POST"])
def upload():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", [])
    altitude = float(data.get("altitude", DRONE_ALTITUDE))
    spacing_m = float(data.get("spacing_m", 1.0))

    result = upload_mission(path, altitude, spacing_m)
    return jsonify(result), 200 if result.get("success") else 400


@app.route("/auto_mission", methods=["POST"])
def auto_mission():
    data = request.get_json(force=True, silent=True) or {}
    path = data.get("path", [])
    altitude = float(data.get("altitude", DRONE_ALTITUDE))
    spacing_m = float(data.get("spacing_m", 1.0))

    result = auto_execute_mission(path, altitude, spacing_m)
    return jsonify(result), 200 if result.get("success") else 400


if __name__ == "__main__":
    app.run(host=HOST, port=PORT, debug=DEBUG)