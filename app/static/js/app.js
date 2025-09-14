// static/js/app.js
console.log("SlidePi app.js loaded");

/**
 * Upload mit Drag & Drop oder Dateiauswahl
 * Backend: /media/upload (erwartet 'file')
 * Ergebnis: Logzeilen + Reload der Medienliste
 */

// Helper
function $(sel){ return document.querySelector(sel); }

document.addEventListener("DOMContentLoaded", ()=>{
  const input = $("#file-input");
  const dropzone = $("#dropzone");
  const logEl = $("#upload-log");
  const uploadUrl = "/media/upload";

  function ensureLogVisible(){ if(logEl) logEl.hidden = false; }
  function addLogLine(name, status){
    ensureLogVisible();
    const li = document.createElement("li");
    li.innerHTML = `<strong>${name}</strong> — <span class="st">${status}</span>`;
    logEl.appendChild(li);
    return li.querySelector(".st");
  }

  async function uploadOne(file){
    const statusEl = addLogLine(file.name, "Lade hoch …");
    const fd = new FormData();
    fd.append("file", file, file.name);
    try{
      const res = await fetch(uploadUrl, { method: "POST", body: fd });
      if(res.redirected || res.ok){
        statusEl.textContent = "fertig";
      }else{
        statusEl.textContent = "Fehler (" + res.status + ")";
      }
    }catch(err){
      console.error(err);
      statusEl.textContent = "Netzwerkfehler";
    }
  }

  async function uploadMany(files){
    if(!files || !files.length) return;
    for(const f of files){
      if(!/^image\//.test(f.type) && !/^video\//.test(f.type)){
        addLogLine(f.name, "übersprungen (nicht erlaubt)");
        continue;
      }
      await uploadOne(f);
    }
    // nach Abschluss neu laden
    try{ location.reload(); }catch(_e){}
  }

  if(input){
    input.addEventListener("change", (e)=> uploadMany(e.target.files));
  }

  if(dropzone){
    ["dragenter","dragover"].forEach(ev=>{
      dropzone.addEventListener(ev, e=>{
        e.preventDefault();
        dropzone.classList.add("is-hover");
      }, {passive:false});
    });
    ["dragleave","drop"].forEach(ev=>{
      dropzone.addEventListener(ev, e=>{
        e.preventDefault();
        dropzone.classList.remove("is-hover");
      }, {passive:false});
    });
    dropzone.addEventListener("drop", e=>{
      e.preventDefault();
      const files = e.dataTransfer?.files ? e.dataTransfer.files : [];
      uploadMany(files);
    });
  }
});
