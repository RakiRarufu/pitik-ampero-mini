/* Pitik patcher: applies the patch data (patch-data.js) to the official Hotone Ampero Mini V2.2 firmware file.
 * The same code runs in the web page (index.html) and on the command line:
 *     node patcher.js "Ampero Mini_firmware_V2.2.bin" out.bin --teal off|white
 * The input may also be Hotone's zip that holds that file. It refuses any input that is not the official V2.2 file
 * (sha256) and any output that is not the tested build.
 * MIT licence (LICENSE). */
'use strict';
(function () {
  const isNode = typeof module !== 'undefined' && module.exports;
  const DATA = isNode ? require('./patch-data.js') : window.PITIK_DATA;
  const hexBytes = h => Uint8Array.from(h.match(/../g) || [], x => parseInt(x, 16));

  async function sha256(bytes) {
    const d = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes));
    return Array.from(d, b => b.toString(16).padStart(2, '0')).join('');
  }

  /* File layout (all little-endian): a 0x40-byte container header, then the firmware payload. Payload words 0-7:
   * 0/1 and 2/3 = two data segments (offset, length), 4/5 = ITCM image (flash offset, length), 6/7 = SDRAM image
   * (flash offset, length); the ITCM image starts at payload 0x2C. Container 0x30..0x3F: part table (MCU part
   * offset/length, DSP part offset/length); 0x04 = file length - 0x30; 0x0E = byte sum of 0x30..end. Our code is
   * inserted right after the ITCM image; everything behind it moves up by its length. */
  function apply(input, v) {
    const P = 0x40, dv = new DataView(input.buffer, input.byteOffset, input.byteLength);
    const w = Array.from({ length: 8 }, (_, i) => dv.getUint32(P + 4 * i, true));
    if (w[5] !== v.at) throw new Error('unexpected ITCM image length');
    const region = hexBytes(v.region), n = region.length;
    const ins = P + 0x10 + w[4] - 0x80000 + w[5];          // end of the ITCM image
    const off = s => s >= 0x80000000 ? P + 0x10 + w[6] - 0x80000 + (s - 0x80000000) + n : P + 0x10 + w[4] - 0x80000 + s;
    const out = new Uint8Array(input.length + n);
    out.set(input.subarray(0, ins)); out.set(region, ins); out.set(input.subarray(ins), ins + n);
    for (const [site, h] of v.edits) out.set(hexBytes(h), off(site));
    const ov = new DataView(out.buffer);
    for (const i of [0, 2, 5, 6]) ov.setUint32(P + 4 * i, w[i] + n, true);
    for (const a of [0x34, 0x38]) ov.setUint32(a, ov.getUint32(a, true) + n, true);   // MCU part length, DSP part offset
    ov.setUint32(0x04, out.length - 0x30, true);
    let sum = 0;
    for (let i = 0x30; i < out.length; i++) sum += out[i];
    out[0x0E] = sum & 0xFF;
    return out;
  }

  /* Hotone's zip -> its firmware entry. Sizes and offsets come from the central directory: Hotone's local headers
   * leave the sizes 0 (they are in a data descriptor after the data). */
  const ENTRY = `Ampero Mini_firmware_${DATA.firmware}.bin`;
  const isZip = b => b.length > 4 && b[0] === 0x50 && b[1] === 0x4B && b[2] === 3 && b[3] === 4;
  async function unzip(z) {
    try {
      const dv = new DataView(z.buffer, z.byteOffset, z.byteLength), u16 = o => dv.getUint16(o, true), u32 = o => dv.getUint32(o, true);
      let e = z.length - 22;
      while (e >= 0 && u32(e) !== 0x06054B50) e--;
      if (e < 0) throw 'no central directory';
      const hits = [];
      for (let i = 0, p = u32(e + 16); i < u16(e + 10); i++, p += 46 + u16(p + 28) + u16(p + 30) + u16(p + 32)) {
        if (u32(p) !== 0x02014B50) throw 'damaged central directory';
        if (String.fromCharCode(...z.subarray(p + 46, p + 46 + u16(p + 28))) === ENTRY) hits.push(p);
      }
      if (hits.length !== 1) throw `it must hold exactly one "${ENTRY}", it holds ${hits.length}`;
      const c = hits[0], size = u32(c + 24), at = u32(c + 42);
      if (u16(c + 10) !== 8) throw 'the firmware entry is not deflated';
      if (size > 64 << 20) throw 'the firmware entry is too large';    // ponytail: size claim checked, not the stream
      if (u32(at) !== 0x04034B50) throw 'damaged local header';
      const raw = z.subarray(at + 30 + u16(at + 26) + u16(at + 28)).subarray(0, u32(c + 20));
      const bin = isNode ? new Uint8Array(require('zlib').inflateRawSync(raw)) : new Uint8Array(await new Response(
        new Blob([raw]).stream().pipeThrough(new DecompressionStream('deflate-raw'))).arrayBuffer());
      if (bin.length !== size) throw 'the firmware entry does not unpack to its recorded size';
      return bin;
    } catch (why) {
      throw new Error(`This zip is not Hotone's Ampero Mini ${DATA.firmware} firmware zip (${typeof why === 'string' ? why :
        'damaged zip'}). Use Hotone's zip as downloaded, or the "${ENTRY}" inside it.`);
    }
  }

  /* The dropped file (Hotone's .bin, or Hotone's zip) -> the official .bin, or an error. The .bin's sha256 is the gate;
   * the zip's own sha256 is only reported. */
  async function check(input) {
    const zip = isZip(input), bin = zip ? await unzip(input) : input, sha = await sha256(bin);
    if (sha !== DATA.input_sha256)
      throw new Error(`${zip ? `The "${ENTRY}" in this zip` : 'This'} is not the official Ampero Mini ${DATA.firmware} ` +
        `firmware file (its sha256 is ${sha}). Use Hotone's zip as downloaded, or the unmodified "${ENTRY}" inside it.`);
    return { bin, sha, zip, zipKnown: zip && await sha256(input) === DATA.zip_sha256 };
  }

  async function patch(input, teal) {
    const v = DATA.variants[teal];
    if (!v) throw new Error(`unknown option ${teal} (have ${Object.keys(DATA.variants).join(', ')})`);
    input = (await check(input)).bin;
    const out = apply(input, v), sha = await sha256(out);
    if (sha !== v.output_sha256) throw new Error(`internal error: output sha256 ${sha} is not the tested build`);
    return { out, sha256: sha, identity: v.identity,
             name: `Ampero_Mini_firmware_${DATA.firmware}_Pitik_${DATA.version}_teal-${teal}.bin` };
  }

  const api = { DATA, apply, check, patch, sha256 };
  if (!isNode) { window.Pitik = api; return; }
  module.exports = api;
  if (require.main !== module) return;
  const fs = require('fs'), a = process.argv.slice(2), t = a.indexOf('--teal');
  const teal = t >= 0 ? a.splice(t, 2)[1] : undefined;
  if (a.length !== 2 || !teal) {
    console.error(`usage: node patcher.js <official ${DATA.firmware} .bin or Hotone's zip> <output .bin> --teal ${Object.keys(DATA.variants).join('|')}`);
    process.exit(2);
  }
  if (require('path').resolve(a[0]) === require('path').resolve(a[1])) { console.error('output would overwrite the input'); process.exit(2); }
  patch(new Uint8Array(fs.readFileSync(a[0])), teal).then(r => {
    fs.writeFileSync(a[1], r.out);
    console.log(`${a[1]}: ${r.out.length} bytes, sha256 ${r.sha256}\nAbout will show: ${r.identity}`);
  }, e => { console.error(e.message); process.exit(1); });
})();
