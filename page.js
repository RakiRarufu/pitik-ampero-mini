/* Pitik page glue: read the dropped file (Hotone's zip or the .bin inside it), run patcher.js's patch(), offer the result for download. Nothing is sent
 * anywhere (the page's Content-Security-Policy forbids network requests). MIT licence (LICENSE). */
'use strict';
(function () {
  const $ = id => document.getElementById(id), O = window.Pitik;
  let input = null, url = null;
  $('ver').textContent = O.DATA.version;
  $('fw').textContent = O.DATA.firmware;
  const say = (msg, err) => { $('status').innerHTML = ''; const p = document.createElement('p');
    p.textContent = msg; if (err) p.className = 'err'; $('status').append(p); };

  async function take(file) {
    $('dl').hidden = true; $('go').disabled = true; input = null;
    if (!file) return;
    say(`Checking ${file.name} ...`);
    let r;
    try { r = await O.check(new Uint8Array(await file.arrayBuffer())); } catch (err) { say(`${file.name}: ${err.message}`, true); return; }
    input = r.bin; $('go').disabled = false;
    say(`${file.name}: ${r.zip ? `zip${r.zipKnown ? ` (Hotone's ${O.DATA.firmware} download)` : ''} holding the ` : ''}` +
        `official ${O.DATA.firmware} firmware (sha256 ${r.sha}). Choose the light and make the file.`);
  }

  $('file').addEventListener('change', e => take(e.target.files[0]));
  for (const r of document.querySelectorAll('input[name=teal]')) r.addEventListener('change', () => { $('dl').hidden = true; });
  const drop = $('drop');
  drop.addEventListener('dragover', e => { e.preventDefault(); drop.classList.add('over'); });
  drop.addEventListener('dragleave', () => drop.classList.remove('over'));
  drop.addEventListener('drop', e => { e.preventDefault(); drop.classList.remove('over'); take(e.dataTransfer.files[0]); });

  $('form').addEventListener('submit', async e => {
    e.preventDefault();
    if (!input) return;
    const teal = document.querySelector('input[name=teal]:checked').value;
    try {
      const r = await O.patch(input, teal);
      if (url) URL.revokeObjectURL(url);
      url = URL.createObjectURL(new Blob([r.out], { type: 'application/octet-stream' }));
      $('save').href = url; $('save').download = r.name; $('dl').hidden = false;
      $('ident').textContent = r.identity;
      say(`Done: ${r.name}, sha256 ${r.sha256}. GLOBAL > About will show "${r.identity}".`);
    } catch (err) { say(err.message, true); }
  });
})();
