"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
// Reuse the existing DOM/backend fixture without running or modifying its tests.
const prefix = fs.readFileSync("tests/test_new_chat.js", "utf8").split("async function run() {")[0];
const cases = `
async function runProviderTests() {
  const failure = (code="PROVIDER_EXHAUSTED") => ({
    status:503, ok:false, json:async()=>({error:{route:"DIRECT",code,message:"RAW PRIVATE UPSTREAM ERROR"}})
  });
  const p = await loadPage({chatGate:()=>failure()});
  await submit(p,"keep my question");
  assert.equal(p.elements.get("prompt").value,"keep my question");
  assert.equal(p.elements.get("messages").children.length,0);
  assert.match(p.elements.get("status").textContent,/Provider sementara tidak tersedia/);
  assert.doesNotMatch(p.elements.get("status").textContent,/RAW PRIVATE/);
  assert.equal(p.elements.get("status").getAttribute("data-research-status"),"");
  assert.equal(p.requests.filter(r=>r.url==="/chat/completions").length,1);
  assert.equal(p.elements.get("send").disabled,false);
  assert.equal(p.backend.conversations.length,2);

  for (const code of ["TERMINAL_REQUEST_FAILURE","INVALID_PROVIDER_OUTPUT"]) {
    const terminal=await loadPage({chatGate:()=>failure(code)});
    await submit(terminal,"unchanged");
    assert.equal(terminal.elements.get("prompt").value,"unchanged");
    assert.match(terminal.elements.get("status").textContent,code==="INVALID_PROVIDER_OUTPUT" ? /format jawaban/ : /ditolak oleh provider/);
  }
  const generic=await loadPage({chatGate:()=>({status:500,ok:false,json:async()=>{throw new Error("not JSON")}})});
  await submit(generic,"generic");
  assert.equal(generic.elements.get("status").textContent,"Jawaban gagal dimuat. Coba lagi.");
  assert.equal(generic.elements.get("prompt").value,"generic");

  const regen=await loadPage({chatGate:()=>failure()});
  await buttonsWithClass(regen.elements.get("conversation-list"),"conversation-item").find(b=>b.textContent==="Conversation A").dispatch("click");
  const before=visibleMessages(regen.elements.get("messages"));
  await descendants(regen.elements.get("messages")).find(b=>b.className.includes("message-action-regenerate")).dispatch("click");
  assert.deepEqual(visibleMessages(regen.elements.get("messages")),before);
  assert.match(regen.elements.get("status").textContent,/Provider sementara tidak tersedia/);
  console.log("DIRECT provider UI: PASS (5 scenarios; prompt/history preserved; safe errors; no automatic UI retry)");
}
runProviderTests().catch(error=>{console.error(error);process.exitCode=1;});
`;
vm.runInNewContext(prefix+cases,{require,console,process,setImmediate,structuredClone});
