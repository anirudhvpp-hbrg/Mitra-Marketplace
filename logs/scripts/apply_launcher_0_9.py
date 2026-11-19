"""0.9.0 launcher page (web/index.html): an activity strip on Your apps while a model works,
what the running model is doing, and the line of those waiting for it on the System page.
Run once from the project root: python logs/scripts/apply_launcher_0_9.py
"""
from pathlib import Path

f = Path("web/index.html")
s = f.read_text("utf-8")
for a, b in [
    ('  <div class="wrap" style="padding-top:0">\n    <div class="tiles" id="applist">',
     '  <div class="wrap" style="padding-top:0">\n'
     '    <div class="card" id="busy" hidden style="padding:12px 16px;margin-bottom:16px;display:flex;gap:10px;align-items:center;flex-wrap:wrap;border-color:var(--action)"></div>\n'
     '    <div class="tiles" id="applist">'),
    ('    <h3>Capabilities on this device</h3>',
     '    <h3>Waiting for the model</h3>\n    <div class="card" id="line"></div>\n    <h3>Capabilities on this device</h3>'),
    ('''<tr><th>Model</th><th>RAM now</th><th>Cap</th><th>Used by</th><th></th></tr>${s.leases.map((l) => `
    <tr><td><b>${M.esc(l.name)}</b></td><td>${l.mb} MB</td><td>${l.budget_mb} MB</td><td>${M.esc(l.apps.join(', '))}</td>''',
     '''<tr><th>Model</th><th>RAM now</th><th>Cap</th><th>Used by</th><th>Doing</th><th></th></tr>${s.leases.map((l) => `
    <tr><td><b>${M.esc(l.name)}</b></td><td>${l.mb} MB</td><td>${l.budget_mb} MB</td><td>${M.esc(l.apps.map(appName).join(', '))}</td><td>${M.esc(l.what || '')}</td>'''),
    ('''No model is running. Nothing of Mitra\\'s model stack is in memory.</div>';
}''',
     '''No model is running. Nothing of Mitra\\'s model stack is in memory.</div>';
  const line = s.line || [];
  $('#line').innerHTML = line.length ? `<table class="plain"><tr><th>#</th><th>App</th><th>What</th><th>Waited</th><th>Goes</th></tr>${line.map((t, i) => `
    <tr><td>${i + 1}</td><td><b>${M.esc(appName(t.app))}</b></td><td>${M.esc(t.what || t.name)}</td><td>${dur(t.waited_s)}</td>
    <td>${t.priority === 'interactive' ? 'next, ahead of long jobs' : 'in turn'}</td></tr>`).join('')}</table>`
    : '<div class="muted">Nobody is waiting. One model runs at a time; a question goes ahead of a long job at its next piece, and nothing in the line times out.</div>';
}
const appName = (id) => (APPS.find((a) => a.id === id) || {}).name || id;
const dur = (sec) => sec < 90 ? `${Math.round(sec)} s` : `${Math.round(sec / 60)} min`;
// While a model works, Your apps says who has it, what for, and who is waiting.
async function loadBusy() {
  if (document.hidden || $('#apps').hidden) return;
  let s; try { s = await M.api('/api/system'); } catch { return; }
  const l = (s.leases || [])[0], line = s.line || [];
  $('#busy').hidden = !l && !line.length;
  if (!l && !line.length) return;
  const who = l ? `<b>${M.esc(appName(l.apps[0]))}</b> · ${M.esc(l.what || l.name)} · ${M.esc(l.name)}, ${l.mb} MB` : 'The model is changing hands';
  const next = line.length ? `${line.length} waiting · ${M.esc(appName(line[0].app))} goes next` : 'nobody waiting';
  $('#busy').innerHTML = `<span class="chip ok">working</span><span style="flex:1;min-width:200px">${who}</span><span class="muted small">${next}</span>
    <button class="ghost" data-show="${M.esc(l ? l.apps[0] : line[0].app)}">Show</button>`;
}
$('#busy').onclick = (e) => { if (e.target.dataset.show) M.launch(e.target.dataset.show); };
setInterval(loadBusy, 4000); loadBusy();'''),
]:
    assert s.count(a) == 1, (s.count(a), a[:60])
    s = s.replace(a, b)
f.write_text(s, "utf-8")
print("ok")
