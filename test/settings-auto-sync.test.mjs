import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
const source=readFileSync(new URL('../public/script.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('const obsSettingsButton='),source.indexOf('// A fresh installation'));
test('an operator edit synchronizes names and logos without a previous manual link',async()=>{
 const requests=[],saved={};let pending;
 const context=vm.createContext({storageKey:'panelgo-tablero-settings-v1',document:{getElementById:()=>({addEventListener(){}})},state:{homeName:'NUEVO LOCAL',awayName:'VISITA',homeLogo:'',awayLogo:'',eventLogo:'',tournament:'Liga',category:'U17'},obsGraphicToken:'test',AbortSignal,
  localStorage:{getItem:()=>null,setItem:(key,value)=>{saved[key]=value;}},refreshOBSGraphic:async()=>{},clearTimeout(){},setTimeout(fn){pending=fn;},fetch:async(url,options)=>{requests.push({url,body:JSON.parse(options.body)});return {ok:true};}});
 vm.runInContext(code+'\nscheduleOBSSettings();',context);
 assert.equal(typeof pending,'function');await pending();
 assert.equal(requests.length,1);assert.equal(requests[0].body.homeName,'NUEVO LOCAL');
 assert.equal(requests[0].url,'http://127.0.0.1:8774/settings');
 assert.equal('homeScore' in requests[0].body,false);
});
