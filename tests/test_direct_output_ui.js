"use strict";
const fs = require("node:fs");
const vm = require("node:vm");
const prefix = fs.readFileSync("tests/test_new_chat.js","utf8").split("async function run() {")[0];
async function runOutputTests() {
  const failure = code => ({status:502,ok:false,json:async()=>({
    error:{route:"DIRECT",code,message:"PRIVATE DRAFT MUST NOT ESCAPE"}
  })});
  for (const code of ["DIRECT_OUTPUT_INVALID","INVALID_PROVIDER_OUTPUT"]) {
    const page = await loadPage({chatGate:()=>failure(code)});
    await submit(page,"keep question and attachments");
    const status = page.elements.get("status").textContent;
    assert.match(status,code==="DIRECT_OUTPUT_INVALID" ? /gagal diverifikasi/ : /format jawaban/);
    assert.doesNotMatch(status,/UNKNOWN|belum diberikan|PRIVATE/);
    assert.equal(page.elements.get("prompt").value,"keep question and attachments");
    assert.equal(page.elements.get("messages").children.length,0);
    assert.equal(page.requests.filter(r=>r.url==="/chat/completions").length,1);
    assert.equal(page.elements.get("status").getAttribute("data-research-status"),"");
  }
  console.log("DIRECT output UI: PASS (technical errors stay distinct from missing data)");
}
vm.runInNewContext(prefix + runOutputTests.toString() +
  "\nrunOutputTests().catch(e=>{console.error(e);process.exitCode=1;});",
  {require,console,process,setImmediate,structuredClone});
