import os, sys, json, subprocess, time, tempfile
from pathlib import Path
from decimal import Decimal

os.chdir("/home/frappe/frappe-bench/sites")
import frappe
from frappe.model.base_document import BaseDocument

frappe.init(site="fac.localhost")
frappe.connect()
frappe.set_user("Administrator")
assert frappe.conf.db_host == "db"
from hausverwaltung.hausverwaltung.test_booking_safeguards import fixture, hk_head

created = []
original = BaseDocument.db_insert
heads = []
contract = None
run = Path(tempfile.mkdtemp(prefix="hv-hk-parallel-"))
workers = []


def track(doc, *args, **kwargs):
	result = original(doc, *args, **kwargs)
	if not doc.meta.istable:
		created.append((doc.doctype, doc.name))
	return result


worker = r"""
import os,sys,time,json,traceback
from pathlib import Path
os.chdir('/home/frappe/frappe-bench/sites')
import frappe
frappe.init(site='fac.localhost');frappe.connect();frappe.set_user('Administrator')
head,folder,index=sys.argv[1:]
folder=Path(folder)
try:
 doc=frappe.get_doc('Heizkostenabrechnung Immobilie',head)
 (folder/('ready'+index)).write_text('ready')
 for _ in range(200):
  if (folder/'start').exists():break
  time.sleep(.05)
 else:raise RuntimeError('barrier timeout')
 doc.submit();frappe.db.commit()
 result={'head':head,'submitted':True}
except Exception as e:
 frappe.db.rollback()
 result={'head':head,'submitted':False,'exception':type(e).__name__,'message':str(e),'trace':traceback.format_exc()}
finally:
 (folder/('result'+index+'.json')).write_text(json.dumps(result))
 frappe.destroy()
"""
try:
	BaseDocument.db_insert = track
	_, _, prop, _, contract = fixture()
	heads = [hk_head(prop), hk_head(prop)]
	BaseDocument.db_insert = original
	frappe.db.commit()
	for index, head in enumerate(heads):
		workers.append(
			subprocess.Popen(
				[sys.executable, "-c", worker, head.name, str(run), str(index)],
				stdout=subprocess.PIPE,
				stderr=subprocess.PIPE,
				text=True,
			)
		)
	deadline = time.monotonic() + 15
	while not all((run / ("ready" + str(i))).exists() for i in range(2)):
		assert time.monotonic() < deadline, "Workers did not reach barrier"
		time.sleep(0.05)
	(run / "start").write_text("start")
	for worker_process in workers:
		out, err = worker_process.communicate(timeout=30)
		assert worker_process.returncode == 0, (out, err)
	results = [json.loads((run / ("result" + str(i) + ".json")).read_text()) for i in range(2)]
	assert sum(r["submitted"] for r in results) == 1, results
	loser = next(r for r in results if not r["submitted"])
	assert loser["exception"] == "ValidationError" and any(
		text in loser["message"] for text in ("bereits die Heizkostenabrechnung", "gleichzeitig geändert")
	), loser
	invoices = frappe.get_all(
		"Sales Invoice", filters={"customer": contract.kunde, "docstatus": 1}, fields=["name", "grand_total"]
	)
	assert len(invoices) == 1 and invoices[0].grand_total == 100, invoices
	gl = frappe.get_all(
		"GL Entry",
		filters={"voucher_no": invoices[0].name, "voucher_type": "Sales Invoice", "is_cancelled": 0},
		fields=["debit", "credit"],
	)
	assert gl and sum(Decimal(str(r.debit)) - Decimal(str(r.credit)) for r in gl) == 0
	print(
		json.dumps(
			{
				"simultaneous_submit_results": results,
				"active_invoice_count": len(invoices),
				"active_invoice_total": 100,
				"gl_balanced": True,
			},
			ensure_ascii=False,
		)
	)
finally:
	BaseDocument.db_insert = original
	for process in workers:
		if process.poll() is None:
			process.kill()
			process.wait()
	frappe.db.rollback()
	if contract:
		invoices = frappe.get_all("Sales Invoice", filters={"customer": contract.kunde}, pluck="name")
		for head in heads:
			if frappe.db.exists("Heizkostenabrechnung Immobilie", head.name):
				doc = frappe.get_doc("Heizkostenabrechnung Immobilie", head.name)
				if doc.docstatus == 1:
					doc.cancel()
		for name in invoices:
			if frappe.db.exists("Sales Invoice", name):
				frappe.delete_doc("Sales Invoice", name, force=True, ignore_permissions=True)
		for dt, name in reversed(created):
			if dt == "Account" and frappe.db.exists("GL Entry", {"account": name}):
				continue
			if frappe.db.exists(dt, name):
				frappe.delete_doc(dt, name, force=True, ignore_permissions=True)
		frappe.db.commit()
	frappe.destroy()
