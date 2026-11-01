// Controller update logic in a simulated DOM; no browser/pixel claim.
import fs from 'node:fs';
import vm from 'node:vm';
import assert from 'node:assert/strict';
const source=fs.readFileSync('director_web/app.js','utf8').split('function recipeSteps()')[0];
const nodes=new Map();
function node(id){if(!nodes.has(id))nodes.set(id,{value:'',options:[],classList:{toggle(){}},replaceChildren(){},textContent:''});return nodes.get(id);}
const state={version:1,staged:{mode:'live',layout:'pip'},program:{mode:'live',layout:'side-by-side'},program_native:true,current_native_layout:'pip',obs:{connected:true},events:[],markers:[],catalog:[],recipes:[],media:{state:'stopped',volume:0}};
const context={document:{getElementById:node,createElement:()=>({}),activeElement:null},recipeSteps(){},fixture:state};
vm.createContext(context);
vm.runInContext(source+';state=fixture;update();',context);
assert.equal(node('program-mode').textContent,'LIVE · pip');
state.current_native_layout=null;
vm.runInContext('update()',context);
assert.match(node('program-mode').textContent,/unknown/);
console.log('PASS simulated controller native layout label and unknown geometry status');
