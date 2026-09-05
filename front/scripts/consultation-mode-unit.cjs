const assert=require('node:assert/strict');const fs=require('node:fs');const ts=require('typescript');const React=require('react');const {renderToStaticMarkup}=require('react-dom/server');
for(const extension of ['.ts','.tsx'])require.extensions[extension]=(module,file)=>module._compile(ts.transpileModule(fs.readFileSync(file,'utf8'),{compilerOptions:{jsx:ts.JsxEmit.ReactJSX,module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2020}}).outputText,file);
const {sessionScreen}=require('../lib/workspace-model.ts');const {Workbench}=require('../components/workspace.tsx');const {Briefing}=require('../components/consultation.tsx');
for(const mode of ['live','text'])assert.equal(sessionScreen(mode),'dashboard');for(const mode of ['replay','trace'])assert.equal(sessionScreen(mode),'playback');
const playback=renderToStaticMarkup(React.createElement(Workbench,{screen:'playback',title:'기록 재생',onNavigate(){},onNew(){}}));
const current=playback.match(/<button[^>]*aria-current="page"[^>]*>[\s\S]*?<\/button>/g);assert.equal(current.length,1);assert.match(current[0],/이력/);
const briefing=renderToStaticMarkup(React.createElement(Briefing,{onStart(){},onNavigate(){},onNew(){},busy:false}));
assert.match(briefing,/<option value="live" selected="">마이크 녹음/);assert.match(briefing,/텍스트 입력/);assert.doesNotMatch(briefing,/value="replay"|준비된 녹취 재생/);
console.log('PASS: manual consultation defaults, no preset option in briefing, playback belongs to history navigation');
