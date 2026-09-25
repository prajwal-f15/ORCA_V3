/**
 * =============================================================================
 * ORCA V3 ROUTE ENGINE — MARINE NAVIGATION TESTING DASHBOARD
 * Pure Vanilla JavaScript Client (No React, No NPM, No External Frameworks)
 * Compatible with Leaflet CDN & FastAPI Backend (http://127.0.0.1:8000)
 * =============================================================================
 */

(function () {
  "use strict";

  // Backend Configuration
  const API_BASE = "http://127.0.0.1:8000";

  // Application State
  const state = {
    backendConnected: false,
    mapClickMode: "start", // 'start' | 'dest' | 'harbour'
    activeTrip: null,      // TripRecord entity if trip is active
    activeRoute: null,     // Latest calculated RouteResponse
    returnState: null,     // Latest ReturnNavigationState
    watchGpsId: null,      // Geolocation watch ID
    simulationInterval: null, // Auto-step simulation timer
    simulatedIndex: 0,
  };

  // Map & Layer State
  let map = null;
  let startMarker = null;
  let destMarker = null;
  let harbourMarker = null;
  let vesselMarker = null;
  let routePolyline = null;
  let trackPolyline = null;
  let returnPolyline = null;
  let waypointMarkersLayer = null;

  // Preset Routes (India Marine Waters)
  const ROUTE_PRESETS = {
    "mumbai-goa": {
      start: { lat: 18.9220, lon: 72.8347 }, // Mumbai Port
      dest: { lat: 15.4909, lon: 73.8278 },  // Goa Panaji
      speed: 12.5,
    },
    "chennai-portblair": {
      start: { lat: 13.0827, lon: 80.2707 }, // Chennai Port
      dest: { lat: 11.6234, lon: 92.7265 },  // Port Blair (Andaman)
      speed: 14.0,
    },
    "kochi-lakshadweep": {
      start: { lat: 9.9312, lon: 76.2673 },  // Kochi Port
      dest: { lat: 10.5667, lon: 72.6417 },  // Kavaratti (Lakshadweep)
      speed: 11.0,
    },
    "gujarat-mumbai": {
      start: { lat: 23.0033, lon: 70.2189 }, // Kandla Port
      dest: { lat: 18.9220, lon: 72.8347 },  // Mumbai Port
      speed: 13.0,
    },
    "visakhapatnam-chennai": {
      start: { lat: 17.6868, lon: 83.2185 }, // Visakhapatnam Port
      dest: { lat: 13.0827, lon: 80.2707 },  // Chennai Port
      speed: 12.0,
    },
    "zero-distance": {
      start: { lat: 18.9220, lon: 72.8347 },
      dest: { lat: 18.9220, lon: 72.8347 },
      speed: 10.0,
    },
  };

  // ===========================================================================
  // INITIALIZATION
  // ===========================================================================

  document.addEventListener("DOMContentLoaded", () => {
    initMap();
    initTabNavigation();
    initFormHandlers();
    initTripControls();
    initReturnControls();
    initHistoryControls();
    initGeographyControls();
    initDrawer();
    checkBackendHealth();

    // Auto-poll health every 10 seconds
    setInterval(checkBackendHealth, 10000);
  });

  // ===========================================================================
  // LEAFLET MAP INITIALIZATION
  // ===========================================================================

  function initMap() {
    // Center around India Marine Waters (Arabian Sea, Bay of Bengal, Indian Ocean)
    map = L.map("marineMap", {
      center: [15.0, 75.0],
      zoom: 5,
      minZoom: 3,
      maxZoom: 18,
    });

    // Dark CartoDB Marine Tiles with OpenStreetMap fallback
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 19,
    }).addTo(map);

    waypointMarkersLayer = L.layerGroup().addTo(map);

    // Map Click Listener
    map.on("click", handleMapClick);

    // Initial Marker Placement from form inputs
    syncMapMarkersFromInputs();

    // Floating Buttons
    document.getElementById("recenterIndiaBtn").addEventListener("click", () => {
      map.setView([15.0, 75.0], 5);
    });

    document.getElementById("fitRouteBtn").addEventListener("click", () => {
      fitMapToActiveRoute();
    });

    document.getElementById("clearMapOverlaysBtn").addEventListener("click", () => {
      clearMapOverlays();
      showToast("Map overlays cleared", "info");
    });
  }

  function handleMapClick(e) {
    const lat = Number(e.latlng.lat.toFixed(6));
    const lon = Number(e.latlng.lng.toFixed(6));

    if (state.mapClickMode === "start") {
      document.getElementById("startLat").value = lat;
      document.getElementById("startLon").value = lon;
      updateStartMarker(lat, lon);
      showToast(`⚓ Start set to: ${lat}, ${lon}`, "info");
    } else if (state.mapClickMode === "dest") {
      document.getElementById("destLat").value = lat;
      document.getElementById("destLon").value = lon;
      updateDestMarker(lat, lon);
      showToast(`📍 Destination set to: ${lat}, ${lon}`, "info");
    } else if (state.mapClickMode === "harbour") {
      document.getElementById("harbourLat").value = lat;
      document.getElementById("harbourLon").value = lon;
      updateHarbourMarker(lat, lon);
      showToast(`🏛️ Harbour set to: ${lat}, ${lon}`, "info");
    }
  }

  function updateStartMarker(lat, lon) {
    if (startMarker) map.removeLayer(startMarker);
    startMarker = L.marker([lat, lon], {
      icon: createCustomIcon("⚓", "#00e5ff"),
    }).addTo(map).bindPopup(`<b>Start Origin</b><br>${lat}, ${lon}`);
  }

  function updateDestMarker(lat, lon) {
    if (destMarker) map.removeLayer(destMarker);
    destMarker = L.marker([lat, lon], {
      icon: createCustomIcon("📍", "#ef4444"),
    }).addTo(map).bindPopup(`<b>Destination</b><br>${lat}, ${lon}`);
  }

  function updateHarbourMarker(lat, lon) {
    if (harbourMarker) map.removeLayer(harbourMarker);
    harbourMarker = L.marker([lat, lon], {
      icon: createCustomIcon("🏛️", "#f59e0b"),
    }).addTo(map).bindPopup(`<b>Safe Harbour</b><br>${lat}, ${lon}`);
  }

  function updateVesselMarker(lat, lon, bearing = 0) {
    if (vesselMarker) map.removeLayer(vesselMarker);
    vesselMarker = L.marker([lat, lon], {
      icon: createCustomIcon("🚢", "#10b981", true),
    }).addTo(map).bindPopup(`<b>Vessel Live GPS</b><br>${lat}, ${lon}<br>Course: ${bearing}°`);
  }

  function createCustomIcon(symbol, color, pulse = false) {
    return L.divIcon({
      className: "custom-leaflet-marker",
      html: `<div style="background: ${color}; width: 28px; height: 28px; border-radius: 50%; display: flex; align-items: center; justify-content: center; color: #fff; font-size: 14px; border: 2px solid #fff; box-shadow: 0 0 10px ${color}; ${pulse ? 'animation: pulse 1.5s infinite;' : ''}">${symbol}</div>`,
      iconSize: [28, 28],
      iconAnchor: [14, 14],
    });
  }

  function syncMapMarkersFromInputs() {
    const sLat = parseFloat(document.getElementById("startLat").value);
    const sLon = parseFloat(document.getElementById("startLon").value);
    if (!isNaN(sLat) && !isNaN(sLon)) updateStartMarker(sLat, sLon);

    const dLat = parseFloat(document.getElementById("destLat").value);
    const dLon = parseFloat(document.getElementById("destLon").value);
    if (!isNaN(dLat) && !isNaN(dLon)) updateDestMarker(dLat, dLon);
  }

  function clearMapOverlays() {
    if (routePolyline) map.removeLayer(routePolyline);
    if (trackPolyline) map.removeLayer(trackPolyline);
    if (returnPolyline) map.removeLayer(returnPolyline);
    if (waypointMarkersLayer) waypointMarkersLayer.clearLayers();
    routePolyline = null;
    trackPolyline = null;
    returnPolyline = null;
  }

  function fitMapToActiveRoute() {
    if (routePolyline) {
      map.fitBounds(routePolyline.getBounds(), { padding: [40, 40] });
    } else if (startMarker && destMarker) {
      const group = new L.featureGroup([startMarker, destMarker]);
      map.fitBounds(group.getBounds(), { padding: [50, 50] });
    }
  }

  // ===========================================================================
  // BACKEND API CLIENT & HEALTH CHECK
  // ===========================================================================

  async function apiRequest(endpoint, options = {}) {
    const url = `${API_BASE}${endpoint}`;
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };

    logApiCall(`REQ ${options.method || "GET"} ${endpoint}`, options.body ? JSON.parse(options.body) : null);

    try {
      const response = await fetch(url, { ...options, headers });
      const data = await response.json().catch(() => null);

      logApiResponse(`RES ${response.status} ${endpoint}`, data);

      if (!response.ok) {
        let errorDetail = `HTTP Error ${response.status}`;
        if (data && data.detail) {
          if (Array.isArray(data.detail)) {
            errorDetail = data.detail.map((d) => (d.loc ? `${d.loc.join(".")}: ` : "") + (d.msg || JSON.stringify(d))).join("; ");
          } else if (typeof data.detail === "string") {
            errorDetail = data.detail;
          } else {
            errorDetail = JSON.stringify(data.detail);
          }
        }
        throw new Error(errorDetail);
      }

      return data;
    } catch (err) {
      logApiResponse(`ERR ${endpoint}`, { error: err.message });
      throw err;
    }
  }

  async function checkBackendHealth() {
    const dot = document.getElementById("backendStatusDot");
    const label = document.getElementById("backendStatusText");

    try {
      const data = await fetch(`${API_BASE}/health`).then((r) => r.json());
      if (data.status === "ok") {
        state.backendConnected = true;
        dot.className = "status-dot connected";
        label.textContent = "Backend: Online";
      }
    } catch {
      state.backendConnected = false;
      dot.className = "status-dot disconnected";
      label.textContent = "Backend: Offline";
    }
  }

  // ===========================================================================
  // TAB NAVIGATION & CONTROL TOGGLES
  // ===========================================================================

  function initTabNavigation() {
    const tabs = document.querySelectorAll(".tab-btn");
    tabs.forEach((tab) => {
      tab.addEventListener("click", () => {
        tabs.forEach((t) => t.classList.remove("active"));
        document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));

        tab.classList.add("active");
        const target = document.getElementById(tab.dataset.tab);
        if (target) target.classList.add("active");

        if (tab.dataset.tab === "tab-history") loadTripHistory();
        if (tab.dataset.tab === "tab-geography") loadGeographyDatasets();
      });
    });

    // Map picker buttons
    const pickerBtns = [
      { id: "pickStartBtn", mode: "start" },
      { id: "pickDestBtn", mode: "dest" },
      { id: "pickHarbourBtn", mode: "harbour" },
    ];
    pickerBtns.forEach(({ id, mode }) => {
      const btn = document.getElementById(id);
      if (btn) {
        btn.addEventListener("click", () => {
          pickerBtns.forEach((b) => document.getElementById(b.id).classList.remove("active"));
          btn.classList.add("active");
          state.mapClickMode = mode;
        });
      }
    });
  }

  // ===========================================================================
  // ROUTING FORM & CALCULATIONS
  // ===========================================================================

  function initFormHandlers() {
    // Preset dropdown
    const presetSelect = document.getElementById("routePresetSelect");
    presetSelect.addEventListener("change", (e) => {
      const key = e.target.value;
      const preset = ROUTE_PRESETS[key];
      if (preset) {
        document.getElementById("startLat").value = preset.start.lat;
        document.getElementById("startLon").value = preset.start.lon;
        document.getElementById("destLat").value = preset.dest.lat;
        document.getElementById("destLon").value = preset.dest.lon;
        document.getElementById("vesselSpeed").value = preset.speed;

        updateStartMarker(preset.start.lat, preset.start.lon);
        updateDestMarker(preset.dest.lat, preset.dest.lon);
        fitMapToActiveRoute();
        showToast(`Loaded route preset: ${key}`, "success");
      }
    });

    // "Use My GPS Location"
    document.getElementById("useMyLocationStartBtn").addEventListener("click", () => {
      if (!navigator.geolocation) {
        showToast("Browser Geolocation not supported on this device.", "error");
        return;
      }

      showToast("Acquiring GPS fix...", "info");
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          const lat = Number(pos.coords.latitude.toFixed(6));
          const lon = Number(pos.coords.longitude.toFixed(6));
          document.getElementById("startLat").value = lat;
          document.getElementById("startLon").value = lon;
          updateStartMarker(lat, lon);
          map.setView([lat, lon], 8);
          updateGpsStatusBadge(lat, lon);
          showToast(`Acquired GPS: ${lat}, ${lon}`, "success");
        },
        (err) => {
          showToast(`GPS Error: ${err.message}`, "error");
        },
        { enableHighAccuracy: true, timeout: 8000 }
      );
    });

    // Swap button
    document.getElementById("swapCoordinatesBtn").addEventListener("click", () => {
      const sLat = document.getElementById("startLat").value;
      const sLon = document.getElementById("startLon").value;
      const dLat = document.getElementById("destLat").value;
      const dLon = document.getElementById("destLon").value;

      document.getElementById("startLat").value = dLat;
      document.getElementById("startLon").value = dLon;
      document.getElementById("destLat").value = sLat;
      document.getElementById("destLon").value = sLon;

      syncMapMarkersFromInputs();
      showToast("Swapped Start and Destination coordinates", "info");
    });

    // Route calculation form submit
    const routeForm = document.getElementById("routeForm");
    routeForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      await calculateRoute();
    });

    // Start trip from calculated route
    document.getElementById("startTripFromRouteBtn").addEventListener("click", () => {
      startTripFromCurrentForm();
    });
  }

  async function calculateRoute() {
    const startLat = parseFloat(document.getElementById("startLat").value);
    const startLon = parseFloat(document.getElementById("startLon").value);
    const destLat = parseFloat(document.getElementById("destLat").value);
    const destLon = parseFloat(document.getElementById("destLon").value);
    const speed = parseFloat(document.getElementById("vesselSpeed").value);
    const rawObjective = document.getElementById("routeObjective").value;

    const objectiveMap = {
      safe_and_efficient: "safe_and_efficient",
      nearest_destination: "nearest_destination",
      shortest_distance: "nearest_destination",
      fastest_arrival: "fastest_arrival",
      fastest: "fastest_arrival",
      lowest_fuel: "lowest_fuel",
      fuel_saving: "lowest_fuel",
      fuel_optimization: "lowest_fuel",
      highest_potential: "highest_potential",
      fishing_potential: "highest_potential",
    };
    const objective = objectiveMap[rawObjective] || rawObjective;

    if (isNaN(startLat) || isNaN(startLon) || isNaN(destLat) || isNaN(destLon) || isNaN(speed)) {
      showToast("Please enter valid numeric coordinates and vessel speed.", "error");
      return;
    }

    const draftEl = document.getElementById("vesselDraft");
    const minSafeEl = document.getElementById("minSafeDepth");
    const draft = draftEl && draftEl.value ? parseFloat(draftEl.value) : null;
    const minSafe = minSafeEl && minSafeEl.value ? parseFloat(minSafeEl.value) : null;

    const vesselObj = { speed_knots: speed };
    if (draft !== null && !isNaN(draft)) vesselObj.draft_meters = draft;
    if (minSafe !== null && !isNaN(minSafe)) vesselObj.minimum_safe_depth_meters = minSafe;

    const payload = {
      start: { latitude: startLat, longitude: startLon },
      destination: { latitude: destLat, longitude: destLon },
      vessel: vesselObj,
      objective: objective,
    };

    try {
      showToast("Calculating maritime route...", "info");
      const routeData = await apiRequest("/route", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      state.activeRoute = routeData;
      renderCalculatedRoute(routeData);
      showToast("Route calculated successfully!", "success");
    } catch (err) {
      showToast(`Calculation failed: ${err.message}`, "error");
    }
  }

  function renderCalculatedRoute(routeData) {
    const card = document.getElementById("calculatedRouteCard");
    card.classList.remove("hidden");

    document.getElementById("calcRouteId").textContent = routeData.route_id;
    document.getElementById("calcDistKm").textContent = `${routeData.summary.total_distance_km || routeData.summary.distance_km} km`;
    document.getElementById("calcDistNm").textContent = `${routeData.summary.total_distance_nm || routeData.summary.distance_nm} NM`;
    document.getElementById("calcEta").textContent = `${routeData.summary.estimated_time_minutes} mins`;
    document.getElementById("calcScore").textContent = routeData.summary.route_score;

    // Safety Decision Badge & Styling
    const safetyDecision = routeData.safety_decision || (routeData.safety_evaluation && routeData.safety_evaluation.decision) || "ALLOW";
    const safetyBadge = document.getElementById("calcSafetyBadge");
    if (safetyBadge) {
      safetyBadge.textContent = safetyDecision;
      safetyBadge.className = "badge";
      if (safetyDecision === "ALLOW") {
        safetyBadge.classList.add("badge-allow");
      } else if (safetyDecision === "WARN") {
        safetyBadge.classList.add("badge-warn");
      } else if (safetyDecision === "REJECT") {
        safetyBadge.classList.add("badge-reject");
      } else if (safetyDecision === "DEGRADED") {
        safetyBadge.classList.add("badge-degraded");
      }
    }

    // Environmental Sources
    const oceanSourceEl = document.getElementById("calcOceanSource");
    const weatherSourceEl = document.getElementById("calcWeatherSource");
    const pfzSourceEl = document.getElementById("calcPfzSource");
    if (oceanSourceEl) oceanSourceEl.textContent = "MOCK";
    if (weatherSourceEl) weatherSourceEl.textContent = "MOCK";
    if (pfzSourceEl) {
      pfzSourceEl.textContent = routeData.evaluation_metadata?.selected_objective === "highest_potential" ? "MOCK / IN-MEMORY" : "TESTING";
    }

    // Safety Assessment Details (Warnings & Blocking Reasons)
    const safetyDetailsBox = document.getElementById("calcSafetyDetails");
    const safetyTitle = document.getElementById("calcSafetyTitle");
    const safetyMessages = document.getElementById("calcSafetyMessages");

    if (safetyDetailsBox && safetyTitle && safetyMessages) {
      safetyDetailsBox.classList.remove("hidden", "allow", "warn", "reject");
      const evalReport = routeData.safety_evaluation || {};
      const blockingReasons = evalReport.blocking_reasons || [];
      const warnings = evalReport.warnings || [];

      if (safetyDecision === "REJECT") {
        safetyDetailsBox.classList.add("reject");
        safetyTitle.textContent = "⛔ Safety Governor Verdict: REJECT (Voyage Blocked)";
        safetyMessages.innerHTML = blockingReasons.length
          ? `<strong>Blocking Reasons:</strong><ul style="margin: 4px 0 0 16px; padding: 0;">${blockingReasons.map(r => `<li>${r}</li>`).join("")}</ul>`
          : "Route rejected by safety governor thresholds.";
      } else if (safetyDecision === "WARN" || safetyDecision === "DEGRADED") {
        safetyDetailsBox.classList.add("warn");
        safetyTitle.textContent = `⚠️ Safety Governor Verdict: ${safetyDecision}`;
        safetyMessages.innerHTML = warnings.length
          ? `<strong>Advisories / Warnings:</strong><ul style="margin: 4px 0 0 16px; padding: 0;">${warnings.map(w => `<li>${w}</li>`).join("")}</ul>`
          : "Route cleared with precautionary advisories.";
      } else {
        safetyDetailsBox.classList.add("allow");
        safetyTitle.textContent = "✅ Safety Governor Verdict: ALLOW (Cleared)";
        safetyMessages.textContent = "All nautical safety checks and constraint envelopes passed.";
      }
    }

    // Update Top Telemetry HUD
    const speed = routeData.summary.vessel_speed_knots || (state.activeRoute && state.activeRoute.vessel && state.activeRoute.vessel.speed_knots) || 12.0;
    document.getElementById("hudSpeed").innerHTML = `${speed} <small>kts</small>`;
    document.getElementById("hudDistance").innerHTML = `${routeData.summary.total_distance_nm || routeData.summary.distance_nm} <small>NM</small>`;
    document.getElementById("hudEta").textContent = formatMinutesToHhMm(routeData.summary.estimated_time_minutes);
    document.getElementById("hudStatus").textContent = safetyDecision === "REJECT" ? "REJECTED" : "ROUTE READY";

    // Draw Route Polyline
    if (routePolyline) map.removeLayer(routePolyline);
    waypointMarkersLayer.clearLayers();

    const latlngs = routeData.waypoints.map((wp) => [wp.latitude, wp.longitude]);
    const routeColor = safetyDecision === "REJECT" ? "#ef4444" : safetyDecision === "WARN" ? "#f59e0b" : "#00e5ff";
    routePolyline = L.polyline(latlngs, {
      color: routeColor,
      weight: 4,
      opacity: 0.85,
      dashArray: "8, 6",
    }).addTo(map);

    // Plot waypoint markers
    routeData.waypoints.forEach((wp, idx) => {
      if (idx > 0 && idx < routeData.waypoints.length - 1) {
        L.circleMarker([wp.latitude, wp.longitude], {
          radius: 5,
          color: routeColor,
          fillColor: "#0a1424",
          fillOpacity: 0.9,
          weight: 2,
        }).addTo(waypointMarkersLayer).bindPopup(`<b>Waypoint #${idx}</b><br>${wp.latitude}, ${wp.longitude}`);
      }
    });

    fitMapToActiveRoute();
  }

  // ===========================================================================
  // TRIP & VOYAGE TRACKING (STEP 6 & 7)
  // ===========================================================================

  function initTripControls() {
    document.getElementById("quickStartTripBtn").addEventListener("click", () => {
      startTripFromCurrentForm();
    });

    document.getElementById("stopTripBtn").addEventListener("click", async () => {
      if (!state.activeTrip) return;
      try {
        const tripId = state.activeTrip.trip_id;
        const res = await apiRequest(`/trips/${tripId}/stop`, { method: "POST" });
        state.activeTrip = null;
        updateTripUI(null);
        showToast(`Trip ${tripId} stopped and marked completed.`, "success");
      } catch (err) {
        showToast(`Failed to stop trip: ${err.message}`, "error");
      }
    });

    // Manual GPS Update
    document.getElementById("sendManualGpsBtn").addEventListener("click", async () => {
      if (!state.activeTrip) {
        showToast("No active trip to update.", "error");
        return;
      }
      const lat = parseFloat(document.getElementById("gpsUpdateLat").value);
      const lon = parseFloat(document.getElementById("gpsUpdateLon").value);
      if (isNaN(lat) || isNaN(lon)) {
        showToast("Please enter valid GPS coordinates.", "error");
        return;
      }
      await sendGpsUpdate(lat, lon);
    });

    // Step 10% forward along route
    document.getElementById("stepAlongRouteBtn").addEventListener("click", async () => {
      if (!state.activeTrip || !state.activeRoute || !state.activeRoute.waypoints.length) {
        showToast("Calculate a route and start a trip first.", "error");
        return;
      }
      state.simulatedIndex = Math.min(state.simulatedIndex + 1, state.activeRoute.waypoints.length - 1);
      const wp = state.activeRoute.waypoints[state.simulatedIndex];
      await sendGpsUpdate(wp.latitude, wp.longitude);
    });

    // Toggle live browser GPS tracking
    const liveGpsBtn = document.getElementById("toggleLiveBrowserGpsBtn");
    liveGpsBtn.addEventListener("click", () => {
      if (state.watchGpsId !== null) {
        navigator.geolocation.clearWatch(state.watchGpsId);
        state.watchGpsId = null;
        liveGpsBtn.textContent = "🌐 Stream Browser GPS";
        showToast("Stopped streaming browser GPS", "info");
      } else {
        if (!navigator.geolocation) {
          showToast("Geolocation not available", "error");
          return;
        }
        state.watchGpsId = navigator.geolocation.watchPosition(
          async (pos) => {
            const lat = Number(pos.coords.latitude.toFixed(6));
            const lon = Number(pos.coords.longitude.toFixed(6));
            document.getElementById("gpsUpdateLat").value = lat;
            document.getElementById("gpsUpdateLon").value = lon;
            updateGpsStatusBadge(lat, lon);
            if (state.activeTrip) await sendGpsUpdate(lat, lon);
          },
          (err) => showToast(`GPS Error: ${err.message}`, "error"),
          { enableHighAccuracy: true }
        );
        liveGpsBtn.textContent = "⏹ Stop Streaming GPS";
        showToast("Streaming browser GPS live...", "success");
      }
    });

    // Toggle Auto-Simulation
    const simBtn = document.getElementById("toggleSimulatedVoyageBtn");
    simBtn.addEventListener("click", () => {
      if (state.simulationInterval) {
        clearInterval(state.simulationInterval);
        state.simulationInterval = null;
        simBtn.textContent = "⚡ Auto-Simulate Voyage";
        showToast("Simulation paused", "info");
      } else {
        if (!state.activeTrip || !state.activeRoute) {
          showToast("Start a trip with a calculated route first", "error");
          return;
        }
        state.simulationInterval = setInterval(async () => {
          if (!state.activeTrip || !state.activeRoute) {
            clearInterval(state.simulationInterval);
            return;
          }
          if (state.simulatedIndex < state.activeRoute.waypoints.length - 1) {
            state.simulatedIndex++;
            const wp = state.activeRoute.waypoints[state.simulatedIndex];
            await sendGpsUpdate(wp.latitude, wp.longitude);
          } else {
            clearInterval(state.simulationInterval);
            state.simulationInterval = null;
            simBtn.textContent = "⚡ Auto-Simulate Voyage";
            showToast("Voyage reached destination!", "success");
          }
        }, 2500);
        simBtn.textContent = "⏸ Pause Simulation";
        showToast("Simulation running (updating GPS every 2.5s)...", "success");
      }
    });
  }

  async function startTripFromCurrentForm() {
    const sLat = parseFloat(document.getElementById("startLat").value);
    const sLon = parseFloat(document.getElementById("startLon").value);
    const dLat = parseFloat(document.getElementById("destLat").value);
    const dLon = parseFloat(document.getElementById("destLon").value);
    const speed = parseFloat(document.getElementById("vesselSpeed").value);

    if (isNaN(sLat) || isNaN(sLon) || isNaN(dLat) || isNaN(dLon)) {
      showToast("Please enter valid start and destination coordinates.", "error");
      return;
    }

    const payload = {
      start: { latitude: sLat, longitude: sLon },
      destination: { latitude: dLat, longitude: dLon },
      vessel: { speed_knots: speed || 12.5 },
      waypoints: state.activeRoute ? state.activeRoute.waypoints : [],
      arrival_threshold_nm: 0.2,
    };

    try {
      showToast("Initializing new voyage...", "info");
      const trip = await apiRequest("/trips/start", {
        method: "POST",
        body: JSON.stringify(payload),
      });

      state.activeTrip = trip;
      state.simulatedIndex = 0;
      updateTripUI(trip);
      document.getElementById("tabTripBtn").click();
      showToast(`Trip ${trip.trip_id} started!`, "success");
    } catch (err) {
      showToast(`Failed to start trip: ${err.message}`, "error");
    }
  }

  async function sendGpsUpdate(lat, lon) {
    if (!state.activeTrip) return;
    const tripId = state.activeTrip.trip_id;

    // Check if return navigation is active
    const isReturn = state.activeTrip.return_navigation_state &&
                     state.activeTrip.return_navigation_state.status === "returning";

    const endpoint = isReturn ? `/trips/${tripId}/return/update` : `/trips/${tripId}/update`;

    const payload = {
      current_position: { latitude: lat, longitude: lon },
      timestamp: new Date().toISOString(),
    };

    try {
      if (isReturn) {
        const retState = await apiRequest(endpoint, { method: "POST", body: JSON.stringify(payload) });
        state.returnState = retState;
        renderReturnState(retState);
      } else {
        const updatedTrip = await apiRequest(endpoint, { method: "POST", body: JSON.stringify(payload) });
        state.activeTrip = updatedTrip;
        updateTripUI(updatedTrip);
      }

      // Update Vessel Pin & Track Line
      updateVesselMarker(lat, lon, state.activeTrip.navigation_state ? state.activeTrip.navigation_state.bearing_degrees : 0);
      drawTrackPoints(state.activeTrip.track_points || []);
    } catch (err) {
      showToast(`GPS Update failed: ${err.message}`, "error");
    }
  }

  function updateTripUI(trip) {
    const noActive = document.getElementById("noActiveTripView");
    const activeView = document.getElementById("activeTripView");
    const tripBadge = document.getElementById("tripStateBadge");
    const tripPill = document.getElementById("activeTripPill");

    if (!trip || trip.status !== "active") {
      noActive.classList.remove("hidden");
      activeView.classList.add("hidden");
      tripBadge.textContent = "NO ACTIVE TRIP";
      tripBadge.className = "badge";
      tripPill.classList.add("hidden");
      return;
    }

    noActive.classList.add("hidden");
    activeView.classList.remove("hidden");
    tripBadge.textContent = "VOYAGE ACTIVE";
    tripBadge.className = "badge badge-success";
    tripPill.classList.remove("hidden");
    document.getElementById("activeTripLabel").textContent = `Trip: ${trip.trip_id.slice(-8)}`;

    document.getElementById("activeTripId").textContent = trip.trip_id;
    document.getElementById("tripTravelledKm").textContent = `${trip.distance_travelled_km} km`;
    document.getElementById("tripTravelledNm").textContent = `${trip.distance_travelled_nm} NM`;
    document.getElementById("tripTrackCount").textContent = `${trip.track_points_count} Points`;

    if (trip.navigation_state) {
      const nav = trip.navigation_state;
      document.getElementById("tripRemainingNm").textContent = `${nav.remaining_distance_nm} NM`;
      document.getElementById("tripBearing").textContent = `${nav.bearing_degrees}°`;
      document.getElementById("tripProgressPercent").textContent = `${nav.progress_percent}%`;
      document.getElementById("tripProgressBar").style.width = `${nav.progress_percent}%`;
      document.getElementById("tripEtaMinutes").textContent = `${nav.estimated_time_remaining_minutes} mins`;

      // Top HUD update
      document.getElementById("hudBearing").textContent = `${nav.bearing_degrees}°`;
      document.getElementById("hudDistance").innerHTML = `${nav.remaining_distance_nm} <small>NM</small>`;
      document.getElementById("hudEta").textContent = formatMinutesToHhMm(nav.estimated_time_remaining_minutes);
      document.getElementById("hudStatus").textContent = nav.status.toUpperCase();
    }
  }

  function drawTrackPoints(trackPoints) {
    if (trackPolyline) map.removeLayer(trackPolyline);
    if (!trackPoints || trackPoints.length < 2) return;

    const latlngs = trackPoints.map((tp) => [tp.latitude, tp.longitude]);
    trackPolyline = L.polyline(latlngs, {
      color: "#10b981",
      weight: 3,
      opacity: 0.9,
    }).addTo(map);
  }

  // ===========================================================================
  // RETURN NAVIGATION (STEP 8)
  // ===========================================================================

  function initReturnControls() {
    const radioStart = document.getElementById("returnModeStart");
    const radioHarbour = document.getElementById("returnModeHarbour");
    const harbourContainer = document.getElementById("harbourInputContainer");

    radioStart.addEventListener("change", () => {
      harbourContainer.classList.add("hidden");
    });
    radioHarbour.addEventListener("change", () => {
      harbourContainer.classList.remove("hidden");
    });

    document.getElementById("startReturnBtn").addEventListener("click", async () => {
      if (!state.activeTrip) {
        showToast("Must have an active voyage to initiate return navigation.", "error");
        return;
      }

      const tripId = state.activeTrip.trip_id;
      const mode = radioHarbour.checked ? "harbour" : "start";

      const payload = { mode };
      if (mode === "harbour") {
        const hLat = parseFloat(document.getElementById("harbourLat").value);
        const hLon = parseFloat(document.getElementById("harbourLon").value);
        if (isNaN(hLat) || isNaN(hLon)) {
          showToast("Please specify valid harbour coordinates.", "error");
          return;
        }
        payload.harbour = { latitude: hLat, longitude: hLon };
      }

      try {
        showToast(`Initiating return to ${mode}...`, "info");
        const retState = await apiRequest(`/trips/${tripId}/return/start`, {
          method: "POST",
          body: JSON.stringify(payload),
        });

        state.returnState = retState;
        renderReturnState(retState);
        showToast(`Switched to Return Navigation (${mode})!`, "success");
      } catch (err) {
        showToast(`Return initiation failed: ${err.message}`, "error");
      }
    });

    document.getElementById("cancelReturnBtn").addEventListener("click", async () => {
      if (!state.activeTrip) return;
      const tripId = state.activeTrip.trip_id;

      try {
        await apiRequest(`/trips/${tripId}/return/cancel`, { method: "POST" });
        state.returnState = null;
        document.getElementById("returnTelemetryCard").classList.add("hidden");
        document.getElementById("returnStatusBadge").textContent = "CANCELLED";
        if (returnPolyline) map.removeLayer(returnPolyline);
        showToast("Return navigation cancelled.", "info");
      } catch (err) {
        showToast(`Failed to cancel return: ${err.message}`, "error");
      }
    });
  }

  function renderReturnState(retState) {
    const card = document.getElementById("returnTelemetryCard");
    card.classList.remove("hidden");

    document.getElementById("retNavStateBadge").textContent = retState.status.toUpperCase();
    document.getElementById("retTargetCoord").textContent = `${retState.return_destination.latitude}, ${retState.return_destination.longitude}`;
    document.getElementById("retDistNm").textContent = `${retState.remaining_distance_nm} NM`;
    document.getElementById("retDistKm").textContent = `${retState.remaining_distance_km} km`;
    document.getElementById("retBearing").textContent = `${retState.bearing_degrees}°`;
    document.getElementById("retEta").textContent = `${retState.estimated_time_remaining_minutes} mins`;
    document.getElementById("retProgressPercent").textContent = `${retState.progress_percent}%`;
    document.getElementById("retProgressBar").style.width = `${retState.progress_percent}%`;

    // Draw return vector line
    if (returnPolyline) map.removeLayer(returnPolyline);
    const returnCoords = [
      [retState.current_position.latitude, retState.current_position.longitude],
      [retState.return_destination.latitude, retState.return_destination.longitude],
    ];
    returnPolyline = L.polyline(returnCoords, {
      color: "#f59e0b",
      weight: 4,
      dashArray: "6, 8",
    }).addTo(map);
  }

  // ===========================================================================
  // TRIP HISTORY (STEP 7)
  // ===========================================================================

  function initHistoryControls() {
    document.getElementById("refreshHistoryBtn").addEventListener("click", loadTripHistory);
    document.getElementById("historyStatusFilter").addEventListener("change", loadTripHistory);
  }

  async function loadTripHistory() {
    const listEl = document.getElementById("tripHistoryList");
    const status = document.getElementById("historyStatusFilter").value;
    listEl.innerHTML = '<div class="loading-spinner-box">Loading saved trips...</div>';

    try {
      const endpoint = status ? `/trips?status=${status}` : "/trips";
      const data = await apiRequest(endpoint);

      if (!data.trips || data.trips.length === 0) {
        listEl.innerHTML = '<div class="empty-state-box"><p>No recorded voyages found.</p></div>';
        return;
      }

      listEl.innerHTML = data.trips
        .map((t) => `
        <div class="history-item">
          <div class="item-header">
            <span class="item-id">${t.trip_id}</span>
            <span class="badge ${t.status === "active" ? "badge-success" : ""}">${t.status.toUpperCase()}</span>
          </div>
          <div class="item-grid">
            <div><strong>Dist:</strong> ${t.distance_travelled_km} km (${t.distance_travelled_nm} NM)</div>
            <div><strong>Time:</strong> ${t.elapsed_time_minutes} min</div>
            <div><strong>Points:</strong> ${t.track_points_count}</div>
            <div><strong>Started:</strong> ${new Date(t.started_at).toLocaleTimeString()}</div>
          </div>
          <div class="item-actions">
            <button type="button" class="btn btn-secondary btn-sm" onclick="window.viewTripTrack('${t.trip_id}')">🗺️ Track on Map</button>
            <button type="button" class="btn btn-danger btn-sm" onclick="window.deleteTripRecord('${t.trip_id}')">🗑️ Delete</button>
          </div>
        </div>
      `)
        .join("");
    } catch (err) {
      listEl.innerHTML = `<div class="empty-state-box" style="color:#ef4444;"><p>Error loading history: ${err.message}</p></div>`;
    }
  }

  window.viewTripTrack = async function (tripId) {
    try {
      showToast(`Loading track for ${tripId}...`, "info");
      const trackData = await apiRequest(`/trips/${tripId}/track`);
      if (trackData.track_points && trackData.track_points.length > 0) {
        drawTrackPoints(trackData.track_points);
        const latlngs = trackData.track_points.map((tp) => [tp.latitude, tp.longitude]);
        map.fitBounds(L.latLngBounds(latlngs), { padding: [40, 40] });
        showToast(`Plotted ${trackData.track_points.length} track points on map.`, "success");
      } else {
        showToast("No track points recorded for this voyage.", "warning");
      }
    } catch (err) {
      showToast(`Failed to load track: ${err.message}`, "error");
    }
  };

  window.deleteTripRecord = async function (tripId) {
    if (!confirm(`Are you sure you want to delete trip ${tripId}?`)) return;
    try {
      await apiRequest(`/trips/${tripId}`, { method: "DELETE" });
      showToast(`Deleted trip ${tripId}`, "success");
      loadTripHistory();
    } catch (err) {
      showToast(`Delete failed: ${err.message}`, "error");
    }
  };

  // ===========================================================================
  // MARINE GEOGRAPHY EXPLORER & REAL MARINE LAYERS (STEP 9, 11 & 12)
  // ===========================================================================

  const marineLayers = {
    port: null,
    harbour: null,
    landing_centre: null,
    lighthouse: null,
    bathymetry: null,
    restricted_area: null,
    nearby: null,
  };

  function initGeographyControls() {
    marineLayers.port = L.layerGroup();
    marineLayers.harbour = L.layerGroup();
    marineLayers.landing_centre = L.layerGroup();
    marineLayers.lighthouse = L.layerGroup();
    marineLayers.bathymetry = L.layerGroup();
    marineLayers.restricted_area = L.layerGroup();
    marineLayers.nearby = L.layerGroup().addTo(map);

    document.getElementById("refreshGeographyBtn").addEventListener("click", loadGeographyDatasets);

    // Layer Checkbox Toggles
    const toggleBindings = [
      { id: "layerTogglePorts", type: "port" },
      { id: "layerToggleHarbours", type: "harbour" },
      { id: "layerToggleLandingCentres", type: "landing_centre" },
      { id: "layerToggleLighthouses", type: "lighthouse" },
      { id: "layerToggleBathymetry", type: "bathymetry" },
      { id: "layerToggleRestrictedAreas", type: "restricted_area" },
    ];

    toggleBindings.forEach(({ id, type }) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("change", (e) => {
          toggleMarineLayer(type, e.target.checked);
        });
      }
    });

    // Nearby Search Handlers
    const searchBtn = document.getElementById("searchNearbyBtn");
    if (searchBtn) {
      searchBtn.addEventListener("click", searchNearbyMarineFacilities);
    }

    const useStartNearbyBtn = document.getElementById("useStartNearbyBtn");
    if (useStartNearbyBtn) {
      useStartNearbyBtn.addEventListener("click", () => {
        const sLat = document.getElementById("startLat").value;
        const sLon = document.getElementById("startLon").value;
        if (sLat && sLon) {
          document.getElementById("nearbyLat").value = sLat;
          document.getElementById("nearbyLon").value = sLon;
          showToast(`Set scan origin to start point: [${sLat}, ${sLon}]`, "info");
        }
      });
    }
  }

  async function toggleMarineLayer(featureType, isChecked) {
    const layer = marineLayers[featureType];
    if (!layer) return;

    if (!isChecked) {
      map.removeLayer(layer);
      layer.clearLayers();
      return;
    }

    try {
      const data = await apiRequest(`/geography/features/type/${featureType}?limit=500`);
      layer.clearLayers();

      if (!data.features || data.features.length === 0) {
        if (featureType === "bathymetry") {
          showToast("Bathymetry data: Pending official dataset", "info");
        } else if (featureType === "restricted_area") {
          showToast("Restricted-area data: Pending official dataset", "info");
        } else {
          showToast(`0 ${featureType.replace('_', ' ')} records in database (official dataset pending ingestion).`, "info");
        }
        map.removeLayer(layer);
        return;
      }

      const icons = {
        port: { color: "#38bdf8", emoji: "🚢", name: "Port" },
        harbour: { color: "#34d399", emoji: "⚓", name: "Harbour" },
        landing_centre: { color: "#fbbf24", emoji: "🐟", name: "Landing Centre" },
        lighthouse: { color: "#f87171", emoji: "🚨", name: "Lighthouse" },
        bathymetry: { color: "#818cf8", emoji: "🌊", name: "Bathymetry" },
        restricted_area: { color: "#f43f5e", emoji: "🚫", name: "Restricted Area" },
      };
      const cfg = icons[featureType] || { color: "#38bdf8", emoji: "📍", name: "Marine Feature" };

      data.features.forEach((f) => {
        if (!f.geometry) return;
        const gType = f.geometry.type;

        if (gType === "Point") {
          const coords = f.geometry.coordinates;
          if (!Array.isArray(coords) || coords.length < 2) return;
          const [lon, lat] = coords;

          const depthVal = f.properties.depth_meters || f.properties.depth || f.properties.sounding;
          const depthHtml = depthVal !== undefined ? `<div><strong>Depth:</strong> ${depthVal} m</div>` : "";
          const restrType = f.properties.restriction_type || f.properties.type || "-";
          const restrHtml = featureType === "restricted_area" ? `<div><strong>Restriction:</strong> ${restrType}</div>` : "";

          const marker = L.circleMarker([lat, lon], {
            radius: 6,
            color: cfg.color,
            fillColor: cfg.color,
            fillOpacity: 0.85,
            weight: 2,
          });

          marker.bindPopup(`
            <div style="font-family: var(--font-sans); color: #0a1424; min-width: 180px;">
              <div style="font-weight: bold; font-size: 13px; border-bottom: 1px solid #ccc; padding-bottom: 4px;">
                ${cfg.emoji} ${f.name || f.feature_id}
              </div>
              <div style="font-size: 11px; margin-top: 4px; line-height: 1.4;">
                <div><strong>Category:</strong> ${cfg.name}</div>
                ${restrHtml}
                ${depthHtml}
                <div><strong>Coordinates:</strong> ${lat.toFixed(4)}, ${lon.toFixed(4)}</div>
                <div><strong>Source:</strong> ${f.source}</div>
                <div><strong>Updated:</strong> ${f.source_updated_at ? new Date(f.source_updated_at).toLocaleDateString() : 'Official'}</div>
              </div>
            </div>
          `);

          layer.addLayer(marker);

        } else if (gType === "Polygon" || gType === "MultiPolygon") {
          // Render authoritative polygon features
          const geoJsonFeature = {
            type: "Feature",
            geometry: f.geometry,
            properties: f.properties,
          };

          const polyStyle = featureType === "restricted_area" ? {
            color: "#f43f5e",
            weight: 2,
            fillColor: "#f43f5e",
            fillOpacity: 0.25,
            dashArray: "4, 4",
          } : {
            color: "#818cf8",
            weight: 2,
            fillColor: "#6366f1",
            fillOpacity: 0.2,
          };

          const polyLayer = L.geoJSON(geoJsonFeature, {
            style: polyStyle,
            onEachFeature: (feature, l) => {
              const depthVal = f.properties.depth_meters || f.properties.depth || f.properties.contour;
              const depthHtml = depthVal !== undefined ? `<div><strong>Depth:</strong> ${depthVal} m</div>` : "";
              const restrType = f.properties.restriction_type || f.properties.type || "Restricted Marine Zone";
              const restrHtml = featureType === "restricted_area" ? `<div><strong>Restriction Type:</strong> ${restrType}</div>` : "";

              l.bindPopup(`
                <div style="font-family: var(--font-sans); color: #0a1424; min-width: 200px;">
                  <div style="font-weight: bold; font-size: 13px; border-bottom: 1px solid #ccc; padding-bottom: 4px; color: ${polyStyle.color};">
                    ${cfg.emoji} ${f.name || f.feature_id}
                  </div>
                  <div style="font-size: 11px; margin-top: 4px; line-height: 1.4;">
                    <div><strong>Category:</strong> ${cfg.name}</div>
                    ${restrHtml}
                    ${depthHtml}
                    <div><strong>Source:</strong> ${f.source}</div>
                    <div><strong>Last Updated:</strong> ${f.source_updated_at ? new Date(f.source_updated_at).toLocaleDateString() : 'Official'}</div>
                  </div>
                </div>
              `);
            },
          });

          layer.addLayer(polyLayer);
        }
      });

      layer.addTo(map);
      showToast(`Plotted ${data.features.length} ${cfg.name} features on map.`, "success");
    } catch (err) {
      showToast(`Failed to load ${featureType} layer: ${err.message}`, "error");
    }
  }

  window.setCoordinateFromMap = function (target, lat, lon) {
    if (target === "dest") {
      document.getElementById("destLat").value = lat;
      document.getElementById("destLon").value = lon;
      updateDestMarker(lat, lon);
      showToast(`📍 Destination set to: [${lat}, ${lon}]`, "info");
    } else if (target === "harbour") {
      document.getElementById("harbourLat").value = lat;
      document.getElementById("harbourLon").value = lon;
      updateHarbourMarker(lat, lon);
      showToast(`🏛️ Harbour target set to: [${lat}, ${lon}]`, "info");
    }
  };

  async function searchNearbyMarineFacilities() {
    const lat = parseFloat(document.getElementById("nearbyLat").value);
    const lon = parseFloat(document.getElementById("nearbyLon").value);
    const fType = document.getElementById("nearbyType").value;
    const radius = parseFloat(document.getElementById("nearbyRadius").value) || 50;

    if (isNaN(lat) || isNaN(lon)) {
      showToast("Please enter valid search coordinates.", "error");
      return;
    }

    const container = document.getElementById("nearbyResultsContainer");
    const listEl = document.getElementById("nearbyList");
    const badgeEl = document.getElementById("nearbyCountBadge");

    container.classList.remove("hidden");
    listEl.innerHTML = '<div class="loading-spinner-box">Scanning nearby facilities...</div>';

    try {
      let queryUrl = `/geography/nearby?latitude=${lat}&longitude=${lon}&radius_km=${radius}&limit=100`;
      if (fType) {
        queryUrl += `&feature_type=${fType}`;
      }

      const data = await apiRequest(queryUrl);
      badgeEl.textContent = `${data.total} Found`;

      if (marineLayers.nearby) {
        marineLayers.nearby.clearLayers();
        // Add search radius circle
        L.circle([lat, lon], {
          radius: radius * 1000,
          color: "#00e5ff",
          fillColor: "#00e5ff",
          fillOpacity: 0.08,
          weight: 1,
          dashArray: "4, 6",
        }).addTo(marineLayers.nearby);
      }

      if (!data.features || data.features.length === 0) {
        listEl.innerHTML = `<div class="empty-state-box"><p>No ${fType || "marine"} facilities found within ${radius} km radius (0 records in database).</p></div>`;
        return;
      }

      listEl.innerHTML = data.features
        .map((item) => {
          const f = item.feature;
          return `
          <div class="nearby-item" onclick="map.setView([${item.feature.geometry.coordinates[1]}, ${item.feature.geometry.coordinates[0]}], 10);">
            <div class="nearby-item-header">
              <span class="nearby-item-title">${f.name || f.feature_id}</span>
              <span class="nearby-item-dist">${item.distance_km.toFixed(1)} km <small>(${item.distance_nm.toFixed(1)} NM)</small></span>
            </div>
            <div class="nearby-item-meta">
              <span>Category: ${f.feature_type.toUpperCase()}</span>
              <span>Bearing: ${item.bearing_degrees.toFixed(0)}°</span>
            </div>
          </div>
        `;
        })
        .join("");

      showToast(`Found ${data.total} marine facilities within ${radius} km.`, "success");
    } catch (err) {
      listEl.innerHTML = `<div class="empty-state-box" style="color:#ef4444;"><p>Scan error: ${err.message}</p></div>`;
    }
  }

  async function loadGeographyDatasets() {
    const listEl = document.getElementById("geographyDatasetList");
    listEl.innerHTML = '<div class="loading-spinner-box">Loading registered datasets...</div>';

    try {
      const data = await apiRequest("/geography/datasets");
      if (!data.datasets || data.datasets.length === 0) {
        listEl.innerHTML = '<div class="empty-state-box"><p>No registered datasets found.</p></div>';
        return;
      }

      listEl.innerHTML = data.datasets
        .map((d) => `
        <div class="dataset-item">
          <div class="item-header">
            <span class="item-id">${d.name}</span>
            <span class="badge">${d.feature_type.toUpperCase()}</span>
          </div>
          <div class="item-grid">
            <div><strong>ID:</strong> ${d.dataset_id}</div>
            <div><strong>Features:</strong> ${d.feature_count}</div>
            <div><strong>Source:</strong> ${d.source}</div>
            <div><strong>Version:</strong> ${d.version}</div>
          </div>
        </div>
      `)
        .join("");
    } catch (err) {
      listEl.innerHTML = `<div class="empty-state-box" style="color:#ef4444;"><p>Error loading datasets: ${err.message}</p></div>`;
    }
  }

  // ===========================================================================
  // LOGS DRAWER & HUD UTILITIES
  // ===========================================================================

  function initDrawer() {
    const drawer = document.getElementById("logsDrawer");
    const toggle = document.getElementById("drawerToggle");
    toggle.addEventListener("click", () => {
      drawer.classList.toggle("open");
    });
  }

  function logApiCall(header, payload) {
    const code = document.getElementById("liveLogCode");
    const timestamp = new Date().toLocaleTimeString();
    const str = `\n[${timestamp}] ▶ ${header}\n${payload ? JSON.stringify(payload, null, 2) : ""}`;
    code.textContent = str + "\n" + code.textContent.slice(0, 3000);
  }

  function logApiResponse(header, payload) {
    const code = document.getElementById("liveLogCode");
    const timestamp = new Date().toLocaleTimeString();
    const str = `\n[${timestamp}] ◀ ${header}\n${payload ? JSON.stringify(payload, null, 2) : ""}`;
    code.textContent = str + "\n" + code.textContent.slice(0, 3000);
  }

  function updateGpsStatusBadge(lat, lon) {
    const dot = document.getElementById("gpsStatusDot");
    const label = document.getElementById("gpsStatusText");
    dot.className = "status-dot active";
    label.textContent = `GPS: [${lat.toFixed(2)}, ${lon.toFixed(2)}]`;
  }

  function formatMinutesToHhMm(mins) {
    if (!mins || isNaN(mins) || mins <= 0) return "--:--";
    const totalM = Math.round(mins);
    const h = Math.floor(totalM / 60);
    const m = totalM % 60;
    return `${h}h ${m}m`;
  }

  function showToast(message, type = "info") {
    const container = document.getElementById("toastContainer");
    const toast = document.createElement("div");
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = "0";
      setTimeout(() => toast.remove(), 300);
    }, 3500);
  }
})();
