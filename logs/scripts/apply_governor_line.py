"""0.9.0: the governor keeps a line instead of giving up after two minutes.

Every governor that wants the model writes a ticket in ~/.mitra/run/line. The model goes to the
head of the line: questions (priority interactive) first, then first come first served. A waiter
whose caller has gone leaves the line; a running model whose caller has gone is stopped.
Run once from the project root: python logs/scripts/apply_governor_line.py
"""
from pathlib import Path

f = Path("governor/src/main.rs")
s = f.read_text("utf-8")


def rep(a, b, n=1):
    global s
    assert s.count(a) == n, (s.count(a), a[:60])
    s = s.replace(a, b)


rep("//!   mitra-governor run --app A --name N --est-mb E [--budget-mb B] [--timeout S] [--wait S]\n//!                      [--hold-stdin] -- <command...>",
    "//!   mitra-governor run --app A --name N --est-mb E [--budget-mb B] [--timeout S] [--wait S]\n//!                      [--priority interactive|background] [--what TEXT] [--hold-stdin] -- <command...>")
rep("allows one model at a time (a lock\n//! file),",
    "allows one model at a time (a lock\n//! file, and a line of tickets for those waiting: questions first, then first come first served),")
rep("    hold_stdin: bool,\n    cmd: Vec<String>,", "    hold_stdin: bool,\n    priority: String,\n    what: String,\n    cmd: Vec<String>,")
rep("timeout_s: 3600, wait_s: 120, hold_stdin: false, cmd: vec![] };",
    "timeout_s: 3600, wait_s: 0, hold_stdin: false,\n                       priority: \"background\".into(), what: String::new(), cmd: vec![] };")
rep('"--wait" => a.wait_s = val().parse().unwrap_or(120),',
    '"--wait" => a.wait_s = val().parse().unwrap_or(0),\n            "--priority" => a.priority = val(),\n            "--what" => a.what = val(),')

rep('fn refuse(app: &str, name: &str, why: String) -> ! {', '''fn line_dir() -> PathBuf {
    home().join("run").join("line")
}

/// Everyone waiting for the model, in the order they will get it: questions (interactive) ahead
/// of long jobs, then first come first served. A ticket whose governor has gone is removed.
fn line(sys: &mut System) -> Vec<(String, Value)> {
    let mut out: Vec<(String, Value)> = vec![];
    let Ok(entries) = fs::read_dir(line_dir()) else { return out };
    sys.refresh_processes(ProcessesToUpdate::All, true);
    for e in entries.flatten() {
        let name = e.file_name().to_string_lossy().to_string();
        let Some(v) = fs::read_to_string(e.path()).ok().and_then(|s| serde_json::from_str::<Value>(&s).ok()) else {
            // half written, or left by a crash: gone after a few seconds
            let old = e.metadata().and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok());
            if old.map_or(false, |d| d > Duration::from_secs(5)) {
                let _ = fs::remove_file(e.path());
            }
            continue;
        };
        let pid = v.get("pid").and_then(Value::as_u64).unwrap_or(0) as u32;
        if pid == 0 || sys.process(Pid::from_u32(pid)).is_none() {
            let _ = fs::remove_file(e.path());
            continue;
        }
        out.push((name, v));
    }
    out.sort_by(|a, b| {
        let key = |x: &(String, Value)| (x.1["priority"] != "interactive", x.0.clone());
        key(a).cmp(&key(b))
    });
    out
}

fn now_ms() -> u128 {
    std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_millis()).unwrap_or(0)
}

fn refuse(app: &str, name: &str, why: String) -> ! {''')

a0 = s.index("    // One model at a time: take the lock, waiting for the current one to finish if need be.")
a1 = s.index("    let write_lock = |f: &mut fs::File")
s = s[:a0] + '''    // Whoever started us: if they go away (a cancelled question, a stopped job), so do we.
    sys.refresh_processes(ProcessesToUpdate::All, true);
    let parent = sys.process(Pid::from_u32(std::process::id())).and_then(|p| p.parent()).filter(|p| sys.process(*p).is_some());
    let caller_gone = |sys: &mut System| match parent {
        Some(p) => {
            sys.refresh_processes(ProcessesToUpdate::Some(&[p]), true);
            sys.process(p).is_none()
        }
        None => false,
    };
    // --hold-stdin: whoever started us keeps our stdin open for as long as it wants the model.
    // When that pipe closes (the caller is done, or died), the model is stopped, or the wait ends.
    let released = Arc::new(AtomicBool::new(false));
    if a.hold_stdin {
        let flag = released.clone();
        thread::spawn(move || {
            let mut buf = [0u8; 64];
            let mut stdin = std::io::stdin();
            while matches!(stdin.read(&mut buf), Ok(n) if n > 0) {}
            flag.store(true, Ordering::SeqCst);
        });
    }

    // One model at a time. Take a ticket and wait in line: the model goes to the head of the
    // line once it is free. Nobody is turned away for waiting unless --wait sets a limit.
    let _ = fs::create_dir_all(lock_path().parent().unwrap());
    let _ = fs::create_dir_all(line_dir());
    let ticket_name = format!("{:015}-{}.json", now_ms(), std::process::id());
    let ticket = line_dir().join(&ticket_name);
    let _ = fs::write(&ticket, json!({"pid": std::process::id(), "app": a.app, "name": a.name, "priority": a.priority,
                                      "what": a.what, "since": now_local().1, "since_ms": now_ms() as u64}).to_string());
    let started_wait = Instant::now();
    let mut waited = false;
    let mut lock = loop {
        let head = line(&mut sys).first().map(|t| t.0 == ticket_name).unwrap_or(true);
        if head && current_lease(&mut sys).is_none() {
            if let Ok(f) = fs::OpenOptions::new().write(true).create_new(true).open(lock_path()) {
                break f;
            }
        }
        if !waited {
            waited = true;
            log_event(&a.app, "model.wait", json!({"name": a.name, "priority": a.priority, "what": a.what}));
        }
        if released.load(Ordering::SeqCst) || caller_gone(&mut sys) {
            let _ = fs::remove_file(&ticket);
            log_event(&a.app, "model.wait_left", json!({"name": a.name, "waited_s": started_wait.elapsed().as_secs()}));
            exit(0);
        }
        if a.wait_s > 0 && started_wait.elapsed().as_secs() >= a.wait_s {
            let _ = fs::remove_file(&ticket);
            refuse(&a.app, &a.name, "another model is still running and one runs at a time.".into());
        }
        thread::sleep(Duration::from_millis(300));
    };
    let _ = fs::remove_file(&ticket);
    let waited_s = started_wait.elapsed().as_secs();
''' + s[a1:]

rep('''"est_mb": a.est_mb, "budget_mb": budget, "mb": mb, "peak_mb": peak,
                       "started": now_local().1});''', '''"est_mb": a.est_mb, "budget_mb": budget, "mb": mb, "peak_mb": peak,
                       "what": a.what, "priority": a.priority, "started": now_local().1});''')
rep('log_event(&a.app, "model.load", json!({"name": a.name, "est_mb": a.est_mb, "budget_mb": budget}));',
    'log_event(&a.app, "model.load", json!({"name": a.name, "est_mb": a.est_mb, "budget_mb": budget, "waited_s": waited_s}));')
b0 = s.index("    // --hold-stdin: whoever started us keeps our stdin open for as long as it wants the model.\n    // When that pipe closes (the caller is done, or died), the model is stopped.\n")
b1 = s.index("    let t0 = Instant::now();\n    let (mut peak")
s = s[:b0] + s[b1:]
rep('''        } else if released.load(Ordering::SeqCst) {
            Some((0, "released"))''', '''        } else if released.load(Ordering::SeqCst) {
            Some((0, "released"))
        } else if tick % 4 == 3 && caller_gone(&mut sys) {
            Some((1, "its caller is gone"))''')
rep('''            if code != 0 {
                eprintln!("[governor] stopped {}: {why}''', '''            if code == 137 || code == 124 {
                eprintln!("[governor] stopped {}: {why}''')
rep('''"budget_mb": l["budget_mb"], "busy": true, "idle_s": 0, "started": l["started"]})''',
    '''"budget_mb": l["budget_mb"], "busy": true, "idle_s": 0, "started": l["started"],
                   "what": l["what"], "priority": l["priority"]})''')
rep('''    let cpus = thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    println!("{}", json!({''', '''    let cpus = thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    let now = now_ms() as u64;
    let waiting: Vec<Value> = line(&mut sys).into_iter().map(|(_, t)| {
        json!({"app": t["app"], "name": t["name"], "priority": t["priority"], "what": t["what"], "since": t["since"],
               "waited_s": now.saturating_sub(t["since_ms"].as_u64().unwrap_or(now)) / 1000})
    }).collect();
    println!("{}", json!({''')
rep('"state": state, "leases": leases,', '"state": state, "leases": leases, "line": waiting,')
rep("[--wait S] [--hold-stdin] -- <command...>\\n", "[--wait S] [--priority P] [--what TEXT] [--hold-stdin] -- <command...>\\n")
f.write_text(s, "utf-8")
print("ok")
