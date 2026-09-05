// Exercise authenticated REST contracts without approving real regulatory content.
const fs=require('node:fs'); const path=require('node:path'); const assert=require('node:assert/strict');
const base=process.env.QA_BASE_URL||'http://127.0.0.1:3000';
const token=process.env.QA_ADMIN_TOKEN||fs.readFileSync(path.resolve(__dirname,'../.admin-token'),'utf8').trim();
const checks=[];
async function check(name,resource,init,expected,authenticated=true){
  const response=await fetch(base+'/api'+resource,{...init,headers:{...(authenticated?{Authorization:`Bearer ${token}`} : {}),...init?.headers},signal:AbortSignal.timeout(15000)});
  checks.push({name,status:response.status}); assert.equal(response.status,expected,name); return response;
}
(async()=>{
  const doc=encodeURIComponent('05_상품설명서_정기예금');
  await check('extraction requires auth',`/documents/${doc}/extraction`,{},401,false);
  const extraction=await(await check('authenticated extraction',`/documents/${doc}/extraction`,{},200)).json();
  assert.ok(extraction.blocks.length>0);
  const pack=JSON.parse(fs.readFileSync(path.resolve(__dirname,'../../back/contracts/fixtures/rulepack_DEP-2026.08-v6.json'),'utf8'));
  const publish={method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(pack)};
  await check('publish requires auth','/packs/publish',publish,401,false);
  await check('immutable pack cannot be overwritten','/packs/publish',publish,409);
  await check('invalid pack rejected','/packs/publish',{...publish,body:'{}'},422);
  await check('incomplete document upload rejected','/documents',{method:'POST',body:new FormData()},422);
  await check('approval requires reviewer',`/documents/${doc}/candidates/nonexistent-qa/approve`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'},422);
  await check('public catalog remains readable','/packs',{},200,false);
  fs.writeFileSync(path.resolve(__dirname,'../qa-output/admin-qa.json'),JSON.stringify({verified_at:new Date().toISOString(),checks,extractionBlocks:extraction.blocks.length,realApprovalsOrNewPublications:0},null,2));
  console.log(JSON.stringify({checks,extractionBlocks:extraction.blocks.length},null,2));
})().catch(error=>{console.error(error);process.exitCode=1;});
