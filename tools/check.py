#!/usr/bin/env python3
"""Release checks (maintainers; needs the official firmware file, which never goes into this repo).

    uv run --with playwright==1.63.0 python3 tools/check.py "<official Ampero Mini_firmware_V2.2.bin>" \
        [--zip "<Hotone's Ampero Mini_firmware_V2.2.*.zip>"] [--against OFF WHITE]

1. regenerate: tools/build_patch.py reproduces the committed patch-data.js byte for byte (needs clang 22.1.8), so every
   byte in it comes from our build;
2. no Hotone bytes: no shipped edit byte equals the official file's byte at its site, and no 8-byte run of our
   appended code occurs anywhere in the official file;
3. CLI: node patcher.js gives each variant's recorded output sha256, and refuses a file that is not the official one;
   with --zip: Hotone's zip gives the same bytes as the .bin, and these zips are refused: Hotone's zip with one byte of
   the firmware entry's data flipped, a valid zip whose firmware entry is a modified .bin, a zip without that entry;
4. page: index.html in headless Chromium, over http://localhost and from file://: drop the file (and the zip), pick the
   option, download; the download is byte-identical to the CLI output; the modified file and zips are refused;
5. --against: the CLI outputs equal the given builds (the Renode-tested files) byte for byte.
"""
import functools, hashlib, http.server, json, subprocess, sys, tempfile, threading, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'tools'))
import build_patch as B


def main():
    a = sys.argv[1:]
    against = zip_path = None
    if '--zip' in a:
        i = a.index('--zip'); zip_path = Path(a[i + 1]).resolve(); del a[i:i + 2]
    if '--against' in a:
        i = a.index('--against'); against = dict(off=Path(a[i + 1]), white=Path(a[i + 2])); del a[i:i + 3]
    stock_path = Path(a[0]).resolve()
    stock = stock_path.read_bytes()
    fails = []
    def need(ok, msg):
        print(('ok    ' if ok else 'FAIL  ') + msg)
        if not ok: fails.append(msg)

    # 1. regenerate
    pd = ROOT / 'patch-data.js'
    old = pd.read_bytes()
    subprocess.run([sys.executable, str(ROOT / 'tools/build_patch.py'), str(stock_path)], check=True, capture_output=True)
    need(pd.read_bytes() == old, 'patch-data.js regenerated from src/ by tools/build_patch.py: identical')
    pd.write_bytes(old)
    data = json.loads(old.decode().split('= ', 1)[1].rsplit(';\nif', 1)[0])

    # 2. no Hotone bytes
    for t, v in data['variants'].items():
        same = [(s, i) for s, h in v['edits'] for i, b in enumerate(bytes.fromhex(h)) if B.stock_at(stock, s + i, 1)[0] == b]
        need(not same, f'{t}: {sum(len(h) // 2 for _, h in v["edits"])} edit bytes, none equal to the official file at its site {same}')
        r = bytes.fromhex(v['region'])
        hits = sorted({i for i in range(len(r) - 7) if r[i:i + 8] in stock})
        need(not hits, f'{t}: no 8-byte run of the {len(r)}-byte appended code occurs in the official file {hits}')
        longest = 0
        while any(r[i:i + longest + 1] in stock for i in range(len(r) - longest)): longest += 1
        print(f'      {t}: longest run of the appended code found anywhere in the official file: {longest} bytes')

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        # 3. CLI
        cli = {}
        for t, v in data['variants'].items():
            out = tmp / f'cli_{t}.bin'
            subprocess.run(['node', str(ROOT / 'patcher.js'), str(stock_path), str(out), '--teal', t], check=True, capture_output=True)
            cli[t] = out.read_bytes()
            need(hashlib.sha256(cli[t]).hexdigest() == v['output_sha256'], f'CLI {t}: sha256 {v["output_sha256"]}')
        bad = tmp / 'modified.bin'
        bad.write_bytes(stock[:-1] + bytes([stock[-1] ^ 1]))
        refuse = {bad: 'not the official'}            # input -> words the refusal must contain
        inputs = [stock_path]
        if zip_path:
            inputs.append(zip_path)
            print(f'      zip sha256 {hashlib.sha256(zip_path.read_bytes()).hexdigest()} '
                  f'({"= Hotone" if hashlib.sha256(zip_path.read_bytes()).hexdigest() == data["zip_sha256"] else "not Hotone"}\'s, informational)')
            for t, v in data['variants'].items():
                out = tmp / f'zip_{t}.bin'
                subprocess.run(['node', str(ROOT / 'patcher.js'), str(zip_path), str(out), '--teal', t], check=True, capture_output=True)
                need(out.read_bytes() == cli[t], f'CLI {t}: zip input gives the same bytes as .bin input')
            z = bytearray(zip_path.read_bytes())
            with zipfile.ZipFile(zip_path) as zf:
                info = zf.getinfo(f'Ampero Mini_firmware_{data["firmware"]}.bin')
                assert zf.namelist().count(info.filename) == 1 and info.compress_type == zipfile.ZIP_DEFLATED
                at = info.header_offset + 30 + int.from_bytes(z[info.header_offset + 26:info.header_offset + 28], 'little') \
                    + int.from_bytes(z[info.header_offset + 28:info.header_offset + 30], 'little')
            z[at + info.compress_size // 2] ^= 0x10
            (tmp / 'modified.zip').write_bytes(z)
            refuse[tmp / 'modified.zip'] = 'not'
            with zipfile.ZipFile(tmp / 'rezipped.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(info.filename, bad.read_bytes())
            refuse[tmp / 'rezipped.zip'] = 'not the official'
            with zipfile.ZipFile(tmp / 'foreign.zip', 'w', zipfile.ZIP_DEFLATED) as zf:
                zf.writestr('Ampero Mini Firmware Release Note.txt', 'not firmware')
                zf.writestr('firmware/Ampero Mini_firmware_V2.2.bin', stock)
            refuse[tmp / 'foreign.zip'] = 'exactly one'
        for f, words in refuse.items():
            r = subprocess.run(['node', str(ROOT / 'patcher.js'), str(f), str(tmp / 'x.bin'), '--teal', 'off'], capture_output=True, text=True)
            need(r.returncode == 1 and words in r.stderr and not (tmp / 'x.bin').exists(),
                 f'CLI refuses {f.name}: {r.stderr.strip()[:110]}...')

        # 4. page
        from playwright.sync_api import sync_playwright
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        http.server.SimpleHTTPRequestHandler.log_message = lambda *a: None
        srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        urls = [f'http://127.0.0.1:{srv.server_address[1]}/index.html', (ROOT / 'index.html').as_uri()]
        with sync_playwright() as p:
            br = p.chromium.launch()
            for url in urls:
                pg = br.new_page(accept_downloads=True)
                errs = []
                pg.on('pageerror', lambda e: errs.append(str(e)))
                pg.on('console', lambda m: m.type == 'error' and errs.append(m.text))
                requests = []
                pg.on('request', lambda q: requests.append(q.url))
                pg.goto(url)
                for src in inputs:             # the same file twice in a row fires no change event: once per input
                  pg.set_input_files('#file', str(src))
                  pg.wait_for_function('n => document.querySelector("#status").textContent.startsWith(n + ":") && '
                                       '!document.querySelector("#go").disabled', arg=src.name, timeout=30000)
                  for t in data['variants']:
                    pg.click(f'label.tile:has(input[value={t}])'); assert pg.is_checked(f'input[name=teal][value={t}]')
                    pg.click('#go')
                    pg.wait_for_selector('#dl:not([hidden])', timeout=30000)
                    with pg.expect_download() as d:
                        pg.click('#save')
                    got = Path(d.value.path()).read_bytes()
                    need(got == cli[t], f'page {url.split(":")[0]} {t} from {src.suffix}: download ({d.value.suggested_filename}) '
                                        f'== CLI output, byte for byte; status: {pg.inner_text("#status")[:70]}...')
                for f, words in refuse.items():
                    pg.set_input_files('#file', str(f))
                    pg.wait_for_function('n => { const e = document.querySelector("#status .err"); '
                                         'return e && e.textContent.startsWith(n + ":"); }', arg=f.name, timeout=30000)
                    need(pg.is_disabled('#go') and pg.is_hidden('#dl') and words in pg.inner_text('#status'),
                         f'page {url.split(":")[0]}: {f.name} refused')
                local = [q for q in requests if not q.startswith((url.rsplit('/', 1)[0], 'blob:', 'data:'))]
                need(not local, f'page {url.split(":")[0]}: no request leaves the page\'s own folder {local}')
                need(not errs, f'page {url.split(":")[0]}: no script errors {errs}')
                pg.close()
            br.close()
        srv.shutdown()

        # 5. against the tested builds
        if against:
            for t, f in against.items():
                need(f.read_bytes() == cli[t], f'CLI {t} == {f} (the Renode-tested build), byte for byte')
    print('PASS' if not fails else f'FAIL ({len(fails)})')
    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()
