/* NextPlan Jarvis v0.2: extension-owned user-consented context capture
 * and proposed canonical writes. No private text is ever sent to GitHub.
 * Site pages cannot obtain the extension backend bearer token.
 */
export const ALLOWED_WEB = "https://changxinjiresearch.github.io";
const MAX_PENDING = 30;
export function validJarvisSender(sender) {
  try {
    const u=new URL(sender?.url||"");
    return u.origin===ALLOWED_WEB && u.pathname==="/LifeOS-App/jarvis.html";
  }catch(_){return false;}
}
export function safeProposal(raw, project) {
  if(!raw||typeof raw!=="object"||!project)throw Error("Unknown project or proposal");
  if(raw.action!=="update_project_snapshot")throw Error("Only non-destructive project updates are supported");
  if(raw.project_id!==project.id)throw Error("Target project does not match canonical state");
  if(typeof raw.expected_status!=="string"||raw.expected_status!==project.status)
    throw Error("Stale project state; refresh before preparing action");
  const allowed=["status","next_action"];
  const changes=Object.keys(raw).filter(k=>allowed.includes(k));
  if(changes.length!==1)throw Error("Exactly one allowed field must change");
  if("status" in raw && !["planned","active","waiting","blocked","completed"].includes(raw.status))
    throw Error("Invalid project status");
  if("next_action" in raw && (typeof raw.next_action!=="string"||
      !raw.next_action.trim()||raw.next_action.length>500))
    throw Error("Invalid next action");
  if(raw.status===project.status||raw.next_action===project.next_action)
    throw Error("No change to queue");
  return {action:"update_project_snapshot",project_id:project.id,
          ...(raw.status?{status:raw.status}:{next_action:raw.next_action.trim()})};
}
export function captureItem(text,url,id) {
  if(typeof text!=="string"||!text.trim()||text.length>2500)
    throw Error("Select at most 2500 characters");
  const u=new URL(url);
  if(u.origin!=="https://chatgpt.com"||!u.pathname.startsWith("/"))
    throw Error("Can capture only from ChatGPT");
  return {id,summary:text.trim(),source_ref:u.origin+u.pathname,
    context_type:"observation",source_kind:"chatgpt_user_selection",
    captured_at:new Date().toISOString(),epistemic_status:"unconfirmed",
    requires_user_review:true};
}
export async function bridgeRequest(message,sender,{storage,readCanonical,uuid}) {
  if(!validJarvisSender(sender))return {status:"rejected",reason:"origin_forbidden"};
  switch(message?.type){
    case "NEXTPLAN_JARVIS_STATE":{
      const state=await readCanonical();
      return {status:"ok",projects:(state.projects||[]).map(p=>({
        id:p.id,name:p.name,status:p.status,next_action:p.next_action||""
      })),authority:"legacy_github"};
    }
    case "NEXTPLAN_JARVIS_QUEUE":{
      const state=await readCanonical();
      const current=(state.projects||[]).find(p=>p.id===message?.proposal?.project_id);
      const action=safeProposal(message?.proposal,current);
      const items=(await storage.get({pendingCandidates:[]})).pendingCandidates;
      const id="jarvis-"+uuid();
      const next=[...items,{id,kind:"jarvis_confirmed_proposal",label:
        "Jarvis：更新项目 "+current.name,reason:"需在 NextPlan Sync 扩展弹窗中人工确认",
        confidence:1,requiresConfirmation:true,destructive:false,
        jarvisProposal:true,verification:{
          project_id:current.id,field:action.status?"status":"next_action",
          value:action.status||action.next_action
        },action}].slice(-50);
      await storage.set({pendingCandidates:next});
      return {status:"queued_for_extension_confirmation",id,
        message:"Open NextPlan Sync extension popup and approve; not applied yet"};
    }
    case "NEXTPLAN_JARVIS_CAPTURES":{
      const captures=(await storage.get({jarvisContextCaptures:[]})).jarvisContextCaptures;
      return {status:"ok",captures};
    }
    case "NEXTPLAN_JARVIS_CAPTURE_ACK":{
      if(typeof message.id!=="string"||!message.id.startsWith("capture-"))
        return {status:"rejected",reason:"bad_id"};
      const captures=(await storage.get({jarvisContextCaptures:[]})).jarvisContextCaptures;
      await storage.set({jarvisContextCaptures:captures.filter(x=>x.id!==message.id)});
      return {status:"acknowledged"};
    }
    default: return {status:"rejected",reason:"unknown_message"};
  }
}
export async function captureSelection(info,tab,{storage,uuid}){
  if(info?.menuItemId!=="jarvis-capture-context")return {status:"ignored"};
  const item=captureItem(info.selectionText,info.pageUrl||tab?.url,"capture-"+uuid());
  const old=(await storage.get({jarvisContextCaptures:[]})).jarvisContextCaptures;
  await storage.set({jarvisContextCaptures:[...old,item].slice(-MAX_PENDING)});
  return {status:"queued",id:item.id};
}
