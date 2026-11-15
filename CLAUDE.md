# wasl (وصل)

Send photos/files between a phone and a computer on the same Wi-Fi: scan a QR code, drop files, they go device-to-device over WebRTC. No app, no account, no server storage. Modeled on drop.musaabk.dev.

- Live: https://aiziz-space.github.io/wasl/ (GitHub Pages, deploys from `main` / root, ~1 min after a push)
- `main` is the live site. Work on a branch and merge only after `bash tests/run.sh` passes.

## Owner
Abdulaziz (GitHub `aiziz-space`). Arabic speaker, mid-level technical, learning as he goes: reply in Arabic, explain each change in one or two plain sentences, and say what you tested.

## Files
- `index.html` — the whole app: HTML, CSS, and one app `<script>` block at the end wrapped in `{ }`. No build step, no framework.
- `vendor/peerjs.min.js` (PeerJS 1.5.5), `vendor/qrcode.js` (qrcode-generator 1.4.4) — copied unmodified, never edit.
- `tests/` — end-to-end tests (`run.sh`, `e2e.py`, `extra.py`).

## How it works
- **Signaling**: PeerJS public cloud server (0.peerjs.com) by default — free, shared, no uptime guarantee. `CFG.server` switches to a self-hosted PeerServer. Peer IDs are `CFG.prefix + 6-char code` (alphabet without look-alike chars). `?signal=host:port` overrides signaling **only on localhost** (used by tests); keep it that way.
- **ICE**: STUN only, deliberately no TURN, so file bytes never relay through any server. Consequence: both devices must reach each other directly (same network). Do not add TURN without asking the owner — the FAQ promises files never pass through a server.
- **Roles**: no `?r` → host: registers its ID, shows QR of `<page>?r=<code>`, code persists per tab in sessionStorage. `?r=<code>` → guest: random ID, dials the host. The code box lets either side dial the other. Host accepts **one** device; extra connections get `{t:'busy'}` and close themselves (host force-closes after 5s).
- **Protocol** (`serialization:'raw'`, one reliable ordered DataChannel): JSON strings `{t:'hi',name}`, `{t:'meta',id,name,size,mime}` → ArrayBuffer chunks (64 KB, capped by `sctp.maxMessageSize`) → `{t:'end',id}`; receiver answers `{t:'got',id}` (sender shows "وصل ✓"). Text/links: `{t:'text',id,text}` (max `CFG.textMax` = 100k chars); texts over 8000 chars go as several `{t:'text',id,text,more:true}` parts, last without `more`, so no single message exceeds `sctp.maxMessageSize`. Receiver shows only the first 3000 chars (laying out a 100k-char Arabic paragraph freezes the page for seconds); «نسخ» copies the full text; only http/https links become `<a>`. Also `{t:'cancel',id}`, `{t:'busy'}`, `{t:'ping'}` every 2s; no data for `CFG.dead` (12s) = peer lost (phones pause background tabs).
- **Backpressure**: sender pauses while `bufferedAmount > 1 MB`, resumes on `bufferedamountlow` (500 ms fallback timer).
- **Memory**: receiver keeps each file as Blob parts until saved → files over 100 MB need confirmation.
- `pagehide` closes the connection cleanly; `beforeunload` warns if unsaved files exist; Wake Lock keeps the screen on while connected.

## Conventions
- Bilingual UI: every string lives in the `I18N` object (`ar` + `en`, same keys). Static text uses `data-i18n` / `data-i18n-ph` / `data-i18n-aria`; dynamic text goes through `t(key, params)` and is stored (`ui`, item `st`) so `applyLang()` can re-render it. Language = saved choice (`localStorage` `wasl-lang`) → else Arabic if the browser lists Arabic → else English. `dir` switches rtl/ltr; use logical CSS properties. Arabic copy is simple and Saudi-friendly. Add every new string in both languages.
- Wrap numbers/sizes with `fmt()` (LRI/PDI isolates) so they don't flip inside Arabic text.
- Look: Alexandria (headings) + IBM Plex Sans Arabic (text), one royal-blue accent, graphite dark / paper light themes via CSS variables in `:root`.
- Anything that comes from the other device (file names, device name) goes into the DOM via `textContent`, never `innerHTML`.
- Keep it a single static page with no build tools or frameworks unless the owner asks. Light and dark themes via `prefers-color-scheme`. Must work on iOS Safari 16+ (no `light-dark()`).
- Short English commit messages.

## Testing
`bash tests/run.sh` starts a local PeerServer (127.0.0.1:9000) and a static server (:8080), then drives two headless Chrome contexts (desktop + iPhone emulation). Covers: QR decodes to the right link, pairing, SHA-256 match in both directions (6 MB, empty, Arabic file name, image), save-link file names, delivery acks, third device refused with a message, item removal, disconnect + reconnect, wrong code, >100 MB confirm, 120 MB transfer, heartbeat detection of a stalled phone, text/links both ways (Arabic, XSS-looking text, link parsing, 100k-char text via Copy, 100,001 refused); `tests/lang.py` covers language detection, the toggle, re-rendering live texts, persistence and no sideways scroll on phones. Tests run Chrome with locale `ar-SA` unless they set another. Needs node/npm, python3, `pip install playwright opencv-python-headless numpy`, and Chrome (or `playwright install chromium`).
Not covered: real iOS/Android devices and the public PeerJS server — say so when reporting.

## Ideas discussed, not built yet
- Ask on the host before accepting a device ("iPhone يبي يتصل — تقبل؟").
- Optional fixed personal code so the phone reconnects with one tap (tradeoff: anyone who has the code can try while the page is open).
- Self-hosted PeerServer if the public one becomes unreliable.
- If this ever becomes a paid product: GitHub Pages terms forbid commercial/SaaS use → move hosting (e.g. Cloudflare Pages or Netlify).
