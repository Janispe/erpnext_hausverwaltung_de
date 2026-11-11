const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/../hausverwaltung/public/js/dunning.js', 'utf8');
function fixture() {
 const calls = [], dialogs = [];
 const prepared = {required:true, token:'opaque-token', dunning:'DUN-1', invoice:'SI-1',amount:100,currency:'EUR',due_date:'2026-10-10',posting_date:'2026-10-16'};
 let submitResolve;
 const frappe = {
  ui:{form:{on(){}},Dialog:class {
   constructor(options){this.options=options;dialogs.push(this);}
   show(){this.shown=true;}
   hide(){this.hidden=true;this.options.onhide();}
   get_primary_btn(){return {prop(){}};}
  }},
  model:{can_submit(){return true;}},utils:{escape_html(s){return s.replace(/</g,'&lt;').replace(/>/g,'&gt;');}},
  call:async(options)=>{calls.push(options);if(options.method.endsWith('prepare_legacy_dunning_confirmation'))return {message:prepared};return new Promise((resolve)=>{submitResolve=resolve;});},
  msgprint(){},throw(message){throw Error(message);},
 };
 const context=vm.createContext({frappe,__: (text,args=[])=>text.replace(/\{(\d+)\}/g,(_,n)=>args[n]),document:{},console});
 vm.runInContext(source,context);
 const frm={doc:{name:'DUN-1',docstatus:0,overdue_payments:[{}]},doctype:'Dunning',is_new:()=>false,is_dirty:()=>false,reloads:0,reload_doc:async()=>{frm.reloads++;}};
 return {context,frm,calls,dialogs,prepared,resolveSubmit:()=>submitResolve({message:{name:'DUN-1',docstatus:1}})};
}
test('cancel creates no submit and no document mutation',async()=>{const f=fixture();const d=await f.context.confirm_legacy_dunning(f.frm);d.options.secondary_action();assert.equal(f.calls.length,1);assert.equal(f.frm.reloads,0);assert.equal(f.frm.doc.docstatus,0);});
test('close prevents even a delayed confirm callback',async()=>{const f=fixture();const d=await f.context.confirm_legacy_dunning(f.frm);d.hide();await d.options.primary_action();assert.equal(f.calls.length,1);assert.equal(f.frm.doc.docstatus,0);});
test('double click executes one bound confirmation',async()=>{const f=fixture();const d=await f.context.confirm_legacy_dunning(f.frm);const first=d.options.primary_action();await d.options.primary_action();assert.equal(f.calls.length,2);assert.equal(f.calls[1].args.token,'opaque-token');assert.equal(f.calls[1].args.dunning,'DUN-1');assert.equal(f.calls[1].args.confirmed,true);f.resolveSubmit();await first;assert.equal(f.frm.reloads,1);});
test('scheduled case sends no legacy submit and opens no warning',async()=>{const f=fixture();f.prepared.required=false;await f.context.confirm_legacy_dunning(f.frm);assert.equal(f.dialogs.length,0);assert.equal(f.calls.length,1);});
test('dirty draft is blocked before any server call',async()=>{const f=fixture();f.frm.is_dirty=()=>true;await assert.rejects(f.context.confirm_legacy_dunning(f.frm));assert.equal(f.calls.length,0);});
test('warning escapes invoice text and names the binding action',async()=>{const f=fixture();f.prepared.invoice='<unsafe>';const d=await f.context.confirm_legacy_dunning(f.frm);assert.match(d.options.fields[0].options,/&lt;unsafe&gt;/);assert.doesNotMatch(d.options.fields[0].options,/<unsafe>/);assert.equal(d.options.primary_action_label,'Vollsaldo-Mahnung verbindlich einreichen');assert.match(d.options.fields[0].options,/gesamten aktuell offenen Betrag/);});
