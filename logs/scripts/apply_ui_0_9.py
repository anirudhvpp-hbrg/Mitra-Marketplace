"""0.9.0 screens: Ask Mitra shows its place in the line and can cancel a waiting question; the RAM
pill in every app names the app a model is working for; TwinMind keeps a dropped file's own name.
Run once from the project root: python logs/scripts/apply_ui_0_9.py
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


patch("apps/assistant/ui/index.html", [
    ('''  const wait = M.el('<div class="msg it"><div class="bubble" style="padding:12px 18px"><span class="dots"><i></i><i></i><i></i></span><span class="muted small"> loading the model, answering, unloading</span></div></div>');
  $('#chat').append(wait); wait.scrollIntoView({ block: 'end' });''',
     '''  const wait = M.el('<div class="msg it"><div class="bubble" style="padding:12px 18px"><span class="dots"><i></i><i></i><i></i></span><span class="muted small" data-say> loading the model, answering, unloading</span> <button class="ghost" data-cancel hidden style="min-height:26px;padding:2px 10px;font-size:12px">Cancel question</button></div></div>');
  $('#chat').append(wait); wait.scrollIntoView({ block: 'end' });
  // One model runs at a time. If a long job has it, the question waits for a turn and says so.
  const ctl = new AbortController(), t0 = Date.now();
  wait.querySelector('[data-cancel]').onclick = () => ctl.abort();
  const watch = setInterval(async () => {
    let s; try { s = await (await fetch('/api/system')).json(); } catch { return; }
    const mine = (s.line || []).findIndex((t) => t.app === M.appId), l = (s.leases || [])[0];
    const say = wait.querySelector('[data-say]'), secs = Math.round((Date.now() - t0) / 1000);
    wait.querySelector('[data-cancel]').hidden = mine < 0;
    if (mine >= 0 && l) say.textContent = ` Waiting for a turn (${secs} s). ${l.apps[0]} is using ${l.name}${l.what ? ' for ' + l.what : ''}. Your question goes ${mine ? 'after ' + mine + ' other' + (mine > 1 ? 's' : '') : 'next'}.`;
    else if (mine >= 0) say.textContent = ` Waiting for a turn (${secs} s). Your question goes next.`;
    else say.textContent = ' loading the model, answering, unloading';
  }, 1500);'''),
    ('''    const r = await M.api('/api/ask', { body: { app_id: M.appId, prompt: q, history, system: 'You are a concise, accurate assistant. Answer the latest question directly; do not repeat earlier answers. If you are not sure, say so.' } });
    wait.remove();
    const meta = `${r.model} · ${(r.ms / 1000).toFixed(1)} s · ${r.mb ?? '?'} MB while answering, now unloaded`;''',
     '''    const res = await fetch('/api/ask', { method: 'POST', signal: ctl.signal, headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ app_id: M.appId, prompt: q, history, system: 'You are a concise, accurate assistant. Answer the latest question directly; do not repeat earlier answers. If you are not sure, say so.' }) });
    const r = await res.json();
    if (!res.ok) throw new Error(r.detail || 'The question could not be answered.');
    clearInterval(watch); wait.remove();
    const meta = `${r.model} · ${(r.ms / 1000).toFixed(1)} s · ${r.mb ?? '?'} MB while answering, now unloaded` + (r.waited_ms > 1500 ? ` · waited ${Math.round(r.waited_ms / 1000)} s for a turn` : '');'''),
    ('''  } catch (e) { wait.remove(); add('assistant', e.message, 'not answered'); }''',
     '''  } catch (e) {
    clearInterval(watch); wait.remove();
    if (e.name === 'AbortError') { add('assistant', 'Question cancelled. Nothing was run.', 'cancelled'); M.log('action.cancel_question', { waited_s: Math.round((Date.now() - t0) / 1000) }); }
    else add('assistant', e.message, 'not answered');
  }'''),
])

patch("web/static/sdk.js", [
    ("(s.leases.length ? ` · ${s.leases[0].name} ${s.leases[0].mb} MB` : ' · no model loaded');",
     "(s.leases.length ? ` · ${s.leases[0].name} ${s.leases[0].mb} MB` + (M.appId !== 'shell' && s.leases[0].apps[0] !== M.appId ? ` · ${s.leases[0].apps[0]}` : '')\n"
     "          : (s.line || []).length ? ' · model changing hands' : ' · no model loaded');"),
])

patch("apps/twinmind/ui/index.html", [
    ("let path = null, following = null, poll = null, est = null;", "let path = null, pickedName = null, following = null, poll = null, est = null;"),
    ("    path = p; const name = shown || p.split(/[\\\\/]/).pop();\n    $('#picked').textContent = name;",
     "    path = p; const name = pickedName = shown || p.split(/[\\\\/]/).pop();\n    $('#picked').textContent = name;"),
    ("await start({ path, title: $('#title').value, attendees: $('#att').value, speed });",
     "await start({ path, name: pickedName, title: $('#title').value, attendees: $('#att').value, speed });"),
])
print("ok")
