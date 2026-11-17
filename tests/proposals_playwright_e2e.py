"""Opt-in UI acceptance on the existing isolated synthetic site; no auth output."""
import argparse,contextlib,json,re,sys,traceback
from pathlib import Path
from uuid import uuid4
from urllib.parse import urlsplit
from proposals_http_contracts import Client,binding


def contrast(first, second):
 def luminance(color):
  channels = [int(channel) / 255 for channel in re.findall(r'\d+', color)]
  assert len(channels) == 3, color
  linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels]
  return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))
 dark, light = sorted((luminance(first), luminance(second)))
 return (light + 0.05) / (dark + 0.05)


def run(args):
 from playwright.sync_api import sync_playwright,expect
 out=Path(args.output_dir);out.mkdir(parents=True,exist_ok=True)
 auth=json.loads(Path(args.auth_file).read_text());assert auth['purpose']=='hv-proposals-disposable-testauth'
 client=Client(args.base_url);client.login('agent@hv4.invalid',auth['agent'])
 proof={'success':False,'phase':'seed','full_acceptance_passed':False}
 def note():
  target='SYN-UI-'+uuid4().hex[:10]
  client.resource('HV Synthetic Note',data={'synthetic_id':target,'label':'Unverändert'})
  return target

 def submit(package, target, dependencies, lane=None, title='Bezeichnung anpassen'):
  return client.api('submit', key=uuid4().hex, package=package,
   package_meta={'title':'Synthetik · UI '+package,'reason':'Ausschließlich synthetischer Oberflächentest','lane_label':'Notizen'},
   payload={'target':target,'label':'Neue Bezeichnung'}, dependencies=dependencies,
   metadata={'title':title,'summary':'Unverändert → Neu','lane':lane,'rationale':'Synthetische Prüfung','sources':[{'label':'Synthetische Quelle'}]})

 def seed(lanes=3,steps=3):
  package='ui-'+uuid4().hex[:10]
  root=submit(package,note(),[])
  nodes=[root]
  for i in range(lanes):
   target=note();parent=root
   for j in range(steps):
    parent=submit(package,target,[binding(parent)],{'key':str(i),'label':'Synthetische Zeile '+str(i+1)})
    nodes.append(parent)
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
   def collapse_sidebar(page):
    if page.evaluate("() => frappe.app.sidebar.sidebar_expanded"):
     page.locator('.sidebar-edge:visible').click()
    page.wait_for_function("() => frappe.app.sidebar.sidebar_expanded === false")
    assert 'sidebar-collapsed' in page.locator('body').get_attribute('class').split()

   def set_theme(page, theme):
    page.locator('.dock-user-button:visible, .sidebar-user-button:visible').first.click()
    page.get_by_text(re.compile(r'^(Einstellungen|Settings)$')).filter(visible=True).click()
    dialog = page.locator('.settings-dialog-wrapper:visible')
    dialog.locator('[data-tab-id="appearance"]').click()
    card = dialog.locator('.theme-card').filter(
     has=page.locator(f'.theme-card-preview > [data-theme="{theme}"]:only-child'))
    card.click()
    expect(page.locator('html')).to_have_attribute('data-theme-mode', theme)
    expect(page.locator('html')).to_have_attribute('data-theme', theme)
    page.keyboard.press('Escape')
    expect(dialog).to_be_hidden()
    expect(page.locator('.modal-backdrop:visible')).to_have_count(0)
    expect(page.locator('.es-toast:visible, .frappe-alert:visible')).to_have_count(0, timeout=12000)

   def snapshot(page, filename, theme, tab_name):
    set_theme(page, theme)
    active = page.locator('.hv-prop-root .hv-tab.is-active')
    expect(active).to_have_count(1)
    expect(active).to_have_attribute('aria-pressed', 'true')
    expect(active).to_contain_text(tab_name)
    page.screenshot(path=str(out / f'{filename}-{theme}.png'), full_page=True, animations='disabled')

   def dimensions(page):
    return page.locator('.hv-prop-scroll').evaluate("""e => ({
     client: e.clientWidth, scroll: e.scrollWidth,
     node: e.querySelector('[data-node]').getBoundingClientRect().width,
     detail: document.querySelector('.hv-prop-detail').getBoundingClientRect().width
    })""")

   proof['phase']='agent';agent=login('agent');agent.locator(f'[data-package="{package}"]').click();expect(agent.locator('[data-node]')).to_have_count(10);expect(agent.get_by_role('button',name='Offene freigeben …',exact=True)).to_have_count(0);expect(agent.get_by_text('Nur Prüfer können freigeben.',exact=True)).to_be_visible()
   proof['phase']='reviewer';page=login('reviewer')
   page.get_by_role('button', name='Alle (', exact=False).click()
   expect(page.locator('.hv-prop-root .hv-tab.is-active')).to_contain_text('Alle')
   page.get_by_role('button', name='Offen (', exact=False).click()
   for theme in ('light','dark'):
    snapshot(page, 'paketliste', theme, 'Offen')
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
   predecessors = page.get_by_role('group', name='Vorgänger')
   successors = page.get_by_role('group', name='Nachfolger')
   expect(predecessors.get_by_text('keine', exact=True)).to_be_visible()
   expect(successors.get_by_role('button')).to_have_count(3)
   assert successors.bounding_box()['y'] >= predecessors.bounding_box()['y'] + predecessors.bounding_box()['height']
   assert page.locator('.hv-prop-detail td').first.evaluate("""cell => {
    const table = cell.closest('table');
    return [...table.querySelectorAll('td')].every(td =>
     [...td.childNodes].filter(node => node.nodeType === Node.TEXT_NODE).every(node =>
      [...node.textContent.matchAll(/[^\\s]+/g)].every(word => {
       const range = document.createRange();
       range.setStart(node, word.index);
       range.setEnd(node, word.index + word[0].length);
       return range.getClientRects().length === 1;
      })
     )
    );
   }""")
   if page.evaluate("() => frappe.app.sidebar.sidebar_expanded"):
    proof['graph_width_sidebar_open'] = dimensions(page)
    assert proof['graph_width_sidebar_open']['node'] == 200 and proof['graph_width_sidebar_open']['detail'] == 360
   collapse_sidebar(page)
   page.wait_for_function("() => { const e = document.querySelector('.hv-prop-scroll'); return e.clientWidth >= e.scrollWidth; }")
   proof['graph_width'] = dimensions(page)
   assert proof['graph_width']['node'] == 200 and proof['graph_width']['detail'] == 360
   proof['theme_colors'] = {}
   for theme in ('light','dark'):
    snapshot(page, 'paket', theme, 'Graph')
    colors = page.locator('.hv-prop-root').evaluate("""root => {
     const background = element => getComputedStyle(element).backgroundColor;
     const primary = getComputedStyle(root.querySelector('.hv-prop-detail .hv-btn-primary'));
     const selected = getComputedStyle(root.querySelector('[data-node][aria-pressed="true"]'));
     return { card: background(root), page: background(document.body),
      node: background(root.querySelector('[data-node]')), button: background(root.querySelector('.hv-btn')),
      primary_background: primary.backgroundColor, primary_text: primary.color,
      outline: selected.outlineColor, outline_width: parseFloat(selected.outlineWidth), outline_style: selected.outlineStyle,
      tab_background: background(root.querySelector('.hv-tab.is-active')),
      tab_text: getComputedStyle(root.querySelector('.hv-tab.is-active')).color };
    }""")
    proof['theme_colors'][theme] = colors
    assert colors['card'] == colors['node'] == colors['button']
    assert contrast(colors['primary_background'], colors['card']) >= 3
    assert contrast(colors['primary_background'], colors['page']) >= 3
    assert contrast(colors['primary_background'], colors['primary_text']) >= 4.5
    assert colors['outline_style'] == 'solid' and colors['outline_width'] >= 2
    assert contrast(colors['outline'], colors['node']) >= 3
   assert proof['theme_colors']['light']['card'] != proof['theme_colors']['dark']['card']
   for group in (predecessors, successors):
    assert group.evaluate("""element => {
     const bounds = [...element.children].map(child => child.getBoundingClientRect());
     return bounds.every((box, index) => !index || box.top >= bounds[index - 1].bottom);
    }""")
   proof['primary_and_selected_node_contrast']=True
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
    snapshot(page, 'paket-liste', theme, 'Liste')
   proof['six_ui_corrections']=True
   proof['phase']='reject';page.goto(args.base_url+'/desk/hv-proposals/'+rejected);page.get_by_role('button',name='Ablehnen …',exact=True).wait_for();page.get_by_role('button',name='Ablehnen …',exact=True).click();page.locator('.modal:visible textarea').fill('Synthetischer Ablehnungsgrund');page.get_by_role('button',name='Ablehnung bestätigen',exact=True).click()
   page.get_by_text('Synthetischer Ablehnungsgrund',exact=False).first.wait_for();graph=client.api('package_graph',package=rejected);assert [n['status'] for n in graph['nodes']]==['Rejected','Stale']
   page.locator(f'[data-node="{small[1]["id"]}"]').click();page.get_by_role('button',name='Neue Revision anfordern',exact=True).click();page.locator('.modal:visible textarea').fill('Bitte synthetisch überarbeiten');page.get_by_role('button',name='Anfordern',exact=True).click();page.get_by_text('Nachbesserung angefordert',exact=False).wait_for()
   proof['phase']='review_regressions'
   wide, wide_nodes = seed(lanes=6, steps=1)
   root, first = wide_nodes[:2]
   page.goto(args.base_url+'/desk/hv-proposals/'+wide)
   canvas_nodes = page.locator('[data-node]')
   expect(canvas_nodes).to_have_count(6)
   root_node = page.locator(f'[data-node="{root["id"]}"]')
   root_node.click()
   successors = page.get_by_role('group', name='Nachfolger')
   expect(successors.get_by_role('button')).to_have_count(6)

   late = submit(wide, note(), [binding(root)], {'key':'0','label':'Synthetische Zeile 1'}, 'Neue Verzweigung')
   late_node = page.locator(f'[data-node="{late["id"]}"]')
   root_node.click()
   expect(successors.get_by_role('button')).to_have_count(7)
   expect(late_node).to_have_count(0)
   with page.expect_response(lambda r: r.url.endswith('.package_graph')) as refreshed:
    successors.get_by_role('button', name='Neue Verzweigung', exact=False).click()
   assert refreshed.value.ok
   expect(late_node).to_have_attribute('aria-pressed','true')
   expect(page.get_by_role('heading',name='Neue Verzweigung',exact=True)).to_be_visible()
   first_box = page.locator(f'[data-node="{first["id"]}"]').bounding_box()
   late_box = late_node.bounding_box()
   assert first_box['x'] == late_box['x']
   assert abs(first_box['y'] - late_box['y']) >= max(first_box['height'], late_box['height'])
   proof['late_branch_visible_without_overlap']=True

   def sent_bindings(response):
    assert response.ok
    refs = response.request.post_data_json['bindings']
    return json.loads(refs) if isinstance(refs, str) else refs

   expect(canvas_nodes).to_have_count(7)
   visible_ids = set(canvas_nodes.evaluate_all("nodes => nodes.map(node => node.dataset.node)"))
   all_refs = {node['id']:binding(node) for node in [*wide_nodes, late]}
   hidden_ids = all_refs.keys() - visible_ids
   assert len(hidden_ids) == 1
   hidden_id = next(iter(hidden_ids))
   page.get_by_role('button',name='Offene freigeben …',exact=True).click()
   expect(page.get_by_text('7 offene Vorschläge freigeben',exact=True)).to_be_visible()
   with page.expect_response(lambda r:r.url.endswith('.review_many')) as response:
    page.get_by_role('button',name='Freigaben bestätigen',exact=True).click()
   refs = sent_bindings(response.value)
   assert len(refs) == len(visible_ids)
   assert {ref['id']:ref for ref in refs} == {id:all_refs[id] for id in visible_ids}
   assert client.api('view',proposal_id=hidden_id)['status'] == 'Pending'

   reviewer = Client(args.base_url)
   reviewer.login('reviewer@hv4.invalid',auth['reviewer'])
   reviewer.api('review',binding=all_refs[hidden_id],approve=True)
   page.reload()
   execute_visible = page.get_by_role('button',name='Freigegebene ausführen (7)',exact=True)
   expect(execute_visible).to_be_enabled()
   page.get_by_role('button',name='Liste',exact=True).click()
   expect(page.get_by_role('button',name='Freigegebene ausführen (8)',exact=True)).to_be_enabled()
   page.get_by_role('button',name='Graph',exact=True).click()
   with page.expect_response(lambda r:r.url.endswith('.execute_ready')) as executed:
    execute_visible.click()
   refs = sent_bindings(executed.value)
   assert len(refs) == len(visible_ids)
   assert {ref['id']:ref for ref in refs} == {id:all_refs[id] for id in visible_ids}
   assert client.api('view',proposal_id=hidden_id)['status'] == 'Approved'
   expect(page.get_by_role('button',name='Freigegebene ausführen (0)',exact=True)).to_be_disabled()
   page.get_by_role('button',name='1 weitere Notizen',exact=False).click()
   expect(canvas_nodes).to_have_count(8)
   expect(page.get_by_role('button',name='Freigegebene ausführen (1)',exact=True)).to_be_enabled()
   proof['bulk_bindings_match_visible_nodes']=True
   proof['phase']='batch_navigation'
   destination, _ = seed(lanes=1, steps=1)

   def switch_before_response(method, action):
    pattern = '**/api/method/hausverwaltung.proposals.frappe_service.' + method
    held = []
    def hold(route):
     held.append(route)
    page.route(pattern, hold, times=1)
    with page.expect_request(lambda request: request.url.endswith('.'+method)):
     action()
    page.get_by_role('button',name='← Alle Pakete',exact=True).click()
    page.locator(f'[data-package="{destination}"]').click()
    expect(page.get_by_role('heading',name=f'Synthetik · UI {destination}',exact=True)).to_be_visible()
    expect(page.get_by_role('heading',name='Änderung',exact=True)).to_be_visible()
    assert len(held) == 1
    graph_requests = []
    def record_graph(request):
     if request.url.endswith('.package_graph'):
      graph_requests.append(request.url)
    page.on('request', record_graph)
    try:
     with page.expect_response(lambda response: response.url.endswith('.'+method)) as released:
      held[0].continue_()
     assert released.value.ok
     assert released.value.finished() is None
     page.evaluate("""async () => {
      await frappe.after_ajax();
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
     }""")
     expect(page.get_by_role('heading',name=f'Synthetik · UI {destination}',exact=True)).to_be_visible()
     expect(page.locator('.hv-prop-root [role="status"]')).to_be_empty()
     assert not graph_requests
    finally:
     page.remove_listener('request', record_graph)

   switch_before_response('execute_ready',
    lambda: page.get_by_role('button',name='Freigegebene ausführen (1)',exact=True).click())
   assert client.api('view',proposal_id=hidden_id)['status'] == 'Succeeded'
   approval_package, approval_nodes = seed(lanes=1,steps=1)
   page.locator('.hv-prop-root').get_by_role('button',name='← Alle Pakete',exact=True).click()
   page.locator(f'[data-package="{approval_package}"]').click()
   page.get_by_role('button',name='Offene freigeben …',exact=True).click()
   expect(page.get_by_text('2 offene Vorschläge freigeben',exact=True)).to_be_visible()
   switch_before_response('review_many',
    lambda: page.get_by_role('button',name='Freigaben bestätigen',exact=True).click())
   assert all(client.api('view',proposal_id=node['id'])['status']=='Approved' for node in approval_nodes)
   proof['batch_results_stay_with_origin_package']=True
   proof['phase']='op_checkbox_contrast'
   set_theme(page, 'dark')
   page.add_style_tag(url=args.base_url+'/assets/hausverwaltung/op_workflow/styles.css')
   # Render the real OP styles without creating invoices or changing workflow data.
   proof['op_checkboxes_dark'] = page.evaluate("""() => {
    const root = document.createElement('div');
    root.id = 'op-workflow-root';
    document.body.append(root);
    const states = {};
    for (const state of ['checked', 'indeterminate']) {
     const checkbox = document.createElement('input');
     checkbox.type = 'checkbox';
     checkbox[state] = true;
     root.append(checkbox);
     const style = getComputedStyle(checkbox);
     states[state] = { background: style.backgroundColor, mark: decodeURIComponent(style.backgroundImage) };
    }
    root.remove();
    return states;
   }""")
   for state in proof['op_checkboxes_dark'].values():
    assert "stroke='white'" in state['mark']
    assert contrast('rgb(255, 255, 255)', state['background']) >= 3
    assert contrast(state['background'], proof['theme_colors']['dark']['card']) >= 3
   proof.update(success=True,full_acceptance_passed=True,phase='complete',package=package,rejected_package=rejected,normal_separate_logins=True,bulk_confirmation=True,ordered_execution=True,rejection_stales_successor=True,list_toggle=True,responsive=True);browser.close()
 except BaseException as e:
  proof.update(error_type=type(e).__name__,frames=[{'file':f.filename,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(e.__traceback__)])
 (out/'desk-e2e.json').write_text(json.dumps(proof,indent=2,ensure_ascii=False));return proof['success']

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--synthetic',action='store_true',required=True)
 for field in ('base-url','auth-file','dependencies','output-dir'):p.add_argument('--'+field,required=True)
 p.add_argument('--chromium',default='/usr/bin/chromium');a=p.parse_args();assert urlsplit(a.base_url).hostname=='127.0.0.1';sys.path.insert(0,a.dependencies)
 with open('/dev/null','w') as sink,contextlib.redirect_stdout(sink),contextlib.redirect_stderr(sink):ok=run(a)
 raise SystemExit(0 if ok else 1)
