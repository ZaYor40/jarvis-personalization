'use strict';
// Runner de preset de briefing post-wakeup. Joue les segments séquentiellement
// (chaque `say` attend la fin de l'audio avant de continuer). Autonome : décodage
// audio inclus, aucune dépendance à wake_sequence.js. Le timing vit ici ; le
// backend ne fait que résoudre les segments (data déclarative).
(function () {
  function _auth() {
    return window.Jarvis && Jarvis.authHeaders ? Jarvis.authHeaders() : {};
  }

  // Décode + joue un base64 audio, en ATTENDANT la fin (sinon les phrases se
  // chevauchent). Même décodage que _playBase64Audio de wake_sequence.
  async function _playB64(b64) {
    try {
      const raw = atob(b64);
      const buf = new Uint8Array(raw.length);
      for (let i = 0; i < raw.length; i++) buf[i] = raw.charCodeAt(i);
      const ctx = new (window.AudioContext || window.webkitAudioContext)();
      const audioBuf = await ctx.decodeAudioData(buf.buffer);
      const src = ctx.createBufferSource();
      src.buffer = audioBuf;
      src.connect(ctx.destination);
      await new Promise((resolve) => { src.onended = resolve; src.start(); });
      try { ctx.close(); } catch (e) { /* déjà fermé */ }
    } catch (e) { console.warn('[briefing] audio', e); }
  }

  async function speak(text) {
    if (!text) return;
    try {
      const r = await fetch('/api/voice/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ..._auth() },
        body: JSON.stringify({ text }),
      });
      const d = await r.json();
      if (d && d.audio_b64) await _playB64(d.audio_b64);
    } catch (e) { console.warn('[briefing] speak', e); }
  }

  async function openUrl(url, bounds) {
    try {
      await fetch('/api/briefing/open-url', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', ..._auth() },
        body: JSON.stringify({ url, bounds }),
      });
    } catch (e) { console.warn('[briefing] open', e); }
  }

  const delay = (ms) => new Promise((r) => setTimeout(r, ms));

  window.runBriefing = async function (presetId = 'morning') {
    let preset;
    try {
      preset = await (
        await fetch('/api/briefing/preset/' + encodeURIComponent(presetId), { headers: _auth() })
      ).json();
    } catch (e) { console.warn('[briefing] preset KO', e); return; }

    // No-op si désactivé côté backend (BRIEFING_ENABLED=false) → pas de pollution en dev.
    if (!preset || !preset.enabled || !Array.isArray(preset.segments)) return;

    for (const seg of preset.segments) {
      switch (seg.type) {
        case 'say':
          await speak(seg.text);
          break;
        case 'open_url':
          await openUrl(seg.url, seg.bounds);
          await delay(700);
          break;
        case 'view':
          if (window.Jarvis && Jarvis.views && Jarvis.views.activate) {
            Jarvis.views.activate(seg.view, seg.params || {});
          }
          await delay(seg.dwell_ms || 3000);
          break;
        case 'wait':
          await delay(seg.ms || 500);
          break;
      }
    }
  };
})();
