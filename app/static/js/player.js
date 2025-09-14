// static/js/player.js
console.log("SlidePi player.js loaded");

// --- Utils / Mode -----------------------------------------------------------
function qs(sel){ return document.querySelector(sel); }
function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

const WRAP = qs(".player-wrap");
const MODE = WRAP?.dataset.mode || "normal";
const IS_KIOSK = MODE === "kiosk";

// --- Player State -----------------------------------------------------------
let feed = [];
let sig = "";
let idx = 0;
let timer = null;
let playing = true;
let pendingUpdate = false;

// Default-Dauer (evtl. vom Server im DOM gesetzt)
let DEFAULT_DURATION = 10;

// Polling + ETag
const POLL_MS_BASE = 5000;
const POLL_MS_MAX  = 30000;
let pollMs = POLL_MS_BASE;
let lastETag = null;

function computeSignature(items){
  const s = items.map(i => {
    const key = i.playlist_item_id ?? i.media_id ?? i.id ?? i.url ?? "?";
    const dur = i.duration ?? i.duration_s ?? "";
    return `${key}:${dur}`;
  }).join("|");
  let h = 0;
  for (let i=0;i<s.length;i++){ h = (h*31 + s.charCodeAt(i)) >>> 0; }
  return h.toString(16);
}

function clearStage(){
  if (timer){ clearTimeout(timer); timer = null; }
  const stage = qs("#stage");
  if (stage) stage.innerHTML = "";
}

function showStatus(msg){
  const hint = qs("#update-hint");
  if (!hint) return;
  hint.textContent = msg;
  hint.hidden = false;
  setTimeout(()=> { hint.hidden = true; }, 2500);
}

async function fetchFeed(){
  const headers = { "cache-control":"no-store" };
  if (lastETag) headers["If-None-Match"] = lastETag;

  const res = await fetch("/api/feed", { headers });
  if (res.status === 304){
    return { items: null, etag: lastETag };
  }
  if (!res.ok) throw new Error(`feed request failed: ${res.status}`);
  const et = res.headers.get("ETag");
  const j = await res.json();
  const items = (j && j.ok && Array.isArray(j.feed)) ? j.feed
              : (j && Array.isArray(j.items)) ? j.items
              : [];
  return { items, etag: et };
}

async function loadFeed(initial=false){
  try{
    const { items, etag } = await fetchFeed();

    if (etag) lastETag = etag;

    // 304: nichts geändert
    if (items === null){
      return false;
    }

    const newSig = computeSignature(items);

    if (initial){
      feed = items; sig = newSig; idx = 0;
      if (!feed.length){
        clearStage();
        const st = qs("#stage");
        if (st) st.innerHTML = "<p>Keine aktiven Medien in der Playlist.</p>";
      }
      return true;
    }

    if (newSig !== sig){
      pendingUpdate = true;
      feed = items; sig = newSig;
      showStatus("Playlist aktualisiert");
      return true;
    }
    return false;
  }catch(e){
    console.warn("Feed Load Error:", e);
    return false;
  }
}

async function startPolling(){
  while (true){
    await sleep(pollMs);
    const changed = await loadFeed(false);
    if (changed){
      pollMs = POLL_MS_BASE;
      if (pendingUpdate && playing && feed.length === 0){ nextItem(true); }
    } else {
      pollMs = Math.min(Math.round(pollMs * 1.25), POLL_MS_MAX);
    }
  }
}

function scheduleNext(ms){
  if (!playing) return;
  if (timer) { clearTimeout(timer); timer = null; }
  const delay = Math.max(0, Number(ms) || 0);
  timer = setTimeout(()=> nextItem(false), delay);
}

// --- Preloading -------------------------------------------------------------
let nextPreload = null;

function kindOf(item){
  if (item.type) return item.type;
  if (item.kind) return item.kind;
  if (item.mime?.startsWith("video/")) return "video";
  if (item.mime?.startsWith("image/")) return "image";
  return "file";
}

function preloadNext(){
  nextPreload = null;
  if (!feed.length) return;

  const nextIdx = (idx + 1) % feed.length;
  const item = feed[nextIdx];
  const k = kindOf(item);
  const src = item.url || item.path;
  if (!src) return;

  if (k === "image"){
    const img = new Image();
    img.className = "stage-media";
    img.alt = item.filename || "Bild";
    img.src = src;
    nextPreload = img;
  } else if (k === "video"){
    const vid = document.createElement("video");
    vid.src = src;
    vid.preload = "metadata";
    nextPreload = vid;
  }
}

// --- Renderers --------------------------------------------------------------
function onLoadErrorSkip(label){
  console.warn(`${label} konnte nicht geladen werden, weiter …`);
  scheduleNext(2000);
}

function renderImage(item){
  const stage = qs("#stage");
  const img = document.createElement("img");
  img.src = item.url || item.path;
  img.alt = item.filename || "Bild";
  img.className = "stage-media";
  img.onload = () => {
    const dur = Number(item.duration ?? DEFAULT_DURATION);
    scheduleNext(dur * 1000);
  };
  img.onerror = ()=> onLoadErrorSkip("Bild");
  stage.appendChild(img);
}

function renderVideo(item){
  const stage = qs("#stage");
  const vid = document.createElement("video");
  vid.src = item.url || item.path;
  vid.autoplay = true;
  vid.controls = false;
  vid.loop = false;
  vid.muted = true;
  vid.playsInline = true;
  vid.className = "stage-media";
  vid.onended = () => nextItem(false);
  vid.onerror = ()=> onLoadErrorSkip("Video");

  stage.appendChild(vid);

  const p = vid.play();
  if (p && typeof p.then === "function"){
    p.catch(()=> {
      showStatus("Autoplay blockiert – bitte Play drücken");
      playing = false;
      const btn = qs("#btn-playpause");
      if (btn) btn.textContent = "▶";
    });
  }
}

function renderFile(item){
  const stage = qs("#stage");
  const link = document.createElement("a");
  link.href = item.url || item.path || "#";
  link.textContent = item.filename || "Datei öffnen";
  link.target = "_blank";
  stage.appendChild(link);
  const dur = Number(item.duration ?? DEFAULT_DURATION);
  scheduleNext(dur * 1000);
}

function showCurrent(){
  clearStage();
  const stage = qs("#stage");

  if (!feed.length){
    if (stage) stage.innerHTML = "<p>Keine aktiven Medien in der Playlist.</p>";
    scheduleNext(5000);
    return;
  }

  const item = feed[idx];
  const k = kindOf(item);

  if (nextPreload && (k === "image" && nextPreload.tagName === "IMG")){
    stage.appendChild(nextPreload);
    if (nextPreload.complete) {
      const dur = Number(item.duration ?? DEFAULT_DURATION);
      scheduleNext(dur * 1000);
    } else {
      nextPreload.onload = () => {
        const dur = Number(item.duration ?? DEFAULT_DURATION);
        scheduleNext(dur * 1000);
      };
    }
  } else if (k === "image"){
    renderImage(item);
  } else if (k === "video"){
    renderVideo(item);
  } else {
    renderFile(item);
  }

  preloadNext();
}

function nextItem(forceApplyUpdate){
  if (pendingUpdate || forceApplyUpdate){
    pendingUpdate = false;
    if (idx >= feed.length) idx = 0;
  }else{
    if (!feed.length) { showCurrent(); return; }
    idx = (idx + 1) % feed.length;
  }
  showCurrent();
}

function prevItem(){
  if (!feed.length){ showCurrent(); return; }
  idx = (idx - 1 + feed.length) % feed.length;
  showCurrent();
}

function togglePlay(){
  playing = !playing;
  const btn = qs("#btn-playpause");
  if (playing){
    if (btn) btn.textContent = "⏯";
    if (!timer) showCurrent();
    const v = qs("#stage video"); if (v) v.play().catch(()=>{});
  }else{
    if (btn) btn.textContent = "▶";
    if (timer){ clearTimeout(timer); timer = null; }
    const v = qs("#stage video"); if (v) v.pause();
  }
}

async function toggleFullscreen(){
  try{
    if (!document.fullscreenElement){
      if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
      else if (document.documentElement.webkitRequestFullscreen) document.documentElement.webkitRequestFullscreen();
      else if (document.documentElement.msRequestFullscreen) document.documentElement.msRequestFullscreen();
    }else{
      if (document.exitFullscreen) await document.exitFullscreen();
      else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
      else if (document.msExitFullscreen) document.msExitFullscreen();
    }
  }catch{}
}

function onVisibilityChanged(){
  if (document.hidden){
    if (timer){ clearTimeout(timer); timer = null; }
    const v = qs("#stage video"); if (v) v.pause();
  } else {
    if (playing && !timer) showCurrent();
  }
}

function bindControls(){
  if (IS_KIOSK) return;

  qs("#btn-next")?.addEventListener("click", ()=> nextItem(true));
  qs("#btn-prev")?.addEventListener("click", prevItem);
  qs("#btn-playpause")?.addEventListener("click", togglePlay);
  qs("#btn-full")?.addEventListener("click", toggleFullscreen);

  document.addEventListener("keydown", (e)=>{
    if (e.target && ["INPUT","TEXTAREA"].includes(e.target.tagName)) return;
    if (e.code === "Space"){ e.preventDefault(); togglePlay(); }
    else if (e.code === "ArrowRight"){ e.preventDefault(); nextItem(true); }
    else if (e.code === "ArrowLeft"){ e.preventDefault(); prevItem(); }
    else if (e.key?.toLowerCase() === "f"){ e.preventDefault(); toggleFullscreen(); }
  });
}

function startClock(){
  const el = qs("#clock");
  if (!el) return;
  function tick(){
    const now = new Date();
    const hh = now.getHours().toString().padStart(2,"0");
    const mm = now.getMinutes().toString().padStart(2,"0");
    el.textContent = `${hh}:${mm}`;
  }
  tick();
  setInterval(tick, 1000 * 30);
}

async function start(){
  const dd = Number(qs("#stage")?.dataset.defaultDuration);
  if (Number.isFinite(dd) && dd > 0) { DEFAULT_DURATION = dd; }

  bindControls();
  if (!IS_KIOSK) {
    document.addEventListener("visibilitychange", onVisibilityChanged);
    startClock();
  }

  await loadFeed(true);
  preloadNext();
  showCurrent();
  startPolling();
}

document.addEventListener("DOMContentLoaded", start);
