"""Opt-in real SQL assertions inside normal authenticated WSGI requests.

Run in the isolated test container/sites cwd. No private APIs or identities;
login uses only that site's explicitly marked new disposable TESTAUTH.
"""
import argparse
import inspect
import json
from pathlib import Path
import re
from unittest.mock import patch


def run(site, auth_path):
	from werkzeug.test import Client
	from werkzeug.wrappers import Response
	import frappe.app
	from frappe.database.database import Database
	from hausverwaltung.proposals import frappe_service as service
	auth = json.loads(Path(auth_path).read_text())
	assert auth.get("purpose") == "hv-proposals-disposable-testauth"
	frappe.app._site = site
	frappe.app._sites_path = str(Path.cwd())
	client = Client(frappe.app.application, Response)
	assert client.post("/api/method/login", json={"usr":"agent@hv4.invalid","pwd":auth["agent"]}).status_code == 200
	desk = client.get("/desk/hv-proposals").get_data(as_text=True)
	csrf = re.search(r'frappe\.csrf_token\s*=\s*["\']([^"\']+)',desk).group(1)
	headers = {"X-Frappe-CSRF-Token":csrf}
	prefix = "/api/method/hausverwaltung.proposals.frappe_service."
	listed = client.post(prefix+"list_proposals", json={}, headers=headers).json["message"]
	assert listed, "Seed the isolated synthetic fixture first"
	pid = listed[0]["id"]
	item = client.post(prefix+"view",json={"proposal_id":pid},headers=headers).json["message"]
	packages = client.post(prefix+"list_packages", json={"limit":100}, headers=headers).json["message"]
	readable_reference_package = next((p["package"] for p in packages if p["reference"] is not None), None)
	assert readable_reference_package, "Run HTTP reference contracts before this SQL check"
	observed = []
	original = Database.sql
	def sql(db, query, *args, **kwargs):
		# Session maintenance outside the service is Frappe's normal request path.
		if any(frame.frame.f_globals.get("__name__")==service.__name__ for frame in inspect.stack()):
			statement = str(query)
			assert "FOR UPDATE" not in statement.upper(), "Read service acquired row lock"
			assert not re.match(r"\s*(INSERT|UPDATE|DELETE|REPLACE|ALTER|CREATE|DROP|TRUNCATE)\b",statement,re.I), "Read service wrote SQL"
			observed.append(statement.split()[0].upper())
		return original(db,query,*args,**kwargs)
	checks = [("view",{"proposal_id":pid}),("audit",{"proposal_id":pid}),("list_proposals",{}),
		("list_packages",{}),("package_graph",{"package":item["package"]})]
	counts = {}
	with patch.object(Database,"sql",sql):
		for name,args in checks:
			before=len(observed)
			response=client.post(prefix+name,json=args,headers=headers)
			assert response.status_code==200, f"Read endpoint failed: {name}"
			counts[name]=len(observed)-before

		# Ordinary resource read invokes can_read/readable_record as well.
		before=len(observed)
		response=client.get('/api/resource/HV%20Action%20Proposal/'+pid)
		assert response.status_code==200
		counts['readable_record']=len(observed)-before
		before=len(observed)
		response=client.get('/api/resource/HV%20Proposal%20Package/'+readable_reference_package)
		assert response.status_code==200
		counts['readable_package_record']=len(observed)-before
		assert sum(counts.values())>0, 'SQL spy did not observe any service reads'
	return {"passed":True,"endpoints":counts,"for_update":0,"service_sql_writes":0}


if __name__ == '__main__':
	parser=argparse.ArgumentParser()
	parser.add_argument('--synthetic',action='store_true',required=True)
	parser.add_argument('--site',required=True)
	parser.add_argument('--auth-file',required=True)
	args=parser.parse_args()
	# Own synthetic site: either named hv4.*.local or marked by scripts/hv_tests.sh as disposable.
	config=Path(args.site)/'site_config.json'
	marked=config.is_file() and bool(json.loads(config.read_text()).get('hv_disposable_test_site'))
	if not (args.site.startswith('hv4.') and args.site.endswith('.local')) and not marked:parser.error('Own synthetic site only')
	print(json.dumps(run(args.site,args.auth_file)))
