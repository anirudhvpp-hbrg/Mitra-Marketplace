/* Mitra SDK: every app page includes this. It gives the app its top bar, native memory logging,
   the shared file browser, a Markdown renderer and the manager panel. No dependencies. */
(() => {
  const M = (window.mitra = {});
  M.appId = (location.pathname.match(/^\/apps\/([^/]+)/) || [])[1] || 'shell';
  M.session = (crypto.randomUUID ? crypto.randomUUID() : String(Math.random()).slice(2));
  M.esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  M.el = (html) => { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };
  M.param = (k) => new URLSearchParams(location.search).get(k);
  M.fileUrl = (p) => '/api/fs/file/' + encodeURIComponent(String(p).split(/[\\/]/).pop()) + '?path=' + encodeURIComponent(p);   // the name in the address titles the PDF viewer
  M.size = (n) => (n > 1e9 ? (n / 1e9).toFixed(1) + ' GB' : n > 1e6 ? (n / 1e6).toFixed(1) + ' MB' : n > 1e3 ? Math.round(n / 1e3) + ' KB' : n + ' B');

  // ---- memory: every event is appended to the native log -------------------------------
  M.log = (type, data = {}) => {
    const body = JSON.stringify({ app: M.appId, session: M.session, type, data });
    if (!navigator.sendBeacon || !navigator.sendBeacon('/api/log', new Blob([body], { type: 'application/json' })))
      fetch('/api/log', { method: 'POST', body, headers: { 'Content-Type': 'application/json' }, keepalive: true }).catch(() => {});
  };
  let active = 0, since = document.hidden ? 0 : Date.now();
  document.addEventListener('visibilitychange', () => {
    if (document.hidden && since) { active += Date.now() - since; since = 0; } else if (!document.hidden) since = Date.now();
  });
  if (M.appId !== 'shell') {
    M.log('app.open', { ref: document.referrer ? new URL(document.referrer).pathname : '' });
    addEventListener('pagehide', () => M.log('app.close', { active_ms: active + (since ? Date.now() - since : 0) }));
  }
  addEventListener('error', (e) => M.log('error', { msg: e.message, at: (e.filename || '').split('/').pop() + ':' + e.lineno }));

  // ---- each app is its own process ------------------------------------------------------
  // A page tells its process it is alive every few seconds and says goodbye when it closes;
  // the process ends a few seconds after the goodbye. That is how closing a window frees it.
  setInterval(() => fetch('/api/heartbeat').catch(() => {}), 3000);
  addEventListener('pagehide', () => { try { navigator.sendBeacon('/api/bye', ''); } catch {} });
  // Start another app (in its own process and window); a path opens that file in it.
  M.launch = async (id, { path, query } = {}) => {
    try {
      const r = await M.api('/api/launch/' + encodeURIComponent(id), { body: path ? { path } : { query: query || '' } });
      if (r.opened === 'page' && !window.open(r.url, '_blank')) location.href = r.url;   // nothing could open it for us
      dispatchEvent(new CustomEvent('mitra-launch', { detail: r }));
      return r;
    } catch (e) { M.toast(e.message); return null; }
  };
  // Go to the launcher (optionally to one of its pages: create, memory, system).
  M.home = async (to = '') => {
    if (M.appId === 'shell') { location.hash = to; return; }
    try { await M.api('/api/launcher?to=' + encodeURIComponent(to), { method: 'POST' }); } catch (e) { M.toast(e.message); }
  };
  // ---- drop a file on any window to open it ---------------------------------------------
  // An app says what it opens here: M.accept = { exts: ['.pdf'] or null for anything, open(path, name) }.
  // A file it does not open goes to the app that does (each manifest lists its types under "opens").
  // The browser never reveals where a dropped file lives, so the app is given a temporary copy.
  M.accept = null;
  let opensMap = null;
  const extOf = (name) => (String(name).match(/\.[^.\/]+$/) || [''])[0].toLowerCase();
  M.appFor = async (name, prefer) => {
    const ext = extOf(name);
    if (M.accept && (!M.accept.exts || M.accept.exts.includes(ext))) return M.appId;
    opensMap = opensMap || await M.api('/api/opens');
    const ids = opensMap[ext] || [];
    if (prefer && (ids.includes(prefer) || (!ids.length && (opensMap['*'] || []).includes(prefer)))) return prefer;
    return ids[0] || (opensMap['*'] || [])[0] || null;
  };
  M.openFile = async (file, prefer) => {
    if (!file || (!file.size && !file.type && !extOf(file.name))) return M.toast('Folders cannot be dropped; drop a file.');
    let target;
    try { target = await M.appFor(file.name, prefer); } catch (e) { return M.toast(e.message); }
    if (!target) return M.toast('No app here opens ' + (extOf(file.name) || 'that kind of file') + '.');
    try {
      const r = await M.api('/api/drop/' + encodeURIComponent(target) + '?name=' + encodeURIComponent(file.name), { method: 'POST', body: file });
      M.log('file.open', { via: 'drop', ext: extOf(file.name), to: target });
      if (target === M.appId) await M.accept.open(r.path, r.name);
      else if (r.opened === 'page' && !window.open(r.url, '_blank')) location.href = r.url;
      dispatchEvent(new CustomEvent('mitra-drop', { detail: r }));
      return r;
    } catch (e) { M.toast(e.message, 6000); return null; }
  };
  const carriesFiles = (e) => e.dataTransfer && [...(e.dataTransfer.types || [])].includes('Files');
  let veil = null, depth = 0;
  const tileUnder = (e) => (M.appId === 'shell' && e.target.closest ? e.target.closest('[data-id]') : null);
  const unveil = () => { depth = 0; veil?.remove(); veil = null; document.querySelectorAll('.droptarget').forEach((t) => t.classList.remove('droptarget')); };
  addEventListener('dragenter', (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault(); depth++;
    if (!veil) {
      const what = M.appId === 'shell' ? 'Drop a file to open it in the app that reads it' : 'Drop to open in ' + (M.app?.name || 'this app');
      // in an app the veil sits above everything (an embedded PDF would otherwise swallow the drop);
      // in the launcher it lets the pointer through, so a file can be dropped on one app's icon
      veil = M.el(`<div class="dropveil${M.appId === 'shell' ? ' through' : ''}"><div>${M.icon('arrow')}<b>${M.esc(what)}</b></div></div>`);
      document.body.append(veil);
    }
  });
  addEventListener('dragover', (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault(); e.dataTransfer.dropEffect = 'copy';
    const t = tileUnder(e);
    document.querySelectorAll('.droptarget').forEach((x) => x !== t && x.classList.remove('droptarget'));
    t?.classList.add('droptarget');
  });
  addEventListener('dragleave', (e) => { if (carriesFiles(e) && --depth <= 0) unveil(); });
  addEventListener('drop', async (e) => {
    if (!carriesFiles(e)) return;
    e.preventDefault();
    const prefer = tileUnder(e)?.dataset.id, files = [...e.dataTransfer.files].slice(0, 8);
    unveil();
    for (const f of files) await M.openFile(f, prefer);
  });

  // A link to another app, or to the launcher from inside an app, starts or shows that
  // product; it never loads it into this window.
  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('a[href]'); if (!a || e.defaultPrevented) return;
    const href = a.getAttribute('href') || '';
    const m = href.match(/^\/apps\/([^/?#]+)\/?(?:\?([^#]*))?/);
    if (m && m[1] !== M.appId) { e.preventDefault(); M.launch(m[1], { query: m[2] || '' }); }
    else if (M.appId !== 'shell' && /^\/(#[\w-]*)?$/.test(href)) { e.preventDefault(); M.home(href.slice(2)); }
  });

  M.api = async (path, opts = {}) => {
    const o = { ...opts };
    if (o.body && typeof o.body === 'object' && !(o.body instanceof Blob)) {
      o.body = JSON.stringify(o.body); o.method = o.method || 'POST';
      o.headers = { 'Content-Type': 'application/json', ...(o.headers || {}) };
    }
    const r = await fetch(path, o);
    const data = await r.json().catch(() => ({}));
    if (!r.ok) { const msg = data.detail || r.statusText; M.log('error', { msg, path: path.split('?')[0] }); throw new Error(msg); }
    return data;
  };
  // ---- icons: one hand-drawn line set, so nothing depends on the OS emoji font ----------
  const ICONS = {
    doc: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5M10 13h6M10 17h4"/>',
    pdf: '<path d="M7 3h7l5 5v13H7z"/><path d="M14 3v5h5"/><path d="M10 18v-5h1.4a1.4 1.4 0 0 1 0 2.8H10M14.5 13v5"/>',
    convert: '<path d="M4 8h14l-3.5-3.5M20 16H6l3.5 3.5"/>',
    chat: '<path d="M4.5 5h15v10.5H10L5.5 19.5v-4h-1z"/><path d="M8.5 9h7M8.5 12h4"/>',
    mic: '<rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21M9 21h6"/>',
    book: '<path d="M5 4.5h9a3 3 0 0 1 3 3V20H8a3 3 0 0 1-3-3z"/><path d="M5 17a3 3 0 0 1 3-3h9M17 7.5h2V20"/>',
    code: '<path d="M9 8l-4 4 4 4M15 8l4 4-4 4M13 6l-2 12"/>',
    coin: '<circle cx="12" cy="12" r="8"/><path d="M14.5 9.5c-.6-.8-1.5-1-2.5-1-1.4 0-2.5.7-2.5 1.8 0 2.6 5 1.2 5 3.9 0 1.100-1.100 1.800-2.500 1.800-1.100 0-2.100-.400-2.700-1.200M12 7v10"/>',
    app: '<rect x="4" y="4" width="7" height="7" rx="1.6"/><rect x="13" y="4" width="7" height="7" rx="1.6"/><rect x="4" y="13" width="7" height="7" rx="1.6"/><path d="M16.5 13.5v6M13.5 16.5h6"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    clock: '<circle cx="12" cy="12" r="8"/><path d="M12 7.5V12l3 2"/>',
    gauge: '<path d="M4 17a8 8 0 1 1 16 0"/><path d="M12 17l4-6"/>',
    search: '<circle cx="11" cy="11" r="6"/><path d="M20 20l-4.500-4.500"/>',
    moon: '<path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/>',
    sun: '<circle cx="12" cy="12" r="4"/><path d="M12 2.500v2.500M12 19v2.500M2.500 12H5M19 12h2.500M5.200 5.200L7 7M17 17l1.800 1.800M5.200 18.800L7 17M17 7l1.800-1.800"/>',
    stop: '<rect x="6.5" y="6.5" width="11" height="11" rx="2"/>',
    arrow: '<path d="M5 12h14M13 6l6 6-6 6"/>',
  };
  M.icon = (name) => `<svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${ICONS[name] || ICONS.app}</svg>`;
  M.glyph = (name) => `<span class="glyph">${M.icon(name)}</span>`;
  const BY_CATEGORY = { 'Documents': 'doc', 'Meeting Intelligence': 'mic', 'Assistant': 'chat', 'Knowledge': 'book', 'Developer': 'code', 'Finance': 'coin' };
  M.glyphFor = (app) => (ICONS[app.glyph] ? app.glyph : BY_CATEGORY[app.category] || 'app');

  // ---- theme: follows the system until the person picks one ----------------------------
  // Kept in a cookie as well as localStorage: every app runs on its own port, so each is its own
  // origin with its own localStorage, but cookies are shared by host across ports. One choice
  // then holds in the launcher and in every app window.
  const cookieTheme = () => (document.cookie.match(/(?:^|; )mitra_theme=(light|dark)/) || [])[1];
  try { const t = cookieTheme() || localStorage.getItem('mitra.theme'); if (t) document.documentElement.dataset.theme = t; } catch {}
  M.isDark = () => (document.documentElement.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')) === 'dark';
  M.toggleTheme = () => {
    const next = M.isDark() ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem('mitra.theme', next); } catch {}
    document.cookie = `mitra_theme=${next}; path=/; max-age=31536000; SameSite=Strict`;
    M.log('action.theme', { theme: next });
    dispatchEvent(new Event('mitra-theme'));
  };
  // a window brought forward picks up a choice made in another one meanwhile
  addEventListener('focus', () => { const t = cookieTheme(); if (t && t !== document.documentElement.dataset.theme) { document.documentElement.dataset.theme = t; dispatchEvent(new Event('mitra-theme')); } });
  if (!document.querySelector('link[rel=icon]')) {
    const ico = document.createElement('link'); ico.rel = 'icon'; ico.href = '/static/brand/mitra-color.png'; document.head.append(ico);
  }

  M.toast = (msg, ms = 3500) => { const t = M.el(`<div class="toast">${M.esc(msg)}</div>`); document.body.append(t); setTimeout(() => t.remove(), ms); };
  // every rendered code block carries a Copy button (M.md adds it); one listener serves them all
  document.addEventListener('click', (e) => {
    const b = e.target.closest && e.target.closest('.md pre .copy'); if (!b) return;
    navigator.clipboard.writeText(b.previousElementSibling.textContent).then(() => { b.textContent = 'Copied'; setTimeout(() => (b.textContent = 'Copy'), 1400); });
  });

  // ---- Markdown renderer ---------------------------------------------------------------
  const safeUrl = (u) => (/^(https?:|mailto:|#|\/|\.{0,2}\/|[\w\-. %]+($|[/#?]))/i.test(u) && !/^\s*javascript:/i.test(u) ? u : '#');
  M.md = (src, baseDir) => {
    const img = (u) => (/^(https?:|data:|\/)/i.test(u) || !baseDir ? u : M.fileUrl(baseDir.replace(/[\\/]$/, '') + '/' + u));
    const inline = (s) => {
      const keep = [];
      const stash = (h) => { keep.push(h); return '\u0000' + (keep.length - 1) + '\u0000'; };
      s = s.replace(/`([^`]+)`/g, (_, c) => stash('<code>' + M.esc(c) + '</code>'));
      s = s.replace(/\\([\\`*_{}\[\]()#+\-.!|>~])/g, (_, c) => stash(M.esc(c)));   // "\#" is a plain "#", not markup
      s = M.esc(s);
      s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (_, a, u) => stash(`<img alt="${a}" src="${M.esc(img(u.replace(/&amp;/g, '&')))}">`));
      s = s.replace(/\[([^\]]+)\]\(([^)\s]+)(?:\s+&quot;[^)]*&quot;)?\)/g, (_, t, u) => `<a href="${safeUrl(u)}"${/^https?:/i.test(u) ? ' target="_blank" rel="noopener"' : ''}>${t}</a>`);
      // a sentence's closing punctuation is not part of the address
      s = s.replace(/(^|[\s(])(https?:\/\/[^\s<)]*[^\s<).,;:!?'"])/g, (_, p, u) => `${p}<a href="${u}" target="_blank" rel="noopener">${u}</a>`);
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/__([^_]+)__/g, '<strong>$1</strong>');
      s = s.replace(/(^|[^*\w])\*([^*\s][^*]*)\*/g, '$1<em>$2</em>').replace(/(^|[^_\w])_([^_\s][^_]*)_(?!\w)/g, '$1<em>$2</em>');
      s = s.replace(/~~([^~]+)~~/g, '<del>$1</del>');
      s = s.replace(/&lt;br\s*\/?&gt;/gi, '<br>');   // a line break inside a table cell
      return s.replace(/\u0000(\d+)\u0000/g, (_, i) => keep[+i]);
    };
    const itemRx = /^(\s*)([-*+]|\d+[.)])\s+(.*)$/;
    const cells = (l) => l.trim().replace(/^\||\|$/g, '').split(/(?<!\\)\|/).map((c) => c.trim().replace(/\\\|/g, '|'));
    const blocks = (lines) => {
      let out = '', i = 0;
      while (i < lines.length) {
        const l = lines[i];
        if (!l.trim()) { i++; continue; }
        let m;
        if ((m = l.match(/^\s*(```+|~~~+)\s*([\w+-]*)/))) {
          const buf = []; i++;
          while (i < lines.length && !lines[i].trim().startsWith(m[1])) buf.push(lines[i++]);
          i++; out += `<pre><code>${M.esc(buf.join('\n'))}</code><button class="ghost copy" type="button" aria-label="Copy code">Copy</button></pre>`; continue;
        }
        if ((m = l.match(/^(#{1,6})\s+(.*?)\s*#*$/))) { out += `<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`; i++; continue; }
        if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(l)) { out += '<hr>'; i++; continue; }
        if (/^\s*>/.test(l)) {
          const buf = [];
          while (i < lines.length && /^\s*>/.test(lines[i])) buf.push(lines[i++].replace(/^\s*>\s?/, ''));
          out += `<blockquote>${blocks(buf)}</blockquote>`; continue;
        }
        if (l.includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(lines[i + 1])) {
          const head = cells(l); i += 2; let body = '';
          while (i < lines.length && lines[i].includes('|') && lines[i].trim()) body += '<tr>' + cells(lines[i++]).map((c) => `<td>${inline(c)}</td>`).join('') + '</tr>';
          out += `<div class="tablewrap"><table><thead><tr>${head.map((c) => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`; continue;
        }
        if ((m = l.match(itemRx))) {
          const indent = m[1].length, ordered = /\d/.test(m[2]), items = [];
          while (i < lines.length) {
            const mm = lines[i].match(itemRx), lead = lines[i].match(/^\s*/)[0].length;
            if (mm && mm[1].length <= indent + 1 && /\d/.test(mm[2]) === ordered) { items.push([mm[3]]); i++; }
            else if (!lines[i].trim()) {
              const nx = lines[i + 1]; const nm = nx !== undefined && nx.match(itemRx);
              if (nx !== undefined && nx.trim() && (nx.match(/^\s*/)[0].length > indent + 1 || (nm && nm[1].length <= indent + 1 && /\d/.test(nm[2]) === ordered))) { items[items.length - 1].push(''); i++; } else break;
            } else if (lead > indent + 1) { items[items.length - 1].push(lines[i].slice(Math.min(lead, indent + 2))); i++; }
            else if (!mm && items.length && !/^(#{1,6}\s|\s*>|\s*```)/.test(lines[i])) { items[items.length - 1][0] += ' ' + lines[i].trim(); i++; }
            else break;
          }
          const li = (it) => {
            let head = it[0], box = '';
            const t = head.match(/^\[( |x|X)\]\s+(.*)$/);
            if (t) { box = `<input type="checkbox" disabled${t[1] !== ' ' ? ' checked' : ''}>`; head = t[2]; }
            return `<li>${box}${inline(head)}${it.length > 1 ? blocks(it.slice(1)) : ''}</li>`;
          };
          out += `<${ordered ? 'ol' : 'ul'}>${items.map(li).join('')}</${ordered ? 'ol' : 'ul'}>`; continue;
        }
        const buf = [];
        while (i < lines.length && lines[i].trim() && !/^(#{1,6}\s|\s*>|\s*```|\s*~~~)/.test(lines[i]) && !(buf.length && itemRx.test(lines[i]))
          && !(lines[i].includes('|') && i + 1 < lines.length && /^\s*\|?\s*:?-{2,}/.test(lines[i + 1]))) buf.push(lines[i++]);
        if (!buf.length) buf.push(lines[i++]);
        out += `<p>${buf.map((x) => inline(x.replace(/\s{2,}$/, '\u0001'))).join('\n').replace(/\u0001\n?/g, '<br>')}</p>`;
      }
      return out;
    };
    let lines = String(src || '').replace(/\r\n?/g, '\n').split('\n'), front = '';
    if (lines[0] === '---') {
      // front matter is the file's properties: folded into one quiet line, open on demand (as Obsidian does)
      const end = lines.indexOf('---', 1);
      if (end > 0) {
        const rows = [];
        for (const l of lines.slice(1, end)) {
          const kv = l.match(/^([\w .-]+):\s?(.*)$/);
          if (kv && !/^\s/.test(l)) rows.push([kv[1], kv[2]]); else if (rows.length) rows[rows.length - 1][1] += '\n' + l.trim();
        }
        front = `<details class="props"><summary>Properties · ${rows.length}</summary><table>${rows.map(([k, v]) =>
          `<tr><td>${M.esc(k)}</td><td style="white-space:pre-wrap;overflow-wrap:anywhere">${M.esc(v.trim())}</td></tr>`).join('')}</table></details>`;
        lines = lines.slice(end + 1);
      }
    }
    return front + blocks(lines);
  };

  // ---- shared file browser -------------------------------------------------------------
  M.browser = async (host, { exts = null, onPick, start = null, title = 'Files' } = {}) => {
    host.classList.add('fb');
    const roots = await M.api('/api/fs/roots');
    let current = null;
    const go = async (path) => {
      let data;
      try { data = await M.api('/api/fs/list?path=' + encodeURIComponent(path)); } catch (e) { return M.toast(e.message); }
      const recents = await M.api('/api/recent?app_id=' + M.appId).catch(() => []);
      const items = data.items.filter((i) => i.dir || !exts || exts.includes(i.ext));
      // two recent files with one name (a copy, an older version) are told apart by their folder
      const recentName = (p) => { const parts = p.split(/[\\/]/), n = parts.pop(); return recents.filter((q) => q.split(/[\\/]/).pop() === n).length > 1 ? `${n} · ${parts.pop() || ''}` : n; };
      host.innerHTML = `<select aria-label="Location">${roots.map((r) => `<option value="${M.esc(r.path)}">${M.esc(r.name)}</option>`).join('')}</select>
        <div class="crumb">${M.esc(data.path)}</div>
        ${data.parent ? `<div class="item" data-dir="${M.esc(data.parent)}"><span><i class="dir">↑</i>Up one level</span></div>` : ''}
        ${items.map((i) => `<div class="item${i.path === current ? ' on' : ''}" ${i.dir ? 'data-dir' : 'data-file'}="${M.esc(i.path)}"><span>${i.dir ? '<i class="dir">▸</i>' : ''}${M.esc(i.name)}</span>${i.dir ? '' : `<small>${M.size(i.size)}</small>`}</div>`).join('') || '<div class="muted small" style="padding:8px">Nothing to open here.</div>'}
        ${recents.length ? `<h4>Recent</h4>${recents.map((p) => `<div class="item" data-file="${M.esc(p)}" title="${M.esc(p)}"><span>${M.esc(recentName(p))}</span></div>`).join('')}` : ''}`;
      const sel = host.querySelector('select');
      const hit = roots.filter((r) => data.path.toLowerCase().startsWith(r.path.toLowerCase())).sort((a, b) => b.path.length - a.path.length)[0];
      if (hit) sel.value = hit.path;
      sel.onchange = () => go(sel.value);
      try { localStorage.setItem('mitra.dir.' + M.appId, data.path); } catch {}
    };
    host.addEventListener('click', (e) => {
      const it = e.target.closest('.item'); if (!it) return;
      if (it.dataset.dir !== undefined) return go(it.dataset.dir);
      current = it.dataset.file;
      host.querySelectorAll('.item.on').forEach((x) => x.classList.remove('on')); it.classList.add('on');
      M.log('file.open', { path: current });
      onPick && onPick(current);
    });
    let saved = null; try { saved = localStorage.getItem('mitra.dir.' + M.appId); } catch {}
    await go(start || saved || roots[0].path);
    return { go, select: (p) => { current = p; M.log('file.open', { path: p }); } };
  };

  // ---- top bar + RAM pill + manager panel ----------------------------------------------
  M.ramPill = (host) => {
    const pill = M.el('<a class="ram" href="/#system" title="RAM governor"><span class="meter"><i></i></span><span class="txt">RAM</span></a>');
    host.append(pill);
    const tick = async () => {
      if (document.hidden) return;
      try {
        const s = await (await fetch('/api/system')).json();
        pill.className = 'ram ' + s.state + (s.leases.length ? ' live' : '');
        pill.querySelector('i').style.width = s.ram.pct + '%';
        pill.querySelector('.txt').textContent = `RAM ${Math.round(s.ram.pct)}%` + (s.leases.length ? ` · ${s.leases[0].name} ${s.leases[0].mb} MB` + (M.appId !== 'shell' && s.leases[0].apps[0] !== M.appId ? ` · ${s.leases[0].apps[0]}` : '')
          : (s.line || []).length ? ' · model changing hands' : ' · no model loaded');
      } catch { pill.querySelector('.txt').textContent = M.appId === 'shell' ? 'Mitra is asleep. Run mitra-marketplace to wake it.' : 'This app has stopped. Open it again from Mitra.'; }
    };
    tick(); setInterval(tick, 5000);
  };
  M.managerPanel = async () => {
    document.querySelector('.panel')?.remove();
    const p = M.el('<div class="panel"><div class="row"><h3 style="margin:0;flex:1">Manager</h3><button data-x>Close</button></div><p class="muted small">Reviewing…</p></div>');
    document.body.append(p);
    p.querySelector('[data-x]').onclick = () => p.remove();
    try {
      const r = await M.api('/api/manager/' + M.appId);
      p.querySelector('p').outerHTML = `
        <p class="small muted">A review of this app from its own measurements. Model budget: ${r.budget_mb} MB.</p>
        ${r.findings.map((f) => `<div class="finding ${f.level}">${M.esc(f.text)}</div>`).join('')}
        <h4>Last 7 days</h4>
        <table class="plain"><tr><td>Opens</td><td>${r.stats.opens}</td></tr><tr><td>Active minutes</td><td>${r.stats.active_min}</td></tr>
        <tr><td>Errors</td><td>${Object.values(r.stats.errors).reduce((a, b) => a + b, 0)}</td></tr><tr><td>Stopped by governor</td><td>${r.stats.evictions}</td></tr>
        ${Object.entries(r.stats.model_calls).map(([m, c]) => `<tr><td>${M.esc(m)}</td><td>${c.n} runs · ${(c.avg_ms / 1000).toFixed(1)} s avg · peak ${c.peak_mb} MB</td></tr>`).join('')}</table>
        ${r.held.length ? `<h4>Holding now</h4>${r.held.map((l) => `<div class="small">${M.esc(l.name)} · ${l.mb} MB · ${l.busy ? 'busy' : 'idle ' + l.idle_s + ' s'}</div>`).join('')}` : ''}`;
    } catch (e) { p.querySelector('p').textContent = e.message; }
  };
  // ---- command palette: Ctrl+K (or Cmd+K) on every screen ------------------------------
  M.palette = () => {
    if (document.querySelector('.palette-back')) return;
    const items = [   // actions appear at once; apps are added as soon as the list arrives
      { label: 'All apps', hint: 'Launcher', glyph: 'app', go: () => M.home('apps') },
      { label: 'Create an app', hint: 'From a description', glyph: 'plus', go: () => M.home('create') },
      { label: 'Memory report', hint: 'Usage and RAM', glyph: 'clock', go: () => M.home('memory') },
      { label: 'System', hint: 'RAM, apps and models', glyph: 'gauge', go: () => M.home('system') },
      { label: 'Switch theme', hint: 'Light or dark', glyph: 'moon', go: () => M.toggleTheme() },
      { label: 'Stop the running model', hint: 'Governor', glyph: 'stop', go: async () => { await M.api('/api/system/evict', { body: {} }); M.toast('Asked the governor to stop the model.'); } },
    ];
    const back = M.el(`<div class="palette-back"><div class="palette" role="dialog" aria-label="Go to"><input placeholder="Go to an app or action" aria-label="Search apps and actions"><ul role="listbox"></ul></div></div>`);
    document.body.append(back);
    const input = back.querySelector('input'), list = back.querySelector('ul');
    let shown = [], at = 0;
    const close = () => back.remove();
    const draw = () => {
      const q = input.value.toLowerCase().trim();
      shown = items.filter((i) => !q || (i.label + ' ' + i.hint).toLowerCase().includes(q));
      at = Math.min(at, Math.max(0, shown.length - 1));
      list.innerHTML = shown.map((i, n) => `<li role="option" class="${n === at ? 'on' : ''}" data-n="${n}">${M.glyph(i.glyph)}<span>${M.esc(i.label)}</span><small>${M.esc(i.hint)}</small></li>`).join('')
        || '<li class="muted">Nothing matches.</li>';
      list.querySelector('.on')?.scrollIntoView({ block: 'nearest' });
    };
    const run = (n) => { const it = shown[n]; if (it) { M.log('palette.go', { to: it.label }); close(); it.go(); } };
    input.oninput = () => { at = 0; draw(); };
    input.onkeydown = (e) => {
      if (e.key === 'ArrowDown') { at = (at + 1) % Math.max(1, shown.length); draw(); e.preventDefault(); }
      else if (e.key === 'ArrowUp') { at = (at - 1 + shown.length) % Math.max(1, shown.length); draw(); e.preventDefault(); }
      else if (e.key === 'Enter') run(at);
      else if (e.key === 'Escape') close();
    };
    list.onclick = (e) => { const li = e.target.closest('li[data-n]'); if (li) run(+li.dataset.n); };
    back.onclick = (e) => { if (e.target === back) close(); };
    draw(); input.focus();
    M.api('/api/apps').then((apps) => {
      items.unshift(...apps.map((a) => ({ label: a.name, hint: a.category, glyph: M.glyphFor(a), go: () => M.launch(a.id) })).filter((i, n) => apps[n].id !== M.appId));
      if (back.isConnected) draw();
    }).catch(() => {});
  };
  addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') { e.preventDefault(); M.palette(); }
  });

  M.ready = (async () => {
    if (M.appId === 'shell') return null;
    const app = await M.api('/api/apps/' + M.appId);
    M.app = app; document.title = app.name + ' · Mitra';
    const bar = M.el(`<header class="bar"><a class="logo-link" href="/" title="Show all apps" aria-label="Show all apps"><span class="logo" role="img" aria-label="Mitra"></span></a>
      <span class="title">${M.glyph(M.glyphFor(app))}${M.esc(app.name)}</span>
      <span class="row" style="gap:6px">${app.needs.map((n) => `<span class="chip ${n.ready ? 'ok' : 'warn'}" title="${M.esc(n.ready ? n.model + ' · about ' + n.est_mb + ' MB when running' : n.hint)}">${M.esc(n.capability)}</span>`).join('')}
      ${app.connectors.map((c) => `<span class="chip ${c.available ? 'ok' : 'warn'}" title="${M.esc(c.resolved || 'not found')}">${M.esc(c.type)}</span>`).join('')}</span>
      <span class="spacer"></span><button class="ghost" data-pal title="Go to (Ctrl+K)" aria-label="Go to an app or action">${M.icon('search')}</button><button class="ghost" data-mgr title="This app's own measurements: RAM, model runs, errors">Manager</button></header>`);
    document.body.prepend(bar);
    bar.querySelector('[data-mgr]').onclick = M.managerPanel;
    bar.querySelector('[data-pal]').onclick = M.palette;
    M.ramPill(bar);
    return app;
  })();
})();
