const fs=require('fs');
const path=require('path');
const {pathToFileURL}=require('url');
const {chromium}=require('C:/Users/hanbin/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
(async()=>{
  const root=__dirname;
  const qa=path.join(root,'qa');fs.mkdirSync(qa,{recursive:true});
  const browser=await chromium.launch({channel:'chrome',headless:true});
  const page=await browser.newPage({viewport:{width:1100,height:1300},deviceScaleFactor:1.5});
  const results=[];
  for(const name of ['말해모해_말틈_기획서','말해모해_말틈_기능명세서']){
    await page.goto(pathToFileURL(path.join(root,name+'.html')).href);
    await page.evaluate(()=>document.fonts.ready);
    await page.emulateMedia({media:'print'});
    const sizes=await page.locator('.page').evaluateAll(els=>els.map(el=>({page:el.dataset.page,height:el.getBoundingClientRect().height,contentBottom:el.querySelector('main').getBoundingClientRect().bottom-el.getBoundingClientRect().top,footerTop:el.querySelector('.footer').getBoundingClientRect().top-el.getBoundingClientRect().top,over:el.querySelector('main').scrollWidth>el.querySelector('main').clientWidth+1})));
    const problems=sizes.filter(x=>x.height>1123.6||x.contentBottom>x.footerTop-12||x.over);
    results.push({name,pages:sizes,problems});
    await page.pdf({path:path.join(root,name+'.pdf'),printBackground:true,preferCSSPageSize:true});
    for(let i=0;i<sizes.length;i++)await page.locator('.page').nth(i).screenshot({path:path.join(qa,name+'-'+String(i+1).padStart(2,'0')+'.png')});
  }
  fs.writeFileSync(path.join(qa,'layout-report.json'),JSON.stringify(results,null,2));
  console.log(JSON.stringify(results.map(x=>({name:x.name,pageCount:x.pages.length,problems:x.problems})),null,2));
  await browser.close();
})();
