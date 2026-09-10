const list = document.getElementById("list");
const statusEl = document.getElementById("status");
function esc(s){return String(s||"").replace(/[&<>\"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'\"':"&quot;","'":"&#39;"}[c]));}
async function refresh(){
  const data=await chrome.runtime.sendMessage({type:"NEXTPLAN_GET_STATUS"});
  if(!data.configured){statusEl.textContent="未完成一次性连接设置";list.innerHTML='<div class="card"><div class="item-title">先连接 NextPlan 后端</div><div class="reason">打开设置，生成一个浏览器 Token，并把同一 Token 保存到 Railway。</div></div>';return;}
  statusEl.textContent=data.autoSync?`自动同步已开启 · 阈值 ${Math.round(data.autoThreshold*100)}%`:"仅候选确认模式";
  const items=data.pending||[];
  if(!items.length){list.innerHTML='<div class="empty">没有待确认的状态变化。</div>';return;}
  list.innerHTML=items.map(x=>`<div class="card" data-id="${esc(x.id)}"><div class="item-title">${esc(x.label)}</div><div class="reason">${esc(x.reason)} · 置信度 ${Math.round((x.confidence||0)*100)}%</div><div class="actions"><button class="primary" data-act="apply">同步</button><button class="secondary" data-act="ignore">忽略</button></div></div>`).join("");
}
list.addEventListener("click",async e=>{const btn=e.target.closest("button");if(!btn)return;const card=btn.closest("[data-id]");const id=card?.dataset.id;if(!id)return;btn.disabled=true;if(btn.dataset.act==="apply")await chrome.runtime.sendMessage({type:"NEXTPLAN_APPLY",id});else await chrome.runtime.sendMessage({type:"NEXTPLAN_IGNORE",id});await refresh();});
document.getElementById("options").onclick=e=>{e.preventDefault();chrome.runtime.openOptionsPage();};
document.getElementById("refresh").onclick=e=>{e.preventDefault();refresh();};
refresh();
