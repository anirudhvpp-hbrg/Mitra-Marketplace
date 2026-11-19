//! mitra-governor: the one manager that keeps local models from clogging the machine.
//!
//!   mitra-governor run --app A --name N --est-mb E [--budget-mb B] [--timeout S] [--wait S]
//!                      [--priority interactive|background] [--what TEXT] [--hold-stdin] -- <command...>
//!   mitra-governor status        JSON: RAM, the model running now, limits
//!   mitra-governor kill          stop the model running now
//!
//! `run` is the only way a model process starts. It refuses the load if the estimate exceeds
//! the model budget or would eat into the free-RAM reserve, allows one model at a time (a lock
//! file, and a line of tickets for those waiting: questions first, then first come first served), measures the real memory of the whole process tree twice a second, kills it if it
//! goes over budget or over time, and writes what happened to the memory log. It exists only
//! while a model is running; when nothing is loaded, nothing of Mitra's model stack is in RAM.
//!
//! Exit codes: the child's own, or 75 refused, 124 timed out, 137 killed over budget,
//! 143 stopped by hand (`mitra-governor kill`, the System page, or its app being closed).

use serde_json::{json, Value};
use std::io::{Read, Write};
use std::path::PathBuf;
use std::process::{exit, Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use std::{env, fs, thread};
use sysinfo::{Pid, ProcessesToUpdate, System};

const MB: u64 = 1024 * 1024;

fn home() -> PathBuf {
    if let Ok(h) = env::var("MITRA_HOME") {
        return PathBuf::from(h);
    }
    let base = env::var("USERPROFILE").or_else(|_| env::var("HOME")).unwrap_or_else(|_| ".".into());
    PathBuf::from(base).join(".mitra")
}

fn config() -> Value {
    fs::read_to_string(home().join("config.json"))
        .ok()
        .and_then(|s| serde_json::from_str(&s).ok())
        .unwrap_or_else(|| json!({}))
}

fn cfg(c: &Value, key: &str, default: u64) -> u64 {
    c.get(key).and_then(Value::as_u64).unwrap_or(default)
}

/// (total_mb, available_mb)
fn ram(sys: &mut System) -> (u64, u64) {
    sys.refresh_memory();
    (sys.total_memory() / MB, sys.available_memory() / MB)
}

/// Local wall-clock time as (date "YYYY-MM-DD", timestamp "YYYY-MM-DDTHH:MM:SS").
/// The standard library has no time zones, so the caller passes its UTC offset in
/// MITRA_TZ_OFFSET_MIN (the gateway and workers always do); without it, UTC is used.
fn now_local() -> (String, String) {
    let offset: i64 = env::var("MITRA_TZ_OFFSET_MIN").ok().and_then(|s| s.parse().ok()).unwrap_or(0);
    let secs = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).map(|d| d.as_secs() as i64).unwrap_or(0) + offset * 60;
    let (days, rem) = (secs.div_euclid(86400), secs.rem_euclid(86400));
    // civil-from-days (Howard Hinnant)
    let z = days + 719468;
    let era = z.div_euclid(146097);
    let doe = z.rem_euclid(146097);
    let yoe = (doe - doe / 1460 + doe / 36524 - doe / 146096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let d = doy - (153 * mp + 2) / 5 + 1;
    let m = if mp < 10 { mp + 3 } else { mp - 9 };
    let y = yoe + era * 400 + if m <= 2 { 1 } else { 0 };
    let date = format!("{y:04}-{m:02}-{d:02}");
    let ts = format!("{date}T{:02}:{:02}:{:02}", rem / 3600, rem % 3600 / 60, rem % 60);
    (date, ts)
}

fn log_event(app: &str, kind: &str, data: Value) {
    let (date, ts) = now_local();
    let dir = home().join("memory").join("events");
    let _ = fs::create_dir_all(&dir);
    let line = json!({"ts": ts, "app": app, "type": kind, "data": data});
    if let Ok(mut f) = fs::OpenOptions::new().create(true).append(true).open(dir.join(format!("{date}.jsonl"))) {
        let _ = writeln!(f, "{}", line);
    }
}

fn tree(sys: &System, root: Pid) -> Vec<Pid> {
    let mut all = vec![root];
    let mut i = 0;
    while i < all.len() {
        let parent = all[i];
        for (pid, p) in sys.processes() {
            if p.parent() == Some(parent) && !all.contains(pid) {
                all.push(*pid);
            }
        }
        i += 1;
    }
    all
}

fn tree_rss_mb(sys: &mut System, root: Pid) -> u64 {
    sys.refresh_processes(ProcessesToUpdate::All, true);
    tree(sys, root).iter().filter_map(|p| sys.process(*p)).map(|p| p.memory()).sum::<u64>() / MB
}

fn kill_tree(sys: &mut System, root: Pid) {
    sys.refresh_processes(ProcessesToUpdate::All, true);
    for pid in tree(sys, root).iter().rev() {
        if let Some(p) = sys.process(*pid) {
            p.kill();
        }
    }
}

fn lock_path() -> PathBuf {
    home().join("run").join("model.lock")
}

/// The lease currently held, if its governor is still alive. A stale lock is removed.
fn current_lease(sys: &mut System) -> Option<Value> {
    let path = lock_path();
    let text = fs::read_to_string(&path).ok()?;
    let v: Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => {
            // being written right now, or left behind by a crash long ago
            let old = fs::metadata(&path).and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok());
            if old.map_or(false, |d| d > Duration::from_secs(5)) {
                let _ = fs::remove_file(&path);
                return None;
            }
            return Some(json!({"name": "starting", "app": "", "governor_pid": 0}));
        }
    };
    let gpid = v.get("governor_pid").and_then(Value::as_u64).unwrap_or(0) as u32;
    sys.refresh_processes(ProcessesToUpdate::All, true);
    if gpid == 0 || sys.process(Pid::from_u32(gpid)).is_none() {
        let _ = fs::remove_file(&path);
        return None;
    }
    Some(v)
}

/// `kill` leaves this note for the governor that holds the model, so that governor can say the
/// model was stopped by hand and not that it failed.
fn stop_note() -> PathBuf {
    home().join("run").join("model.stop")
}

fn stopped_by_hand() -> bool {
    let mine = fs::read_to_string(stop_note()).map_or(false, |s| s.trim() == std::process::id().to_string());
    if mine {
        let _ = fs::remove_file(stop_note());
    }
    mine
}

fn line_dir() -> PathBuf {
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

fn refuse(app: &str, name: &str, why: String) -> ! {
    eprintln!("[governor] refused {name}: {why}");
    log_event(app, "governor.denied", json!({"name": name, "why": why}));
    exit(75);
}

struct Args {
    app: String,
    name: String,
    est_mb: u64,
    budget_mb: Option<u64>,
    timeout_s: u64,
    wait_s: u64,
    hold_stdin: bool,
    priority: String,
    what: String,
    cmd: Vec<String>,
}

fn parse(mut it: impl Iterator<Item = String>) -> Args {
    let mut a = Args { app: "unknown".into(), name: "model".into(), est_mb: 0, budget_mb: None,
                       timeout_s: 3600, wait_s: 0, hold_stdin: false,
                       priority: "background".into(), what: String::new(), cmd: vec![] };
    while let Some(arg) = it.next() {
        let mut val = || it.next().unwrap_or_default();
        match arg.as_str() {
            "--app" => a.app = val(),
            "--name" => a.name = val(),
            "--est-mb" => a.est_mb = val().parse().unwrap_or(0),
            "--budget-mb" => a.budget_mb = val().parse().ok(),
            "--timeout" => a.timeout_s = val().parse().unwrap_or(3600),
            "--wait" => a.wait_s = val().parse().unwrap_or(0),
            "--priority" => a.priority = val(),
            "--what" => a.what = val(),
            "--hold-stdin" => a.hold_stdin = true,
            "--" => {
                a.cmd = it.collect();
                break;
            }
            other => {
                eprintln!("[governor] unknown argument {other}");
                exit(2);
            }
        }
    }
    if a.cmd.is_empty() {
        eprintln!("[governor] nothing to run; put the command after --");
        exit(2);
    }
    a
}

fn run(a: Args) -> ! {
    let c = config();
    let mut sys = System::new();
    let budget = a.budget_mb.unwrap_or_else(|| cfg(&c, "model_budget_mb", 1024));
    let reserve = cfg(&c, "reserve_mb", 800);

    if a.est_mb > budget {
        refuse(&a.app, &a.name, format!("it needs about {} MB and the model budget is {} MB.", a.est_mb, budget));
    }

    // Whoever started us: if they go away (a cancelled question, a stopped job), so do we.
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
    let write_lock = |f: &mut fs::File, child: u32, mb: u64, peak: u64| {
        let v = json!({"governor_pid": std::process::id(), "child_pid": child, "name": a.name, "app": a.app,
                       "est_mb": a.est_mb, "budget_mb": budget, "mb": mb, "peak_mb": peak,
                       "what": a.what, "priority": a.priority, "started": now_local().1});
        // rewrite in place: the file stays ours for the whole run
        use std::io::Seek;
        let _ = f.set_len(0);
        let _ = f.seek(std::io::SeekFrom::Start(0));
        let _ = f.write_all(v.to_string().as_bytes());
        let _ = f.flush();
    };
    write_lock(&mut lock, 0, 0, 0);
    let unlock = || {
        let _ = fs::remove_file(lock_path());
    };

    let (_, avail) = ram(&mut sys);
    if avail < a.est_mb + reserve {
        unlock();
        refuse(&a.app, &a.name, format!("{avail} MB is free; it needs about {} MB and {reserve} MB must stay in reserve.", a.est_mb));
    }

    let mut command = low_priority_command(&a.cmd);
    if a.hold_stdin {
        command.stdin(Stdio::null());
    }
    let mut child = match command.spawn() {
        Ok(ch) => ch,
        Err(e) => {
            unlock();
            eprintln!("[governor] could not start {}: {e}", a.cmd[0]);
            log_event(&a.app, "error", json!({"msg": format!("could not start {}: {e}", a.cmd[0])}));
            exit(127);
        }
    };
    let root = Pid::from_u32(child.id());
    log_event(&a.app, "model.load", json!({"name": a.name, "est_mb": a.est_mb, "budget_mb": budget, "waited_s": waited_s}));

    let t0 = Instant::now();
    let (mut peak, mut over, mut tick) = (0u64, 0u32, 0u32);
    let (code, reason): (i32, &str) = loop {
        if let Ok(Some(status)) = child.try_wait() {
            if stopped_by_hand() {
                break (143, "stopped by hand");
            }
            break (status.code().unwrap_or(1), "exit");
        }
        let rss = tree_rss_mb(&mut sys, root);
        peak = peak.max(rss);
        over = if rss > budget + budget / 10 { over + 1 } else { 0 };
        let (_, free) = ram(&mut sys);
        let stop = if over >= 3 {
            Some((137, "over budget"))
        } else if free < reserve / 3 {
            Some((137, "system RAM critically low"))
        } else if t0.elapsed().as_secs() > a.timeout_s {
            Some((124, "timeout"))
        } else if released.load(Ordering::SeqCst) {
            Some((0, "released"))
        } else if tick % 4 == 3 && caller_gone(&mut sys) {
            Some((1, "its caller is gone"))
        } else {
            None
        };
        if let Some((code, why)) = stop {
            kill_tree(&mut sys, root);
            let _ = child.wait();
            if code == 137 || code == 124 {
                eprintln!("[governor] stopped {}: {why} ({rss} MB used, budget {budget} MB)", a.name);
                log_event("governor", "governor.evict", json!({"name": a.name, "apps": [a.app], "reason": why, "mb": rss}));
            }
            break (code, why);
        }
        if tick % 4 == 0 {
            write_lock(&mut lock, child.id(), rss, peak);
        }
        tick += 1;
        thread::sleep(Duration::from_millis(500));
    };
    drop(lock);
    unlock();
    log_event(&a.app, "model.run", json!({"name": a.name, "ms": t0.elapsed().as_millis() as u64, "peak_mb": peak,
                                          "budget_mb": budget, "exit": code, "end": reason}));
    exit(code);
}

/// Models run below normal priority, so the browser and everything else you are using get
/// the CPU first and the machine stays responsive while a model works.
#[cfg(windows)]
fn low_priority_command(cmd: &[String]) -> Command {
    use std::os::windows::process::CommandExt;
    const BELOW_NORMAL_PRIORITY_CLASS: u32 = 0x0000_4000;
    let mut c = Command::new(&cmd[0]);
    c.args(&cmd[1..]).creation_flags(BELOW_NORMAL_PRIORITY_CLASS);
    c
}

#[cfg(not(windows))]
fn low_priority_command(cmd: &[String]) -> Command {
    let has_nice = env::var_os("PATH")
        .map(|p| env::split_paths(&p).any(|d| d.join("nice").is_file()))
        .unwrap_or(false);
    if has_nice {
        let mut c = Command::new("nice"); // nice replaces itself with the model, so the pid is the model's
        c.args(["-n", "10"]).args(cmd);
        c
    } else {
        let mut c = Command::new(&cmd[0]);
        c.args(&cmd[1..]);
        c
    }
}

/// Remove files in `dir` older than `max_age`; returns (bytes freed, files removed).
fn clean(dir: PathBuf, max_age: Duration) -> (u64, u64) {
    let (mut bytes, mut files) = (0, 0);
    if let Ok(entries) = fs::read_dir(dir) {
        for e in entries.flatten() {
            let Ok(meta) = e.metadata() else { continue };
            let old = meta.modified().ok().and_then(|t| t.elapsed().ok()).map_or(false, |d| d > max_age);
            if meta.is_file() && old && fs::remove_file(e.path()).is_ok() {
                bytes += meta.len();
                files += 1;
            }
        }
    }
    (bytes, files)
}

/// Housekeeping, so Mitra's own footprint on disk stays small: temporary conversions and
/// uploads older than a day, finished job files older than a week, an oversized server log,
/// replaced binaries left by an update, and a model lock left behind by a crash.
fn optimize() {
    let h = home();
    let day = Duration::from_secs(86400);
    let (b1, f1) = clean(h.join("tmp"), day);
    let (b2, f2) = clean(h.join("run").join("jobs"), day * 7);
    let (mut bytes, mut files) = (b1 + b2, f1 + f2);
    if let Ok(root) = env::var("MITRA_ROOT") {
        if let Ok(entries) = fs::read_dir(PathBuf::from(root).join("bin")) {
            for e in entries.flatten() {
                if e.path().extension().map_or(false, |x| x == "old") {
                    let len = e.metadata().map(|m| m.len()).unwrap_or(0);
                    if fs::remove_file(e.path()).is_ok() {
                        bytes += len;
                        files += 1;
                    }
                }
            }
        }
    }
    let log = h.join("server.log");
    let mut rotated = false;
    if fs::metadata(&log).map_or(false, |m| m.len() > 5 * MB) {
        rotated = fs::rename(&log, h.join("server.log.1")).is_ok();
    }
    let mut sys = System::new();
    let had_lock = lock_path().exists();
    let lease = current_lease(&mut sys); // also clears a stale lock
    let stale_lock_cleared = had_lock && lease.is_none();
    let (total, avail) = ram(&mut sys);
    let out = json!({"files_removed": files, "freed_kb": bytes / 1024, "log_rotated": rotated,
                     "stale_lock_cleared": stale_lock_cleared, "model_running": lease.is_some(),
                     "ram_free_mb": avail, "ram_total_mb": total});
    log_event("governor", "optimizer.run", out.clone());
    println!("{out}");
}

fn status() {
    let c = config();
    let mut sys = System::new();
    let (total, avail) = ram(&mut sys);
    let pct = ((total - avail.min(total)) as f64 * 1000.0 / total.max(1) as f64).round() / 10.0;
    let reserve = cfg(&c, "reserve_mb", 800);
    let state = if avail < reserve { "hard" } else if avail < reserve * 2 { "soft" } else { "ok" };
    let leases: Vec<Value> = current_lease(&mut sys)
        .map(|l| {
            let child = l.get("child_pid").and_then(Value::as_u64).unwrap_or(0) as u32;
            let mb = if child > 0 { tree_rss_mb(&mut sys, Pid::from_u32(child)) } else { 0 };
            json!({"key": "model", "name": l["name"], "apps": [l["app"]], "mb": mb, "peak_mb": l["peak_mb"],
                   "budget_mb": l["budget_mb"], "busy": true, "idle_s": 0, "started": l["started"],
                   "what": l["what"], "priority": l["priority"]})
        })
        .into_iter()
        .collect();
    let cpus = thread::available_parallelism().map(|n| n.get()).unwrap_or(4);
    let now = now_ms() as u64;
    let waiting: Vec<Value> = line(&mut sys).into_iter().map(|(_, t)| {
        json!({"app": t["app"], "name": t["name"], "priority": t["priority"], "what": t["what"], "since": t["since"],
               "waited_s": now.saturating_sub(t["since_ms"].as_u64().unwrap_or(now)) / 1000})
    }).collect();
    println!("{}", json!({
        "ram": {"total_mb": total, "used_mb": total - avail.min(total), "free_mb": avail, "pct": pct},
        "state": state, "leases": leases, "line": waiting,
        "limits": {"model_budget_mb": cfg(&c, "model_budget_mb", 1024), "reserve_mb": reserve, "max_models": 1,
                   "threads": cfg(&c, "threads", (cpus / 2).max(1) as u64)},
        "cpus": cpus, "os": env::consts::OS, "arch": env::consts::ARCH
    }));
}

fn kill() {
    let mut sys = System::new();
    match current_lease(&mut sys) {
        Some(l) => {
            let child = l.get("child_pid").and_then(Value::as_u64).unwrap_or(0) as u32;
            let _ = fs::write(stop_note(), l.get("governor_pid").and_then(Value::as_u64).unwrap_or(0).to_string());
            if child > 0 {
                kill_tree(&mut sys, Pid::from_u32(child));
            }
            log_event("governor", "governor.evict", json!({"name": l["name"], "apps": [l["app"]], "reason": "manual"}));
            println!("{}", json!({"evicted": true, "name": l["name"]}));
        }
        None => println!("{}", json!({"evicted": false})),
    }
}

fn main() {
    let mut args = env::args().skip(1);
    match args.next().as_deref() {
        Some("run") => run(parse(args)),
        Some("status") => status(),
        Some("kill") => kill(),
        Some("optimize") => optimize(),
        _ => {
            eprintln!("usage: mitra-governor run --app A --name N --est-mb E [--budget-mb B] [--timeout S] [--wait S] [--priority P] [--what TEXT] [--hold-stdin] -- <command...>\n       mitra-governor status | kill | optimize");
            exit(2);
        }
    }
}
