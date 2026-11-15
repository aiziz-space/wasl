import hashlib, os, re, shutil, tempfile, time
import numpy as np, cv2
from playwright.sync_api import sync_playwright

BASE = os.environ.get('WASL_URL', 'http://localhost:8080/') + '?signal=127.0.0.1:9000'
T = tempfile.mkdtemp(prefix='wasl-')
ROOT = BASE.split('?')[0]
SHOTS = os.environ.get('WASL_SHOTS', tempfile.gettempdir())
CHROME = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium') or None
ARGS = ['--no-proxy-server', '--disable-features=WebRtcHideLocalIpsWithMdns']

files = {
    'big.bin': os.urandom(6 * 1024 * 1024 + 123),
    'ملف تجربة.txt': 'مرحبا — اختبار اسم عربي\n'.encode() * 50,
    'empty.txt': b'',
}
img = np.zeros((300, 400, 3), np.uint8); img[:] = (40, 120, 255); cv2.circle(img, (200, 150), 90, (255, 255, 255), -1)
cv2.imwrite(f'{T}/pic.png', img)
for n, b in files.items():
    open(f'{T}/{n}', 'wb').write(b)
files['pic.png'] = open(f'{T}/pic.png', 'rb').read()
back = os.urandom(1_500_000); open(f'{T}/from-phone.jpg', 'wb').write(back)
sha = lambda b: hashlib.sha256(b).hexdigest()
results = []
def check(name, ok, detail=''):
    results.append((name, bool(ok), detail)); print(('PASS' if ok else 'FAIL'), name, detail)

HASHES = """async () => Promise.all([...document.querySelectorAll('#list .it.done')].filter(li => li.dataset.url).map(async li => {
  const buf = await (await fetch(li.dataset.url)).arrayBuffer();
  const h = [...new Uint8Array(await crypto.subtle.digest('SHA-256', buf))].map(b => b.toString(16).padStart(2,'0')).join('');
  return {name: li.querySelector('.nm').textContent, sha: h, len: buf.byteLength, dl: li.querySelector('a[download]').getAttribute('download'), thumb: !!li.querySelector('.th img')};
}))"""
vis = lambda pg, sel: pg.evaluate(f"!document.querySelector('{sel}').hidden")

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=ARGS)
    iphone = {k: v for k, v in p.devices['iPhone 13'].items() if k != 'default_browser_type'}
    def ctx(**kw):
        c = br.new_context(**kw)
        c.route(re.compile(r'fonts\.(googleapis|gstatic)\.com'), lambda r: r.abort())
        return c
    logs = []
    def page(c, tag):
        pg = c.new_page()
        pg.on('console', lambda m: logs.append(f'[{tag}] {m.type}: {m.text}') if m.type in ('error', 'warning') else None)
        pg.on('pageerror', lambda e: logs.append(f'[{tag}] PAGEERROR {e}'))
        return pg

    A = ctx(viewport={'width': 1280, 'height': 900})
    pa = page(A, 'PC')
    pa.goto(BASE)
    pa.wait_for_selector('#pair:not([hidden])', timeout=15000)
    code = pa.inner_text('#code').replace(' ', '')
    check('host shows 6-char code', re.fullmatch(r'[a-z0-9]{6}', code), code)
    pa.screenshot(path=f'{SHOTS}/wasl_pc_pair.png', full_page=True)
    pa.locator('#qr').screenshot(path=f'{T}/qr.png')
    q = cv2.imread(f'{T}/qr.png'); q = cv2.copyMakeBorder(q, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=(255, 255, 255))
    link, _, _ = cv2.QRCodeDetector().detectAndDecode(q)
    check('QR decodes to pairing link', link == f'{ROOT}?r={code}&signal=127.0.0.1%3A9000', link)

    B = ctx(**iphone)
    pb = page(B, 'PHONE')
    t0 = time.time()
    pb.goto(link or f'{ROOT}?r={code}&signal=127.0.0.1:9000')
    pb.wait_for_selector('#room:not([hidden])', timeout=20000)
    pa.wait_for_selector('#room:not([hidden])', timeout=20000)
    check('both devices connect', True, f'{time.time()-t0:.1f}s')
    time.sleep(0.5)
    check('PC sees device name', 'iPhone' in pa.inner_text('#peerName'), pa.inner_text('#peerName'))
    check('phone sees device name', 'Linux' in pb.inner_text('#peerName'), pb.inner_text('#peerName'))

    # PC -> phone, 4 files incl. empty, image, Arabic name
    t0 = time.time()
    pa.set_input_files('#pick', [f'{T}/{n}' for n in files])
    pb.wait_for_function("document.querySelectorAll('#list .it.done').length >= 4", timeout=60000)
    pa.wait_for_function("document.querySelectorAll('#list .it.done').length >= 4", timeout=20000)
    dt = time.time() - t0
    got = {r['name']: r for r in pb.evaluate(HASHES)}
    for n, b in files.items():
        r = got.get(n)
        check(f'PC→phone {n} byte-identical', r and r['sha'] == sha(b) and r['len'] == len(b), f"{r and r['len']} bytes")
        check(f'save link filename {n}', r and r['dl'] == n)
    check('image thumbnail shown', got.get('pic.png', {}).get('thumb'))
    check('sender shows delivered ✓ (acks)', pa.evaluate("[...document.querySelectorAll('#list .sz')].every(s => s.textContent.includes('وصل ✓'))"))
    print(f'  6MB+ batch over loopback: {dt:.2f}s')

    # phone -> PC
    pb.set_input_files('#pick', f'{T}/from-phone.jpg')
    pa.wait_for_function("[...document.querySelectorAll('#list .it.done')].some(li => li.dataset.url)", timeout=30000)
    r = pa.evaluate(HASHES)
    check('phone→PC byte-identical', r and r[0]['sha'] == sha(back), r and r[0]['name'])
    pa.screenshot(path=f'{SHOTS}/wasl_pc_room.png', full_page=True)
    pb.screenshot(path=f'{SHOTS}/wasl_phone_room.png', full_page=True)

    # third device is refused, existing pair keeps working
    C = ctx(**iphone)
    pc = page(C, 'THIRD')
    pc.goto(link)
    time.sleep(6)
    check('third device not admitted', not vis(pc, '#room'))
    check('third device told why', vis(pc, '#fail') and 'جهاز ثالث' in pc.inner_text('#failMsg'), pc.inner_text('#failMsg') if vis(pc, '#fail') else 'no message')
    check('original pair still connected', vis(pa, '#room') and vis(pb, '#room'))
    C.close()

    # remove (×) a received item
    n0 = pb.evaluate("document.querySelectorAll('#list .it').length")
    pb.locator('#list .it .x').first.click()
    check('× removes item', pb.evaluate("document.querySelectorAll('#list .it').length") == n0 - 1)

    # phone closes the page -> PC returns to QR; phone reopens link -> reconnects
    t0 = time.time()
    pb.close()
    try:
        pa.wait_for_selector('#pair:not([hidden])', timeout=30000)
        check('PC detects disconnect, shows QR again', vis(pa, '#pairNote'), f'{time.time()-t0:.1f}s')
    except Exception as e:
        check('PC detects disconnect, shows QR again', False, str(e)[:80])
    check('PC keeps code after disconnect', pa.inner_text('#code').replace(' ', '') == code)
    check('PC keeps received files list', pa.evaluate("document.querySelectorAll('#list .it').length") >= 5)
    pb2 = page(B, 'PHONE2')
    pb2.goto(link)
    try:
        pb2.wait_for_selector('#room:not([hidden])', timeout=20000)
        pa.wait_for_selector('#room:not([hidden])', timeout=20000)
        pb2.set_input_files('#pick', f'{T}/ملف تجربة.txt')
        pa.wait_for_function("document.querySelectorAll('#list .it.done').length >= 6", timeout=20000)
        check('reconnect + transfer works', True)
    except Exception as e:
        check('reconnect + transfer works', False, str(e)[:120])

    # wrong code
    D = ctx(**iphone, color_scheme='dark')
    pd = page(D, 'DARK')
    pd.goto(BASE)
    pd.wait_for_selector('#pair:not([hidden])', timeout=15000)
    pd.screenshot(path=f'{SHOTS}/wasl_phone_pair_dark.png', full_page=True)
    pd.fill('#codeIn', 'zzz 999')
    pd.click('#join button[type=submit]')
    pd.wait_for_selector('#fail:not([hidden])', timeout=15000)
    check('wrong code → clear error', 'الرمز غير صحيح' in pd.inner_text('#failMsg'), pd.inner_text('#failMsg'))
    br.close()

print('\n'.join(logs[:30]) or 'no console errors')
print(f"\n{sum(r[1] for r in results)}/{len(results)} passed")

import sys
sys.exit(0 if all(r[1] if isinstance(r, tuple) else r for r in results) else 1)
