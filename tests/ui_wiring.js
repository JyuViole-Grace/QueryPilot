const fs=require('fs'),assert=require('assert');
class N{constructor(t){this.tag=t;this.children=[];this.attrs={};this.className='';this._text='';this.value='';this.disabled=false;this.listeners={};
 this.classList={toggle:(c,on)=>{this._c=this._c||new Set(); on?this._c.add(c):this._c.delete(c);}};}
 set textContent(v){this._text=String(v);this.children=[];} get textContent(){return this._text+this.children.map(c=>c.textContent??c).join('');}
 setAttribute(k,v){this.attrs[k]=v;} append(...xs){for(const x of xs)this.children.push(typeof x==='string'?{textContent:x}:x);}
 replaceChildren(){this.children=[];} addEventListener(e,f){this.listeners[e]=f;} focus(){}}
const ids={}; for(const id of ['question','send','send-label','output','status','examples']) ids[id]=new N('x');
global.document={createElement:t=>new N(t),createTextNode:s=>({textContent:s}),getElementById:id=>ids[id]};
let fetched=null;
global.fetch=async(url,opts)=>{fetched={url,body:JSON.parse(opts.body)};return {ok:true,status:200,json:async()=>({sql:'SELECT 1',columns:['n'],rows:[[1]],truncated:false,execution_time_seconds:0.001,quality_repair_attempts:0})};};
const html=fs.readFileSync(require('path').join(__dirname,'..','app','static','index.html'),'utf8'); const script=html.match(/<script>([\s\S]*)<\/script>/)[1];
new Function(script)();
const chips=ids.examples.children; assert.strictEqual(chips.length,6);
chips[0].onclick();
assert.strictEqual(ids.question.value,"For each product category, show the category name and the number of products.");  // chip inserts the full question, not its label
(async()=>{
  ids.question.value='  How many customers are there?  '; await ids.send.onclick();
  assert.strictEqual(fetched.url,'/api/query'); assert.strictEqual(fetched.body.question,'How many customers are there?');   // trimmed
  assert.strictEqual(ids.output.children.length,3); assert.strictEqual(ids.send.disabled,false);                              // result shown, button usable again
  ids.question.value=''; ids.output.children=[]; fetched=null; await ids.send.onclick();
  assert.strictEqual(ids.status.textContent,'Please enter a question.'); assert.strictEqual(fetched,null);                    // no request for empty input
  console.log('ok');
})();
