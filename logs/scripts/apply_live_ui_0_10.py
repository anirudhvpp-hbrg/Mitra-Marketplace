"""0.10.0, part 4: the Live tab in TwinMind's page.

While the page is open it asks its own process every five seconds whether a meeting app is using
the microphone (a list Windows keeps; nothing is listened to). If one is, it offers to record.
Recording shows the levels of both tracks, the transcript as it grows, and a box for your own notes.
Run once from the project root: python logs/scripts/apply_live_ui_0_10.py
"""
from pathlib import Path

f = Path("apps/twinmind/ui/index.html")
s = f.read_text("utf-8")


def rep(a, b):
    global s
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)


rep("</style>", '''  .banner { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; padding: 14px 16px; margin: 0 0 16px; border: 1.5px solid var(--action); border-radius: var(--r-md); background: linear-gradient(180deg, var(--glow-c), transparent); }
  .banner b { flex: 1 1 260px; } .rec { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: var(--bad, #b42318); animation: pulse 1.2s infinite; margin-right: 8px; }
  .lv { display: grid; grid-template-columns: 90px 1fr; gap: 8px; align-items: center; font-size: 13px; margin: 4px 0; } .lv .bar2 { margin: 0; height: 8px; }
  #liveLines { max-height: 46vh; overflow: auto; border: 1px solid var(--line); border-radius: var(--r-md); padding: 10px 14px; background: var(--panel); }
  #liveNotes { min-height: 46vh; font-family: var(--sans); font-size: 15px; line-height: 23px; }
</style>''')

rep('''    <div class="tabs" role="tablist" id="tabs">
      <button role="tab" data-tab="lib" class="on">Meetings</button>''', '''    <div class="banner" id="meetBanner" hidden></div>
    <div class="tabs" role="tablist" id="tabs">
      <button role="tab" data-tab="live">Live</button><button role="tab" data-tab="lib" class="on">Meetings</button>''')

rep('''    <section id="tab-lib">''', '''    <section id="tab-live" hidden>
      <div id="liveIdle">
        <div class="card" style="padding:22px">
          <h2>Record a meeting</h2>
          <p class="muted" style="margin:6px 0 14px">Two tracks are recorded: your microphone (you) and what this computer plays (everyone else). The transcript appears as the meeting runs, and the memo is written when you stop. Nothing joins your call and nothing leaves this device.</p>
          <label for="liveTitle">Title (optional)</label><input id="liveTitle">
          <label for="liveAtt">Who is there, comma separated (optional)</label><input id="liveAtt" placeholder="Priya, Sam">
          <div class="row" style="margin-top:16px"><button class="primary" id="liveStart">Start recording</button><span class="muted small" id="liveHint"></span></div>
          <label style="display:flex;gap:8px;align-items:center;margin-top:16px;font-weight:400"><input type="checkbox" id="liveNotify" style="width:auto;margin:0"> Tell me with a notification when a meeting starts (only while TwinMind is open)</label>
          <p class="muted small" style="margin:14px 0 0">While this window is open, TwinMind checks every five seconds whether a meeting app is using the microphone, and offers to record. It reads a list Windows keeps; it does not listen. Recordings are saved in half-minute pieces, so a three-hour meeting is as safe as a short one, and are kept for 30 days.</p>
        </div>
        <div id="leftover"></div>
      </div>
      <div id="liveOn" hidden>
        <div class="card" style="padding:22px">
          <div class="row"><h2 style="flex:1"><span class="rec"></span>Recording <span id="liveClock">0:00</span></h2><button class="primary" id="liveStop">Stop and write the memo</button></div>
          <input id="liveTitle2" placeholder="Title (optional)" style="margin-top:10px" aria-label="Title">
          <div class="lv"><span>You</span><div class="bar2"><i id="lvMic" style="width:0"></i></div></div>
          <div class="lv"><span>Others</span><div class="bar2"><i id="lvSys" style="width:0"></i></div></div>
          <div class="muted small" id="liveInfo"></div>
        </div>
        <div class="two" style="margin-top:14px">
          <div><h3 style="margin-top:0">Transcript, as it happens</h3><div id="liveLines"><div class="muted">The first lines appear about half a minute after someone speaks.</div></div></div>
          <div><h3 style="margin-top:0">Your notes</h3><textarea id="liveNotes" placeholder="Type what matters to you. Your notes are kept as written and put in the memo."></textarea></div>
        </div>
      </div>
    </section>
    <section id="tab-lib">''')

rep("  ['lib', 'new', 'across', 'people'].forEach((k) => ($('#tab-' + k).hidden = k !== t));", "  ['live', 'lib', 'new', 'across', 'people'].forEach((k) => ($('#tab-' + k).hidden = k !== t));")
rep("showTab(first ? 'new' : ['lib', 'new', 'across', 'people'].includes(want) ? want : 'lib');", "showTab(first ? 'new' : ['live', 'lib', 'new', 'across', 'people'].includes(want) ? want : 'lib');\n  liveTick(); setInterval(liveTick, 2000);")

rep("// ---- across meetings ---", '''// ---- live: notice a meeting, record it, show the transcript as it grows ---------------------------
let liveOn = false, liveNext = 0, liveJob = null, dismissed = '', lastMic = 0, notesTimer, notified = '';
const clock = (s) => `${Math.floor(s / 3600) ? Math.floor(s / 3600) + ':' + String(Math.floor(s / 60) % 60).padStart(2, '0') : Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
async function liveTick() {
  let st; try { st = await api('live?after=' + liveNext); } catch { return; }
  const on = !!st.recording;
  if (on !== liveOn) {
    liveOn = on; $('#liveIdle').hidden = on; $('#liveOn').hidden = !on;
    if (on) { liveNext = 0; $('#liveLines').innerHTML = '<div class="muted">The first lines appear about half a minute after someone speaks.</div>'; $('#liveTitle2').value = st.recording.title || ''; liveJob = st.recording.job; }
    else if (liveJob) { const j = liveJob; liveJob = null; showTab('new'); follow(j); }       // stopped: the same job now writes the memo
  }
  if (on) {
    $('#meetBanner').hidden = true;
    const s = st.status || {}; $('#liveClock').textContent = clock(s.seconds || 0);
    const lv = Object.fromEntries((s.tracks || []).map((t) => [t.name, t.level]));
    $('#lvMic').style.width = Math.min(100, Math.round(Math.sqrt(lv.mic || 0) * 100)) + '%'; $('#lvSys').style.width = Math.min(100, Math.round(Math.sqrt(lv.sys || 0) * 100)) + '%';
    $('#liveInfo').textContent = `${st.owner} on the microphone · live transcript by ${st.model || 'no model'} · saved every 30 seconds` + ((s.problems || []).length ? ' · ' + s.problems.join('; ') : '');
    if (st.lines && st.lines.length) {
      if (!liveNext) $('#liveLines').innerHTML = '';
      $('#liveLines').insertAdjacentHTML('beforeend', st.lines.map((l) => `<div class="tline"><span class="t">${clock(Math.round(l.t))}</span><span><b>${M.esc(l.who)}</b> ${M.esc(l.text)}</span></div>`).join(''));
      liveNext = st.next; $('#liveLines').scrollTop = $('#liveLines').scrollHeight;
    }
    return;
  }
  $('#liveHint').textContent = st.recorder ? '' : 'The recorder is not built on this system, so recording is unavailable.'; $('#liveStart').disabled = !st.recorder;
  $('#leftover').innerHTML = (st.leftover || []).map((r) => `<div class="box live" style="margin-top:14px"><h4>A recording ended without a memo</h4>
    <div class="muted">${M.esc(r.title || 'Untitled')} · started ${new Date(r.started * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })} · about ${Math.round(r.pieces / 2)} min saved</div>
    <div class="row" style="margin-top:8px"><button class="primary" data-finish="${r.id}">Write its memo</button></div></div>`).join('');
  // is a meeting app using the microphone? asked of this app's own process, every five seconds
  if (Date.now() - lastMic < 5000 || !st.recorder) return; lastMic = Date.now();
  let mic; try { mic = await M.api('/api/mic'); } catch { return; }
  if (!mic.meeting) { dismissed = ''; notified = ''; $('#meetBanner').hidden = true; document.title = 'TwinMind'; return; }
  if (dismissed === mic.meeting) return;
  $('#meetBanner').hidden = false; document.title = '● Meeting? · TwinMind';
  $('#meetBanner').innerHTML = `<b>${M.esc(mic.meeting[0].toUpperCase() + mic.meeting.slice(1))} is using the microphone. It looks like a meeting. Do you want me to record it?</b><button class="primary" id="bRec">Record it</button><button id="bNo">Not this one</button>`;
  $('#bRec').onclick = () => startLive(''); $('#bNo').onclick = () => { dismissed = mic.meeting; $('#meetBanner').hidden = true; document.title = 'TwinMind'; M.log('action.meeting_declined'); };
  if (notified !== mic.meeting && $('#liveNotify').checked && window.Notification && Notification.permission === 'granted') {
    notified = mic.meeting; const n = new Notification('A meeting seems to be on', { body: `${mic.meeting} is using the microphone. Open TwinMind to record it.` }); n.onclick = () => { window.focus(); showTab('live'); };
  }
}
async function startLive(title) {
  $('#liveStart').disabled = true; M.log('action.live_start');
  try { const r = await api('job/live', { body: { title: title ?? $('#liveTitle').value, attendees: $('#liveAtt').value } }); liveJob = r.id; showTab('live'); }
  catch (e) { M.toast(e.message); }
  $('#liveStart').disabled = false; setTimeout(liveTick, 1200);
}
$('#liveStart').onclick = () => startLive($('#liveTitle').value);
$('#liveStop').onclick = async () => { $('#liveStop').disabled = true; await saveLiveNotes(); await api('live/stop', { body: {} }); M.log('action.live_stop'); setTimeout(() => ($('#liveStop').disabled = false), 4000); };
const saveLiveNotes = () => api('live/notes', { body: { notes: $('#liveNotes').value, title: $('#liveTitle2').value } }).catch(() => {});
['#liveNotes', '#liveTitle2'].forEach((x) => ($(x).oninput = () => { clearTimeout(notesTimer); notesTimer = setTimeout(saveLiveNotes, 1500); }));
$('#leftover').onclick = async (e) => { const id = e.target.dataset.finish; if (!id) return; e.target.disabled = true; const r = await api('job/live-finish', { body: { id } }); showTab('new'); follow(r.id); };
try { $('#liveNotify').checked = localStorage.getItem('mitra.twinmind.notify') === '1' && Notification.permission === 'granted'; } catch {}
$('#liveNotify').onchange = async (e) => {
  if (e.target.checked && window.Notification && Notification.permission !== 'granted') e.target.checked = (await Notification.requestPermission()) === 'granted';
  try { localStorage.setItem('mitra.twinmind.notify', e.target.checked ? '1' : '0'); } catch {}
};

// ---- across meetings ---''')
f.write_text(s, "utf-8")
print("ok")
