const {readFileSync}=require('node:fs');
const vm=require('node:vm');
const assert=require('node:assert/strict');
function setup(locale='en') {
 const elements=new Map(), calls=[], sends=[];
 function el(key) { if(!elements.has(key)) elements.set(key,{listeners:{},files:[],style:{setProperty(){}},classList:{add(){},remove(){},toggle(){}},attributes:{},addEventListener(k,f){this.listeners[k]=f},setAttribute(k,v){this.attributes[k]=v},getAttribute(){return ''}});return elements.get(key); }
 const win={FormeI18n:{locale},addEventListener(){}};
 let release;
 const hold=new Promise(r=>release=r);
 const context={window:win,document:{querySelector:el,querySelectorAll:()=>[]},location:{assign(){}},scrollTo(){},fetch:async(path,opts)=>{calls.push([path,opts]);if(path==='/api/uploads/init')await hold;return {ok:true,status:200,json:async()=>path.endsWith('/init')?{uploadId:'drop-id',uploadUrl:'/put'}:path.endsWith('templates')?{items:[]}:{} };},XMLHttpRequest:class{constructor(){this.upload={};this.status=200;this.responseText='{}'}open(method,url){this.url=url}send(file){sends.push(file);this.onload()} }};
 vm.runInNewContext(readFileSync(require('node:path').join(__dirname, '../dist/js/create-workflow.js'),'utf8'),context);
 const drop=files=>el('.upload-zone').listeners.drop({preventDefault(){},dataTransfer:{types:['Files'],files}});
 return {el,drop,calls,sends,release};
}
(async()=>{
 const a=setup(), original={name:'dragged.MOV',type:'',size:42};
 a.drop([original]);assert.match(a.el('#video-feedback').textContent,/dragged.MOV/);
 a.drop([{name:'bad.txt',type:'text/plain',size:10}]);assert.match(a.el('#wizard-error').textContent,/MP4/);
 a.drop([original,original]);assert.match(a.el('#wizard-error').textContent,/one video/);
 a.drop([{name:'huge.mp4',type:'video/mp4',size:513*1024**2}]);assert.match(a.el('#wizard-error').textContent,/512/);
 const uploading=a.el('#next-step').listeners.click();
 assert.equal(a.el('#video-input').disabled,true);
 a.drop([{name:'replacement.mp4',type:'video/mp4',size:99}]);
 a.release();await uploading;
 assert.equal(a.sends[0],original,'XHR must receive the original dropped file');
 const init=JSON.parse(a.calls.find(c=>c[0]==='/api/uploads/init')[1].body);
 assert.equal(init.filename,'dragged.MOV');assert.equal(init.content_type,'video/quicktime');
 assert.ok(a.calls.some(c=>c[0]==='/api/uploads/drop-id/complete'));
 assert.equal(a.el('#video-input').disabled,false);
 const b=setup('zh-Hant'), picked={name:'picked.webm',type:'video/webm',size:55};
 b.el('#video-input').files=[picked];b.el('#video-input').listeners.change();
 assert.equal(b.el('#video-input').value,'');assert.match(b.el('#video-feedback').textContent,/已選擇/);
 b.drop([]);assert.match(b.el('#wizard-error').textContent,/電腦/);
 b.drop([{name:'bad.png',type:'image/png',size:12}]);
 const second=b.el('#next-step').listeners.click();b.release();await second;
 assert.equal(b.sends[0],picked,'invalid selection must retain previous valid file');
 console.log('PASS: drop → init → XHR → complete; picker fallback; invalid/multiple/oversize; busy lock; Traditional Chinese');
})().catch(e=>{console.error(e);process.exitCode=1});
