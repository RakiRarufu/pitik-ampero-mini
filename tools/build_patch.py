#!/usr/bin/env python3
"""Regenerate patch-data.js from our sources (maintainers only; users never need this).

    python3 tools/build_patch.py "<official Ampero Mini_firmware_V2.2.bin>"

Compiles src/about.c with the pinned compiler (CLANG below: other versions give other bytes, so another identity hash
and another output sha256), works out our edits, and keeps only the bytes that differ from the user's file at each
site. The official file is read to drop unchanged bytes and to record the output sha256 of each variant (through
patcher.js, i.e. the code the page runs); none of its bytes are written to patch-data.js (tools/check.py proves it).
Needs clang, ld.lld, llvm-objcopy, llvm-nm and node.
"""
import hashlib, json, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = '1.0.0'
FW = 'V2.2'
INPUT_SHA256 = '2928e3ca297cce1759944418cb91ce73a936a6b35032219086b652c3708c6f7c'   # Hotone's Ampero Mini_firmware_V2.2.bin
ZIP_SHA256 = '9b5565ceb6011abc3c6d287eee28e7a42444427f260958eebcb17738830c44e1'     # Hotone's download that holds it (informational)
CLANG = '22.1.8'
ITCM_LEN = 0x4C324                    # V2.2 ITCM image length; our code is linked right after it, 8-aligned
BASE = (ITCM_LEN + 7) & ~7
ABOUT = 0x1678C                       # About-only version getter: its first instruction becomes B.W about_version
# Footswitch teal = the green + blue channels (FS1 mask bits 0-2 = green, red, blue; FS2 = the same << 3). Stock lights
# teal in two places: the preset-mode masks (immediates of two MOVS r0,#mask in the LED logic, each after the switch is
# switched dark) and the looper's drum-slot colour table (SDRAM data, one word per footswitch).
TEAL = {'off': (0, 0), 'white': (7, 0x38)}
TEAL_SITES = ((0x196CE, 0), (0x19744, 1), (0x80388100, 0), (0x80388104, 1))   # (address of the mask byte, FS1/FS2)


def tool(*a, **k):
    return subprocess.run(a, check=True, capture_output=True, text=True, **k).stdout


def compile_about(ident):
    """src/about.c with IDENT -> (blob linked at BASE, address of about_version)."""
    with tempfile.TemporaryDirectory() as t:
        t = Path(t)
        (t / 'u.c').write_text(f'#include "{ROOT / "src/about.c"}"\n')
        (t / 'l.ld').write_text(f'SECTIONS {{ . = {BASE:#x}; .text : {{ *(.text.hook) *(.text*) *(.rodata*) *(.data*) '
                                f'*(.bss*) *(COMMON) }} /DISCARD/ : {{ *(.ARM.exidx*) *(.comment) }} }}\n')
        tool('clang', '--target=thumbv7em-none-eabi', '-mcpu=cortex-m7', '-mfloat-abi=soft', '-O2', '-mno-unaligned-access',
             '-ffreestanding', '-fno-builtin', '-nostdlib', '-Wall', '-Werror', '-fno-unwind-tables',
             '-fno-asynchronous-unwind-tables', f'-DIDENT="{ident}"', '-c', 'u.c', '-o', 'o.o', cwd=t)
        tool('ld.lld', '-e', 'about_version', '-T', 'l.ld', 'o.o', '-o', 'o.elf', cwd=t)
        tool('llvm-objcopy', '-O', 'binary', '-j', '.text', 'o.elf', 'o.bin', cwd=t)
        assert not tool('llvm-nm', '-u', 'o.elf', cwd=t).strip(), 'undefined symbols (no libc here)'
        syms = {n: int(a, 16) for a, _, n in (l.split() for l in tool('llvm-nm', 'o.elf', cwd=t).splitlines())}
        return (t / 'o.bin').read_bytes(), syms['about_version'] & ~1


def b_w(site, target):
    """Thumb-2 B.W (encoding T4) at `site` to `target`."""
    off = target - (site + 4)
    assert -(1 << 24) <= off < (1 << 24) and not off & 1
    s, i1, i2 = off >> 24 & 1, off >> 23 & 1, off >> 22 & 1
    hw1 = 0xF000 | s << 10 | off >> 12 & 0x3FF
    hw2 = 0x9000 | ((1 - i1) ^ s) << 13 | ((1 - i2) ^ s) << 11 | off >> 1 & 0x7FF
    return hw1.to_bytes(2, 'little') + hw2.to_bytes(2, 'little')


def stock_at(stock, site, n):
    """n bytes of the official file at an ITCM (or, >= 0x80000000, SDRAM image) address."""
    p = stock[0x40:]
    w = [int.from_bytes(p[4 * i:4 * i + 4], 'little') for i in range(8)]
    o = 0x10 + w[6] - 0x80000 + site - 0x80000000 if site >= 0x80000000 else 0x10 + w[4] - 0x80000 + site
    return p[o:o + n]


def variant(teal, stock):
    params = f'Pitik {VERSION}|{FW}|{BASE:#x}|{ABOUT:#x}|about_identity,leds_fixed|teal={teal}'
    ident = lambda h: f'{FW} + Pitik {VERSION} {h}'
    h = hashlib.sha256(compile_about(ident('0' * 8))[0] + params.encode()).hexdigest()[:8]
    blob, fn = compile_about(ident(h))
    region = bytes(BASE - ITCM_LEN) + blob
    region += bytes(-len(region) % 4)
    edits = [(ABOUT, b_w(ABOUT, fn))] + [(s, bytes([TEAL[teal][i]])) for s, i in TEAL_SITES]
    runs = []                         # only the bytes that differ from the official file, as (address, hex) runs
    for site, new in edits:
        old = stock_at(stock, site, len(new))
        i = 0
        while i < len(new):
            if new[i] == old[i]: i += 1; continue
            j = i
            while j < len(new) and new[j] != old[j]: j += 1
            runs.append([site + i, new[i:j].hex()]); i = j
    return dict(identity=ident(h), at=ITCM_LEN, region=region.hex(), edits=runs, output_sha256=None)


def main():
    if len(sys.argv) != 2: sys.exit(__doc__)
    stock = Path(sys.argv[1]).read_bytes()
    if hashlib.sha256(stock).hexdigest() != INPUT_SHA256: sys.exit('not the official V2.2 file')
    ver = tool('clang', '--version').splitlines()[0]
    if f'clang version {CLANG}' not in ver: sys.exit(f'{ver}: releases are built with clang {CLANG} (pinned)')
    data = dict(version=VERSION, firmware=FW, compiler=f'clang {CLANG}', input_sha256=INPUT_SHA256, zip_sha256=ZIP_SHA256,
                variants={t: variant(t, stock) for t in TEAL})
    out = ROOT / 'patch-data.js'
    write = lambda: out.write_text('// Generated by tools/build_patch.py from src/about.c. Only our own bytes (README '
                                   '"What the patch contains").\n'
                                   f'var PITIK_DATA = {json.dumps(data, indent=1)};\n'
                                   "if (typeof module !== 'undefined') module.exports = PITIK_DATA;\n")
    write()
    for t, v in data['variants'].items():         # output sha256 through the page's own apply()
        js = (f"const p = require({json.dumps(str(ROOT / 'patcher.js'))}), fs = require('fs');"
              f"process.stdout.write(Buffer.from(p.apply(new Uint8Array(fs.readFileSync({json.dumps(sys.argv[1])})), "
              f"p.DATA.variants[{json.dumps(t)}])).toString('hex'))")
        v['output_sha256'] = hashlib.sha256(bytes.fromhex(tool('node', '-e', js))).hexdigest()
        print(f'{t}: {v["identity"]}, +{len(v["region"]) // 2} B, edits {v["edits"]}, output sha256 {v["output_sha256"]}')
    write()
    print(f'{out} written ({ver})')


if __name__ == '__main__':
    main()
