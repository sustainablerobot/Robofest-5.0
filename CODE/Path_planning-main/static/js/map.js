const isMobile = window.matchMedia("(max-width: 768px)").matches;

const map = L.map("map", {
	zoomControl: false,
	minZoom: 3,
	zoomAnimation: false,
	markerZoomAnimation: false,
	fadeAnimation: false,
	wheelDebounceTime: 120,
	wheelPxPerZoomLevel: 120,
	doubleClickZoom: false,
	scrollWheelZoom: !isMobile,
	preferCanvas: true,
}).setView([20.5937, 78.9629], 5);
window.map = map;

const zoomControl = L.control.zoom({ position: "topleft" }).addTo(map);

function setupZoomControlPlacement() {
	const sidebar = document.getElementById("sidebar");
	const zoomEl = zoomControl.getContainer();
	const mapContainer = map.getContainer();

	if (!zoomEl || !mapContainer) {
		return;
	}

	const applyPlacement = () => {
		let marginTop = 10;

		if (sidebar) {
			const mapRect = mapContainer.getBoundingClientRect();
			const sidebarRect = sidebar.getBoundingClientRect();
			const sidebarBottomInMap = sidebarRect.bottom - mapRect.top;
			if (sidebarBottomInMap > 0) {
				marginTop = Math.round(sidebarBottomInMap + 8);
			}
		}

		zoomEl.style.marginTop = `${marginTop}px`;
		zoomEl.style.marginLeft = "10px";
	};

	applyPlacement();
	window.setTimeout(applyPlacement, 80);
	window.setTimeout(applyPlacement, 260);

	window.addEventListener("resize", applyPlacement);
	window.addEventListener("orientationchange", applyPlacement);

	if (sidebar && "ResizeObserver" in window) {
		const observer = new ResizeObserver(() => applyPlacement());
		observer.observe(sidebar);
	}
}

function setupZoomControlCenterLock() {
	const container = map.getContainer();
	if (!container) {
		return;
	}

	const zoomInBtn = container.querySelector(".leaflet-control-zoom-in");
	const zoomOutBtn = container.querySelector(".leaflet-control-zoom-out");

	const zoomBy = (delta) => {
		const center = map.getCenter();
		const currentZoom = map.getZoom();
		const nextZoom = Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), currentZoom + delta));
		map.setView(center, nextZoom, { animate: false });
	};

	if (zoomInBtn) {
		zoomInBtn.addEventListener(
			"click",
			(event) => {
				event.preventDefault();
				event.stopPropagation();
				event.stopImmediatePropagation();
				zoomBy(1);
			},
			true
		);
	}
	if (zoomOutBtn) {
		zoomOutBtn.addEventListener(
			"click",
			(event) => {
				event.preventDefault();
				event.stopPropagation();
				event.stopImmediatePropagation();
				zoomBy(-1);
			},
			true
		);
	}
}

setupZoomControlCenterLock();
setupZoomControlPlacement();

const street = L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
	attribution: "© OpenStreetMap contributors",
	maxZoom: 22,
});

const satellite = L.tileLayer(
	"https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
	{
		attribution: "Tiles © Esri",
		maxZoom: 22,
	}
);

street.addTo(map);

L.control.layers(
	{ Street: street, Satellite: satellite },
	{},
	{ collapsed: isMobile }
).addTo(map);

window.mapState = {
	userLocation: null,
	selectedRectangleLayer: null,
	selectedRectangleLatLngs: null,
	selectedPolygonLatLngs: null,
};

function updateSystemLog(message) {
	if (typeof window.logMessage === "function") {
		window.logMessage(message);
	}
}

function showCurrentLocationMarker(latlng) {
	if (window.mapState.userLocation) {
		map.removeLayer(window.mapState.userLocation);
	}

	window.mapState.userLocation = L.circleMarker(latlng, {
		radius: 6,
		color: "#2e7d32",
		fillColor: "#66bb6a",
		fillOpacity: 1,
		weight: 2,
	}).addTo(map);

	window.mapState.userLocation.bindPopup("Your Location");
}

window.requestLocation = function requestLocation(forceRecenter = true) {
	if (!navigator.geolocation) {
		updateSystemLog("Geolocation is not supported in this browser.");
		return;
	}

	updateSystemLog("Location permission requested. Please click Allow in browser.");

	navigator.geolocation.getCurrentPosition(
		(pos) => {
			const latlng = L.latLng(pos.coords.latitude, pos.coords.longitude);
			showCurrentLocationMarker(latlng);

			if (forceRecenter) {
				map.setView(latlng, 19, { animate: false });
			}

			updateSystemLog("Centered to your current location.");
		},
		(err) => {
			if (err && err.code === err.PERMISSION_DENIED) {
				updateSystemLog("Location denied. Allow location for correct local planning.");
				return;
			}

			updateSystemLog("Could not fetch location. Use My Location to retry.");
		},
		{
			enableHighAccuracy: true,
			timeout: 15000,
			maximumAge: 0,
		}
	);
};

setTimeout(() => window.requestLocation(false), 300);