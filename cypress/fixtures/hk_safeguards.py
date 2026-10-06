import os,json
from pathlib import Path
os.chdir('/home/frappe/frappe-bench/sites')
import frappe
frappe.init(site='fac.localhost');frappe.connect();frappe.set_user('Administrator')
assert frappe.conf.db_host=='db'
from frappe.model.base_document import BaseDocument
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture,hk_head
manifest=Path('/tmp/hk_safeguards_fixture.json')
try:
 if os.environ.get('HV_HK_UI_CLEANUP'):
  saved=json.loads(manifest.read_text())
  head=frappe.get_doc('Heizkostenabrechnung Immobilie',saved['head'])
  if head.docstatus==1:head.cancel()
  retained=[]
  for doctype,name in reversed(saved['created']):
   if doctype=='Account' and frappe.db.exists('GL Entry',{'account':name}):
    retained.append((doctype,name))
    continue
   if frappe.db.exists(doctype,name):frappe.delete_doc(doctype,name,ignore_permissions=True,force=True)
  frappe.db.commit()
  missing=[(dt,n) for dt,n in saved['created'] if (dt,n) not in retained and frappe.db.exists(dt,n)]
  assert not missing,missing
  print(json.dumps({'cleanup':True,'remaining_fixture_documents':missing,'retained_shared_accounts':retained,'reason':'An income account adopted by other UI-test ledger transactions is preserved.'}))
 else:
  created=[];original=BaseDocument.db_insert
  def track(doc,*args,**kwargs):
   result=original(doc,*args,**kwargs)
   if not doc.meta.istable:created.append((doc.doctype,doc.name))
   return result
  BaseDocument.db_insert=track
  _,_,prop,_,_=fixture()
  head=hk_head(prop,costs=0)
  BaseDocument.db_insert=original
  saved={'head':head.name,'created':created}
  manifest.write_text(json.dumps(saved));frappe.db.commit()
  print(json.dumps(saved,ensure_ascii=False))
finally:
 frappe.db.rollback();frappe.destroy()
