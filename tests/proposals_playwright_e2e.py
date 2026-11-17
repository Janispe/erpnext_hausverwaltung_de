"""Opt-in UI acceptance on the existing isolated synthetic site; no auth output."""
import argparse,contextlib,json,sys,traceback
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from proposals_http_contracts import Client,binding


def run(args):
 from playwright.sync_api import sync_playwright,expect
 out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 auth=json.loads(Path(args.auth_file).read_text());assert auth['purpose']=='hv-proposals-disposable-testauth'
 client=Client(args.base_url);client.login('agent@hv4.invalid',auth['agent'])
 proof={'success':False,'phase':'seed','diagnostic_layout':args.diagnostic_layout,'full_acceptance_passed':False}
 def seed(lanes=3,steps=3):
  package='ui-'+uuid4().hex[:10];nodes=[]
  def note():
   target='SYN-UI-'+uuid4().hex[:10];client.resource('HV Synthetic Note',data={'synthetic_id':target,'label':'Unverändert'});return target
  def add(target,deps,lane=None):
   p=client.api('submit',key=uuid4().hex,package=package,package_meta={'title':'Synthetik · UI '+package,'reason':'Ausschließlich synthetischer Oberflächentest','lane_label':'Notizen'},payload={'target':target,'label':'Neue Bezeichnung'},dependencies=deps,metadata={'title':'Bezeichnung anpassen','summary':'Unverändert → Neu','lane':lane,'rationale':'Synthetische Prüfung','sources':[{'label':'Synthetische Quelle'}]});nodes.append(p);return p
  root=add(note(),[])
  for i in range(lanes):
   target=note();parent=root
   for j in range(steps):parent=add(target,[binding(parent)],{'key':str(i),'label':'Synthetische Zeile '+str(i+1)})
  return package,nodes
 package,nodes=seed();rejected,small=seed(1,1)
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path=args.chromium,headless=True,args=['--disable-dev-shm-usage','--disable-background-networking','--disable-sync','--no-first-run'])
   def login(account):
    ctx=browser.new_context(viewport={'width':1440,'height':1100},locale='de-DE')
    origin=urlsplit(args.base_url)
    ctx.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).netloc==origin.netloc or urlsplit(route.request.url).scheme in ('data','blob') else route.abort())
    page=ctx.new_page();page.goto(args.base_url+'/login');page.locator('#login_email:visible').fill(account+'@hv4.invalid');page.locator('#login_password:visible').fill(auth[account]);page.locator('.for-login button[type=submit]:visible').click();page.wait_for_url('**/desk*');page.goto(args.base_url+'/desk/hv-proposals');page.get_by_role('table',name='Paketliste').wait_for();return page
   proof['phase']='agent';agent=login('agent');agent.locator(f'[data-package="{package}"]').click();expect(agent.locator('[data-node]')).to_have_count(10);expect(agent.get_by_role('button',name='Offene freigeben …',exact=True)).to_have_count(0);expect(agent.get_by_text('Nur Prüfer können freigeben.',exact=True)).to_be_visible()
   proof['phase']='reviewer';page=login('reviewer')
   for theme in ('light','dark'):
    page.evaluate('(theme)=>document.documentElement.setAttribute("data-theme",theme)',theme);page.screenshot(path=str(out/f'paketliste-{theme}.png'),full_page=True)
   page.locator(f'[data-package="{package}"]').click();expect(page.locator('[data-node]')).to_have_count(10);page.get_by_role('heading',name='Änderung',exact=True).wait_for()
   expect(page.get_by_role('button',name='Graph',exact=True)).to_have_attribute('aria-pressed','true')
   expect(page.get_by_role('button',name='Liste',exact=True)).to_have_attribute('aria-pressed','false')
   expect(page.locator('.hv-prop-node-glyph')).to_have_count(10)
   assert page.locator('.hv-prop-node-glyph').first.evaluate('(e)=>e.offsetWidth===22 && e.offsetHeight===22')
   actual=client.api('view',proposal_id=nodes[0]['id'])
   expect(page.locator('.hv-prop-detail')).to_contain_text(actual['target']['doctype'])
   # Isolated rendering contract with two effects and a different doctype.
   # No request, approval or business save uses this component-only fixture.
   assert page.evaluate("""(p)=>{const x=Object.create(hausverwaltung.hv_proposals.Inbox.prototype);x.detail=$('<aside>');x.graph={nodes:[{id:p.id,lane:null,executable:false}]};x.reviewer=false;x.renderDetail({...p,target:{...p.target,doctype:'Synthetischer Prüftyp'},effects:['Wirkung eins','Wirkung zwei']},[]);return x.detail.find('ul[aria-label="Auswirkungen"]').length===1 && x.detail.find('ul[aria-label="Auswirkungen"] > li').length===2 && x.detail.text().includes('Synthetischer Prüftyp');}""",actual)
   proof['graph_width']=page.locator('.hv-prop-scroll').evaluate('(e)=>({client:e.clientWidth,scroll:e.scrollWidth})')
   if not args.diagnostic_layout: assert proof['graph_width']['scroll']<=proof['graph_width']['client'],'Graph scrolls at1440'
   for theme in ('light','dark'):
    page.evaluate('(theme)=>document.documentElement.setAttribute("data-theme",theme)',theme);page.screenshot(path=str(out/f'paket-{theme}.png'),full_page=True)
   page.set_viewport_size({'width':1000,'height':1100});positions=page.locator('.hv-prop-layout').evaluate('(e)=>{const [a,b]=e.children;return {graph:a.getBoundingClientRect().bottom,detail:b.getBoundingClientRect().top}}');assert positions['detail']>=positions['graph'];page.set_viewport_size({'width':1440,'height':1100})
   proof['phase']='approve';page.get_by_role('button',name='Revision 1 freigeben',exact=True).click();page.get_by_text('gilt nur für Revision 1',exact=False).wait_for()
   page.get_by_role('button',name='Offene freigeben …',exact=True).click();page.get_by_text('Jede Freigabe wird einzeln',exact=False).wait_for()
   assert client.api('view',proposal_id=nodes[1]['id'])['status']=='Pending'
   with page.expect_response(lambda r:r.url.endswith('.review_many')) as response:page.get_by_role('button',name='Freigaben bestätigen',exact=True).click()
   assert response.value.status==200;assert all(r['ok'] for r in response.value.json()['message'])
   page.get_by_role('button',name='Freigegebene ausführen (10)',exact=True).wait_for()
   expect(page.get_by_role('button',name='Offene freigeben …',exact=True)).to_be_disabled()
   proof['phase']='execute';page.get_by_role('button',name='Freigegebene ausführen (10)',exact=True).click();page.get_by_role('button',name='Freigegebene ausführen (0)',exact=True).wait_for()
   assert all(n['status']=='Succeeded' for n in client.api('package_graph',package=package)['nodes'])
   page.get_by_role('button',name='Liste',exact=True).click();expect(page.get_by_role('table',name='Vorschlagsliste')).to_be_visible()
   expect(page.get_by_role('button',name='Liste',exact=True)).to_have_attribute('aria-pressed','true')
   expect(page.get_by_role('button',name='Graph',exact=True)).to_have_attribute('aria-pressed','false')
   rows=page.locator('table[aria-label="Vorschlagsliste"] tbody tr');expect(rows).to_have_count(10)
   assert rows.first.evaluate('(e)=>getComputedStyle(e).cursor')=='pointer'
   rows.first.hover();assert rows.first.evaluate('(e)=>getComputedStyle(e).backgroundColor') not in ('transparent','rgba(0, 0, 0, 0)')
   for theme in ('light','dark'):
    page.evaluate('(theme)=>document.documentElement.setAttribute("data-theme",theme)',theme);page.screenshot(path=str(out/f'paket-liste-{theme}.png'),full_page=True)
   proof['six_ui_corrections']=True
   proof['phase']='reject';page.goto(args.base_url+'/desk/hv-proposals/'+rejected);page.get_by_role('button',name='Ablehnen …',exact=True).wait_for();page.get_by_role('button',name='Ablehnen …',exact=True).click();page.locator('.modal:visible textarea').fill('Synthetischer Ablehnungsgrund');page.get_by_role('button',name='Ablehnung bestätigen',exact=True).click()
   page.get_by_text('Synthetischer Ablehnungsgrund',exact=False).first.wait_for();graph=client.api('package_graph',package=rejected);assert [n['status'] for n in graph['nodes']]==['Rejected','Stale']
   page.locator(f'[data-node="{small[1]["id"]}"]').click();page.get_by_role('button',name='Neue Revision anfordern',exact=True).click();page.locator('.modal:visible textarea').fill('Bitte synthetisch überarbeiten');page.get_by_role('button',name='Anfordern',exact=True).click();page.get_by_text('Nachbesserung angefordert',exact=False).wait_for()
   proof.update(success=True,full_acceptance_passed=not args.diagnostic_layout,phase='complete',package=package,rejected_package=rejected,normal_separate_logins=True,bulk_confirmation=True,ordered_execution=True,rejection_stales_successor=True,list_toggle=True,responsive=True);browser.close()
 except BaseException as e:
  proof.update(error_type=type(e).__name__,frames=[{'file':f.filename,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(e.__traceback__)])
 (out/'desk-e2e.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False));return proof['success']

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--synthetic',action='store_true',required=True)
 for field in ('base-url','auth-file','dependencies','output-dir'):p.add_argument('--'+field,required=True)
 p.add_argument('--diagnostic-layout',action='store_true',help='Record layout metrics but leave strict layout acceptance open');p.add_argument('--chromium',default='/usr/bin/chromium');a=p.parse_args();assert urlsplit(a.base_url).hostname=='127.0.0.1';sys.path.insert(0,a.dependencies)
 with open('/dev/null','w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):ok=run(a)
 raise SystemExit(0 if ok else 1)
