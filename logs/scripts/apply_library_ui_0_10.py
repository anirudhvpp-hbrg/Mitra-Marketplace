"""0.10.0, part 2: TwinMind's page gets the meeting library.

Four tabs: Meetings (every meeting, old and new, with filters; one meeting opens in the page as
Summary and Transcript, with tags and a project), New memo (what the page was before), Across
meetings (one project over time), People (names that must come out right).
Run once from the project root: python logs/scripts/apply_library_ui_0_10.py
"""
from pathlib import Path

f = Path("apps/twinmind/ui/index.html")
s = f.read_text("utf-8")


def rep(a, b):
    global s
    assert s.count(a) == 1, (s.count(a), a[:70])
    s = s.replace(a, b)


def cut(start, end, new=""):
    global s
    a0 = s.index(start)
    a1 = s.index(end, a0)
    s = s[:a0] + new + s[a1:]


rep("</style>", '''  .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin: 0 0 18px; border-bottom: 1px solid var(--line); }
  .tabs button { border: 0; background: none; border-radius: 0; padding: 10px 14px; font-weight: 600; color: var(--muted); border-bottom: 3px solid transparent; min-height: 44px; }
  .tabs button.on { color: var(--ink); border-bottom-color: var(--action); }
  .filters { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin: 10px 0 14px; } .filters select, .filters input { width: auto; margin: 0; min-width: 130px; flex: 0 1 auto; }
  .filters input#q { flex: 1 1 240px; }
  .row2 { display: grid; grid-template-columns: 92px 1fr auto; gap: 12px; align-items: baseline; padding: 11px 14px; border: 1px solid var(--line); border-radius: var(--r-md); background: var(--panel); margin-bottom: 8px; cursor: pointer; color: inherit; text-align: left; width: 100%; font-weight: 400; }
  .row2:hover { border-color: var(--border-strong); } .row2 b { font: 600 16px/22px var(--serif); overflow-wrap: anywhere; } .row2 .when { color: var(--muted); font-size: 13px; }
  .row2 .sub { color: var(--muted); font-size: 13px; line-height: 18px; margin-top: 2px; }
  @media (max-width: 560px) { .row2 { grid-template-columns: 1fr; gap: 2px; } }
  .tag { display: inline-block; font-size: 12px; line-height: 18px; padding: 0 8px; border-radius: 99px; background: var(--chip); color: var(--ink); margin: 0 4px 2px 0; white-space: nowrap; }
  .tag.proj { background: var(--navy-800); color: #fff; } .tag.sum { background: var(--ok); color: #fff; }
  .tline { display: grid; grid-template-columns: 64px 1fr; gap: 10px; padding: 3px 0; font-size: 15px; line-height: 23px; } .tline .t { color: var(--muted); font: 12px/23px var(--mono); }
  .tline b { color: var(--action-2, var(--ink)); }
  .two { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; } @media (max-width: 860px) { .two { grid-template-columns: 1fr; } }
  .stat3 { display: flex; gap: 22px; flex-wrap: wrap; margin: 6px 0 14px; } .stat3 div b { display: block; font: 600 24px/30px var(--serif); } .stat3 div span { color: var(--muted); font-size: 13px; }
  .months { display: flex; gap: 3px; align-items: flex-end; height: 56px; margin: 8px 0 4px; } .months i { flex: 1; background: var(--action); border-radius: 2px 2px 0 0; min-height: 2px; }
  .item { padding: 8px 0; border-bottom: 1px solid var(--line); font-size: 14px; line-height: 20px; } .item:last-child { border: 0; } .item a { color: var(--muted); font-size: 12px; cursor: pointer; }
  .person { display: grid; grid-template-columns: 200px 1fr auto; gap: 8px; margin-bottom: 8px; } .person input { margin: 0; } @media (max-width: 560px) { .person { grid-template-columns: 1fr; } }
</style>''')

# the tab bar, and the Meetings / Across / People tabs before the old content (which becomes "New memo")
rep('''  <main><div class="wrap" style="max-width:1000px">
    <div id="unfinished"></div>''', '''  <main><div class="wrap" style="max-width:1000px">
    <div class="tabs" role="tablist" id="tabs">
      <button role="tab" data-tab="lib" class="on">Meetings</button><button role="tab" data-tab="new">New memo</button>
      <button role="tab" data-tab="across">Across meetings</button><button role="tab" data-tab="people">People</button>
    </div>
    <section id="tab-lib">
      <div id="libList">
        <div class="filters">
          <input id="q" placeholder="Find a meeting: title, person, project, date" aria-label="Find a meeting">
          <select id="fProject" aria-label="Project"></select><select id="fYear" aria-label="Year"></select>
          <select id="fSummary" aria-label="Summary"><option value="">With or without summary</option><option value="yes">Has a summary</option><option value="no">No summary yet</option></select>
          <button id="inside">Search inside transcripts</button>
        </div>
        <div class="muted small" id="libCount"></div>
        <div id="hits" style="margin:10px 0"></div>
        <div id="meetings"><div class="skeleton" style="height:90px"></div></div>
        <div class="row" style="margin-top:10px"><button id="more" hidden>Show more</button></div>
      </div>
      <div id="detail" hidden></div>
    </section>
    <section id="tab-across" hidden>
      <div class="filters"><select id="aProject" aria-label="Project"></select><select id="aYear" aria-label="Year"></select></div>
      <div id="acrossBody"><div class="muted">Pick a project to see its meetings over time, who was in them, and the action items and decisions gathered from every summary.</div></div>
    </section>
    <section id="tab-people" hidden>
      <div class="card" style="padding:22px"><h2>People</h2>
        <p class="muted small" style="margin:6px 0 14px">Names that must come out right. Each name is given to the speech model before it listens, and any wrong spelling listed beside it is replaced in the transcript before notes are written.</p>
        <div id="peopleRows"></div>
        <div class="row" style="margin-top:8px"><button id="addPerson">Add a person</button><button class="primary" id="savePeople">Save</button><span class="muted small" id="peopleSaved"></span></div>
        <p class="muted small" style="margin:16px 0 6px">Heard most often in your meetings (also given to the speech model):</p><div id="heard"></div>
      </div>
    </section>
    <section id="tab-new" hidden>
    <div id="unfinished"></div>''')

# the old search box and meetings list at the bottom go; the section closes there
cut('    <h3>Find what was said</h3>', '  </div></main>', '    </section>\n')

# old meetings list and old search handler are replaced by the library
cut('async function loadMeetings() {', '\n// ---- the job running now', '''// ---- the library: every meeting, old and new ------------------------------------------------
let lib = { rows: [], total: 0, facets: null }, shown = 80;
const fmtDate = (d) => new Date(d + 'T12:00:00').toLocaleDateString([], { day: 'numeric', month: 'short', year: 'numeric' });
const mins = (m) => m ? (m >= 60 ? `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')} min` : `${m} min`) : '';
function libQuery(extra = '') {
  const p = new URLSearchParams({ q: $('#q').value.trim(), project: $('#fProject').value, year: $('#fYear').value, summary: $('#fSummary').value, limit: shown });
  return 'library?' + p + extra;
}
async function loadMeetings(first) {
  const r = await api(libQuery(first ? '' : '&refresh=0')); lib = r;
  if (first || !$('#fProject').options.length) {
    const opt = (list, all) => `<option value="">${all}</option>` + list.map(([v, n]) => `<option value="${M.esc(v)}">${M.esc(v)} (${n})</option>`).join('');
    const keepP = $('#fProject').value, keepY = $('#fYear').value;
    $('#fProject').innerHTML = opt(r.facets.projects, 'All projects'); $('#fYear').innerHTML = opt(r.facets.years, 'All years');
    $('#fProject').value = keepP; $('#fYear').value = keepY;
    $('#aProject').innerHTML = opt(r.facets.projects.filter(([v]) => v !== '(none)'), 'Pick a project'); $('#aYear').innerHTML = opt(r.facets.years, 'All years');
  }
  $('#libCount').textContent = `${r.total} of ${r.facets.total} meetings · ${r.facets.with_summary} have a summary` + (r.archive ? ' · old meetings are read from your archive and never changed' : '');
  $('#meetings').innerHTML = r.rows.length ? r.rows.map((m) => `<button class="row2" data-id="${m.id}"><span class="when">${fmtDate(m.date)}</span>
    <span><b>${M.esc(m.title)}</b><div class="sub">${m.project ? `<span class="tag proj">${M.esc(m.project)}</span>` : ''}${m.tags.map((t) => `<span class="tag">${M.esc(t)}</span>`).join('')}${M.esc(m.speakers.slice(0, 5).join(', '))}</div></span>
    <span class="when">${m.has_summary ? '<span class="tag sum">summary</span>' : ''}${mins(m.minutes)}</span></button>`).join('')
    : '<div class="empty"><div>No meeting matches. Clear a filter, or search inside the transcripts.</div></div>';
  $('#more').hidden = r.total <= r.rows.length;
}
$('#meetings').onclick = (e) => { const b = e.target.closest('[data-id]'); if (b) openMeeting(b.dataset.id); };
$('#more').onclick = () => { shown += 120; loadMeetings(); };
let ft; const refilter = () => { clearTimeout(ft); ft = setTimeout(() => { shown = 80; $('#hits').innerHTML = ''; loadMeetings(); }, 200); };
$('#q').oninput = refilter; ['#fProject', '#fYear', '#fSummary'].forEach((x) => ($(x).onchange = refilter));
$('#inside').onclick = async () => {
  const q = $('#q').value.trim(); if (q.length < 3) return ($('#hits').innerHTML = '<div class="muted small">Type at least three letters, then search inside.</div>');
  $('#hits').innerHTML = '<div class="muted small">Reading every transcript…</div>';
  const hits = await api('inside?q=' + encodeURIComponent(q));
  const rx = new RegExp('(' + q.split(/\\s+/).filter((w) => w.length > 2).map((w) => w.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&')).join('|') + ')', 'gi');
  $('#hits').innerHTML = hits.length ? `<div class="muted small" style="margin-bottom:6px">${hits.length} meetings say this. Passages are quoted exactly.</div>` + hits.map((h) => `<div class="hit">${M.esc(h.text).replace(rx, '<mark>$1</mark>')}
    <div class="small"><a href="#" data-id="${h.id}">${M.esc(h.meeting)}</a> <span class="muted">${fmtDate(h.date)}${h.project ? ' · ' + M.esc(h.project) : ''}</span></div></div>`).join('')
    : '<div class="muted small">No transcript says that.</div>';
};
$('#hits').onclick = (e) => { const a = e.target.closest('[data-id]'); if (a) { e.preventDefault(); openMeeting(a.dataset.id, $('#q').value.trim()); } };

// One meeting, in the page: the summary, and the transcript as it is.
async function openMeeting(id, find) {
  showTab('lib'); $('#libList').hidden = true; const box = $('#detail'); box.hidden = false; box.innerHTML = '<div class="skeleton" style="height:200px"></div>'; scrollTo({ top: 0 });
  const m = await api('meeting?id=' + id);
  const tline = (l) => { const x = l.match(/^\\[?(\\d{1,2}:\\d{2}(?::\\d{2})?)\\]?\\s*(?:([^:]{1,40}):\\s+)?(.*)$/); return x ? `<div class="tline"><span class="t">${x[1]}</span><span>${x[2] ? `<b>${M.esc(x[2])}</b> ` : ''}${M.esc(x[3])}</span></div>` : `<div class="tline"><span></span><span>${M.esc(l)}</span></div>`; };
  box.innerHTML = `<div class="row" style="margin-bottom:10px"><button id="back">← All meetings</button><span class="muted small" style="margin-left:auto">${m.src === 'archive' ? 'From your archive (read only)' : 'Written by Mitra'}</span></div>
    <div class="card" style="padding:22px">
      <h2 style="overflow-wrap:anywhere">${M.esc(m.title)}</h2>
      <div class="muted" style="margin:4px 0 10px">${fmtDate(m.date)}${m.minutes ? ' · ' + mins(m.minutes) : ''}${m.speakers.length ? ' · ' + M.esc(m.speakers.join(', ')) : ''}</div>
      <div class="filters"><input id="mProject" placeholder="Project" value="${M.esc(m.project)}" aria-label="Project" style="min-width:160px"><input id="mTags" placeholder="Tags, comma separated" value="${M.esc(m.tags.join(', '))}" aria-label="Tags" style="flex:1 1 220px"><button id="mSave">Save tags</button><span class="muted small" id="mSaved"></span></div>
      <div class="tabs" id="mTabs"><button data-m="sum" class="on">Summary</button><button data-m="tr">Transcript <span class="muted">${m.transcript_lines} lines</span></button><button data-m="com">Promised or asked <span class="muted">${m.commitments.length}</span></button></div>
      <div id="m-sum">${m.summary ? `<div class="md">${M.md(m.summary)}</div>` : `<div class="empty"><div>This meeting has no summary yet. The transcript is in the next tab, exactly as recorded.</div>
        <button class="primary" id="mWrite" style="margin-top:12px">Write the summary</button><div class="muted small" style="margin-top:8px">Runs on this device. The summary is saved in Mitra's own folder; the archive is not changed.</div></div>`}</div>
      <div id="m-tr" hidden>${m.transcript.split('\\n').filter((l) => l.trim()).map(tline).join('')}</div>
      <div id="m-com" hidden>${m.commitments.length ? `<p class="muted small">Every sentence that sounds like a promise or a request, quoted as spoken. No model.</p>` + m.commitments.map((c) => `<div class="item">${M.esc(c)}</div>`).join('') : '<div class="muted">None found.</div>'}</div>
    </div>`;
  $('#back').onclick = () => { box.hidden = true; $('#libList').hidden = false; };
  $('#mTabs').onclick = (e) => { const b = e.target.closest('[data-m]'); if (!b) return; $('#mTabs').querySelectorAll('button').forEach((x) => x.classList.toggle('on', x === b)); ['sum', 'tr', 'com'].forEach((k) => ($('#m-' + k).hidden = k !== b.dataset.m)); };
  $('#mSave').onclick = async () => { await api('meta', { body: { id, project: $('#mProject').value, tags: $('#mTags').value.split(',') } }); $('#mSaved').textContent = 'Saved.'; M.log('action.tag_meeting'); loadMeetings(true); };
  if ($('#mWrite')) $('#mWrite').onclick = async () => { showTab('new'); M.log('action.summarise_old'); await start({ path: m.path, name: m.title, title: m.title, attendees: m.speakers.join(', '), speed: 'accurate' }); };
  if (find) { $('#mTabs [data-m=tr]').click(); const w = find.split(/\\s+/)[0].toLowerCase(); const hit = [...$('#m-tr').children].find((d) => d.textContent.toLowerCase().includes(w)); if (hit) { hit.style.background = 'var(--amber-200)'; hit.scrollIntoView({ block: 'center' }); } }
}

// ---- tabs ------------------------------------------------------------------------------------
function showTab(t) {
  ['lib', 'new', 'across', 'people'].forEach((k) => ($('#tab-' + k).hidden = k !== t));
  $('#tabs').querySelectorAll('button').forEach((b) => b.classList.toggle('on', b.dataset.tab === t));
  $('#files').style.display = t === 'new' ? '' : 'none';
  if (t === 'people') loadPeople();
  try { history.replaceState(null, '', location.pathname + location.search + '#' + t); } catch {}
}
$('#tabs').onclick = (e) => { const b = e.target.closest('[data-tab]'); if (b) { showTab(b.dataset.tab); if (b.dataset.tab === 'lib') { $('#detail').hidden = true; $('#libList').hidden = false; } } };

// ---- across meetings ---------------------------------------------------------------------------
async function loadAcross() {
  const project = $('#aProject').value; if (!project) return;
  $('#acrossBody').innerHTML = '<div class="skeleton" style="height:160px"></div>';
  const a = await api('across?' + new URLSearchParams({ project, year: $('#aYear').value }));
  const max = Math.max(1, ...a.months.map((m) => m[1]));
  const list = (rows, none) => rows.length ? rows.map((x) => `<div class="item">${M.esc(x.text)}<div><a data-id="${x.id}">${fmtDate(x.date)} · ${M.esc(x.meeting)}</a></div></div>`).join('') : `<div class="muted">${none}</div>`;
  $('#acrossBody').innerHTML = `<div class="card" style="padding:22px"><h2>${M.esc(project)}</h2>
      <div class="stat3"><div><b>${a.meetings}</b><span>meetings</span></div><div><b>${a.with_summary}</b><span>have a summary</span></div><div><b>${a.first ? fmtDate(a.first) : '–'}</b><span>first</span></div><div><b>${a.last ? fmtDate(a.last) : '–'}</b><span>latest</span></div></div>
      <div class="months" title="Meetings per month">${a.months.map((m) => `<i style="height:${100 * m[1] / max}%" title="${m[0]}: ${m[1]}"></i>`).join('')}</div>
      <div class="muted small">${a.months.length ? `${a.months[0][0]} to ${a.months[a.months.length - 1][0]}, meetings per month` : ''}</div>
      <p style="margin:14px 0 0">${a.people.map(([n, c]) => `<span class="tag">${M.esc(n)} ${c}</span>`).join('')}</p></div>
    ${a.with_summary < a.meetings ? `<div class="finding" style="margin:14px 0">${a.meetings - a.with_summary} of these meetings have no summary yet, so their action items and decisions are not below. Open a meeting and choose "Write the summary", or line up several: <button id="sumAll">Write summaries for the latest 5 without one</button></div>` : ''}
    <div class="two" style="margin-top:14px"><div class="card" style="padding:18px"><h3 style="margin-top:0">Action items <span class="muted">${a.actions.length}</span></h3>${list(a.actions, 'None in the summaries so far.')}</div>
      <div class="card" style="padding:18px"><h3 style="margin-top:0">Decisions <span class="muted">${a.decisions.length}</span></h3>${list(a.decisions, 'None in the summaries so far.')}
        <h3>Still open <span class="muted">${a.open.length}</span></h3>${list(a.open, 'Nothing recorded as open.')}</div></div>
    <h3>Meetings</h3>${a.rows.map((m) => `<button class="row2" data-id="${m.id}"><span class="when">${fmtDate(m.date)}</span><span><b>${M.esc(m.title)}</b></span><span class="when">${m.has_summary ? '<span class="tag sum">summary</span>' : ''}${mins(m.minutes)}</span></button>`).join('')}`;
  const todo = a.rows.filter((m) => !m.has_summary).slice(0, 5);
  if ($('#sumAll')) $('#sumAll').onclick = async () => {
    showTab('new'); M.log('action.summarise_project', { n: todo.length });
    for (const m of todo) { const full = await api('meeting?id=' + m.id); await start({ path: full.path, name: full.title, title: full.title, attendees: full.speakers.join(', '), speed: 'accurate' }); }
  };
}
$('#aProject').onchange = loadAcross; $('#aYear').onchange = loadAcross;
$('#acrossBody').onclick = (e) => { const b = e.target.closest('[data-id]'); if (b) openMeeting(b.dataset.id); };

// ---- people --------------------------------------------------------------------------------------
function personRow(p = { name: '', aliases: [] }) { return `<div class="person"><input placeholder="Name, as it should be written" value="${M.esc(p.name)}" data-n><input placeholder="Wrong spellings to replace, comma separated" value="${M.esc(p.aliases.join(', '))}" data-a><button class="ghost" data-x>Remove</button></div>`; }
async function loadPeople() {
  const r = await api('people');
  $('#peopleRows').innerHTML = (r.people.length ? r.people : [{ name: '', aliases: [] }]).map(personRow).join('');
  $('#heard').innerHTML = r.heard.map((n) => `<span class="tag">${M.esc(n)}</span>`).join('');
}
$('#addPerson').onclick = () => $('#peopleRows').insertAdjacentHTML('beforeend', personRow());
$('#peopleRows').onclick = (e) => { if (e.target.dataset.x != null) e.target.closest('.person').remove(); };
$('#savePeople').onclick = async () => {
  const people = [...document.querySelectorAll('.person')].map((d) => ({ name: d.querySelector('[data-n]').value, aliases: d.querySelector('[data-a]').value.split(',').map((x) => x.trim()).filter(Boolean) }));
  const r = await api('people', { body: { people } }); $('#peopleSaved').textContent = `Saved: ${r.people.length} ${r.people.length === 1 ? 'person' : 'people'}.`; M.log('action.save_people', { n: r.people.length });
};
''')

# the old search handler (memos only) is gone; the library's search replaces it
cut("let timer;\n$('#q').oninput = () => {", "M.ready.then(async () => {")
rep("  loadMeetings(); refresh();\n});", "  await loadMeetings(true); refresh();\n  const want = location.hash.slice(1); showTab(first ? 'new' : ['lib', 'new', 'across', 'people'].includes(want) ? want : 'lib');\n});")
f.write_text(s, "utf-8")
print("ok")
