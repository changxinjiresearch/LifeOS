import test from "node:test";
import assert from "node:assert/strict";
import worker from "../src/worker.mjs";

const TOKEN = "local-test-only-token-with-at-least-32-characters";
const origin = "https://changxinjiresearch.github.io";
const valid = {
  question: "我的实验代码应该保存在哪里？",
  allow_model: true,
  projects: [{name:"RP新实验",status:"active",next_action:"核查实验"}],
  knowledge: [{summary:"所有实验代码必须入 GitHub",source_ref:"manual://unit-test",epistemic_status:"user_confirmed"}],
  history:[{role:"user",content:"我们昨天聊到了 GitHub"}]
};
function env(overrides={}) {
  return {
    JARVIS_SHARED_TOKEN:TOKEN,
    AI:{run:async (model,args)=>({
      choices:[{message:{content:"应保存到指定的 GitHub 仓库。"}}]
    })},
    ...overrides
  };
}
function req(path="/v1/chat", body=valid, method="POST", opts={}) {
  return new Request("https://nextplan-jarvis-free.example.workers.dev"+path,{
    method, headers:{"Origin":opts.origin||origin,"Authorization":"Bearer "+(opts.token||TOKEN),
      "Content-Type":"application/json"},
    ...(method==="POST"?{body:JSON.stringify(body)}:{})
  });
}
test("free model returns source-grounded read-only response", async()=>{
  let selected="",call;
  const e=env({AI:{run:async(model,args)=>{
    selected=model;call=args;
    return {choices:[{message:{content:"实验代码应放到 GitHub，依据你的已确认知识。"}}]};
  }}});
  const r=await worker.fetch(req(),e);
  assert.equal(r.status,200);
  const out=await r.json();
  assert.equal(selected,"@cf/qwen/qwen3-30b-a3b-fp8");
  assert.ok(call.messages.length>=3);
  assert.equal(out.executed_actions,0);
  assert.equal(out.sources[0].source_ref,"manual://unit-test");
  assert.equal(out.mode,"free_cloudflare_ai");
  assert.equal(r.headers.get("Access-Control-Allow-Origin"),origin);
});
test("server secret is mandatory and never accepted from query strings",async()=>{
  const r=await worker.fetch(req("/v1/chat",valid,"POST",{token:"wrong"}),env());
  assert.equal(r.status,401);
  const bad=await worker.fetch(req(),env({JARVIS_SHARED_TOKEN:"short"}));
  assert.equal(bad.status,401);
});
test("only NextPlan web origin may call model",async()=>{
  const r=await worker.fetch(req("/v1/chat",valid,"POST",{origin:"https://evil.example"}),env());
  assert.equal(r.status,403);
});
test("preflight is limited to NextPlan origin",async()=>{
  const r=await worker.fetch(new Request("https://unit-test.workers.dev/v1/chat",{
    method:"OPTIONS",headers:{Origin:origin}}),env());
  assert.equal(r.status,204);
  assert.equal(r.headers.get("access-control-allow-origin"),origin);
});
test("unconsented questions cannot call AI model",async()=>{
  let called=false;
  const r=await worker.fetch(req("/v1/chat",{...valid,allow_model:false}),env({
    AI:{run:async()=>{called=true;return {response:"unsafe"};}}
  }));
  assert.equal(r.status,400);assert.equal(called,false);
});
test("oversized or untrusted context rejected",async()=>{
  const over={...valid,knowledge:Array(9).fill(valid.knowledge[0])};
  assert.equal((await worker.fetch(req("/v1/chat",over),env())).status,400);
  const dangerous={...valid,knowledge:[{...valid.knowledge[0],epistemic_status:"unconfirmed"}]};
  assert.equal((await worker.fetch(req("/v1/chat",dangerous),env())).status,400);
});
test("rate limit or provider error never switches to paid alternative",async()=>{
  let called=0;
  const r=await worker.fetch(req(),env({AI:{run:async()=>{called++;throw new Error("quota reached: PRIVATE");}}}));
  assert.equal(r.status,503);assert.equal(called,1);
  const response=await r.text();
  assert.ok(!response.includes("PRIVATE"));
  assert.ok(response.includes("no paid model fallback"));
});
test("health reports configuration but never token or private context",async()=>{
  const r=await worker.fetch(req("/health",undefined,"GET"),env());
  assert.equal(r.status,200);
  const str=await r.text();assert.ok(!str.includes(TOKEN));
  assert.equal(JSON.parse(str).configured,true);
});
test("no AI binding fails closed",async()=>{
  const r=await worker.fetch(req(),env({AI:null}));assert.equal(r.status,503);
});
test("method and path restricted",async()=>{
  assert.equal((await worker.fetch(req("/anything"),env())).status,404);
});
