import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import vm from 'node:vm';
const html=readFileSync(new URL('../public/graphics.html',import.meta.url),'utf8');
const code=html.match(/<script>([\s\S]*?)<\/script>/)[1];
test('OBS output displays every delivered second, rejects older frames and never invents ticks',()=>{
 const nodes={},timers=[];let eventStream;
 class Events{constructor(){eventStream=this;}}
 class XHR{open(){}send(){}}
 const context=vm.createContext({document:{getElementById:id=>nodes[id]??=( {textContent:'',style:{}} )},localStorage:{getItem:()=>null},location:{search:'',hostname:'127.0.0.1'},URLSearchParams,Date,XMLHttpRequest:XHR,EventSource:Events,window:{EventSource:Events},setInterval:fn=>timers.push(fn)});
 vm.runInContext(code,context);
 for(const [clock,second] of [['09:03',1],['09:02',2],['09:01',3]]){
  eventStream.onmessage({data:JSON.stringify({service:'panelgo-tablero',clock,updatedAt:`2026-10-17T12:00:0${second}Z`})});
  assert.equal(nodes.clock.textContent,clock);
 }
 eventStream.onmessage({data:JSON.stringify({service:'panelgo-tablero',clock:'09:02',updatedAt:'2026-10-17T12:00:02Z'})});
 assert.equal(nodes.clock.textContent,'09:01');
 for(let i=0;i<10;i++)for(const tick of timers)tick();
 assert.equal(nodes.clock.textContent,'09:01');
});
