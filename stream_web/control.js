// Operator controller. Every request goes to this same local service; the server validates everything.
(() => {
  const $ = id => document.getElementById(id);
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }).then(r => r.json());
  const LABEL = { voice: 'Voice', chat: 'Chat input', random: 'Random', typed: 'Typed' };
  function paint(s) {
    $('conn').textContent = `connected · ${s.build_tag} · port ${s.connector_port}`;
    $('inputs').replaceChildren(...Object.entries(s.inputs).map(([k, on]) => {
      const b = document.createElement('button'); b.type = 'button'; b.dataset.input = k; b.setAttribute('aria-pressed', String(on));
      b.textContent = `${LABEL[k] || k}: ${on ? 'ON' : 'off'}`; return b; }));
    const sel = $('planner'); const cur = sel.value;
    const PLABEL = { rules: 'rules (offline, live-safe)', codex: 'codex (experimental, unavailable unless the operator enables it)', openai: 'openai (unavailable)' };
    const avail = { rules: true, codex: !!(s.models && s.models.codex && s.models.codex.available), openai: false };
    sel.replaceChildren(...s.planners.map(p => { const o = document.createElement('option'); o.value = p; o.textContent = PLABEL[p] || p; o.disabled = !avail[p]; return o; }));
    sel.value = s.planner || cur;
    const m = s.models || {}, notes = { rules: 'Rules: works offline. Say or type the wake word “Director”.',
      codex: m.codex ? (m.codex.enabled ? `Codex CLI on your subscription · ${m.codex.model} · calls ${m.codex.calls} of ${m.codex.cap} this session` : 'Codex CLI: experimental and off. Not isolated from its built-in tools, so not for live use.') : 'Codex CLI not found',
      openai: m.openai ? `OpenAI API · ${m.openai.state}` : '' };
    $('planner-note').textContent = notes[s.planner] || '';
    if (document.activeElement !== $('rand')) $('rand').value = String(s.random_interval_s);
    $('twitch').textContent = 'Real Twitch is managed by the separate EventSub receiver. Check its trace; this box is a local test input.';
    $('counters').replaceChildren(...Object.entries(s.counters).flatMap(([k, v]) => { const dt = document.createElement('dt'); dt.textContent = k.replace(/_/g, ' '); const dd = document.createElement('dd'); dd.textContent = String(v); return [dt, dd]; }));
  }
  const refresh = () => fetch('/status').then(r => r.json()).then(paint).catch(() => { $('conn').textContent = 'not connected'; });
  $('inputs').addEventListener('click', e => { const b = e.target.closest('[data-input]'); if (!b) return; post('/input', { source: b.dataset.input, on: b.getAttribute('aria-pressed') !== 'true' }).then(paint); });
  const setPlanner = () => post('/planner', { planner: $('planner').value, model: $('model').value.trim() }).then(s => { if (s.error) $('planner-note').textContent = s.error; else paint(s); });
  $('rand').addEventListener('change', e => post('/random', { seconds: Number(e.target.value) }).then(paint));
  $('planner').addEventListener('change', setPlanner); $('model').addEventListener('change', setPlanner);
  const say = (form, input, url, extra) => form.addEventListener('submit', e => { e.preventDefault(); const text = $(input).value.trim(); if (!text) return;
    post(url, { text, ...extra }).then(r => { note(r.shown ? `shown · ${r.event.action.kind}` : (r.reason || r.error || 'not shown'), text); refresh(); }); $(input).value = ''; });
  say($('typed'), 'typed-text', '/cue', { source: 'typed' });
  say($('chat'), 'chat-text', '/chat-sim', {});
  function note(result, text) { const li = document.createElement('li'); const b = document.createElement('b'); b.textContent = result; li.append(b, ' · ', text); $('log').prepend(li); while ($('log').children.length > 30) $('log').lastChild.remove(); }
  function fit() { const f = document.querySelector('.frame'); $('preview').style.transform = `scale(${f.clientWidth / 1920})`; }
  addEventListener('resize', fit); fit();
  // Continuous listening: 16 kHz mono from the mic, 3 s chunks as WAV, silent chunks skipped.
  const MIC = { ctx: null, stream: null, node: null, buf: [], timer: null };
  function wav(samples) {
    const out = new DataView(new ArrayBuffer(44 + samples.length * 2)); const w = (o, s) => [...s].forEach((c, i) => out.setUint8(o + i, c.charCodeAt(0)));
    w(0, 'RIFF'); out.setUint32(4, 36 + samples.length * 2, true); w(8, 'WAVE'); w(12, 'fmt '); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
    out.setUint32(24, 16000, true); out.setUint32(28, 32000, true); out.setUint16(32, 2, true); out.setUint16(34, 16, true); w(36, 'data'); out.setUint32(40, samples.length * 2, true);
    samples.forEach((v, i) => out.setInt16(44 + i * 2, Math.max(-1, Math.min(1, v)) * 0x7fff, true)); return new Blob([out], { type: 'audio/wav' });
  }
  function flush() {
    const parts = MIC.buf; MIC.buf = []; const n = parts.reduce((a, p) => a + p.length, 0); if (n < 3200) return;
    const all = new Float32Array(n); let o = 0; parts.forEach(p => { all.set(p, o); o += p.length; });
    const rms = Math.sqrt(all.reduce((a, v) => a + v * v, 0) / n); if (rms < 0.01) return;
    fetch('/voice-chunk', { method: 'POST', headers: { 'Content-Type': 'audio/wav' }, body: wav(all) }).then(r => r.json()).then(r => { if (r.error) $('heard').textContent = r.error; });
  }
  async function listen(on) {
    const b = $('listen');
    if (!on) { clearInterval(MIC.timer); MIC.node?.disconnect(); MIC.stream?.getTracks().forEach(t => t.stop()); MIC.ctx?.close(); Object.assign(MIC, { ctx: null, stream: null, node: null, buf: [] });
      b.setAttribute('aria-pressed', 'false'); b.textContent = 'Start listening'; return; }
    try {
      MIC.stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
      MIC.ctx = new AudioContext({ sampleRate: 16000 }); const src = MIC.ctx.createMediaStreamSource(MIC.stream);
      MIC.node = MIC.ctx.createScriptProcessor(4096, 1, 1); MIC.node.onaudioprocess = e => MIC.buf.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      src.connect(MIC.node); MIC.node.connect(MIC.ctx.destination); MIC.timer = setInterval(flush, 3000);
      b.setAttribute('aria-pressed', 'true'); b.textContent = 'Listening… tap to stop';
    } catch (e) { $('heard').textContent = 'Microphone not available: ' + e.message; }
  }
  $('listen').addEventListener('click', () => listen($('listen').getAttribute('aria-pressed') !== 'true'));
  const es = new EventSource('/events');
  es.onmessage = m => { const ev = JSON.parse(m.data); if (ev.type === 'transcript') { $('heard').textContent = `Heard (${ev.whisper_s}s): ${ev.text}`; note('heard', ev.text); } refresh(); };
  refresh(); setInterval(refresh, 5000);
})();
