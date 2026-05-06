(function () {
    const MINE_RADIUS_METERS = 1.0;
    const ALT_PATH_SPACING_METERS = 1.0;
    const AREA_CLOSE_SNAP_METERS = 3.0; // click near first point to close loop

    let mode = null;
    let mines = [];
    let start = null;
    let goal = null;
    let plannedPath = [];
    let alternatePath = [];
    let livePathRequestInFlight = false;
    let livePathRequestQueued = false;

    let mineMarkers = [];
    let mineSafetyCircles = [];
    let startMarker = null;
    let goalMarker = null;
    let safePathLine = null;
    let safePathMixLine = null;
    let safePathLabel = null;
    let alternatePathLine = null;
    let alternatePointMarkers = [];

    let missionWaypoints = [];
    let missionWaypointMarkers = [];
    let missionWaypointLine = null;

    // NEW: free-form selected area (polygon)
    let selectedAreaPoints = []; // [[lat, lng], ...]
    let selectedAreaLayer = null;
    let selectedAreaDraftLine = null;
    let selectedAreaPointMarkers = [];

    const modeButtons = {
        mine: document.getElementById("modeMine"),
        start: document.getElementById("modeStart"),
        goal: document.getElementById("modeGoal"),
        waypoint: document.getElementById("modeWaypoint"),
        area: document.getElementById("modeArea"), // optional button
    };

    function logMessage(message, level = "info") {
        const box = document.getElementById("log");
        if (!box) {
            return;
        }

        const time = new Date().toLocaleTimeString();
        const row = document.createElement("div");
        row.className = `log-row log-${level}`;
        row.textContent = `[${time}] ${message}`;
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
    }

    window.logMessage = logMessage;

    function setConnectionStatus(text, connected = false) {
        const el = document.getElementById("connectionStatus");
        if (!el) {
            return;
        }

        el.textContent = text;
        el.classList.toggle("connected", connected);
    }

    function updateStats() {
        const stats = document.getElementById("plannerStats");
        if (!stats) {
            return;
        }

        stats.textContent = `Mines: ${mines.length} | Waypoints: ${missionWaypoints.length}`;
    }

    function activateMode(nextMode) {
        mode = nextMode;
        Object.entries(modeButtons).forEach(([name, btn]) => {
            if (btn) {
                btn.classList.toggle("mode-active", name === nextMode);
            }
        });

        if (!nextMode) {
            logMessage("No mode selected. Select a mode from Mission Planner to interact on map.");
            return;
        }

        if (nextMode === "area") {
            logMessage("Area mode active. Click points to draw loop. Click near first point to close.");
        } else if (nextMode === "waypoint") {
            logMessage("Waypoint mode active. Click map to create mission waypoints.");
        } else {
            logMessage(`Mode changed to ${nextMode}. Click inside selected area loop.`);
        }
    }

    function isAreaReady() {
        return selectedAreaPoints.length >= 3 && !!selectedAreaLayer;
    }

    function isPointInPolygon(latlng, polygon) {
        // Ray-casting, polygon points are [lat, lng]
        const x = latlng.lng;
        const y = latlng.lat;
        let inside = false;

        for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
            const yi = polygon[i][0];
            const xi = polygon[i][1];
            const yj = polygon[j][0];
            const xj = polygon[j][1];

            const intersects =
                (yi > y) !== (yj > y) &&
                x < ((xj - xi) * (y - yi)) / ((yj - yi) || Number.EPSILON) + xi;

            if (intersects) inside = !inside;
        }

        return inside;
    }

    function polygonToBoundingRectangle(polygon) {
        if (!Array.isArray(polygon) || !polygon.length) return null;

        let minLat = Infinity, maxLat = -Infinity, minLng = Infinity, maxLng = -Infinity;
        polygon.forEach(([lat, lng]) => {
            minLat = Math.min(minLat, lat);
            maxLat = Math.max(maxLat, lat);
            minLng = Math.min(minLng, lng);
            maxLng = Math.max(maxLng, lng);
        });

        return [
            [minLat, minLng],
            [minLat, maxLng],
            [maxLat, maxLng],
            [maxLat, minLng],
        ];
    }

    // Kept name for compatibility with existing calls
    function pointInRectangle(latlng) {
        if (isAreaReady()) {
            return isPointInPolygon(latlng, selectedAreaPoints);
        }

        // Fallback if legacy rectangle tool still exists
        if (window.mapState && window.mapState.selectedRectangleLayer) {
            return window.mapState.selectedRectangleLayer.getBounds().contains(latlng);
        }

        return false;
    }

    function clearAreaSelection() {
        if (selectedAreaLayer) {
            map.removeLayer(selectedAreaLayer);
            selectedAreaLayer = null;
        }

        if (selectedAreaDraftLine) {
            map.removeLayer(selectedAreaDraftLine);
            selectedAreaDraftLine = null;
        }

        selectedAreaPointMarkers.forEach((m) => map.removeLayer(m));
        selectedAreaPointMarkers = [];
        selectedAreaPoints = [];

        if (window.mapState) {
            window.mapState.selectedRectangleLayer = null;
            window.mapState.selectedRectangleLatLngs = null;
            window.mapState.selectedPolygonLatLngs = null;
        }

        clearSafePath();
    }

    function redrawAreaDraft() {
        if (selectedAreaDraftLine) {
            map.removeLayer(selectedAreaDraftLine);
            selectedAreaDraftLine = null;
        }

        if (selectedAreaPoints.length >= 2) {
            selectedAreaDraftLine = L.polyline(selectedAreaPoints, {
                color: "#ab47bc",
                weight: 2,
                dashArray: "6 6",
                opacity: 0.9,
            }).addTo(map);
        }
    }

    function updateAreaInfo() {
        if (!selectedAreaLayer) return;
        const bounds = selectedAreaLayer.getBounds();
        const sw = bounds.getSouthWest();
        const se = L.latLng(bounds.getSouth(), bounds.getEast());
        const ne = bounds.getNorthEast();

        const width = map.distance(sw, se).toFixed(1);
        const height = map.distance(se, ne).toFixed(1);
        logMessage(`Area loop selected (approx bbox): ${width}m x ${height}m.`, "ok");
    }

    function getFramePadding() {
        const size = map.getSize();
        return {
            x: Math.max(24, Math.round(size.x * 0.06)),
            y: Math.max(24, Math.round(size.y * 0.08)),
        };
    }

    function fitBoundsToScreen(bounds, paddingFactor = 0.08) {
        if (!bounds || !bounds.isValid()) {
            return;
        }

        const padding = getFramePadding();

        map.invalidateSize();
        window.requestAnimationFrame(() => {
            map.fitBounds(bounds.pad(paddingFactor), {
                paddingTopLeft: [padding.x, padding.y],
                paddingBottomRight: [padding.x, padding.y],
                maxZoom: 20,
                animate: false,
            });
        });
    }

    function fitAreaInFrame(layer) {
        if (!layer) {
            return;
        }

        fitBoundsToScreen(layer.getBounds(), 0.05);
    }

    function fitAreaPointsInFrame(points) {
        if (!Array.isArray(points) || !points.length) {
            return;
        }

        const bounds = L.latLngBounds(points.map(([lat, lng]) => L.latLng(lat, lng)));
        fitBoundsToScreen(bounds, 0.18);
    }

    function closeAreaLoop() {
        if (selectedAreaPoints.length < 3) {
            logMessage("Add at least 3 points to close area loop.", "warn");
            return;
        }

        if (selectedAreaLayer) {
            map.removeLayer(selectedAreaLayer);
            selectedAreaLayer = null;
        }

        selectedAreaLayer = L.polygon(selectedAreaPoints, {
            color: "#8e24aa",
            fillColor: "#ce93d8",
            fillOpacity: 0.12,
            weight: 2,
        }).addTo(map);

        if (selectedAreaDraftLine) {
            map.removeLayer(selectedAreaDraftLine);
            selectedAreaDraftLine = null;
        }

        window.mapState = window.mapState || {};
        window.mapState.selectedPolygonLatLngs = selectedAreaPoints.map((p) => [p[0], p[1]]);
        window.mapState.selectedRectangleLatLngs = polygonToBoundingRectangle(selectedAreaPoints); // backend fallback
        window.mapState.selectedRectangleLayer = selectedAreaLayer; // compatibility

        clearMines();
        clearStartGoal();
        updateAreaInfo();
        fitAreaInFrame(selectedAreaLayer);
        logMessage("Closed loop area created. Now select mine/start/goal inside it.", "ok");

        if (mode === "area") {
            activateMode("mine");
        }
    }

    function handleAreaClick(latlng) {
        // If loop already exists and user is in area mode, start redraw
        if (mode === "area" && selectedAreaLayer) {
            clearAreaSelection();
            clearMines();
            clearStartGoal();
            logMessage("Area cleared. Start clicking points for a new loop.", "ok");
        }

        if (selectedAreaPoints.length >= 3) {
            const first = L.latLng(selectedAreaPoints[0][0], selectedAreaPoints[0][1]);
            if (map.distance(first, latlng) <= AREA_CLOSE_SNAP_METERS) {
                closeAreaLoop();
                return;
            }
        }

        selectedAreaPoints.push([latlng.lat, latlng.lng]);

        const marker = L.circleMarker(latlng, {
            radius: 4,
            color: "#8e24aa",
            fillColor: "#ce93d8",
            fillOpacity: 1,
            weight: 1,
        }).addTo(map);

        selectedAreaPointMarkers.push(marker);

        redrawAreaDraft();

        if (selectedAreaPoints.length >= 3) {
            logMessage("Click near first point to close loop.", "ok");
        }
    }

    function clearMissionWaypoints() {
        missionWaypointMarkers.forEach((m) => map.removeLayer(m));
        missionWaypointMarkers = [];
        missionWaypoints = [];

        if (missionWaypointLine) {
            map.removeLayer(missionWaypointLine);
            missionWaypointLine = null;
        }
        updateStats();
    }

    function clearSafePath() {
        plannedPath = [];
        alternatePath = [];

        if (safePathLine) {
            map.removeLayer(safePathLine);
            safePathLine = null;
        }

        if (safePathMixLine) {
            map.removeLayer(safePathMixLine);
            safePathMixLine = null;
        }

        if (safePathLabel) {
            map.removeLayer(safePathLabel);
            safePathLabel = null;
        }

        if (alternatePathLine) {
            map.removeLayer(alternatePathLine);
            alternatePathLine = null;
        }

        alternatePointMarkers.forEach((m) => map.removeLayer(m));
        alternatePointMarkers = [];
    }

    function clearMines() {
        mineMarkers.forEach((marker) => map.removeLayer(marker));
        mineSafetyCircles.forEach((circle) => map.removeLayer(circle));
        mineMarkers = [];
        mineSafetyCircles = [];
        mines = [];
        clearSafePath();
        updateStats();
    }

    function clearStartGoal() {
        if (startMarker) {
            map.removeLayer(startMarker);
            startMarker = null;
        }
        if (goalMarker) {
            map.removeLayer(goalMarker);
            goalMarker = null;
        }
        start = null;
        goal = null;
        clearSafePath();
    }

    function addMine(latlng, options = {}) {
        const { recompute = true } = options;

        const mineMarker = L.circleMarker(latlng, {
            radius: 5,
            color: "#c62828",
            fillColor: "#ef5350",
            fillOpacity: 1,
            weight: 1,
        }).addTo(map);

        const safetyCircle = L.circle(latlng, {
            radius: MINE_RADIUS_METERS,
            color: "#ff5252",
            fillColor: "#ff8a80",
            fillOpacity: 0.25,
            weight: 1,
        }).addTo(map);

        mineMarkers.push(mineMarker);
        mineSafetyCircles.push(safetyCircle);
        mines.push([latlng.lat, latlng.lng]);
        clearSafePath();
        updateStats();
        logMessage(`Mine geotagged (${mines.length}).`);

        if (recompute) {
            requestLivePathUpdate();
        }
    }

    function addWaypoint(latlng) {
        missionWaypoints.push([latlng.lat, latlng.lng]);
        const index = missionWaypoints.length;

        const marker = L.circleMarker(latlng, {
            radius: 6,
            color: "#ffb300",
            fillColor: "#ffd54f",
            fillOpacity: 1,
            weight: 2,
        }).addTo(map);

        marker.bindTooltip(`WP${index}`, {
            permanent: true,
            direction: "top",
            offset: [0, -10],
        });

        missionWaypointMarkers.push(marker);

        if (missionWaypointLine) {
            map.removeLayer(missionWaypointLine);
            missionWaypointLine = null;
        }

        if (missionWaypoints.length >= 2) {
            missionWaypointLine = L.polyline(missionWaypoints, {
                color: "#ffa000",
                weight: 4,
            }).addTo(map);
        }

        updateStats();
        logMessage(`Mission waypoint WP${index} added.`);
    }

    function randomPointInsideRectangle() {
        const layer = window.mapState.selectedRectangleLayer;
        if (!layer) {
            return null;
        }

        const bounds = layer.getBounds();
        for (let i = 0; i < 200; i += 1) {
            const lat = bounds.getSouth() + Math.random() * (bounds.getNorth() - bounds.getSouth());
            const lng = bounds.getWest() + Math.random() * (bounds.getEast() - bounds.getWest());
            const latlng = L.latLng(lat, lng);
            if (pointInRectangle(latlng)) {
                return latlng;
            }
        }

        return null;
    }

    function generateFakeMines() {
        if (!window.mapState.selectedRectangleLayer) {
            logMessage("Create a closed area loop first, then generate fake mines.", "warn");
            return;
        }

        const countInput = document.getElementById("fakeMineCount");
        const count = Math.max(1, Math.min(200, parseInt(countInput.value, 10) || 20));

        for (let i = 0; i < count; i += 1) {
            const randomPoint = randomPointInsideRectangle();
            if (randomPoint) {
                addMine(randomPoint, { recompute: false });
            }
        }

        logMessage(`Generated ${count} fake mines in selected area.`);
        requestLivePathUpdate();
    }

    function pointsEqual(a, b) {
        return (
            Array.isArray(a) &&
            Array.isArray(b) &&
            Math.abs(a[0] - b[0]) < 1e-12 &&
            Math.abs(a[1] - b[1]) < 1e-12
        );
    }

    function buildAlternatePath(path, spacingMeters = ALT_PATH_SPACING_METERS) {
        if (!Array.isArray(path) || path.length < 2) {
            return Array.isArray(path) ? path.slice() : [];
        }

        const sampled = [[path[0][0], path[0][1]]];

        for (let i = 0; i < path.length - 1; i += 1) {
            const a = path[i];
            const b = path[i + 1];

            const aLatLng = L.latLng(a[0], a[1]);
            const bLatLng = L.latLng(b[0], b[1]);
            const segmentDistance = map.distance(aLatLng, bLatLng);

            if (!Number.isFinite(segmentDistance) || segmentDistance <= 0) {
                if (!pointsEqual(sampled[sampled.length - 1], b)) {
                    sampled.push([b[0], b[1]]);
                }
                continue;
            }

            const steps = Math.floor(segmentDistance / spacingMeters);
            for (let step = 1; step <= steps; step += 1) {
                const t = (step * spacingMeters) / segmentDistance;
                if (t >= 1) {
                    break;
                }
                sampled.push([
                    a[0] + (b[0] - a[0]) * t,
                    a[1] + (b[1] - a[1]) * t,
                ]);
            }

            if (!pointsEqual(sampled[sampled.length - 1], b)) {
                sampled.push([b[0], b[1]]);
            }
        }

        return sampled;
    }

    function getPathToFly() {
        return alternatePath.length > 1 ? alternatePath : plannedPath;
    }

    function drawSafePath(path) {
        clearSafePath();
        plannedPath = Array.isArray(path) ? path.slice() : [];

        if (!plannedPath.length) {
            return;
        }

        // Base safe path
        safePathLine = L.polyline(plannedPath, {
            color: "#00b0ff",
            weight: 5,
            opacity: 0.9,
        }).addTo(map);

        // Mixed overlay color
        safePathMixLine = L.polyline(plannedPath, {
            color: "#00e676",
            weight: 3,
            opacity: 0.95,
            dashArray: "8 8",
        }).addTo(map);

        // Alternate 1m path
        alternatePath = buildAlternatePath(plannedPath, ALT_PATH_SPACING_METERS);

        if (alternatePath.length > 1) {
            alternatePathLine = L.polyline(alternatePath, {
                color: "#ffea00",
                weight: 2,
                opacity: 0.9,
                dashArray: "3 6",
            }).addTo(map);

            alternatePointMarkers = alternatePath.map((pt) =>
                L.circleMarker(pt, {
                    radius: 2,
                    color: "#ff6f00",
                    fillColor: "#ffca28",
                    fillOpacity: 0.95,
                    weight: 1,
                }).addTo(map)
            );

            logMessage(`Alternate 1m follow-path created (${alternatePath.length} points).`, "ok");
        }

        // Label at start point
        const startPt = plannedPath[0];
        if (startPt) {
            safePathLabel = L.marker(startPt, {
                interactive: false,
                zIndexOffset: 1000,
                icon: L.divIcon({
                    className: "drone-safe-path-label",
                    html: '<div style="background:rgba(0,0,0,0.65);color:#fff;padding:2px 8px;border-radius:10px;font-size:11px;font-weight:600;">Start → Drone Safe Path</div>',
                }),
            }).addTo(map);
        }
    }

    async function autoExecuteMission(path) {
        const altitude = parseFloat(document.getElementById("missionAltitude").value || "10");
        const missionPath = Array.isArray(path) && path.length > 1 ? path : getPathToFly();
        const spacingM = ALT_PATH_SPACING_METERS;

        if (!missionPath || missionPath.length < 2) {
            logMessage("No valid mission path to auto-execute.", "warn");
            return;
        }

        try {
            logMessage(`Auto mission: sending alternate 1m path (${missionPath.length} points)...`);
            const response = await fetch("/auto_mission", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    path: missionPath,
                    altitude,
                    spacing_m: spacingM,
                }),
            });

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "Auto mission failed");
            }

            if (Array.isArray(data.mission_path) && data.mission_path.length > 1) {
                drawSafePath(data.mission_path);
                logMessage(`Mission path resampled to ${data.mission_waypoints} waypoints.`, "ok");
            }

            logMessage(data.message || "Drone armed, takeoff initiated, mission started.", "ok");
        } catch (err) {
            logMessage(err.message || "Auto mission failed.", "error");
        }
    }

    async function computePath(options = {}) {
        const { autoStart = true, liveUpdate = false } = options;

        if (!isAreaReady()) {
            if (!liveUpdate) {
                logMessage("Create a closed area loop first.", "warn");
            }
            return false;
        }

        if (!start || !goal) {
            if (!liveUpdate) {
                logMessage("Set both start and goal points.", "warn");
            }
            return false;
        }

        const gridResolution = parseFloat(document.getElementById("gridResolution").value || "0.5");
        const polygon = selectedAreaPoints.map((p) => [p[0], p[1]]);
        const rectangleFallback = polygonToBoundingRectangle(polygon);

        try {
            if (!liveUpdate) {
                logMessage("Computing A* safe path...");
            }

            const response = await fetch("/compute_path", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    start,
                    goal,
                    mines,
                    polygon,                      // NEW: random closed loop area
                    rectangle: rectangleFallback, // fallback for existing backend
                    grid_resolution: gridResolution,
                    mine_radius: MINE_RADIUS_METERS,
                }),
            });

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.error || data.message || "Path planning failed.");
            }

            drawSafePath(data.path);
            if (liveUpdate) {
                logMessage(`Path updated with ${data.path.length} points after mine update.`, "ok");
            } else {
                logMessage(`Safe path generated with ${data.path.length} points.`, "ok");
            }

            const autoStartAfterCompute = document.getElementById("autoStartAfterCompute").checked;
            if (autoStart && autoStartAfterCompute) {
                await autoExecuteMission(getPathToFly());
            }

            return true;
        } catch (err) {
            if (liveUpdate) {
                logMessage(err.message || "Path update failed for current mine layout.", "warn");
            } else {
                logMessage(err.message || "Path compute failed.", "error");
            }

            return false;
        }
    }

    function requestLivePathUpdate() {
        if (!isAreaReady() || !start || !goal) {
            return;
        }

        if (livePathRequestInFlight) {
            livePathRequestQueued = true;
            return;
        }

        livePathRequestInFlight = true;

        computePath({ autoStart: false, liveUpdate: true })
            .finally(() => {
                livePathRequestInFlight = false;

                if (livePathRequestQueued) {
                    livePathRequestQueued = false;
                    requestLivePathUpdate();
                }
            });
    }

    async function loadPorts() {
        const select = document.getElementById("comport");
        select.innerHTML = "";

        try {
            const response = await fetch("/ports");
            const data = await response.json();
            if (!data.success) {
                throw new Error("Could not load ports");
            }

            data.ports.forEach((port) => {
                const option = document.createElement("option");
                option.value = port;
                option.textContent = port;
                select.appendChild(option);
            });

            logMessage("Ports refreshed.");
        } catch (err) {
            logMessage("Failed to load COM/UDP options.", "warn");
        }
    }

    function getSelectedConnectionString() {
        const manual = (document.getElementById("manualPort").value || "").trim();
        if (manual) {
            return manual;
        }
        return (document.getElementById("comport").value || "").trim();
    }

    async function connectDrone() {
        const port = getSelectedConnectionString();
        const baud = parseInt(document.getElementById("baud").value || "115200", 10);

        if (!port) {
            logMessage("Choose or type a COM/UDP connection string first.", "warn");
            return;
        }

        try {
            const response = await fetch("/connect", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ port, baud }),
            });

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "Connection failed");
            }

            setConnectionStatus(`Connected: ${port}`, true);
            logMessage(data.message || "Drone connected.", "ok");
        } catch (err) {
            setConnectionStatus("Disconnected", false);
            logMessage(err.message || "Drone connection failed.", "error");
        }
    }

    async function disconnectDrone() {
        try {
            await fetch("/disconnect", { method: "POST" });
            setConnectionStatus("Disconnected", false);
            logMessage("Telemetry disconnected.");
        } catch (err) {
            logMessage("Disconnect request failed.", "warn");
        }
    }

    async function uploadMission() {
        const missionPath = getPathToFly();
        if (missionPath.length < 2) {
            logMessage("Compute path before upload.", "warn");
            return;
        }

        const altitude = parseFloat(document.getElementById("missionAltitude").value || "10");
        const spacingM = ALT_PATH_SPACING_METERS;

        try {
            const response = await fetch("/upload", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ path: missionPath, altitude, spacing_m: spacingM }),
            });

            const data = await response.json();
            if (!response.ok || !data.success) {
                throw new Error(data.message || "Upload failed");
            }

            if (Array.isArray(data.mission_path) && data.mission_path.length > 1) {
                drawSafePath(data.mission_path);
                logMessage(`Mission resampled to ${data.mission_waypoints} waypoints.`, "ok");
            }

            logMessage(data.message || "Mission uploaded.", "ok");
        } catch (err) {
            logMessage(err.message || "Mission upload failed.", "error");
        }
    }

    function updateRectangleInfo(layer) {
        const corners = layer.getLatLngs()[0];
        const sideA = map.distance(corners[0], corners[1]);
        const sideB = map.distance(corners[1], corners[2]);
        const longSide = Math.max(sideA, sideB).toFixed(1);
        const shortSide = Math.min(sideA, sideB).toFixed(1);
        logMessage(`Search area selected: ${longSide}m x ${shortSide}m.`);
    }

    // Replace rectangle callback with polygon conversion (if legacy draw tool still triggers it)
    window.onRectangleSelected = function onRectangleSelected(layer) {
        if (!layer) return;

        const latlngs = layer.getLatLngs()[0] || [];
        const points = latlngs
            .map((p) => [p.lat, p.lng])
            .filter((_, i, arr) => i < arr.length - 1); // remove repeated closing point

        if (map.hasLayer(layer)) {
            map.removeLayer(layer);
        }

        clearAreaSelection();
        clearMines();
        clearStartGoal();
        clearMissionWaypoints();

        points.forEach(([lat, lng]) => {
            selectedAreaPoints.push([lat, lng]);
            const marker = L.circleMarker([lat, lng], {
                radius: 4,
                color: "#8e24aa",
                fillColor: "#ce93d8",
                fillOpacity: 1,
                weight: 1,
            }).addTo(map);
            selectedAreaPointMarkers.push(marker);
        });

        closeAreaLoop();
    };

    function setupPlannerToggle() {
        const sidebar = document.getElementById("sidebar");
        const button = document.getElementById("btnTogglePlanner");
        if (!sidebar || !button) {
            return;
        }

        let isCollapsed = sidebar.classList.contains("is-collapsed");

        const applyState = () => {
            sidebar.classList.toggle("is-collapsed", isCollapsed);
            button.textContent = isCollapsed ? "Show Planner" : "Hide Planner";
            button.setAttribute("aria-expanded", String(!isCollapsed));

            window.setTimeout(() => {
                map.invalidateSize();
            }, 220);
        };

        button.addEventListener("click", () => {
            isCollapsed = !isCollapsed;
            applyState();
        });

        applyState();
    }

    map.on("click", (event) => {
        const latlng = event.latlng;

        if (!mode) {
            return;
        }

        if (mode === "area") {
            handleAreaClick(latlng);
            return;
        }

        if (!isAreaReady()) {
            logMessage("Select Area Mode from Mission Planner to draw area first.", "warn");
            return;
        }

        if (mode === "waypoint") {
            if (!pointInRectangle(latlng)) {
                logMessage("Click inside selected area loop.", "warn");
                return;
            }
            addWaypoint(latlng);
            return;
        }

        if (!pointInRectangle(latlng)) {
            logMessage("Click inside selected area loop.", "warn");
            return;
        }

        if (mode === "mine") {
            addMine(latlng);
            return;
        }

        if (mode === "start") {
            if (startMarker) {
                map.removeLayer(startMarker);
            }
            start = [latlng.lat, latlng.lng];
            startMarker = L.marker(latlng).addTo(map).bindPopup("Start");
            clearSafePath();
            logMessage("Start point selected.", "ok");
            requestLivePathUpdate();
            return;
        }

        if (mode === "goal") {
            if (goalMarker) {
                map.removeLayer(goalMarker);
            }
            goal = [latlng.lat, latlng.lng];
            goalMarker = L.marker(latlng).addTo(map).bindPopup("Goal");
            clearSafePath();
            logMessage("Goal point selected.", "ok");
            requestLivePathUpdate();
        }
    });

    document.getElementById("btnMyLocation").addEventListener("click", () => window.requestLocation(true));
    document.getElementById("btnRefreshPorts").addEventListener("click", loadPorts);
    document.getElementById("btnConnect").addEventListener("click", connectDrone);
    document.getElementById("btnDisconnect").addEventListener("click", disconnectDrone);

    document.getElementById("btnAddFakeMines").addEventListener("click", generateFakeMines);
    document.getElementById("btnClearMines").addEventListener("click", () => {
        clearMines();
        logMessage("All mines cleared.");
    });
    document.getElementById("btnClearPath").addEventListener("click", () => {
        clearSafePath();
        logMessage("Path cleared.");
    });
    document.getElementById("btnComputePath").addEventListener("click", computePath);
    document.getElementById("btnUploadMission").addEventListener("click", uploadMission);

    // safer button wiring (modeArea may or may not exist in HTML)
    Object.entries(modeButtons).forEach(([name, btn]) => {
        if (btn) {
            btn.addEventListener("click", () => {
                if (mode === name) {
                    activateMode(null);
                    return;
                }

                activateMode(name);
            });
        }
    });

    // Optional controls if present in HTML
    const btnCloseArea = document.getElementById("btnCloseArea");
    if (btnCloseArea) {
        btnCloseArea.addEventListener("click", closeAreaLoop);
    }

    const btnClearArea = document.getElementById("btnClearArea");
    if (btnClearArea) {
        btnClearArea.addEventListener("click", () => {
            clearAreaSelection();
            clearMines();
            clearStartGoal();
            clearMissionWaypoints();
            activateMode(null);
            logMessage("Area cleared. Select Area Mode to draw new closed loop.", "ok");
        });
    }

    setupPlannerToggle();

    activateMode(null);
    loadPorts();
    updateStats();
    logMessage("Mission Planner UI ready. Select a mode to start interacting on map.", "ok");
})();