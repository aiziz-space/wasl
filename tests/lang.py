import os, re, shutil, tempfile, time
from playwright.sync_api import sync_playwright

BASE = os.environ.get('WASL_URL', 'http://localhost:8080/') + '?signal=127.0.0.1:9000'
ROOT = BASE.split('?')[0]
T = tempfile.mkdtemp(prefix='wasl-')
SHOTS = os.environ.get('WASL_SHOTS', tempfile.gettempdir())
CHROME = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium') or None
ARGS = ['--no-proxy-server', '--disable-features=WebRtcHideLocalIpsWithMdns']
res = []
def check(n, ok, d=''): res.append(bool(ok)); print('PASS' if ok else 'FAIL', n, d)
open(f'{T}/note.txt', 'w').write('hello')

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=ARGS)
    iphone = {k: v for k, v in p.devices['iPhone 13'].items() if k != 'default_browser_type'}
    def ctx(**kw):
        c = br.new_context(**kw); c.route(re.compile(r'fonts\.(googleapis|gstatic)\.com'), lambda r: r.abort()); return c
    A = ctx(viewport={'width': 1280, 'height': 900}, locale='en-US')
    pa = A.new_page(); pa.goto(BASE); pa.wait_for_selector('#pair:not([hidden])')
    attr = lambda pg: pg.evaluate("[document.documentElement.lang, document.documentElement.dir]")
    check('English browser opens in English, LTR', attr(pa) == ['en', 'ltr'] and pa.inner_text('h2') == 'Scan the code with your phone camera', attr(pa))
    check('toggle offers Arabic', pa.inner_text('#lang').strip() == 'العربية')
    pa.screenshot(path=f'{SHOTS}/wasl_en_pc_pair.png', full_page=True)
    code = re.sub(r'\s', '', pa.inner_text('#code'))
    B = ctx(**iphone, locale='ar-SA')
    pb = B.new_page(); pb.goto(f'{ROOT}?r={code}&signal=127.0.0.1:9000')
    pa.wait_for_selector('#ask[open]')
    check('accept prompt in English', pa.inner_text('#askTitle') == '\u2068iPhone\u2069 wants to connect — accept?' and pa.inner_text('#askYes') == 'Accept', pa.inner_text('#askTitle'))
    pa.click('#askYes')
    pb.wait_for_selector('#room:not([hidden])'); pa.wait_for_selector('#room:not([hidden])'); time.sleep(0.5)
    check('each device uses its own language', pa.inner_text('#peerName') == 'Connected to iPhone' and pb.inner_text('#peerName') == 'متصل بـ Linux',
          f"{pa.inner_text('#peerName')} | {pb.inner_text('#peerName')}")
    pa.set_input_files('#pick', f'{T}/note.txt')
    pa.wait_for_function("document.querySelector('#list .it.done')")
    check('English status on sender', 'Delivered ✓' in pa.inner_text('#list .sz'), pa.inner_text('#list .sz'))
    pa.screenshot(path=f'{SHOTS}/wasl_en_pc_room.png', full_page=True)
    pa.click('#lang')
    check('toggle switches to Arabic RTL', attr(pa) == ['ar', 'rtl'] and pa.inner_text('h1') == 'انقل ملفاتك بين جوالك وكمبيوترك.', attr(pa))
    check('live texts re-render', 'وصل ✓' in pa.inner_text('#list .sz') and pa.inner_text('#peerName') == 'متصل بـ iPhone' and pa.title().startswith('وصل'),
          pa.inner_text('#list .sz') + ' | ' + pa.inner_text('#peerName'))
    check('connection survives the switch', pa.evaluate("!document.querySelector('#room').hidden"))
    p2 = A.new_page(); p2.goto(BASE); p2.wait_for_selector('#pair:not([hidden])')
    check('choice is remembered', attr(p2) == ['ar', 'rtl'])
    p2.click('#lang')
    check('and can switch back', attr(p2) == ['en', 'ltr'] and p2.inner_text('#lang').strip() == 'العربية')
    D = ctx(**iphone, locale='en-US', color_scheme='dark')
    pd = D.new_page(); pd.goto(BASE); pd.wait_for_selector('#pair:not([hidden])')
    pd.screenshot(path=f'{SHOTS}/wasl_en_phone_dark.png', full_page=True)
    no_overflow = pd.evaluate("document.documentElement.scrollWidth <= innerWidth")
    check('no sideways scroll on phone', no_overflow)
    br.close()
print(f'{sum(res)}/{len(res)} passed')
import sys; sys.exit(0 if all(res) else 1)
