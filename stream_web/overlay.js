// Draws validated cues from /events. Text goes in with textContent only, never as markup.
(() => {
  const $ = id => document.getElementById(id);
  const timers = {};
  const hide = (id) => { $(id).hidden = true; };
  const showFor = (id, ms) => { $(id).hidden = false; clearTimeout(timers[id]); timers[id] = setTimeout(() => hide(id), ms); };
  const labelSource = (ev) => {
    // A chat cue says where it came from; the chat feed is a simulator until a platform is connected.
    if (ev.source === 'chat') { $('source').textContent = 'CHAT SIMULATOR'; showFor('source', ev.action.duration_ms || 4000); }
  };
  function draw(ev) {
    const a = ev.action;
    if (a.kind === 'clear') { ['popup', 'lower', 'count', 'burst', 'source'].forEach(hide); $('burst').replaceChildren(); return; }
    labelSource(ev);
    if (a.kind === 'popup') { $('popup-text').textContent = a.text; $('popup').style.animation = 'none'; void $('popup').offsetWidth; $('popup').style.animation = ''; showFor('popup', a.duration_ms); }
    if (a.kind === 'lower_third') { $('lower-tag').textContent = ev.source === 'chat' ? 'CHAT' : 'LIVE'; $('lower-text').textContent = a.text; showFor('lower', a.duration_ms); }
    if (a.kind === 'countdown') {
      $('count-label').textContent = a.text; let n = a.seconds; $('count-num').textContent = String(n); $('count').hidden = false;
      clearInterval(timers.tick); timers.tick = setInterval(() => { n -= 1; if (n <= 0) { clearInterval(timers.tick); hide('count'); } else $('count-num').textContent = String(n); }, 1000);
    }
    if (a.kind === 'emoji_burst') {
      const box = $('burst'); box.replaceChildren(); box.hidden = false;
      for (let i = 0; i < 18; i++) {
        const s = document.createElement('span'); s.textContent = a.emoji;
        s.style.left = (5 + Math.random() * 90) + '%'; s.style.setProperty('--d', (1.6 + Math.random() * 1.4) + 's'); s.style.setProperty('--r', (Math.random() * 60 - 30) + 'deg');
        s.style.animationDelay = (Math.random() * 0.4) + 's'; box.append(s);
      }
      showFor('burst', a.duration_ms);
    }
  }
  const es = new EventSource('/events');
  es.onmessage = (m) => {
    const ev = JSON.parse(m.data);
    if (!ev.action) return; // transcripts and other notices are for the controller
    draw(ev);
    // Exposed for the latency receipt: when this page updated its DOM (not when the frame was painted).
    window.__lastShown = { id: ev.id, kind: ev.action.kind, domUpdatedAt: Date.now() / 1000, timing: ev.timing };
    document.body.dataset.lastShown = ev.id;
  };
})();
