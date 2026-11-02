/* Avoid alphabetical defaults such as the old novelty Albert voice. */
(function(root){
const preferred=['Samantha','Daniel','Karen','Moira','Tessa','Serena'];
function chooseVoice(voices,selected=''){
 const local=voices.filter(v=>v.localService&&v.lang.replace('_','-').startsWith('en-'));
 return local.find(v=>v.name===selected)||preferred.map(name=>local.find(v=>v.name.includes(name))).find(Boolean)||null;
}
if(typeof module!=='undefined')module.exports={chooseVoice};else root.chooseVoice=chooseVoice;
})(globalThis);
