import hashlib, os, re, shutil, tempfile, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get('WASL_URL', 'http://localhost:8080/') + '?signal=127.0.0.1:9000'
T = tempfile.mkdtemp(prefix='wasl-')
ROOT = BASE.split('?')[0]
SHOTS = os.environ.get('WASL_SHOTS', tempfile.gettempdir())
CHROME = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium') or None
ARGS = ['--no-proxy-server', '--disable-features=WebRtcHideLocalIpsWithMdns']
big = os.urandom(120 * 1024 * 1024); open(f'{T}/video.mp4', 'wb').write(big)
H = hashlib.sha256(big).hexdigest()
res = []
def check(n, ok, d=''): res.append(ok); print('PASS' if ok else 'FAIL', n, d)
vis = lambda pg, sel: pg.evaluate(f"!document.querySelector('{sel}').hidden")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=ARGS)
    iphone = {k: v for k, v in p.devices['iPhone 13'].items() if k != 'default_browser_type'}
    def ctx(**kw):
        c = br.new_context(**kw); c.route(re.compile(r'fonts\.(googleapis|gstatic)\.com'), lambda r: r.abort()); return c
    pa = ctx(viewport={'width': 1280, 'height': 900}).new_page(); pa.goto(BASE)
    pa.wait_for_selector('#pair:not([hidden])'); code = pa.inner_text('#code').replace(' ', '')
    link = f'{ROOT}?r={code}&signal=127.0.0.1:9000'
    pb = ctx(**iphone).new_page(); pb.goto(link)
    pb.wait_for_selector('#room:not([hidden])'); pa.wait_for_selector('#room:not([hidden])')

    # >100MB: declining the confirm sends nothing
    msgs = []
    pa.once('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
    pa.set_input_files('#pick', f'{T}/video.mp4'); time.sleep(1)
    check('>100MB asks first; cancel sends nothing', msgs and '100MB' in msgs[0] and pa.evaluate("document.querySelectorAll('#list .it').length") == 0)
    # accept -> 120MB arrives intact
    pa.once('dialog', lambda d: d.accept())
    t0 = time.time(); pa.set_input_files('#pick', f'{T}/video.mp4')
    pb.wait_for_function("document.querySelectorAll('#list .it.done').length >= 1", timeout=180000)
    dt = time.time() - t0
    h = pb.evaluate("""async () => { const u = document.querySelector('#list .it').dataset.url; const b = await (await fetch(u)).arrayBuffer();
      return [...new Uint8Array(await crypto.subtle.digest('SHA-256', b))].map(x => x.toString(16).padStart(2, '0')).join(''); }""")
    check('120MB arrives byte-identical', h == H, f'{dt:.1f}s on loopback ({120/dt:.0f} MB/s)')

    # phone goes to background (page frozen, like iOS) -> PC notices via heartbeat
    # block the phone's JS for 25s (what iOS does to a background tab)
    t0 = time.time(); pb.evaluate("setTimeout(() => { const t = Date.now(); while (Date.now() - t < 25000) {} }, 0)")
    pa.wait_for_selector('#pair:not([hidden])', timeout=40000)
    check('PC notices frozen phone', True, f'{time.time()-t0:.1f}s')
    pb.wait_for_selector('#fail:not([hidden])', timeout=40000)
    check('phone wakes up → shows reconnect', 'انقطع' in pb.inner_text('#failMsg'))
    pb.click('#retry')
    pb.wait_for_selector('#room:not([hidden])', timeout=20000); pa.wait_for_selector('#room:not([hidden])', timeout=20000)
    check('one tap reconnects', True)
    br.close()
print(f'{sum(res)}/{len(res)} passed')

import sys
sys.exit(0 if all(res) else 1)
