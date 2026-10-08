import test from "node:test";
import assert from "node:assert/strict";
import {safeProposal,validJarvisSender,captureItem,bridgeRequest,captureSelection,parseExplicitMemory,captureExplicitChatGPTMemory} from "../jarvis_bridge_v1.js";

const project={id:"p-001",name:"Research",status:"active",next_action:"Old action"};
const sender={url:"https://changxinjiresearch.github.io/LifeOS-App/jarvis.html"};
function storage(){
  const db={pendingCandidates:[],jarvisContextCaptures:[]};
  return {db,get:async fallback=>Object.fromEntries(Object.keys(fallback).map(k=>[k,db[k]??fallback[k]])),
    set:async x=>Object.assign(db,x)};
}
test("reject unapproved origin and unrelated NextPlan pages",()=>{
  assert.equal(validJarvisSender(sender),true);
  for(const url of ["https://evil.com/LifeOS-App/jarvis.html",
    "https://changxinjiresearch.github.io/LifeOS-App/index.html",
    "https://changxinjiresearch.github.io.evil.com/LifeOS-App/jarvis.html"])
    assert.equal(validJarvisSender({url}),false);
});
test("project field proposal is allowlisted and compare-and-swap",()=>{
  assert.deepEqual(safeProposal({action:"update_project_snapshot",project_id:"p-001",
    expected_status:"active",status:"completed"},project),
    {action:"update_project_snapshot",project_id:"p-001",status:"completed"});
  assert.equal(safeProposal({action:"update_project_snapshot",project_id:"p-001",
    expected_status:"active",next_action:"New experiment"},project).next_action,"New experiment");
  const base={action:"update_project_snapshot",project_id:"p-001",expected_status:"active"};
  for(const raw of [
    {...base,expected_status:"waiting",status:"completed"},
    {...base,action:"delete_project",status:"completed"},
    {...base,status:"deleted"},
    {...base,status:"completed",next_action:"new"},
    {...base,status:"active"},
    {...base,next_action:"Old action"}
  ])assert.throws(()=>safeProposal(raw,project));
});
test("queued mutation cannot bypass extension popup approval",async()=>{
  const store=storage();
  const resp=await bridgeRequest({
    type:"NEXTPLAN_JARVIS_QUEUE",proposal:{action:"update_project_snapshot",
      project_id:"p-001",expected_status:"active",next_action:"New action"}
  },sender,{storage:store,readCanonical:async()=>({projects:[project]}),uuid:()=> "case-12345678"});
  assert.equal(resp.status,"queued_for_extension_confirmation");
  assert.equal(store.db.pendingCandidates.length,1);
  assert.equal(store.db.pendingCandidates[0].requiresConfirmation,true);
  assert.equal(store.db.pendingCandidates[0].action.next_action,"New action");
});
test("read state never returns extension auth secret",async()=>{
  const store=storage();
  const r=await bridgeRequest({type:"NEXTPLAN_JARVIS_STATE"},sender,
    {storage:store,readCanonical:async()=>({projects:[project]}),uuid:()=>"x"});
  assert.equal(r.authority,"legacy_github");
  assert.equal(r.projects[0].name,"Research");
  assert.equal(JSON.stringify(r).includes("Bearer"),false);
});
test("selected text captured only from ChatGPT and held unconfirmed",async()=>{
  assert.throws(()=>captureItem("Selected","https://evil.com","capture-001"));
  const store=storage();
  await captureSelection({menuItemId:"jarvis-capture-context",selectionText:"Evidence from ChatGPT",
    pageUrl:"https://chatgpt.com/c/example-id"},null,{storage:store,uuid:()=>"12345678"});
  const r=await bridgeRequest({type:"NEXTPLAN_JARVIS_CAPTURES"},sender,
    {storage:store,readCanonical:async()=>{},uuid:()=>""});
  assert.equal(r.captures.length,1);
  assert.equal(r.captures[0].requires_user_review,true);
  assert.equal(r.captures[0].epistemic_status,"unconfirmed");
  const ack=await bridgeRequest({type:"NEXTPLAN_JARVIS_CAPTURE_ACK",id:r.captures[0].id},sender,
    {storage:store,readCanonical:async()=>{},uuid:()=>""});
  assert.equal(ack.status,"acknowledged");
  assert.equal(store.db.jarvisContextCaptures.length,0);
});
test("untrusted website cannot request sensitive context",async()=>{
  const result=await bridgeRequest({type:"NEXTPLAN_JARVIS_CAPTURES"},
    {url:"https://attacker.invalid/x"},
    {storage:storage(),readCanonical:async()=>({}),uuid:()=>""});
  assert.equal(result.status,"rejected");
});

test("explicit Jarvis memory only queues user-authorized text and remains unconfirmed",async()=>{
  assert.equal(parseExplicitMemory("Jarvis，记住：研究结果必须入 GitHub"),"研究结果必须入 GitHub");
  assert.equal(parseExplicitMemory("请解释 GitHub 的作用"),null);
  const store=storage();
  const turn={userText:"Jarvis，记住：实验结果必须放在 GitHub 正式仓库里",url:"https://chatgpt.com/c/one"};
  const result=await captureExplicitChatGPTMemory(turn,{url:"https://chatgpt.com/c/one"},{
    storage:store,uuid:()=>"test-uuid"});
  assert.equal(result.status,"queued_for_review");
  assert.equal(store.db.jarvisContextCaptures.length,1);
  assert.equal(store.db.jarvisContextCaptures[0].epistemic_status,"unconfirmed");
  const dup=await captureExplicitChatGPTMemory(turn,{url:"https://chatgpt.com/c/one"},{
    storage:store,uuid:()=>"test-uuid"});
  assert.equal(dup.status,"already_queued");
  const denied=await captureExplicitChatGPTMemory(turn,{url:"https://evil.invalid/c/one"},{
    storage:store,uuid:()=>"test-uuid"});
  assert.equal(denied.status,"rejected");
});
