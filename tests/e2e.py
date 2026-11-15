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
def approve(pg, timeout=20000):
    pg.wait_for_selector('#ask[open]', timeout=timeout); pg.click('#askYes')
asking = lambda pg: pg.evaluate("document.querySelector('#ask').open")
# counts how many times the "accept?" dialog opens on a page
ASKS = "() => { window.__asks = 0; new MutationObserver(() => { if (document.querySelector('#ask').open) window.__asks++; }).observe(document.querySelector('#ask'), {attributes: true}); }"
# makes a phone never send its hi message (to test the 3s «جهاز» fallback)
NO_HI = """(() => { const s = RTCDataChannel.prototype.send;
  RTCDataChannel.prototype.send = function (d) { if (typeof d === 'string' && d.includes('"t":"hi"')) return; return s.call(this, d); }; })()"""

with sync_playwright() as p:
    br = p.chromium.launch(executable_path=CHROME, args=ARGS)
    iphone = {k: v for k, v in p.devices['iPhone 13'].items() if k != 'default_browser_type'}
    def ctx(**kw):
        kw.setdefault('locale', 'ar-SA')
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
    code = pa.inner_text('#code').replace(' ', '').replace('\n', '')
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
    pa.wait_for_selector('#ask[open]', timeout=20000)
    check('PC asks before accepting, with the device name', pa.inner_text('#askTitle') == '\u2068iPhone\u2069 يبي يتصل — تقبل؟', pa.inner_text('#askTitle'))
    check('focus is on «قبول»', pa.evaluate("document.activeElement.id") == 'askYes')
    pb.wait_for_function("document.querySelector('#waitMsg').textContent.includes('بانتظار موافقة')", timeout=5000)
    check('phone waits for approval, room hidden on both', not vis(pb, '#room') and not vis(pa, '#room'), pb.inner_text('#waitMsg'))
    pa.screenshot(path=f'{SHOTS}/wasl_pc_ask.png')
    pa.keyboard.press('Enter')
    pb.wait_for_selector('#room:not([hidden])', timeout=20000)
    pa.wait_for_selector('#room:not([hidden])', timeout=20000)
    check('Enter accepts; both devices connect', not asking(pa), f'{time.time()-t0:.1f}s')
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
    check('no prompt for the third device (busy as before)', not asking(pa))
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
    check('PC keeps code after disconnect', pa.inner_text('#code').replace(' ', '').replace('\n', '') == code)
    check('PC keeps received files list', pa.evaluate("document.querySelectorAll('#list .it').length") >= 5)
    pb2 = page(B, 'PHONE2')
    pb2.goto(link)
    try:
        approve(pa)  # new tab = new session → asks again
        pb2.wait_for_selector('#room:not([hidden])', timeout=20000)
        pa.wait_for_selector('#room:not([hidden])', timeout=20000)
        pb2.set_input_files('#pick', f'{T}/ملف تجربة.txt')
        pa.wait_for_function("document.querySelectorAll('#list .it.done').length >= 6", timeout=20000)
        check('reconnect + transfer works', True)
    except Exception as e:
        check('reconnect + transfer works', False, str(e)[:120])

    # text / links both ways ({t:'text'})
    TXT = """() => [...document.querySelectorAll('#list .it.txt.in')].map(li => {
      const p = li.querySelector('.tx');
      return {text: p.textContent, links: [...p.querySelectorAll('a')].map(a => a.getAttribute('href')), tags: [...p.querySelectorAll('*')].map(e => e.tagName)};
    })"""
    def got_text(pg, n):
        pg.wait_for_function(f"document.querySelectorAll('#list .it.txt.in').length >= {n}", timeout=20000)
        return pg.evaluate(TXT)[0]  # newest first
    try:
        AR = 'مرحبا يا عبدالعزيز 👋\nسطر ثاني — اختبار <img src=x onerror=alert(1)> & "اقتباس"'
        pa.fill('#msg', AR); pa.press('#msg', 'Enter')
        r = got_text(pb2, 1)
        check('PC→phone Arabic text identical (Enter sends)', r['text'] == AR, repr(r['text'][:40]))
        check('text shown as text only (no injected tags)', r['tags'] == [], str(r['tags']))
        check('PC input cleared after send', pa.input_value('#msg') == '')
        check('sender lists its own text', pa.evaluate("document.querySelectorAll('#list .it.txt.out').length") == 1)

        LNK = 'شوف https://example.com/a?b=1&c=ت، وهذا لا javascript:alert(1) ولا ftp://x.com'
        pa.fill('#msg', LNK); pa.click('#say button[type=submit]')
        r = got_text(pb2, 2)
        check('PC→phone link text identical', r['text'] == LNK)
        check('only the http(s) link is clickable, without trailing «،»', r['links'] == ['https://example.com/a?b=1&c=ت'], str(r['links']))

        BACK = 'من الجوال: http://192.168.1.5:8080/x?y=ي\nhttps://wasl.example/مسار).'
        pb2.fill('#msg', BACK); pb2.click('#say button[type=submit]')
        r = got_text(pa, 1)
        check('phone→PC text identical', r['text'] == BACK)
        check('phone→PC links', r['links'] == ['http://192.168.1.5:8080/x?y=ي', 'https://wasl.example/مسار'], str(r['links']))

        # built in JS so length counts UTF-16 units like the app does; 7999/8000 cut lands inside an emoji
        LONG = pb2.evaluate("() => { let s = 'ن'.repeat(7999); while (s.length < 100000) s += '😀 نص طويل '; s = s.slice(0, 100000); if (/[\\uD800-\\uDBFF]$/.test(s)) s = s.slice(0, -1) + 'ي'; document.querySelector('#msg').value = s; return s; }")
        check('long test text is 100,000 JS chars', pb2.evaluate("document.querySelector('#msg').value.length") == 100000)
        pb2.click('#say button[type=submit]')
        r = got_text(pa, 2)
        A.grant_permissions(['clipboard-read', 'clipboard-write'], origin=ROOT.rstrip('/'))
        pa.locator('#list .it.txt.in .cp').first.click(); time.sleep(0.3)
        check('100,000-char text arrives identical (split into parts, checked via Copy)', pa.evaluate('navigator.clipboard.readText()') == LONG)
        check('long text shows a preview + note', LONG.startswith(r['text']) and 1000 < len(r['text']) < 3001 and vis(pa, '#list .it.txt.in .more'), f"{len(r['text'])} shown")
        check('page stays responsive (still connected)', vis(pa, '#room') and vis(pb2, '#room'))
        msgs = []
        pb2.on('dialog', lambda d: (msgs.append(d.message), d.dismiss()))
        pb2.evaluate("s => { document.querySelector('#msg').value = s + 'x'; setTimeout(() => document.querySelector('#say').requestSubmit()); }", LONG)
        for _ in range(30):
            if msgs: break
            pb2.wait_for_timeout(100)
        time.sleep(1)
        check('100,001 chars refused with a message', msgs and '100' in msgs[0] and pa.evaluate("document.querySelectorAll('#list .it.txt.in').length") == 2, msgs[:1])
        check('still connected after the refusal', vis(pa, '#room') and vis(pb2, '#room'))

        pa.locator('#list .it.txt.in .cp').nth(1).click()  # the BACK text
        time.sleep(0.3)
        check('copy button copies the exact text', pa.evaluate('navigator.clipboard.readText()') == BACK)
    except Exception as e:
        check('text messages', False, str(e)[:160])

    # same device comes back in the same session (reload keeps sessionStorage) → accepted without asking
    try:
        pa.evaluate(ASKS)
        pb2.reload()
        pb2.wait_for_selector('#room:not([hidden])', timeout=20000)
        pa.wait_for_selector('#room:not([hidden])', timeout=20000)
        check('returning device auto-accepted (no prompt)', pa.evaluate('window.__asks') == 0, f"prompts: {pa.evaluate('window.__asks')}")
        n0 = pa.evaluate("document.querySelectorAll('#list .it.done').length")
        pb2.set_input_files('#pick', f'{T}/from-phone.jpg')
        pa.wait_for_function(f"document.querySelectorAll('#list .it.done').length > {n0}", timeout=20000)
        check('transfer works after auto-accept', pa.evaluate(HASHES)[0]['sha'] == sha(back))
    except Exception as e:
        check('returning device auto-accepted (no prompt)', False, str(e)[:160])

    # decline: nothing passes, the other side is told
    E = ctx(viewport={'width': 1280, 'height': 900})
    pe = page(E, 'PC2')
    pe.goto(BASE); pe.wait_for_selector('#pair:not([hidden])', timeout=15000)
    code2 = pe.inner_text('#code').replace(' ', '').replace('\n', '')
    F = ctx(**iphone)
    F.add_init_script(NO_HI)
    pf = page(F, 'PHONE3')
    try:
        pf.goto(f'{ROOT}?r={code2}&signal=127.0.0.1:9000')
        pf.wait_for_function("document.querySelector('#waitMsg').textContent.includes('بانتظار')", timeout=20000)
        t0 = time.time()
        pf.set_input_files('#pick', f'{T}/from-phone.jpg')  # tries to send before being accepted
        pf.evaluate("() => { document.querySelector('#msg').value = 'نص قبل القبول'; document.querySelector('#say').requestSubmit(); }")
        pe.wait_for_selector('#ask[open]', timeout=10000)
        check('no hi → prompt after ~3s says «جهاز»', pe.inner_text('#askTitle') == 'جهاز يبي يتصل — تقبل؟' and time.time() - t0 > 2, f"{pe.inner_text('#askTitle')} after {time.time()-t0:.1f}s")
        pe.click('#askNo')
        pf.wait_for_selector('#fail:not([hidden])', timeout=10000)
        check('decline reaches the other side', 'الجهاز الثاني رفض الاتصال' in pf.inner_text('#failMsg'), pf.inner_text('#failMsg'))
        pf.screenshot(path=f'{SHOTS}/wasl_phone_rejected.png')
        time.sleep(1)
        check('nothing transferred; PC back to QR', pe.evaluate("document.querySelectorAll('#list .it').length") == 0 and vis(pe, '#pair') and not vis(pe, '#room'))

        pf.click('#retry')
        pe.wait_for_selector('#ask[open]', timeout=15000)
        pe.keyboard.press('Escape')
        pf.wait_for_selector('#fail:not([hidden])', timeout=10000)
        check('Esc declines', 'رفض' in pf.inner_text('#failMsg') and not asking(pe))

        pf.click('#retry')
        pe.wait_for_selector('#ask[open]', timeout=15000)
        t0 = time.time()
        pf.wait_for_selector('#fail:not([hidden])', timeout=45000)
        dt = time.time() - t0
        check('no answer for 30s → declined (heartbeat kept it alive meanwhile)', 'رفض' in pf.inner_text('#failMsg') and 28 < dt < 36 and not asking(pe), f'{dt:.1f}s')
        check('still nothing transferred', pe.evaluate("document.querySelectorAll('#list .it').length") == 0)
    except Exception as e:
        check('decline flow', False, str(e)[:160])
    E.close(); F.close()

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
