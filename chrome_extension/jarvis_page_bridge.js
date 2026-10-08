/* Isolated extension content script for the exact NextPlan Jarvis page.
 * Cannot expose extension credentials to the webpage. Sensitive capture payload
 * crosses into the page only after a direct user click in the page's import UI.
 */
(()=>{
  const ORIGIN="https://changxinjiresearch.github.io";
  if(location.origin!==ORIGIN||location.pathname!=="/LifeOS-App/jarvis.html")return;
  const allowed=new Set(["NEXTPLAN_JARVIS_STATE","NEXTPLAN_JARVIS_QUEUE",
    "NEXTPLAN_JARVIS_CAPTURES","NEXTPLAN_JARVIS_CAPTURE_ACK"]);
  window.addEventListener("message",async event=>{
    if(event.source!==window||event.origin!==ORIGIN)return;
    const body=event.data;
    if(!body||body.channel!=="nextplan-jarvis-to-extension"||
        !allowed.has(body.type)||typeof body.requestId!=="string"||
        !/^[a-zA-Z0-9-]{8,80}$/.test(body.requestId))return;
    try{
      const result=await chrome.runtime.sendMessage({type:body.type,
        proposal:body.proposal,id:body.id});
      window.postMessage({channel:"nextplan-extension-to-jarvis",
        requestId:body.requestId,result},ORIGIN);
    }catch(e){
      window.postMessage({channel:"nextplan-extension-to-jarvis",
        requestId:body.requestId,result:{status:"error",reason:"extension_unavailable"}},ORIGIN);
    }
  });
  window.postMessage({channel:"nextplan-extension-to-jarvis",ready:true},ORIGIN);
})();
