/* Mudwatch: static front end. All numbers come from site/data/, built by pipeline/. */
(async function () {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Math.round(n).toLocaleString("en-US");
  const pct = (x) => Math.round(x * 100) + "%";
  const acres = (km2) => fmt(km2 * 247.105);
  const NEVER = 255;
  const CINDER = "#e5482d", BONE = "#f4f4f5";
  const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const day = (iso) => `${MONTHS[+iso.slice(5, 7) - 1]} ${+iso.slice(8, 10)}`;
  const daysBetween = (a, b) => Math.round((Date.parse(b) - Date.parse(a)) / 864e5);
  const loadJson = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(u); return r.json(); });
  const loadImage = async (u) => { const im = new Image(); im.src = u; await im.decode(); return im; };

  // Which fire: ?fire=<id> in the address, otherwise the first one built.
  const fires = await loadJson("data/fires.json");
  const asked = new URLSearchParams(location.search).get("fire");
  const fid = fires.some((f) => f.id === asked) ? asked : fires[0].id;
  const D = `data/${fid}/`;
  const [fire, blocks, homes, perimeter, basins, segments, routes, clearPts, layersImg, terrainImg] = await Promise.all([
    loadJson(D + "fire.json"), loadJson(D + "blocks.geojson"), loadJson(D + "homes.geojson"), loadJson(D + "perimeter.geojson"),
    loadJson(D + "usgs_basins.geojson"), loadJson(D + "usgs_segments.geojson"), loadJson(D + "routes.geojson"), loadJson(D + "clear_points.geojson"), loadImage(D + "layers.png"), loadImage(D + "terrain.png"),
  ]);
  const T = fire.timeline, K = T.length, tot = fire.totals, C = fire.usgs_check, N = fire.nisar && fire.nisar.ok ? fire.nisar : null;
  const byId = new Map(blocks.features.map((f) => [f.properties.id, f.properties]));
  const homesOf = new Map();   // block id -> pass index of each home in a path
  for (const f of homes.features) if (f.properties.k >= 0) (homesOf.get(f.properties.b) || homesOf.set(f.properties.b, []).get(f.properties.b)).push(f.properties.k);
  const SAT = { S1A: "Sentinel-1A", S1C: "Sentinel-1C", S1D: "Sentinel-1D" };
  const ICON = {
    play: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4 2.5v11l9.5-5.5z" fill="currentColor"/></svg>',
    shovel: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M10.5 2.5l3 3M12 4 7.2 8.8" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" fill="none"/><path d="M5.3 7.6 8.4 10.7 6.6 12.5c-1.2 1.2-3 1.3-3.9.9-.4-.9-.3-2.7.9-3.9z" fill="currentColor"/></svg>',
    out: '<svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true"><path d="M3 8h9M8.5 4.5 12 8l-3.5 3.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    pause: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3.5 2.5h3v11h-3zM9.5 2.5h3v11h-3z" fill="currentColor"/></svg>',
  };

  const WO = fire.ways_out, miles = (km) => (km * 0.621).toFixed(1);
  // Who is looking: a resident, or a first responder who also gets the clearing points. Remembered between visits.
  const store = { get: () => { try { return localStorage.getItem("mudwatch-role"); } catch (e) { return null; } }, set: (v) => { try { localStorage.setItem("mudwatch-role", v); } catch (e) { /* private window */ } } };
  const state = { role: store.get() === "responder" ? "responder" : "resident", view: "watch", idx: K - 1, fade: 100, layers: { burn: false, slope: false, people: false }, routes: false, selected: null, playing: null };
  const all = () => state.layers.burn && state.layers.slope && state.layers.people;
  document.title = `Mudwatch: ${fire.name}`;
  if (fires.length > 1) {
    $("place").innerHTML = `<label class="sr-only" for="fire-pick">Fire</label><select id="fire-pick">${fires.map((f) => `<option value="${f.id}"${f.id === fid ? " selected" : ""}>${f.name}</option>`).join("")}</select>`;
    $("fire-pick").onchange = (e) => (location.search = "?fire=" + e.target.value);
  } else {
    $("place").textContent = fire.name;
  }
  document.querySelectorAll('a[href="methods.html"]').forEach((a) => (a.href = "methods.html?fire=" + fid));
  $("tab-nisar").hidden = !N;
  if (tot.roads_in_zone.length) $("addr").placeholder = tot.roads_in_zone[0].name;

  /* ---------- map ---------- */
  const map = new maplibregl.Map({
    container: "map",
    style: "https://tiles.openfreemap.org/styles/dark",
    bounds: [fire.focus.slice(0, 2), fire.focus.slice(2)],
    fitBoundsOptions: { padding: 50 },
    maxBounds: [[fire.bounds[0] - 0.6, fire.bounds[1] - 0.4], [fire.bounds[2] + 0.6, fire.bounds[3] + 0.4]],
    attributionControl: { compact: true },
  });
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
  await new Promise((res) => map.on("load", res));
  // Tint the dark base map to zinc so the data carries the only colour.
  for (const l of map.getStyle().layers) {
    try {
      if (l.type === "background") map.setPaintProperty(l.id, "background-color", "#19191b");
      else if (l.type === "fill" && /water/.test(l.id)) map.setPaintProperty(l.id, "fill-color", "#0e0e10");
      else if (l.type === "fill" && /landuse|landcover|park|building|aeroway|pier/.test(l.id)) map.setPaintProperty(l.id, "fill-color", "#1c1c1f");
      else if (l.type === "line" && /water/.test(l.id)) map.setPaintProperty(l.id, "line-color", "#3f3f46");
      else if (l.type === "line" && /road|highway|motorway|bridge|tunnel|rail|aeroway/.test(l.id)) map.setPaintProperty(l.id, "line-color", /casing|subtle|path/.test(l.id) ? "rgba(255,255,255,0)" : "rgba(255,255,255,0.16)");
      else if (l.type === "line" && /boundary|admin/.test(l.id)) map.setPaintProperty(l.id, "line-color", "rgba(255,255,255,0.1)");
      else if (l.type === "symbol") {
        map.setPaintProperty(l.id, "text-color", /water/.test(l.id) ? "#71717a" : "#d4d4d8");
        map.setPaintProperty(l.id, "text-halo-color", "#151517");
      }
    } catch (e) { /* a layer without that property: leave it */ }
  }

  // The two data pictures share one grid. layers.png: R = pass that confirmed the burn, G = pass a cell
  // turned red, B = pass a mud path reached it. terrain.png: R = slope in degrees, G = hillshade.
  const W = layersImg.width, H = layersImg.height;
  const pixels = (img) => {
    const c = document.createElement("canvas");
    c.width = W; c.height = H;
    const x = c.getContext("2d", { willReadFrequently: true });
    x.drawImage(img, 0, 0);
    return x.getImageData(0, 0, W, H).data;
  };
  const L = pixels(layersImg), TR = pixels(terrainImg);
  const canvas = (id) => { const c = document.createElement("canvas"); c.width = W; c.height = H; c.id = id; return c; };
  const cv = canvas("cv-data"), ctx = cv.getContext("2d");
  const out = ctx.createImageData(W, H), out32 = new Uint32Array(out.data.buffer);
  const abgr = (r, g, b, a) => ((a << 24) | (b << 16) | (g << 8) | r) >>> 0;
  const ASH = abgr(212, 212, 216, 96), HATCH = abgr(244, 244, 245, 84), HATCH_SOFT = abgr(244, 244, 245, 26), RED = abgr(229, 72, 45, 225), PATH = abgr(229, 72, 45, 105);
  const [bw, bs, be, bn] = fire.bounds;
  const corners = [[bw, bn], [be, bn], [be, bs], [bw, bs]];

  // Hillshade: light and shadow as white and black washes over the base map. Drawn once.
  const rv = canvas("cv-relief");
  {
    const rx = rv.getContext("2d"), im = rx.createImageData(W, H), px = new Uint32Array(im.data.buffer);
    for (let i = 0, p = 1; i < px.length; i++, p += 4) {
      const s = TR[p] - 127, x = i % W, y = (i / W) | 0;
      const edge = Math.min(1, Math.min(x, y, W - 1 - x, H - 1 - y) / 40);   // feather the picture into the base map
      px[i] = s >= 0 ? abgr(255, 255, 255, Math.min(255, s * 0.5) * edge) : abgr(0, 0, 0, Math.min(255, -s * 1.0) * edge);
    }
    rx.putImageData(im, 0, 0);
  }

  function drawData() {
    const { burn, slope, people } = state.usgsLook ? { burn: false, slope: false, people: true } : state.layers;
    const showRed = state.usgsLook || (burn && slope), showPath = state.usgsLook || all();
    const idx = state.usgsLook ? K - 1 : state.idx, steepDeg = fire.steep_deg;
    for (let i = 0, p = 0, y = 0; y < H; y++) {
      for (let x = 0; x < W; x++, i++, p += 4) {
        let c = 0;
        if (burn && L[p] <= idx) c = ASH;
        if (slope && TR[p] >= steepDeg && (x + y) % 3 === 0) c = showPath ? HATCH_SOFT : HATCH;   // quiet once the red is on
        if (showRed && L[p + 1] <= idx) c = RED;
        else if (showPath && L[p + 2] <= idx) c = PATH;
        out32[i] = c;
      }
    }
    ctx.putImageData(out, 0, 0);
    const src = map.getSource("data");
    if (src) { src.play(); src.pause(); }
  }

  const firstLabel = map.getStyle().layers.find((l) => l.type === "symbol")?.id;
  const add = (layer) => map.addLayer(layer, firstLabel);
  const image = (id, url, c = corners) => {
    map.addSource(id, { type: "image", url, coordinates: c });
    add({ id, type: "raster", source: id, paint: { "raster-opacity": 0, "raster-fade-duration": 0, "raster-opacity-transition": { duration: 900 } } });
  };
  map.addSource("relief", { type: "canvas", canvas: rv, coordinates: corners, animate: false });
  add({ id: "relief", type: "raster", source: "relief", paint: { "raster-opacity": 0.9, "raster-fade-duration": 0 } });
  if (fire.optical && fire.optical.ok) { const [w, s, e, n] = fire.optical.bounds; image("optical", D + "optical.jpg", [[w, n], [e, n], [e, s], [w, s]]); }
  if (fire.radar_picture) image("radar", D + "radar.png");
  if (N) { image("nisar-before", D + "nisar_before.png"); image("nisar-after", D + "nisar_after.png"); }
  map.addSource("basins", { type: "geojson", data: basins });
  map.addSource("segments", { type: "geojson", data: segments });
  map.addSource("perimeter", { type: "geojson", data: perimeter });
  map.addSource("blocks", { type: "geojson", data: blocks, promoteId: "id" });
  map.addSource("homes", { type: "geojson", data: homes });
  add({ id: "basins", type: "fill", source: "basins", layout: { visibility: "none" }, paint: { "fill-color": BONE, "fill-opacity": ["match", ["get", "h"], 3, 0.46, 2, 0.24, 0.08] } });
  add({ id: "basins-line", type: "line", source: "basins", layout: { visibility: "none" }, paint: { "line-color": BONE, "line-opacity": 0.3, "line-width": 0.6 } });
  map.addSource("data", { type: "canvas", canvas: cv, coordinates: corners, animate: false });
  add({ id: "data", type: "raster", source: "data", paint: { "raster-opacity": 1, "raster-resampling": "nearest", "raster-fade-duration": 0 } });
  add({ id: "segments", type: "line", source: "segments", layout: { visibility: "none" }, filter: [">=", ["get", "h"], 2], paint: { "line-color": BONE, "line-width": ["match", ["get", "h"], 3, 2.4, 1.2], "line-opacity": 0.85 } });
  add({ id: "perimeter-case", type: "line", source: "perimeter", layout: { visibility: "none" }, paint: { "line-color": "#0e0e10", "line-width": 3.2, "line-opacity": 0.7 } });
  add({ id: "perimeter", type: "line", source: "perimeter", layout: { visibility: "none" }, paint: { "line-color": BONE, "line-width": 1.4, "line-dasharray": [3, 2], "line-opacity": 0.9 } });
  add({ id: "block-fill", type: "fill", source: "blocks", paint: { "fill-color": "#000", "fill-opacity": 0 } });
  add({ id: "block-line", type: "line", source: "blocks", paint: { "line-color": "#ffffff", "line-opacity": 0.1, "line-width": 0.6 } });
  // Ways out by road: white, and dashed where the road lies in a possible mud path.
  map.addSource("routes", { type: "geojson", data: routes });
  map.addLayer({ id: "routes-case", type: "line", source: "routes", layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": "#0e0e10", "line-width": 7, "line-opacity": 0.75 } });
  map.addLayer({ id: "routes", type: "line", source: "routes", filter: ["==", ["get", "cut"], 0], layout: { "line-cap": "round", "line-join": "round" }, paint: { "line-color": BONE, "line-width": 3.4 } });
  map.addLayer({ id: "routes-cut", type: "line", source: "routes", filter: ["==", ["get", "cut"], 1], paint: { "line-color": BONE, "line-width": 3.4, "line-dasharray": [0.9, 0.9] } });
  map.addLayer({ id: "homes", type: "circle", source: "homes", paint: { "circle-radius": 2 } });
  map.addLayer({ id: "block-selected", type: "line", source: "blocks", paint: { "line-color": BONE, "line-width": 3 }, filter: ["==", "id", ""] });
  // Homes in a possible mud path get a marker of their own, so they are the first thing anyone sees.
  const HOUSE = '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M8 2.2 1.8 7.6h1.7v5.9h3.3V9.9h2.4v3.6h3.3V7.6h1.7z" fill="currentColor"/></svg>';
  const pins = homes.features.filter((f) => f.properties.k >= 0).map((f) => {
    const el = document.createElement("button");
    el.type = "button"; el.className = "home-pin"; el.innerHTML = HOUSE;
    el.setAttribute("aria-label", "Home in a possible mud path. Open its block.");
    el.onclick = (ev) => { ev.stopPropagation(); stop(); select(f.properties.b); };
    new maplibregl.Marker({ element: el }).setLngLat(f.geometry.coordinates).addTo(map);
    return { el, k: f.properties.k, b: f.properties.b };
  });
  const exits = WO.routes.map((r) => {
    const el = document.createElement("button");
    el.type = "button"; el.className = "exit-pin"; el.innerHTML = `${ICON.out}<span>Way out: ${r.to || "main road"}</span>`;
    el.onclick = (ev) => { ev.stopPropagation(); stop(); showRoute(r.id); };
    new maplibregl.Marker({ element: el, anchor: "left", offset: [6, 0] }).setLngLat(r.end).addTo(map);
    return el;
  });
  // Clearing points, for first responders: where a mud channel crosses a public road.
  let popup;
  const clearPins = clearPts.features.map((f) => {
    const el = document.createElement("button");
    el.type = "button"; el.className = "clear-pin"; el.innerHTML = ICON.shovel;
    el.setAttribute("aria-label", `Clearing point ${f.properties.rank}, ${f.properties.road}`);
    el.onclick = (ev) => { ev.stopPropagation(); stop(); showClear(f.properties.rank); };
    new maplibregl.Marker({ element: el }).setLngLat(f.geometry.coordinates).addTo(map);
    return { el, f };
  });
  const show = (id, on) => map.getLayer(id) && map.setLayoutProperty(id, "visibility", on ? "visible" : "none");
  const fadeTo = (id, o) => map.getLayer(id) && map.setPaintProperty(id, "raster-opacity", o);

  /* ---------- rendering ---------- */
  function renderMap() {
    const usgs = state.view === "usgs", nisar = state.view === "nisar";
    state.usgsLook = usgs;
    show("data", !nisar);
    if (!nisar) drawData();
    for (const id of ["basins", "basins-line", "segments"]) show(id, usgs);
    show("perimeter", usgs || nisar);
    show("perimeter-case", nisar);
    fadeTo("nisar-before", nisar ? 1 : 0);
    fadeTo("nisar-after", nisar ? state.fade / 100 : 0);
    const people = !nisar && (usgs || state.layers.people);
    show("homes", people);
    show("block-line", people);
    const lit = usgs || all(), upto = usgs ? K - 1 : state.idx;
    for (const p of pins) {
      p.el.style.display = !nisar && lit && p.k <= upto ? "" : "none";
      p.el.classList.toggle("sel", p.b === state.selected);
    }
    const ways = state.view === "watch" && all() && state.routes;
    $("routes-toggle").setAttribute("aria-pressed", String(state.routes));
    $("routes-switch").hidden = state.view !== "watch";
    for (const id of ["routes-case", "routes", "routes-cut"]) show(id, ways);
    for (const el of exits) el.style.display = ways ? "" : "none";
    const clearing = state.view === "watch" && all() && state.role === "responder";
    for (const c of clearPins) c.el.style.display = clearing && state.role === "responder" && c.f.properties.k <= state.idx ? "" : "none";
    if (popup && !clearing) { popup.remove(); popup = null; }
    // Homes beside a path get a ring; every other home stays a quiet dot.
    const beside = ["all", ["==", ["get", "near"], 1], lit];
    map.setPaintProperty("homes", "circle-color", ["case", beside, "#18181b", "#a1a1aa"]);
    map.setPaintProperty("homes", "circle-opacity", ["case", beside, 1, 0.55]);
    map.setPaintProperty("homes", "circle-radius", ["interpolate", ["linear"], ["zoom"], 10, ["case", beside, 3, 1], 14, ["case", beside, 6, 2.6]]);
    map.setPaintProperty("homes", "circle-stroke-color", BONE);
    map.setPaintProperty("homes", "circle-stroke-width", ["case", beside, 1.6, 0]);
    map.setLayoutProperty("homes", "circle-sort-key", ["case", beside, 1, 0]);
  }

  const key = (style, label, cls = "") => `<div class="key"><span class="sw ${cls}" style="${style}"></span>${label}</div>`;
  function renderLegend() {
    const { burn, slope, people } = state.layers;
    let h;
    if (state.view === "nisar") {
      h = `<b>NISAR L-band radar, ${state.fade < 50 ? "before the fire" : "after the fire"}</b>
        ${key("background:linear-gradient(90deg,#18181b,#f4f4f5)", "Dark is a weak echo, bright a strong one")}
        ${key("border:1.5px dashed #f4f4f5", "Official burn perimeter")}
        <div class="src">${state.fade < 50 ? N.before_dates.map(day).join(" and ") : N.after_dates.map(day).join(" and ")}, 2026. Forest that burned goes dark.</div>`;
    } else if (state.view === "usgs") {
      h = `<b>White is USGS, red is this screen</b>
        ${key("background:rgba(244,244,245,0.46)", "USGS basin, High hazard")}
        ${key("background:rgba(244,244,245,0.24)", "USGS basin, Moderate")}
        ${key("background:rgba(244,244,245,0.08);box-shadow:inset 0 0 0 1px rgba(244,244,245,0.3)", "USGS basin, Low")}
        ${key("background:#e5482d", "Our red zone: burned and steep")}
        ${key("background:rgba(229,72,45,0.5)", "Our possible mud path")}
        <div class="src">USGS combined hazard for a storm peaking at ${C.design_storm_mm_h} mm per hour over 15 minutes.</div>`;
    } else {
      h = `<b>${all() ? "How to read this map" : "Layers switched on"}</b>`;
      if (all()) h += key("background:#e5482d;box-shadow:0 0 0 2px #fff", "Home that mud could reach", "dot") + key("background:#18181b;box-shadow:0 0 0 1.6px #f4f4f5", "Home right beside a path", "dot")
        + key("background:rgba(229,72,45,0.45)", "Path mud could take downhill");
      if (all() && state.routes && WO.routes.length) h += key("background:#f4f4f5;height:0.24rem;border-radius:2px", "Way out by road") + key("background:repeating-linear-gradient(90deg,#f4f4f5 0 4px,transparent 4px 8px);height:0.24rem;border-radius:0", "Way out that mud could cut");
      if (all() && state.role === "responder" && clearPts.features.length) h += key("background:#29292d;box-shadow:0 0 0 1.5px #f4f4f5;border-radius:3px", "Clearing point: mud path meets a road");
      if (burn && slope) h += key("background:#e5482d", "Burned and steep hillside");
      if (burn) h += key("background:rgba(212,212,216,0.4)", "Burned area, seen by radar");
      if (slope) h += key("background:repeating-linear-gradient(135deg,rgba(244,244,245,0.8) 0 1.5px,transparent 1.5px 5px)", `Steep ground (${fire.steep_deg}° or more)`);
      if (people) h += key("background:#a1a1aa", "Other homes", "dot");
      if (!burn && !slope && !people) h += `<div class="src">None yet. Use the three switches in the panel.</div>`;
    }
    $("legend").innerHTML = h;
  }

  function renderStack() {
    const { burn, slope, people } = state.layers, t = T[state.idx], when = day(t.date);
    for (const k of ["burn", "slope", "people"]) {
      document.querySelector(`.layer[data-layer="${k}"]`).setAttribute("aria-pressed", String(state.layers[k]));
      document.querySelector(`.p-${k}`).classList.toggle("on", state.layers[k]);
    }
    $("stack").classList.toggle("all", all());
    let s;
    if (all()) s = t.homes
      ? `All three line up: <b>red</b> hillsides burned and are steep, the lighter red is the way mud would run downhill, and <b>${t.homes} homes</b> sit in its way.`
      : `<b>Red</b> hillsides burned and are steep. By ${when} none had been confirmed above a home.`;
    else if (burn && slope) s = `<b>Red</b> is burned and steep: ${acres(t.red_km2)} acres by ${when}. Switch on Homes to see who is below.`;
    else if (burn && people) s = "Burned ground and homes. Switch on Steep ground to see which burned hills could slide.";
    else if (slope && people) s = "Steep ground and homes. Switch on Burned area to see which steep hills lost their cover.";
    else if (burn) s = t.scar_km2 ? `By ${when}, radar had confirmed ${acres(t.scar_km2)} acres of burn scar, through the smoke.` : `On ${when} the fire was ${daysBetween(fire.dates.ignition, t.date)} days old. Radar needs ${fire.scar_method.looks} passes that agree before it confirms a scar.`;
    else if (slope) s = `Hatched ground is ${fire.steep_deg} degrees or steeper: steep enough for loose soil to move in a heavy storm.`;
    else if (people) s = `Each dot is a home: ${fmt(tot.homes_in_window)} of them, about ${fmt(tot.people_in_window)} people, in this map window.`;
    else s = "Switch a layer on. Where all three line up, the map turns red.";
    $("stack-says").innerHTML = s;
  }

  function renderBar() {
    const slider = $("slider"), count = $("count");
    slider.style.setProperty("--p", (+slider.max ? (slider.value / slider.max) * 100 : 0) + "%");
    count.classList.remove("hot");
    if (state.view === "nisar") {
      const after = state.fade >= 50;
      $("date-label").textContent = after ? day(N.after_dates[1]) : day(N.before_dates[1]);
      $("pass-label").textContent = `NISAR radar, ${after ? "after" : "before"} the fire`;
      count.textContent = `${N.change_in_scar_db.toFixed(1)} dB`;
      $("count-label").textContent = `change in NISAR's echo over the Sentinel-1 burn scar. Unburned ground around it: ${N.change_outside_db.toFixed(1)} dB.`;
    } else if (state.view === "usgs") {
      $("date-label").textContent = day(fire.dates.usgs_assessment);
      $("pass-label").textContent = `USGS expert map, ${daysBetween(fire.dates.ignition, fire.dates.usgs_assessment)} days after the fire started`;
      count.textContent = pct(C.agreement);
      $("count-label").textContent = `of ${C.n_basins} USGS basins get the same answer from both: flagged by this screen and rated Moderate or High, or neither.`;
    } else {
      const t = T[state.idx];
      $("date-label").textContent = day(t.date);
      $("pass-label").textContent = `Satellite pass ${state.idx + 1} of ${K}, ${daysBetween(fire.dates.ignition, t.date)} days after the fire started`;
      slider.setAttribute("aria-valuetext", t.date);
      const { burn, slope } = state.layers;
      if (all()) {
        count.textContent = fmt(t.people);
        count.classList.toggle("hot", t.people > 0);
        $("count-label").textContent = `people live in the ${t.homes} homes that mud could reach, as mapped by ${day(t.date)}`;
      } else if (burn && slope) {
        count.textContent = acres(t.red_km2);
        count.classList.toggle("hot", t.red_km2 > 0);
        $("count-label").textContent = `acres of burned, steep hillside mapped by ${day(t.date)}`;
      } else if (burn) {
        count.textContent = acres(t.scar_km2);
        $("count-label").textContent = `acres of burned area mapped by radar by ${day(t.date)}`;
      } else {
        count.textContent = "–";
        $("count-label").textContent = "Switch on Burned area to count what the radar has mapped.";
      }
    }
  }

  function setupSlider() {
    const slider = $("slider"), ticks = $("ticks");
    ticks.innerHTML = "";
    if (state.view === "nisar") {
      slider.max = 100; slider.value = state.fade;
      slider.setAttribute("aria-label", "Before to after");
      $("slider-hint").textContent = "Drag to fade from before the fire to after";
      ticks.innerHTML = `<span style="left:0;transform:none">Before the fire</span><span style="left:100%;transform:translateX(-100%)">After</span>`;
    } else {
      slider.max = K - 1; slider.value = state.idx;
      slider.setAttribute("aria-label", "Radar pass");
      $("slider-hint").textContent = "Drag to go back in time and watch the satellite map the burn, or press play";
      let last = "";
      T.forEach((t, i) => {
        const m = t.date.slice(0, 7);
        if (m !== last && (i > 0 || t.date.slice(8) < "10")) ticks.insertAdjacentHTML("beforeend", `<span style="left:${(i / (K - 1)) * 100}%">${MONTHS[+m.slice(5) - 1]}</span>`);
        last = m;
      });
    }
  }

  const inPathNow = (id) => (homesOf.get(id) || []).filter((k) => k <= state.idx).length;
  const where = (p) => (p.place ? `${(p.place_km * 0.621).toFixed(p.place_km < 16 ? 1 : 0)} miles from ${p.place}` : fire.county);

  function renderOverview() {
    const rows = blocks.features.map((f) => f.properties);
    $("rank").innerHTML = ""; $("extra").innerHTML = ""; $("rank-note").textContent = ""; $("rank-title").textContent = "";
    $("how").hidden = $("find").hidden = state.view !== "watch";
    renderWays();
    if (state.view === "nisar") {
      $("headline").textContent = "NISAR sees the scar too";
      $("subhead").textContent = `NISAR is the NASA and ISRO radar this challenge is built around. Its long L-band waves reach into the canopy, so burned forest goes dark. Drag the slider to fade from before the fire to after.`;
      $("extra").innerHTML = `<dl class="facts">
        <div><dt>Over our burn scar</dt><dd><span class="big">${N.change_in_scar_db.toFixed(1)} dB</span><span class="small">median change in echo strength, ${N.before_dates.map(day).join(" and ")} against ${N.after_dates.map(day).join(" and ")}</span></dd></div>
        <div><dt>Over unburned ground</dt><dd><span class="big">${N.change_outside_db.toFixed(1)} dB</span><span class="small">the rest of the map window</span></dd></div>
        <div><dt>Scar clearly darker</dt><dd><span class="big">${pct(N.share_of_scar_darker)}</span><span class="small">of the Sentinel-1 scar is darker in NISAR than unburned ground normally varies. Outside the scar: ${pct(N.share_of_unburned_darker)}.</span></dd></div>
      </dl>`;
      $("rank-note").textContent = "The scar was mapped with Sentinel-1. NISAR was not used to draw it, which makes this an independent check by a second radar.";
    } else if (state.view === "usgs") {
      const t = C.table, late = daysBetween(fire.dates.first_home, fire.dates.usgs_assessment);
      $("headline").textContent = "How close is this to the experts?";
      $("subhead").innerHTML = `USGS already maps debris-flow hazard after wildfires, with a far richer model than ours. Its assessment of this fire is dated ${day(fire.dates.usgs_assessment)}. This screen first flagged a home on ${day(fire.dates.first_home)}, ${late} days earlier.`;
      $("extra").innerHTML = `<dl class="facts">
        <div><dt>Same answer</dt><dd><span class="big">${t.both + t.neither} of ${C.n_basins}</span><span class="small">basins. ${t.both} flagged by both, ${t.neither} by neither.</span></dd></div>
        <div><dt>Only we flag</dt><dd><span class="big">${t.only_ours}</span><span class="small">basins with steep burned ground that USGS rates Low</span></dd></div>
        <div><dt>Only USGS flags</dt><dd><span class="big">${t.only_usgs}</span><span class="small">basins USGS rates Moderate or High where we found under ${fire.rule.min_source_ha} hectare of red zone</span></dd></div>
        <div><dt>Steep and burned</dt><dd><span class="big">${(C.mean_red_share * 100).toFixed(1)}% vs ${(C.mean_terrain_term * 100).toFixed(1)}%</span><span class="small">of basin area: our radar figure, then the USGS figure from optical burn severity. Rank agreement across basins: ${C.red_vs_terrain.spearman.toFixed(2)}.</span></dd></div>
      </dl>`;
      $("rank-note").innerHTML = `We flag risk zones. USGS estimates likelihood and volume for a given storm. Where the two disagree, trust USGS: <a href="${fire.usgs.sciencebase_url}" target="_blank" rel="noopener">open its assessment</a>.`;
    } else {
      const t = T[state.idx];
      if (all() && t.homes) {
        $("headline").innerHTML = `<b>${t.homes} homes</b> could be in the path of a mudslide`;
        $("subhead").textContent = `The ${fire.short_name} Fire left steep hillsides bare. A heavy rainstorm could send mud down them. The red house markers are homes in the way, where about ${t.people} people live. This is a warning to be ready, not a prediction.`;
      } else if (all()) {
        $("headline").textContent = "No homes flagged yet";
        $("subhead").textContent = `By ${day(t.date)}, ${daysBetween(fire.dates.ignition, t.date)} days after the fire started, the satellite had not yet confirmed burned, steep ground above a home. Drag the slider at the bottom forward.`;
      } else {
        $("headline").textContent = "Who is below the burn?";
        $("subhead").textContent = "Switch on all three layers above to see the homes that mud could reach after a heavy rainstorm.";
      }
      const top = !all() ? [] : rows.map((p) => ({ p, n: inPathNow(p.id) })).filter((r) => r.n > 0).sort((a, b) => b.n - a.n || b.p.people_in - a.p.people_in).slice(0, 7);
      $("rank-title").textContent = top.length ? "Where those homes are" : "";
      $("rank").innerHTML = top.map(({ p, n }, i) => `<li style="--i:${i}"><button type="button" data-id="${p.id}">
          <span class="rank-name">${p.name}</span>
          <span class="rank-when">${n} ${n === 1 ? "home" : "homes"}</span>
          <span class="rank-sub">${where(p)}</span>
        </button></li>`).join("");
      $("rank-note").textContent = top.length
        ? "Select a place here, or a red house on the map, to see what it means and what to do."
        : all() ? `No home was below confirmed red zones by ${day(T[state.idx].date)}. Move the slider forward.`
        : "";
    }
  }

  const routeName = (r) => `${r.via || "Local roads"}, heading ${r.heading}`;
  const routeEnd = (r) => (r.to && r.to !== r.via ? `to ${r.to}` : "to a stretch clear of the mud paths") + (r.place ? `, near ${r.place.name}` : "");
  const crosses = (r) => `runs through ${r.crossings} possible mud ${r.crossings === 1 ? "path" : "paths"}`;
  function renderWays() {
    const on = state.view === "watch" && all();
    $("ways").hidden = !on || !state.routes || !WO.routes.length;
    $("clear").hidden = !on || state.role !== "responder";
    if (!on) return;
    $("ways-list").innerHTML = WO.routes.map((r, i) => `<li style="--i:${i}"><button type="button" data-route="${r.id}">
        <span class="rank-name">${routeName(r)}</span>
        <span class="rank-when plain">${miles(r.km)} mi</span>
        <span class="rank-sub">${routeEnd(r)}. Used by ${r.homes} of the flagged homes. ${r.crossings ? `It ${crosses(r)}, so leave before heavy rain.` : "It stays clear of the mapped mud paths."}</span>
      </button></li>`).join("");
    $("ways-note").textContent = `These are not official evacuation routes. Each is the shortest drive on the OpenStreetMap road map from a flagged home to a main road at least ${WO.rule.clear_m / 1000} km clear of every mapped mud path. Dashed stretches lie in a possible mud path. If officials name a route, take theirs.`;
    if (state.role !== "responder") return;
    const pts = clearPts.features.map((f) => f.properties).filter((p) => p.k <= state.idx);
    $("clear-lede").textContent = pts.length
      ? `${pts.length} places where a possible mud path meets a public road. A plugged culvert or ditch there could send mud across the road. Ways out are listed first, then the largest burned slopes.`
      : `No possible mud path had reached a public road by ${day(T[state.idx].date)}.`;
    $("clear-list").innerHTML = pts.map((p, i) => `<li style="--i:${i}"><button type="button" data-clear="${p.rank}">
        <span class="rank-name"><i class="num">${p.rank}</i>${p.road}</span>
        <span class="rank-when plain">${fmt(p.ha * 2.471)} ac</span>
        <span class="rank-sub">of steep burned ground drain to this ${p.kind === "basin" ? "basin" : "crossing"}${p.on_route ? ". On a way out" : ""}</span>
      </button></li>`).join("");
    $("clear-note").textContent = `There is no public map of debris basins for this fire${WO.osm_basins_checked ? `, and OpenStreetMap shows ${WO.osm_basins_found || "none"} in this area` : ""}. These points are worked out instead: each is where a mud channel on this map crosses a public road, with crossings closer than ${WO.rule.cluster_m} m counted once. Check them on the ground before sending a crew.`;
  }
  function showRoute(id) {
    const b = new maplibregl.LngLatBounds();
    for (const f of routes.features) if (f.properties.r === id) (function walk(c) { typeof c[0] === "number" ? b.extend(c) : c.forEach(walk); })(f.geometry.coordinates);
    if (!b.isEmpty()) map.fitBounds(b, { padding: 90, maxZoom: 14, duration: 1400 });
  }
  function showClear(rank, fly) {
    const f = clearPts.features.find((c) => c.properties.rank === rank), p = f.properties;
    popup?.remove();
    popup = new maplibregl.Popup({ offset: 18, closeButton: true, maxWidth: "260px" }).setLngLat(f.geometry.coordinates)
      .setHTML(`<b>Clearing point ${p.rank}: ${p.road}</b><p>${fmt(p.ha * 2.471)} acres of steep burned ground drain to this ${p.kind === "basin" ? "basin" : "road crossing"}. First mapped on ${day(T[p.k].date)}.${p.on_route ? " It is on a way out for flagged homes." : ""}</p><p class="small">Clear the culvert, ditch and channel here before heavy rain. Worked out from the map, not surveyed.</p>`).addTo(map);
    if (fly) map.flyTo({ center: f.geometry.coordinates, zoom: Math.max(map.getZoom(), 13.5), duration: 1200 });
  }
  function setRole(r, keep = true) {
    state.role = r;
    if (keep) store.set(r);
    $("role-btn").textContent = r === "responder" ? "Switch to resident" : "Switch to first responder";
    render();
  }

  const todo = () => `<ol>
      <li>Sign up for ${fire.county} emergency alerts and keep emergency alerts switched on in your phone.</li>
      <li>Watch the forecast. The National Weather Service in ${fire.nws_office} issues Flash Flood Watches and Warnings for burn scars: <a href="${fire.nws_url}" target="_blank" rel="noopener">weather.gov</a>.</li>
      <li>Decide now where you would go and which road you would take. Leave before the heavy rain starts, not during it. Debris flows move faster than a person can run.</li>
      <li>Never walk or drive through moving water or mud, and stay out of creek beds and gullies during a storm.</li>
      <li>If you cannot leave, go upstairs or to the side of the house away from the hill. Rumbling, cracking trees or a creek that suddenly turns muddy or stops are warnings.</li>
    </ol><p class="small">General guidance from <a href="https://www.ready.gov/landslides-debris-flow" target="_blank" rel="noopener">Ready.gov</a> and the <a href="https://www.usgs.gov/programs/landslide-hazards/science/postfire-debris-flow-hazards" target="_blank" rel="noopener">USGS</a>. Local officials have the final word.</p>`;

  function renderCard() {
    const card = $("card");
    const p = state.selected && byId.get(state.selected);
    $("overview").hidden = !!p;
    card.hidden = !p;
    map.setFilter("block-selected", ["==", "id", p ? p.id : ""]);
    if (!p) return;
    const latest = day(fire.dates.latest_pass);
    const S = {
      in: ["You are below a steep burn scar. A heavy storm could send mud here.", `${p.homes_in} of the ${p.homes} homes mapped in this block sit in a possible mud path: a channel that drains ground the radar says burned and that is ${fire.steep_deg} degrees or steeper. That does not mean a mudslide will happen. It means this is where one could arrive, so it is worth being ready before the rain.`],
      near: ["Close to a possible mud path.", `No mapped home here is inside a path, but ${p.homes_near} ${p.homes_near === 1 ? "is" : "are"} within ${fire.rule.near_path_m} meters of one. Paths on this map are drawn narrow, and real flows spread where the ground flattens, so treat the advice below as yours too.`],
      clear: ["No mapped home here is in or beside a possible mud path.", `This screen found no steep burned slope draining onto the homes mapped in this block. It does not cover ordinary flash flooding on the creeks, which also rises after a fire, or slopes the radar did not flag.`],
      empty: ["No homes are mapped in this block.", "The building inventory shows no homes here, so there is nobody to count. If that is wrong, use the nearest block with homes as a guide."],
    }[p.status];
    const flagged = p.k >= 0 ? `<div><dt>First flagged</dt><dd><span class="big">${day(T[p.k].date)}</span><span class="small">day ${daysBetween(fire.dates.ignition, T[p.k].date)} after the fire started, on radar pass ${p.k + 1}</span></dd></div>` : "";
    const up = p.up_ha >= 1 ? `<div><dt>Steep burned ground upstream</dt><dd><span class="big">${fmt(p.up_ha * 2.471)} acres</span><span class="small">drain past the most exposed home here</span></dd></div>` : "";
    const rt = p.route >= 0 ? WO.routes[p.route] : null;
    const wayOut = rt ? `<div><dt>Way out by road</dt><dd><span class="big">${routeName(rt)}</span><span class="small">about ${miles(p.route_km)} miles ${routeEnd(rt)}. ${rt.crossings ? `It ${crosses(rt)}, so leave before heavy rain.` : ""} Not an official evacuation route. <button type="button" class="inline" id="see-route">Show it on the map</button></span></dd></div>` : "";
    card.innerHTML = `
      <button class="btn back" type="button" id="back">Back to the map summary</button>
      <h1>${p.name}</h1>
      <p class="where">${where(p)}. Census block ${p.id.slice(-4)}, tract ${p.id.slice(5, 11)}.</p>
      <p class="status ${p.status}"><i></i><span>${S[0]}</span></p>
      <dl class="facts">
        <div><dt>Homes in a possible mud path</dt><dd><span class="big ${p.homes_in ? "hot" : ""}">${p.homes_in} of ${p.homes}</span><span class="small">${p.homes_in ? `about ${p.people_in} ${p.people_in === 1 ? "person" : "people"}, ` : ""}as of the ${latest} radar pass</span></dd></div>
        <div><dt>Homes beside one</dt><dd><span class="big">${p.homes_near}</span><span class="small">within ${fire.rule.near_path_m} meters of a path</span></dd></div>
        ${up}${flagged}${wayOut}
        <div><dt>People living here</dt><dd><span class="big">${fmt(p.pop)}</span><span class="small">2020 Census, whole block</span></dd></div>
      </dl>
      <div class="say"><h3>What this means</h3>${S[1]}</div>
      ${p.status === "in" || p.status === "near" ? `<div class="say"><h3>Here's what to do</h3>${todo()}</div>` : ""}
      <div class="card-actions"><button class="btn" type="button" id="print">Print this page</button><button class="btn" type="button" id="csv">Download all blocks (CSV)</button></div>`;
    $("back").onclick = () => select(null);
    $("print").onclick = () => window.print();
    $("csv").onclick = downloadCsv;
    if (rt) $("see-route").onclick = () => { state.routes = true; renderMap(); renderLegend(); showRoute(rt.id); };
  }

  function downloadCsv() {
    const cols = ["id", "name", "place", "pop", "homes", "homes_in", "people_in", "homes_near", "people_near", "status"];
    const head = "census_block_geoid,label,nearest_place,population_2020,homes_mapped,homes_in_path,people_in_path,homes_within_100m,people_within_100m,status";
    const lines = blocks.features.map((f) => cols.map((c) => { const v = f.properties[c]; return v == null ? "" : typeof v === "string" ? `"${v.replace(/"/g, '""')}"` : v; }).join(","));
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([head + "\n" + lines.join("\n")], { type: "text/csv" }));
    a.download = "mudwatch-" + fire.id + ".csv";
    a.click();
  }

  function render() { renderMap(); renderLegend(); renderStack(); renderBar(); renderOverview(); renderCard(); }

  function boundsOf(geom) {
    const b = new maplibregl.LngLatBounds();
    (function walk(c) { typeof c[0] === "number" ? b.extend(c) : c.forEach(walk); })(geom.coordinates);
    return b;
  }
  function select(id, fly) {
    state.selected = id;
    renderCard();
    for (const p of pins) p.el.classList.toggle("sel", p.b === id);
    if (id) document.querySelector(".panel").scrollTop = 0;
    if (id && fly) map.fitBounds(boundsOf(blocks.features.find((t) => t.properties.id === id).geometry), { padding: 120, maxZoom: 14, duration: 1400 });
  }
  function setView(v) {
    state.view = v;
    document.body.classList.toggle("view-usgs", v === "usgs");
    document.querySelectorAll(".views button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.view === v)));
    setupSlider();
    render();
  }
  function setLayers(l) { Object.assign(state.layers, l); renderMap(); renderLegend(); renderStack(); renderBar(); if (!state.selected) renderOverview(); }

  /* ---------- interaction ---------- */
  document.querySelectorAll(".views button").forEach((b) => (b.onclick = () => { stop(); select(null); setView(b.dataset.view); }));
  $("routes-toggle").onclick = () => { stop(); state.routes = !state.routes; render(); };
  document.querySelectorAll(".layer[data-layer]").forEach((b) => {
    const plate = document.querySelector(`.p-${b.dataset.layer}`);
    b.onclick = () => { stop(); setLayers({ [b.dataset.layer]: !state.layers[b.dataset.layer] }); };
    b.onmouseenter = () => plate.classList.add("lift");
    b.onmouseleave = () => plate.classList.remove("lift");
  });
  // The prompt above the slider and the breathing play button are only for first-time visitors.
  function used() {
    $("slider-hint").classList.add("gone");
    $("play").classList.remove("invite");
  }
  $("slider").addEventListener("pointerdown", () => { used(); stop(); });
  $("slider").addEventListener("keydown", used);
  $("slider").oninput = (ev) => {
    if (state.view === "nisar") { state.fade = +ev.target.value; fadeTo("nisar-after", state.fade / 100); renderBar(); renderLegend(); return; }
    state.idx = +ev.target.value;
    renderMap(); renderStack(); renderBar();
    if (!state.selected) renderOverview();
  };
  $("ways-list").onclick = (ev) => { const b = ev.target.closest("button[data-route]"); if (b) showRoute(+b.dataset.route); };
  $("clear-list").onclick = (ev) => { const b = ev.target.closest("button[data-clear]"); if (b) showClear(+b.dataset.clear, true); };
  $("role-btn").onclick = () => { stop(); setRole(state.role === "responder" ? "resident" : "responder"); };
  $("who").addEventListener("click", (ev) => { const b = ev.target.closest("button[data-role]"); if (b) { setRole(b.dataset.role); $("who").close(); } });
  $("rank").onclick = (ev) => { const b = ev.target.closest("button[data-id]"); if (b) select(b.dataset.id, true); };
  map.on("click", "block-fill", (ev) => { stop(); select(ev.features[0].properties.id); });
  map.on("mouseenter", "block-fill", () => (map.getCanvas().style.cursor = "pointer"));
  map.on("mouseleave", "block-fill", () => (map.getCanvas().style.cursor = ""));

  // Address search: OpenStreetMap's geocoder, limited to the map window.
  const inRing = (pt, ring) => { let c = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const [xi, yi] = ring[i], [xj, yj] = ring[j]; if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) c = !c; } return c; };
  const inGeom = (pt, g) => (g.type === "Polygon" ? [g.coordinates] : g.coordinates).some((poly) => inRing(pt, poly[0]) && !poly.slice(1).some((hole) => inRing(pt, hole)));
  let pin;
  $("find").onsubmit = async (ev) => {
    ev.preventDefault();
    const q = $("addr").value.trim(), msg = $("find-msg");
    if (!q) return;
    msg.textContent = "Looking it up…";
    try {
      const u = `https://nominatim.openstreetmap.org/search?format=json&limit=1&bounded=1&viewbox=${bw},${bn},${be},${bs}&q=${encodeURIComponent(q)}`;
      const hit = (await loadJson(u))[0];
      if (!hit) { msg.textContent = "Nothing by that name inside this map. Try a road name, or select your block on the map."; return; }
      const pt = [+hit.lon, +hit.lat];
      const f = blocks.features.find((b) => inGeom(pt, b.geometry));
      pin?.remove();
      pin = new maplibregl.Marker({ color: BONE, scale: 0.8 }).setLngLat(pt).addTo(map);
      setLayers({ burn: true, slope: true, people: true });
      map.flyTo({ center: pt, zoom: 13.5, duration: 1400 });
      msg.textContent = "";
      if (f) select(f.properties.id);
    } catch (e) {
      msg.textContent = "The address lookup did not answer. Select your block on the map instead.";
    }
  };

  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function stop() {
    if (state.playing) state.playing.cancelled = true;
    state.playing = null;
    $("play").innerHTML = ICON.play;
    $("play").setAttribute("aria-label", "Play");
    $("caption").hidden = true;
    fadeTo("optical", 0); fadeTo("radar", 0);
  }
  async function sweep(token, ms, from) {
    const slider = $("slider"), max = +slider.max, start = from ?? 0, t0 = performance.now();
    while (!token.cancelled) {
      const f = Math.min(1, (performance.now() - t0) / ms);
      const v = Math.round(start + (max - start) * f);
      if (+slider.value !== v) { slider.value = v; slider.oninput({ target: slider }); }
      if (f >= 1) break;
      await new Promise(requestAnimationFrame);
    }
  }
  $("play").onclick = async () => {
    if (state.playing) return stop();
    const token = (state.playing = { cancelled: false });
    $("play").innerHTML = ICON.pause;
    $("play").setAttribute("aria-label", "Pause");
    used();
    const cur = +$("slider").value;
    await sweep(token, state.view === "nisar" ? 4000 : 10000, cur >= +$("slider").max ? 0 : cur);
    if (!token.cancelled) stop();
  };

  // Guided story, timed to fit a 30-second demo recording.
  $("story").onclick = async () => {
    stop(); used(); select(null);
    const token = (state.playing = { cancelled: false });
    const cap = $("caption"), say = (t) => { cap.textContent = t; cap.hidden = false; };
    const wait = async (ms) => { await sleep(ms); return token.cancelled; };
    const O = fire.optical && fire.optical.ok ? fire.optical : null, R = fire.radar_picture;
    state.idx = 0; state.layers = { burn: false, slope: false, people: false };
    setView("watch");
    map.fitBounds([fire.focus.slice(0, 2), fire.focus.slice(2)], { padding: 50, duration: 800 });
    if (O) {
      fadeTo("optical", 1);
      say(`${day(O.date)}, day ${daysBetween(fire.dates.ignition, O.date)} of the fire. ${O.haze_share >= 0.3 ? "An ordinary satellite camera sees smoke." : `An ordinary satellite camera: ${pct(O.haze_share)} of the view is smoke or cloud.`}`);
      if (await wait(4200)) return;
    }
    if (R) {
      fadeTo("radar", 1); fadeTo("optical", 0);
      say(`Radar sees through smoke and cloud. Sentinel-1, ${day(R.date)}.`);
      if (await wait(3800)) return;
    }
    setLayers({ burn: true });
    fadeTo("radar", 0.35);
    say("Pass by pass, NASA's OPERA radar product maps the burn scar.");
    await sweep(token, 6500); if (token.cancelled) return;
    fadeTo("radar", 0);
    setLayers({ slope: true });
    say(`Steep burned hills turn red: ${acres(tot.red_km2)} acres.`);
    if (await wait(3600)) return;
    setLayers({ people: true });
    const star = blocks.features.map((f) => f.properties).sort((a, b) => b.people_in - a.people_in)[0];
    say(`Homes below light up: ${tot.homes_in_zone} homes, about ${tot.people_in_zone} people, where mud could reach.`);
    if (star && star.homes_in) map.fitBounds(boundsOf(blocks.features.find((f) => f.properties.id === star.id).geometry), { padding: 160, maxZoom: 13.2, duration: 2200 });
    if (await wait(5200)) return;
    setView("usgs");
    map.fitBounds([fire.focus.slice(0, 2), fire.focus.slice(2)], { padding: 50, duration: 1600 });
    say(`The USGS expert map, dated ${day(fire.dates.usgs_assessment)}, gives the same answer for ${pct(C.agreement)} of basins. This screen flagged its first home on ${day(fire.dates.first_home)}.`);
    if (await wait(6500)) return;
    stop();
  };

  /* ---------- science check ---------- */
  function checkHtml() {
    const k = fire.scar_check, t = C.table, d = fire.dates, m = fire.scar_method;
    const Wd = 300, pad = 40, lim = Math.max(0.3, ...C.points.flatMap((p) => [p[0], p[1]])) * 1.05;
    const sx = (v) => pad + (v / lim) * (Wd - pad - 10), sy = (v) => Wd - pad - (v / lim) * (Wd - pad - 10);
    const dots = C.points.map((p) => `<circle cx="${sx(p[0]).toFixed(1)}" cy="${sy(p[1]).toFixed(1)}" r="3.6" fill="${p[3] >= 2 ? BONE : "none"}" stroke="${BONE}" stroke-opacity="0.75" fill-opacity="0.75"><title>Ours ${(p[0] * 100).toFixed(0)}%, USGS ${(p[1] * 100).toFixed(0)}%</title></circle>`).join("");
    const ticks = [0, 0.2, 0.4, 0.6].filter((v) => v <= lim).map((v) => `<text x="${sx(v)}" y="${Wd - pad + 14}" text-anchor="middle" font-size="10">${v * 100}%</text><text x="${pad - 6}" y="${sy(v) + 3}" text-anchor="end" font-size="10">${v * 100}%</text>`).join("");
    return `<h2>Check the science</h2>
      <p>Every number on this site is computed from public data by the code in this project. This panel shows how the result holds up against sources we did not use to make it.</p>
      <h3>Is the red in the right places?</h3>
      <div class="two"><div>
        <p>The USGS model has a term for the same idea as our red zones: the share of each basin that burned at moderate or high severity on slopes of 23 degrees or more, taken from optical burn-severity maps. Ours comes from radar. Each dot is one of ${C.n_basins} basins.</p>
        <table><tr><th>Check</th><th class="num">Result</th></tr>
          <tr><td>Rank agreement, our red share against the USGS terrain term</td><td class="num">${C.red_vs_terrain.spearman.toFixed(2)}</td></tr>
          <tr><td>Rank agreement, our red share against USGS likelihood</td><td class="num">${C.red_vs_likelihood.spearman.toFixed(2)}</td></tr>
          <tr><td>Rank agreement, radar darkening against optical burn severity</td><td class="num">${C.radar_vs_severity.spearman.toFixed(2)}</td></tr>
          <tr><td>Basins flagged by both, or by neither</td><td class="num">${t.both + t.neither} of ${C.n_basins}</td></tr>
          <tr><td>Flagged only by us / only by USGS</td><td class="num">${t.only_ours} / ${t.only_usgs}</td></tr>
          <tr><td>Our flagged homes within 150 m of a USGS Moderate or High stream segment</td><td class="num">${C.homes_flagged_near_usgs_moderate_high} of ${C.homes_flagged}</td></tr></table>
        <p class="small">Rank agreement is Spearman's correlation: 1 is the same ordering, 0 is none. "Flagged by us" means at least ${fire.rule.min_source_ha} hectare of red zone in the basin. USGS ratings are for a storm peaking at ${C.design_storm_mm_h} mm per hour.</p>
      </div>
      <svg viewBox="0 0 ${Wd} ${Wd}" width="${Wd}" role="img" aria-label="Our red-zone share against the USGS terrain term, one dot per basin">
        <rect x="${pad}" y="10" width="${Wd - pad - 10}" height="${Wd - pad - 10}" fill="#1d1d20"/>
        <line x1="${sx(0)}" y1="${sy(0)}" x2="${sx(lim)}" y2="${sy(lim)}" stroke="#71717a" stroke-dasharray="4 3"/>${dots}${ticks}
        <text x="${(Wd + pad) / 2}" y="${Wd - 6}" text-anchor="middle" font-size="10.5">Our red share of basin (radar)</text>
        <text x="11" y="${(Wd - pad) / 2}" text-anchor="middle" font-size="10.5" transform="rotate(-90 11 ${(Wd - pad) / 2})">USGS terrain term (optical)</text></svg></div>
      <p class="small">Filled dots are basins USGS rates Moderate or High. Dots on the dashed line would be perfect agreement.</p>

      <h3>Is the burn scar real?</h3>
      <table><tr><th>Check</th><th class="num">Result</th></tr>
        <tr><td>Radar scar that falls inside the official burn perimeter</td><td class="num">${pct(k.share_of_scar_inside_perimeter)}</td></tr>
        <tr><td>Official perimeter that the radar confirmed as scar</td><td class="num">${pct(k.share_of_perimeter_detected)}</td></tr>
        <tr><td>False scar when the same method is run on passes before the fire</td><td class="num">${acres(k.prefire_false_alarm_km2)} acres of ${acres(k.window_km2)}</td></tr>
        ${N ? `<tr><td>NISAR L-band change over the scar / over unburned ground</td><td class="num">${N.change_in_scar_db.toFixed(1)} / ${N.change_outside_db.toFixed(1)} dB</td></tr>` : ""}</table>
      <p class="small">The radar confirms less than the whole perimeter because a perimeter also encloses lightly burned and unburned ground, and because C-band radar mostly sees canopy loss. Light burns under intact trees are missed. A cell needs ${m.looks} passes in a row averaging ${m.drop_db} dB darker than before the fire.</p>

      <h3>How fast was it?</h3>
      <table><tr><th>Event</th><th class="num">Date</th><th class="num">Day</th></tr>
        ${[["Fire starts", d.ignition], ["First radar pass after ignition", d.first_pass], fire.optical && fire.optical.ok ? [`Optical view, ${pct(fire.optical.haze_share)} smoke or cloud`, fire.optical.date] : null, ["Radar confirms the first scar and the first home below it", d.first_home],
           fire.optical && fire.optical.first_clear_view ? ["First clear optical view of the whole area", fire.optical.first_clear_view] : null, ["USGS assessment is dated", d.usgs_assessment]].filter(Boolean)
          .sort((a, b) => a[1].localeCompare(b[1])).map(([n, dt]) => `<tr><td>${n}</td><td class="num">${day(dt)}</td><td class="num">${daysBetween(d.ignition, dt)}</td></tr>`).join("")}</table>
      <p class="small">A fair reading: this fire kept burning for weeks, and USGS waits for a reliable burn-severity map. A radar screen can give an early, rough answer while that work is under way. It does not replace it.</p>

      <h3>Which radar product drew the scar</h3>
      <p>${fire.dist && !fire.dist.available_for_fire
        ? `We planned to read the scar from NASA's OPERA DIST-ALERT-S1 disturbance alerts. That product's archive currently covers ${day(fire.dist.first_date)} to ${day(fire.dist.last_date)}, 2026 over this area, so it does not reach this fire yet. The scar here is drawn from OPERA RTC-S1, the calibrated Sentinel-1 backscatter that DIST-ALERT-S1 is itself built from, using the same confirm-over-several-passes idea.`
        : `The scar is drawn from NASA's OPERA radar products.`}</p>
      <p><a href="methods.html?fire=${fid}">Read the full method and its limits</a></p>`;
  }
  $("open-check").onclick = () => { $("check-body").innerHTML = checkHtml(); $("check").showModal(); };

  setView("watch");
  setRole(state.role, false);
  document.body.classList.remove("loading");
  $("who").showModal();   // asked on every visit; the last answer is the default if the dialog is dismissed
})().catch((err) => {
  console.error(err);
  document.body.classList.remove("loading");
  document.querySelector(".panel").insertAdjacentHTML("afterbegin", `<p class="notice">The map data did not load. Check your connection and reload the page.</p>`);
});
