const defaults = {
  homeName: 'LOCAL', awayName: 'VISITA', homeScore: '--', awayScore: '--',
  homeLogo: '', awayLogo: '', eventLogo: '', period: '--', clock: '--:--', shotClock: '',
  tournament: 'PANEL GO', category: '',
};
const liveKeys = ['clock','homeScore','awayScore','period'];
const params = new URLSearchParams(location.search);
const liveMode = params.get('live') !== '0';
const storageKey = 'panelgo-tablero-settings-v1';
var switcherName = 'OBS';
function savedSettings() { try { return JSON.parse(localStorage.getItem(storageKey) || '{}'); } catch { return {}; } }
const state = {...defaults, ...savedSettings()};
for (const [key,value] of params) if (key in defaults && (!liveMode || !liveKeys.includes(key))) state[key] = value;
if (liveMode) for (const key of liveKeys) state[key] = defaults[key];
let lastFeed = null, lastEvent = 0, polling = false;
let remoteMonitorsActive = false, lastLocalEvent = 0;
let programStream=null;

function render() {
  document.querySelectorAll('[data-bind]').forEach(node => {
    const value = state[node.dataset.bind] || '';
    if (node.textContent !== value) node.textContent = value;
  });
  document.querySelectorAll('[data-logo]').forEach(img => {
    const value = state[img.dataset.logo] || '';
    img.hidden = !value;
    if (value && img.getAttribute('src') !== value) img.src = value;
    const holder=img.closest('.team-logo'); if(holder) holder.hidden = false;
  });
  document.querySelectorAll('input:not([type=file])').forEach(input => {
    if (input.id in state && document.activeElement !== input) input.value = state[input.id];
    if (liveMode && liveKeys.includes(input.id)) {input.readOnly = true; input.title = 'Lectura automática del tablero';}
  });
  const link = document.getElementById('rendererLink');
  if (link) {
    const query = new URLSearchParams(Object.fromEntries(Object.entries(state).filter(([k,v]) => v && v.length < 1000 && !liveKeys.includes(k))));
    query.set('live', liveMode ? '1' : '0');
    link.href = 'graphics.html?' + query;
  }
}
function showHealth() {
  if (!liveMode) return;
  const elapsed = Date.now() - lastEvent;
  const healthy = lastFeed && elapsed < 4000 && lastFeed.connected && ['ok','standby'].includes(lastFeed.ocrStatus);
  document.body.classList.toggle('feed-stale', !healthy);
  const status = document.getElementById('liveStatus');
  if (status) {
    status.textContent = elapsed > 4000 ? 'Sin actualización del lector' : (lastFeed?.status || 'Esperando lectura del tablero');
    status.dataset.ok = String(Boolean(healthy));
  }
  document.querySelectorAll('[data-bind]').forEach(node => {
    const key = node.dataset.bind;
    if (liveKeys.includes(key)) node.classList.toggle('value-stale', !lastFeed?.fields?.[key]?.valid || elapsed > 4000);
  });
  const stamp = document.getElementById('lastCapture');
  if (stamp) stamp.textContent = lastFeed?.updatedAt ? 'Captura: ' + new Date(lastFeed.updatedAt).toLocaleTimeString('es-AR') : 'Sin capturas';
}
function acceptFeed(live, local=false) {
  if(!local && Date.now()-lastLocalEvent<2500)return;
  if(local)lastLocalEvent=Date.now();
  if (!liveMode || live.service !== 'panelgo-tablero') return;
  lastFeed = live; lastEvent = Date.now();
  for (const key of liveKeys) if (typeof live[key] === 'string') state[key] = live[key];
  render(); showHealth();
  for (const [key,id] of Object.entries({clock:'liveClock',homeScore:'liveHome',awayScore:'liveAway',period:'livePeriod'})) {
    const node = document.getElementById(id);
    if (node) {node.textContent = state[key];node.classList.toggle('value-stale',!live.fields?.[key]?.valid);}
  }
  updateMonitors(live);
}
function updateMonitors(live) {
  if(remoteMonitorsActive && !live.gameMode)return;
  const game = document.getElementById('gamePreview');
  const gameStatus = document.getElementById('gameStatus');
  const gameLabel = document.getElementById('gameLabel'); if (gameLabel) gameLabel.textContent = live.gameLabel ? '02 / '+live.gameLabel : live.gameView === 'program' ? '02 / Salida de '+switcherName : '02 / Cancha';
  const continuous = live.gameMode === 'continuous';
  const player = document.getElementById('gameVideo');
  if (player) player.hidden = !continuous;
  if (player && continuous && player.dataset.enabled !== 'true') {
    player.dataset.enabled = 'true';
    customElements.whenDefined('club-game').then(() => { player.src = '/video/ws'; });
  }
  if (continuous && game) game.hidden = true;
  if (gameStatus && !continuous && !programStream) gameStatus.textContent = live.gameConnected ? (live.gameView === 'program' ? 'Programa · sin audio' : 'Capturas de respaldo') : (live.gameStatus || 'Sin actualización');
  if (gameStatus && continuous && !live.gameReady) gameStatus.textContent = live.gameStatus || 'Preparando video continuo';
  if (game && !continuous && !programStream) {
    game.classList.toggle('value-stale', !live.gameConnected);
    if (live.gameImage && live.gameRevision && game.dataset.revision !== String(live.gameRevision)) {
      game.hidden = false; game.src = live.gameImage + '?r=' + live.gameRevision; game.dataset.revision = live.gameRevision;
    }
  }
  const preview = document.getElementById('boardPreview');
  if (preview && live.updatedAt && preview.dataset.revision !== String(live.revision)) {
    preview.hidden = false;preview.src = (live.boardImage || 'board.png') + '?t=' + live.revision;preview.dataset.revision = live.revision;
  }
}
async function poll() {
  if (polling || !liveMode) return;
  polling = true;
  try {
    const r = await fetch('api/state', {cache:'no-store',signal:AbortSignal.timeout(2500)});
    if (r.ok) acceptFeed(await r.json());
  } catch {showHealth();} finally {polling = false;}
}
function persist() {
  const config = Object.fromEntries(Object.entries(state).filter(([key]) => !liveKeys.includes(key)));
  if (!liveMode) Object.assign(config, Object.fromEntries(liveKeys.map(k => [k,state[k]])));
  localStorage.setItem(storageKey, JSON.stringify(config));
  scheduleOBSSettings();
}
document.querySelectorAll('[data-scorebug]').forEach(target => target.replaceChildren(document.getElementById('scorebugTemplate').content.cloneNode(true)));
document.querySelectorAll('input:not([type=file])').forEach(input => input.addEventListener('input', () => {
  if (input.id in state && !(liveMode && liveKeys.includes(input.id))) {state[input.id] = input.value.trim();persist();render();}
}));
for (const [id,key] of Object.entries({homeLogoFile:'homeLogo',awayLogoFile:'awayLogo',eventLogoFile:'eventLogo'})) {
  document.getElementById(id)?.addEventListener('change', e => {
    if (!e.target.files?.[0]) return;
    const reader = new FileReader();reader.onload = () => {state[key] = reader.result;persist();render();};reader.readAsDataURL(e.target.files[0]);
  });
}
window.addEventListener('storage', e => {if (e.key === storageKey) {Object.assign(state,savedSettings());render();}});
function fitStage() {
  document.querySelectorAll('.stage-preview,.stage-render').forEach(stage => {
    const parent = stage.classList.contains('stage-render') ? document.documentElement : stage.parentElement;
    const width = parent.clientWidth, height = stage.classList.contains('stage-render') ? innerHeight : Math.min(500, width*1080/1920);
    const scale = Math.min(width/1920,height/1080);
    stage.style.transform = stage.classList.contains('stage-render') ? `translate(-50%,-50%) scale(${scale})` : `scale(${scale})`;
    if (stage.classList.contains('stage-preview')) { const compact=innerWidth>1000&&innerWidth<=1400&&innerHeight<=850; stage.style.top = `${-(compact?890:820)*scale}px`; stage.parentElement.style.height = `${(compact?120:260)*scale}px`; }
  });
}
render();fitStage();window.addEventListener('resize',fitStage);
if (liveMode) {
  poll();
  const events = new EventSource('api/events');
  events.onmessage = event => {try {acceptFeed(JSON.parse(event.data));} catch {}};
  setInterval(() => {if (Date.now()-lastEvent > 2000) poll();showHealth();},1000);
} else {
  document.getElementById('liveStatus')?.replaceChildren('Modo manual');
}

// Responsive settings drawer keeps desktop controls visible and small screens compact.
const settingsDrawer = document.querySelector('.settings-drawer');
function fitSettingsDrawer() { if (settingsDrawer) settingsDrawer.open = innerWidth > 700; }
fitSettingsDrawer(); window.addEventListener('resize',fitSettingsDrawer);

// Dedicated OBS graphic control: initial reads never change visibility.
const obsGraphicButton=document.getElementById('obsGraphicButton');
const obsGraphicStatus=document.getElementById('obsGraphicStatus');
let obsGraphicToken='',obsGraphicState=null,obsGraphicBusy=false;
async function refreshOBSGraphic() {
 if (!obsGraphicButton || obsGraphicBusy) return;
 try {
  const r=await fetch('http://127.0.0.1:8774/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});
  if(!r.ok)throw Error(); const s=await r.json();obsGraphicState=s;obsGraphicToken=s.token;
  const sw=s.switcher||'OBS';switcherName=sw;document.querySelectorAll('.monitor-video-button').forEach(b=>b.hidden=!(sw==='OBS'&&s.local!==false));
  if(s.safetyLocked&&!s.enabled){obsGraphicButton.disabled=true;obsGraphicButton.textContent='Prueba pausada';obsGraphicStatus.textContent='APAGADO EN '+sw.toUpperCase();return;}
  obsGraphicButton.disabled=false;
  obsGraphicButton.textContent=!s.ready?'Preparar en '+sw:s.enabled?'Ocultar de '+sw:'Mostrar en '+sw;
  obsGraphicButton.dataset.on=String(s.enabled);obsGraphicButton.setAttribute('aria-pressed',String(s.enabled));
  obsGraphicStatus.textContent=!s.ready?'Sin agregar':s.enabled?'VISIBLE EN '+sw.toUpperCase():'APAGADO EN '+sw.toUpperCase();
  obsGraphicStatus.dataset.on=String(s.enabled);
 } catch {obsGraphicButton.disabled=true;obsGraphicStatus.textContent='Control de '+switcherName+' sin conexión';}
}
obsGraphicButton?.addEventListener('click',async()=>{
 if(obsGraphicBusy)return;
 await refreshOBSGraphic();if(!obsGraphicState||!obsGraphicToken)return;
 obsGraphicBusy=true;obsGraphicButton.disabled=true;
 try{
  if (!obsGraphicState.enabled && !(await syncOBSSettings())) throw Error();
  const route=obsGraphicState.ready?'visibility':'install';
  const r=await fetch('http://127.0.0.1:8774/'+route,{method:'POST',headers:{'Content-Type':'application/json','X-Panel-Token':obsGraphicToken},body:JSON.stringify({enabled:!obsGraphicState.enabled}),signal:AbortSignal.timeout(12000)});
  if(!r.ok)throw Error();
 }catch{obsGraphicStatus.textContent='No se pudo cambiar en '+switcherName;}
 finally{obsGraphicBusy=false;await refreshOBSGraphic();}
});
if(obsGraphicButton){refreshOBSGraphic();setInterval(refreshOBSGraphic,3000);}

// Names and logos are explicitly shared with the OBS renderer, not only localStorage.
const obsSettingsButton=document.getElementById('obsSettingsButton');
let obsSettingsTimer=0;
async function syncOBSSettings() {
 if(!obsSettingsButton)return false;
 if(!obsGraphicToken)await refreshOBSGraphic();
 if(!obsGraphicToken){obsSettingsButton.textContent='Sin conexión con '+switcherName;return false;}
 obsSettingsButton.disabled=true;
 try{
  const settings=Object.fromEntries(['homeName','awayName','homeLogo','awayLogo','eventLogo','tournament','category'].map(k=>[k,state[k]||'']));
  const r=await fetch('http://127.0.0.1:8774/settings',{method:'POST',headers:{'Content-Type':'application/json','X-Panel-Token':obsGraphicToken},body:JSON.stringify(settings),signal:AbortSignal.timeout(5000)});
  if(!r.ok)throw Error();
  localStorage.setItem('panelgo-tablero-obs-linked','1');obsSettingsButton.textContent='Datos enviados a '+switcherName+' ✓';return true;
 }catch{obsSettingsButton.textContent='No se pudieron enviar los datos';return false;}
 finally{obsSettingsButton.disabled=false;}
}
function scheduleOBSSettings(){
 clearTimeout(obsSettingsTimer);obsSettingsTimer=setTimeout(syncOBSSettings,350);
}
obsSettingsButton?.addEventListener('click',syncOBSSettings);
if(localStorage.getItem(storageKey)&&localStorage.getItem('panelgo-tablero-obs-linked')!=='1')scheduleOBSSettings();

// A fresh installation inherits the saved match names and logos from its local controller.
if (!localStorage.getItem(storageKey)) {
 fetch('http://127.0.0.1:8774/settings',{signal:AbortSignal.timeout(5000)}).then(r=>r.ok?r.json():{}).then(settings=>{
  if(localStorage.getItem(storageKey)||!Object.keys(settings).length)return;
  for(const key of ['homeName','awayName','homeLogo','awayLogo','eventLogo','tournament','category'])if(typeof settings[key]==='string')state[key]=settings[key];
  localStorage.setItem(storageKey,JSON.stringify(Object.fromEntries(Object.entries(state).filter(([key])=>!liveKeys.includes(key)))));
  localStorage.setItem('panelgo-tablero-obs-linked','1');render();
 }).catch(()=>{});
}

// The hosted panel reads monitors only from the reader on this same PC.
if(location.hostname==='panelgo-tablero.onrender.com') {
 const note=document.querySelector('.cloud-note');
 const cameras=document.createElement('div');cameras.className='camera-pair';cameras.hidden=true;
 cameras.innerHTML='<figure><figcaption>01 / Tablero <small>Lectura automática · esta PC</small></figcaption><div class="camera-image"><img id="boardPreview" alt="Captura del tablero" hidden></div></figure><figure><figcaption><span id="gameLabel">02 / Salida de OBS</span> <small id="gameStatus">Conectando</small></figcaption><div class="camera-image"><img id="gamePreview" alt="Salida de OBS de esta PC" hidden></div></figure>';
 note?.before(cameras);
 if(note)note.textContent='Conectando con los monitores de esta PC. Mantené abierto el lector; si el navegador pide acceso a la red local, permitilo para este panel.';
 function acceptLocalState(local){
  if(local.service!=='panelgo-tablero')return;
  remoteMonitorsActive=true;cameras.hidden=false;if(note)note.hidden=true;
  cameras.querySelectorAll('img').forEach(img=>img.classList.remove('value-stale'));
  acceptFeed({...local,gameMode:'snapshots',gameImage:'http://127.0.0.1:8771/game.jpg',boardImage:'http://127.0.0.1:8771/board.png'},true);
 }
 let busy=false;
 const localEvents=new EventSource('http://127.0.0.1:8771/api/events');
 localEvents.onmessage=event=>{try{acceptLocalState(JSON.parse(event.data));}catch{}};
 async function pollLocalMonitors(){
  if(busy||Date.now()-lastLocalEvent<800)return;busy=true;
  try{
   const response=await fetch('http://127.0.0.1:8771/api/state',{cache:'no-store',signal:AbortSignal.timeout(2500)});
   if(!response.ok)throw Error();const local=await response.json();if(local.service!=='panelgo-tablero')throw Error();
   acceptLocalState(local);
  }catch{
   if(note){note.hidden=false;note.textContent='Monitores sin conexión con esta PC. Abrí el lector actualizado y permití el acceso a la red local si el navegador lo solicita.';}
   cameras.querySelectorAll('img').forEach(img=>img.classList.add('value-stale'));
  }finally{busy=false;}
 }
 pollLocalMonitors();setInterval(pollLocalMonitors,500);
}

// Live preview stays on this PC and captures only OBS Virtual Camera.
function mountProgramVideo(){
 const image=document.getElementById('gamePreview');if(!image)return;
 const frame=image.closest('.camera-image'),caption=frame?.previousElementSibling;if(!frame||!caption)return;
 const video=document.createElement('video');video.id='programLiveVideo';video.autoplay=true;video.muted=true;video.playsInline=true;video.hidden=true;frame.append(video);
 const button=document.createElement('button');button.type='button';button.className='monitor-video-button';button.textContent='Video fluido';caption.append(button);
 function stopPreview(){
  if(programStream)programStream.getTracks().forEach(track=>track.stop());
  programStream=null;video.srcObject=null;video.hidden=true;button.disabled=false;button.textContent='Video fluido';
 }
 button.addEventListener('click',async()=>{
  const status=document.getElementById('gameStatus');
  if(programStream){stopPreview();if(status)status.textContent='Capturas de respaldo';return;}
  button.disabled=true;let acquired=null;
  try{
   if(!navigator.mediaDevices?.getUserMedia)throw Error('Abrí el panel en Chrome o Edge actualizado.');
   if(status)status.textContent='Preparando video de OBS...';
   await refreshOBSGraphic();if(!obsGraphicToken)throw Error('Abrí el lector actualizado en esta PC.');
   const response=await fetch('http://127.0.0.1:8774/virtual-camera',{method:'POST',headers:{'Content-Type':'application/json','X-Panel-Token':obsGraphicToken},body:'{}',signal:AbortSignal.timeout(10000)});
   if(!response.ok)throw Error('Actualizá el lector con el BAT de video fluido.');
   let devices=await navigator.mediaDevices.enumerateDevices();
   const findOBS=()=>devices.find(device=>device.kind==='videoinput'&&/obs.*(virtual|camera)|obs-camera/i.test(device.label));
   let obsDevice=findOBS();
   if(!obsDevice){
    if(status)status.textContent='Permití el acceso a cámaras para encontrar OBS Virtual Camera.';
    const permission=await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    permission.getTracks().forEach(track=>track.stop());
    devices=await navigator.mediaDevices.enumerateDevices();obsDevice=findOBS();
   }
   if(!obsDevice)throw Error('No aparece OBS Virtual Camera. Revisá la instalación de OBS en esta PC.');
   acquired=await navigator.mediaDevices.getUserMedia({audio:false,video:{deviceId:{exact:obsDevice.deviceId},width:{ideal:1280},height:{ideal:720},frameRate:{ideal:25,max:30}}});
   programStream=acquired;video.srcObject=programStream;await video.play();
   video.hidden=false;image.hidden=true;button.textContent='Volver a capturas';
   const fps=programStream.getVideoTracks()[0]?.getSettings().frameRate;
   if(status)status.textContent='Video de OBS · '+(fps?Math.round(fps)+' fps · ':'')+'sin audio';
   programStream.getVideoTracks()[0]?.addEventListener('ended',()=>{stopPreview();if(status)status.textContent='Se desconectó el video de OBS';},{once:true});
  }catch(error){
   acquired?.getTracks().forEach(track=>track.stop());stopPreview();
   if(status)status.textContent=error.name==='NotAllowedError'?'Permití el acceso a cámaras para ver OBS.':error.message||'No se pudo abrir el video de OBS.';
  }finally{button.disabled=false;}
 });
 window.addEventListener('pagehide',stopPreview,{once:true});
}
mountProgramVideo();

// Refit when the compact grid settles after images and fonts are loaded.
const stageSizeObserver=new ResizeObserver(entries=>{
 const changed=entries.some(entry=>{
  const width=String(Math.round(entry.contentRect.width));
  if(entry.target.dataset.fitWidth===width)return false;
  entry.target.dataset.fitWidth=width;return true;
 });
 if(changed)fitStage();
});
document.querySelectorAll('.stage-frame').forEach(frame=>stageSizeObserver.observe(frame));
