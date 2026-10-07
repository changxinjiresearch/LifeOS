const DEFAULTS = {
  endpoint: "http://127.0.0.1:47123",
  bridgeEndpoint: "http://127.0.0.1:47124",
  token: "",
  autoSync: true,
  autoThreshold: 0.88
};
const GENERATION = "local-v0.1.4-batch-project-status";
const CAL_COMPAT_PREFIX = "__NP_CAL_V1__:";

async function getConfig() {
  return {...DEFAULTS, ...(await chrome.storage.local.get(DEFAULTS))};
}
async function readJson(res) { try { return await res.json(); } catch { return {}; } }

async function bootstrapSession() {
  const cfg = await getConfig();
  let res;
  try {
    res = await fetch(`${cfg.bridgeEndpoint}/bridge/bootstrap`, {
      method: "POST", cache: "no-store",
      headers: {"Content-Type":"application/json","X-NextPlan-Extension-Id":chrome.runtime.id},
      body: "{}"
    });
  } catch { throw new Error("Open NextPlan Desktop to connect"); }
  const body = await readJson(res);
  if (!res.ok) {
    if (res.status === 403) throw new Error("This is not the official NextPlan Local Bridge build");
    if (res.status === 503) throw new Error("NextPlan Desktop is starting. Try again in a moment.");
    throw new Error(body.error || `Desktop bridge HTTP ${res.status}`);
  }
  if (!body.token || !body.endpoint) throw new Error("Desktop bridge returned an incomplete session");
  const endpoint = String(body.endpoint).replace(/\/$/, "");
  await chrome.storage.local.set({token:body.token,endpoint,lastBootstrap:new Date().toISOString()});
  return {...cfg,token:body.token,endpoint};
}

async function api(path, options = {}, requireAuth = true, allowRetry = true) {
  let cfg = await getConfig();
  if (requireAuth && !cfg.token) cfg = await bootstrapSession();
  const headers = {"Content-Type":"application/json",...(options.headers||{})};
  if (requireAuth) headers.Authorization = `Bearer ${cfg.token}`;
  let res;
  try { res = await fetch(`${cfg.endpoint}${path}`, {...options,headers,cache:"no-store"}); }
  catch {
    if (requireAuth && allowRetry) {
      await chrome.storage.local.set({token:""});
      await bootstrapSession();
      return api(path, options, requireAuth, false);
    }
    throw new Error("NextPlan Desktop is not reachable");
  }
  const body = await readJson(res);
  if ((res.status===401 || res.status===403) && requireAuth && allowRetry) {
    await chrome.storage.local.set({token:""});
    await bootstrapSession();
    return api(path, options, requireAuth, false);
  }
  if (!res.ok) throw new Error(body.detail || body.error || `HTTP ${res.status}`);
  return body;
}

async function getPending(){ const r=await api("/pending"); return r.pending||[]; }
async function refreshBadge(){
  let items=[]; try{items=await getPending();}catch{}
  await chrome.action.setBadgeText({text:items.length?String(Math.min(items.length,99)):""});
  await chrome.action.setBadgeBackgroundColor({color:"#3478F6"});
  return items;
}
async function connectDesktop(){
  const cfg=await getConfig(); if(!cfg.token) await bootstrapSession();
  await api("/state"); const health=await api("/healthz",{},false); await refreshBadge();
  const cur=await getConfig(); return {status:"connected",endpoint:cur.endpoint,runtime:health.runtime||"nextplan-local-core"};
}
async function seen(fp){ const {processedFingerprints=[]}=await chrome.storage.local.get({processedFingerprints:[]}); return processedFingerprints.includes(`${GENERATION}:${fp}`); }
async function remember(fp){
  const {processedFingerprints=[]}=await chrome.storage.local.get({processedFingerprints:[]});
  const key=`${GENERATION}:${fp}`;
  if(!processedFingerprints.includes(key)) await chrome.storage.local.set({processedFingerprints:[...processedFingerprints,key].slice(-300)});
}
function clientContext(){
  let timezone=""; try{timezone=Intl.DateTimeFormat().resolvedOptions().timeZone||"";}catch{}
  return {source:"nextplan-local-extension",bridgeVersion:"0.1.4",now:new Date().toISOString(),timezone,utcOffsetMinutes:-new Date().getTimezoneOffset()};
}
function normalizeCommandText(text){
  return String(text||"")
    .replace(/next\s*plan\s*[：:]\s*/gi,"NextPlan ")
    .replace(/((?:新增|新建|创建|添加)\s*(?:一个)?\s*(?:新)?项目)(?=[^\s：:，。])/gi,"$1 ")
    .trim();
}
function cleanName(value){
  return String(value||"").trim()
    .replace(/^[\s“”"'「」『』【】]+|[\s“”"'「」『』【】]+$/g,"")
    .replace(/\s*项目$/i,"").trim();
}
function nameKey(value){return cleanName(value).replace(/\s+/g,"").toLocaleLowerCase();}
function statusValue(raw){
  const s=String(raw||"").trim().toLocaleLowerCase();
  if(["active","进行中","正在进行","已开始"].includes(s))return"active";
  if(["waiting","等待","待定"].includes(s))return"waiting";
  if(["planned","计划中","未开始","尚未开始"].includes(s))return"planned";
  if(["completed","done","已完成","完成"].includes(s))return"completed";
  if(["blocked","阻塞","暂停"].includes(s))return"blocked";
  return"";
}
function parseProjectStatusCommands(text){
  const source=normalizeCommandText(text).replace(/^NextPlan\s*/i,"").trim();
  const statusWords="active|waiting|planned|completed|done|blocked|进行中|正在进行|已开始|等待|待定|计划中|未开始|尚未开始|已完成|完成|阻塞|暂停";
  const pattern=new RegExp("(?:把|将)\\s*(.+?)\\s*(?:(?:这|这些|这几个|\\d+个|[一二三四五六七八九十两]+个)\\s*)?(?:项目)?\\s*(?:的)?\\s*(?:状态)?\\s*(?:全部|都)?\\s*(?:更新为|更新成|设置为|设为|改成|改为|标记为|设置成)\\s*("+statusWords+")","i");
  const m=source.match(pattern);
  if(!m)return[];
  const status=statusValue(m[2]);if(!status)return[];
  const rawTargets=String(m[1]||"").trim();
  const quoted=[...rawTargets.matchAll(/[“"「『]([^”"」』]+)[”"」』]/g)].map(x=>cleanName(x[1])).filter(Boolean);
  const names=quoted.length?quoted:rawTargets.split(/\s*(?:、|，|,|；|;|和|与|及)\s*/).map(cleanName).filter(Boolean);
  const unique=[];const seenNames=new Set();
  for(const name of names){const key=nameKey(name);if(key&&!seenNames.has(key)){seenNames.add(key);unique.push({name,status});}}
  return unique;
}
function localDateISO(date){return `${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,"0")}-${String(date.getDate()).padStart(2,"0")}`;}
function parseCalendarDate(text){
  const now=new Date(); let m=text.match(/(20\d{2})年(\d{1,2})月(\d{1,2})日/);
  if(m){const d=new Date(Number(m[1]),Number(m[2])-1,Number(m[3]));return Number.isNaN(d.getTime())?"":localDateISO(d);}
  m=text.match(/(?<!\d)(\d{1,2})月(\d{1,2})日/);
  if(m){let d=new Date(now.getFullYear(),Number(m[1])-1,Number(m[2]));if(d.getTime()<new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime()-86400000)d=new Date(now.getFullYear()+1,Number(m[1])-1,Number(m[2]));return Number.isNaN(d.getTime())?"":localDateISO(d);}
  const d=new Date(now.getFullYear(),now.getMonth(),now.getDate());
  if(text.includes("后天"))d.setDate(d.getDate()+2); else if(text.includes("明天"))d.setDate(d.getDate()+1); else if(!text.includes("今天"))return"";
  return localDateISO(d);
}
function parseCalendarTime(text){
  let m=text.match(/\b([01]?\d|2[0-3]):([0-5]\d)\s*(am|pm)?\b/i);
  if(m){let h=Number(m[1]);const min=Number(m[2]),ap=String(m[3]||"").toLowerCase();if(ap==="pm"&&h<12)h+=12;if(ap==="am"&&h===12)h=0;return `${String(h).padStart(2,"0")}:${String(min).padStart(2,"0")}`;}
  m=text.match(/(上午|早上|中午|下午|晚上|傍晚)?\s*(\d{1,2})点(半|([0-5]?\d)分?)?/);if(!m)return"";
  const period=m[1]||"";let h=Number(m[2]);const min=m[3]==="半"?30:Number(m[4]||0);
  if(["下午","晚上","傍晚"].includes(period)&&h<12)h+=12; else if(period==="中午"&&h>=1&&h<11)h+=12; else if(["上午","早上"].includes(period)&&h===12)h=0;
  return h<=23&&min<=59?`${String(h).padStart(2,"0")}:${String(min).padStart(2,"0")}`:"";
}
function parseCalendarCommand(text){
  const source=normalizeCommandText(text);
  if(!/(next\s*plan|记录|记一下|日历|calendar|加入|添加)/i.test(source))return null;
  if(!/(meeting|会议|约会|appointment|presentation|提醒|reminder)/i.test(source))return null;
  const date=parseCalendarDate(source);if(!date)return null; const time=parseCalendarTime(source);
  let title="Meeting";
  const afterHave=source.match(/有(?:一个|个)?\s*[“"「『]?([^”"」』，。]+?)[”"」』]?\s*(?:[。！!]|$)/i);
  if(afterHave)title=cleanName(afterHave[1]); else if(/导师/.test(source)&&/meeting|会议|见面/i.test(source))title="与导师 Meeting"; else if(/presentation|汇报/i.test(source))title="Presentation"; else if(/提醒|reminder/i.test(source))title="Reminder";
  const kind=/presentation|汇报/i.test(source)?"presentation":/提醒|reminder/i.test(source)?"reminder":/appointment|约会/i.test(source)?"appointment":"meeting";
  return {title:title||"Meeting",date,time,kind,timezone:clientContext().timezone||"",category:"其他"};
}
function compatCalendarTitle(event){return CAL_COMPAT_PREFIX+encodeURIComponent(JSON.stringify({title:event.title,time:event.time||"",timezone:event.timezone||"",kind:event.kind||"event",category:event.category||"其他"}));}

async function directProjectStatus(text){
  const parsed=parseProjectStatusCommands(text);if(!parsed.length)return null;
  const state=await api("/state");
  const resolved=parsed.map(item=>({item,project:(state.projects||[]).find(p=>nameKey(p.name)===nameKey(item.name))}));
  const missing=resolved.filter(x=>!x.project).map(x=>x.item.name);
  if(missing.length)return{status:"error",error:`Project not found: ${missing.join("、")}`};
  const updates=resolved.map(x=>({project_id:x.project.id,status:x.item.status}));
  const targetStatus=parsed[0].status;
  const changed=resolved.filter(x=>String(x.project.status||"")!==targetStatus);
  if(!changed.length)return{status:"informational",label:`${resolved.length} 个项目状态已是 ${targetStatus}`};
  const receipt=await api("/actions/execute",{method:"POST",body:JSON.stringify({action:{action:"batch_update_project_status",updates,source_command:text}})});
  return{status:"auto_synced",label:`批量更新项目状态：${changed.length} 项 → ${targetStatus}`,receipt,projects:changed.map(x=>x.project.name)};
}
async function directCalendarWrite(text){
  const event=parseCalendarCommand(text);if(!event)return null;
  try{
    const receipt=await api("/actions/execute",{method:"POST",body:JSON.stringify({action:{action:"upsert_calendar_event",...event}})});
    return{status:"auto_synced",label:`记录日历：${event.title} · ${event.date}${event.time?` ${event.time}`:""}`,receipt};
  }catch(err){const message=String(err?.message||"");if(!/unsupported local action|unsupported.*upsert_calendar_event/i.test(message))throw err;}
  const receipt=await api("/actions/execute",{method:"POST",body:JSON.stringify({action:{action:"set_deadline",project_id:"calendar",title:compatCalendarTitle(event),date:event.date}})});
  return{status:"auto_synced",label:`记录日历：${event.title} · ${event.date}${event.time?` ${event.time}`:""}`,receipt,compatibility:"calendar-event-v1"};
}
async function recordDirectResult(fp,result){if(!result)return null;if(result.status==="auto_synced")await chrome.storage.local.set({lastSync:{at:new Date().toISOString(),label:result.label,result:result.receipt?.status||"applied"}});await remember(fp);return result;}

async function handleTurn(turn){
  if(await seen(turn.fingerprint))return{status:"duplicate"};
  const normalizedTurn={...turn,userText:normalizeCommandText(turn.userText)};
  try{
    const ps=await directProjectStatus(normalizedTurn.userText);if(ps)return await recordDirectResult(turn.fingerprint,ps);
    const cal=await directCalendarWrite(normalizedTurn.userText);if(cal)return await recordDirectResult(turn.fingerprint,cal);
  }catch(err){const message=String(err?.message||"Connection failed");return{status:message.includes("Open NextPlan Desktop")||message.includes("not reachable")?"needs_desktop":"error",error:message};}
  let result;
  try{result=await api("/conversation/capture",{method:"POST",body:JSON.stringify({turn:normalizedTurn,client:clientContext(),apply:true})});}
  catch(err){const message=String(err?.message||"Connection failed");return{status:message.includes("Open NextPlan Desktop")||message.includes("not reachable")?"needs_desktop":"error",error:message};}
  const candidate=result?.candidate||null;
  if(!candidate){await remember(turn.fingerprint);return{status:"no_change"};}
  if(candidate.informational||!candidate.action){await remember(turn.fingerprint);return{status:"informational",label:candidate.label||"No change needed"};}
  if(result.receipt){await remember(turn.fingerprint);await chrome.storage.local.set({lastSync:{at:new Date().toISOString(),label:candidate.label,result:result.receipt.status}});return{status:"auto_synced",label:candidate.label,receipt:result.receipt};}
  await refreshBadge();await remember(turn.fingerprint);return{status:"queued",label:candidate.label,confidence:candidate.confidence,requiresConfirmation:Boolean(candidate.requiresConfirmation),kind:candidate.kind};
}
async function applyPending(id){const receipt=await api("/pending/apply",{method:"POST",body:JSON.stringify({id})});await refreshBadge();await chrome.storage.local.set({lastSync:{at:new Date().toISOString(),label:receipt.summary||id,result:receipt.status}});return receipt;}
async function ignorePending(id){const result=await api("/pending/ignore",{method:"POST",body:JSON.stringify({id})});await refreshBadge();return result;}
async function statusSnapshot(){
  let connectionError=null,runtime=null;try{const connected=await connectDesktop();runtime=connected.runtime;}catch(err){connectionError=err.message;}
  const config=await getConfig();let pending=[];if(!connectionError){try{pending=await getPending();}catch(err){connectionError=err.message;}}
  const {lastSync=null}=await chrome.storage.local.get({lastSync:null});return{connected:!connectionError,paired:!connectionError,connectionError,runtime,endpoint:config.endpoint,pending,lastSync,mode:"desktop-auto-bootstrap",version:"0.1.4"};
}
chrome.runtime.onInstalled.addListener(async()=>{const current=await chrome.storage.local.get(Object.keys(DEFAULTS));await chrome.storage.local.set({...DEFAULTS,...current,token:""});try{await connectDesktop();}catch{}});
chrome.runtime.onStartup.addListener(async()=>{await chrome.storage.local.set({token:""});try{await connectDesktop();}catch{}});
chrome.runtime.onMessage.addListener((message,_sender,sendResponse)=>{
  if(message?.type==="NEXTPLAN_TURN"){handleTurn(message.turn).then(sendResponse).catch(err=>sendResponse({status:"error",error:err.message}));return true;}
  if(message?.type==="NEXTPLAN_CONNECT"||message?.type==="NEXTPLAN_PAIR"){connectDesktop().then(sendResponse).catch(err=>sendResponse({status:"error",error:err.message}));return true;}
  if(message?.type==="NEXTPLAN_GET_STATUS"){statusSnapshot().then(sendResponse).catch(err=>sendResponse({connected:false,paired:false,connectionError:err.message,pending:[]}));return true;}
  if(message?.type==="NEXTPLAN_APPLY"){applyPending(message.id).then(sendResponse).catch(err=>sendResponse({status:"error",error:err.message}));return true;}
  if(message?.type==="NEXTPLAN_IGNORE"){ignorePending(message.id).then(sendResponse).catch(err=>sendResponse({status:"error",error:err.message}));return true;}
  if(message?.type==="NEXTPLAN_TEST"){connectDesktop().then(sendResponse).catch(err=>sendResponse({status:"error",error:err.message}));return true;}
});
