"""0.9.0 fixes found when the person used Mitra during the first long run (2026-11-14):

1. Stopping the model by hand (System page "Stop", or closing the app) was reported to the job as an
   ordinary model failure, so TwinMind dropped the speakers and carried on to the next stage. Now the
   governor ends with its own code (143, "stopped by hand"), the worker raises models.Stopped, and
   the job stops with its pieces kept.
2. Closing an app that had a job at work ended the app but left the job's worker running with no app,
   and it went on to the next recording in the line. Now closing the app stops its job workers first.
Run once from the project root: python logs/scripts/apply_stop_fixes.py
"""
from pathlib import Path


def patch(path, edits):
    f = Path(path)
    s = f.read_text("utf-8")
    for a, b in edits:
        assert s.count(a) == 1, (path, s.count(a), a[:70])
        s = s.replace(a, b)
    f.write_text(s, "utf-8")


# ---- governor: a stop by hand is its own outcome
patch("governor/src/main.rs", [
    ("//! Exit codes: the child's own, or 75 refused, 124 timed out, 137 killed over budget.",
     "//! Exit codes: the child's own, or 75 refused, 124 timed out, 137 killed over budget,\n//! 143 stopped by hand (`mitra-governor kill`, the System page, or its app being closed)."),
    ("fn line_dir() -> PathBuf {",
     '''/// `kill` leaves this note for the governor that holds the model, so that governor can say the
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

fn line_dir() -> PathBuf {'''),
    ('''        if let Ok(Some(status)) = child.try_wait() {
            break (status.code().unwrap_or(1), "exit");
        }''',
     '''        if let Ok(Some(status)) = child.try_wait() {
            if stopped_by_hand() {
                break (143, "stopped by hand");
            }
            break (status.code().unwrap_or(1), "exit");
        }'''),
    ('''            let child = l.get("child_pid").and_then(Value::as_u64).unwrap_or(0) as u32;
            if child > 0 {
                kill_tree(&mut sys, Pid::from_u32(child));
            }
            log_event("governor", "governor.evict"''',
     '''            let child = l.get("child_pid").and_then(Value::as_u64).unwrap_or(0) as u32;
            let _ = fs::write(stop_note(), l.get("governor_pid").and_then(Value::as_u64).unwrap_or(0).to_string());
            if child > 0 {
                kill_tree(&mut sys, Pid::from_u32(child));
            }
            log_event("governor", "governor.evict"'''),
])

# ---- workers: Stopped
patch("workers/mitra_workers/models.py", [
    ("class MemoryDenied(Exception):\n    pass\n",
     "class MemoryDenied(Exception):\n    pass\n\n\nclass Stopped(Exception):\n"
     "    \"\"\"The model was stopped by hand: from the System page, or because its app was closed.\"\"\"\n"),
    ("    if code in (75, 137):\n",
     "    if code == 143:\n        raise Stopped(\"The model was stopped by hand before it finished.\")\n    if code in (75, 137):\n"),
    ("            if self.proc.poll() is not None:  # the governor stopped it mid-answer\n",
     "            try:\n                self.proc.wait(timeout=3)     # give the governor a moment to report why the model went away\n"
     "            except Exception:\n                pass\n"
     "            if self.proc.poll() is not None:  # the governor stopped it mid-answer\n"),
])
patch("workers/mitra_workers/dispatch.py", [
    ("    except models.MemoryDenied as e:\n        return 507, {\"detail\": str(e)}\n",
     "    except models.MemoryDenied as e:\n        return 507, {\"detail\": str(e)}\n"
     "    except models.Stopped as e:\n        return 409, {\"detail\": str(e)}\n"),
])
patch("apps/twinmind/worker.py", [
    ("        except work.Paused:\n            raise\n        except models.ModelUnavailable as e:\n            stages[\"diarize\"]",
     "        except (work.Paused, models.Stopped):\n            raise\n        except models.ModelUnavailable as e:\n            stages[\"diarize\"]"),
    ("            except Exception as e:\n                if w:\n                    w.note(state=\"failed\", why=str(e)[:300], pid=0)",
     "            except models.Stopped:\n"
     "                # Stopped by hand. The pieces are kept, and the line waits, as with a pause.\n"
     "                w.note(state=\"stopped\", why=\"The model was stopped by hand.\", pid=0)\n"
     "                job.state.update(status=\"stopped\", seconds=round(time.time() - job.state[\"started\"], 1))\n"
     "                job.save()\n"
     "                memory.log(\"twinmind\", \"job.stopped\", {\"how\": \"model stopped by hand\", \"progress\": w.meta.get(\"progress\")})\n"
     "                return None\n"
     "            except Exception as e:\n                if w:\n                    w.note(state=\"failed\", why=str(e)[:300], pid=0)"),
])

# ---- gateway: closing an app stops its job workers first
patch("gateway/main.go", [
    ("\tactiveJobs.Add(1)\n\tgo func() {\n\t\tcmd.Wait()\n\t\tlogf.Close()\n\t\tactiveJobs.Add(-1)\n",
     "\tactiveJobs.Add(1)\n\tjobMu.Lock()\n\tjobProcs[id] = cmd.Process\n\tjobMu.Unlock()\n"
     "\tgo func() {\n\t\tcmd.Wait()\n\t\tlogf.Close()\n\t\tjobMu.Lock()\n\t\tdelete(jobProcs, id)\n\t\tjobMu.Unlock()\n\t\tactiveJobs.Add(-1)\n"),
    ("// A job is a worker that keeps running after the request returns; the browser polls its file.\n",
     '''// The job workers this process started and that are still at work.
var (
	jobMu    sync.Mutex
	jobProcs = map[string]*os.Process{}
)

// stopJobs ends every job this process started: used when the app itself is told to close, so no
// worker is left running with no app. What each job had finished stays on disk and can be resumed.
func stopJobs() {
	jobMu.Lock()
	defer jobMu.Unlock()
	for id, p := range jobProcs {
		p.Kill()
		f := filepath.Join(home, "run", "jobs", id+".json")
		var j map[string]any
		if b, err := os.ReadFile(f); err == nil && json.Unmarshal(b, &j) == nil && (j["status"] == "running" || j["status"] == nil) {
			j["status"] = "stopped"
			if b, err := json.Marshal(j); err == nil {
				os.WriteFile(f, b, 0o644)
			}
		}
		logEvent(appMode, "job.stopped", map[string]any{"job": id, "how": "its app was closed"}, "")
	}
}

// A job is a worker that keeps running after the request returns; the browser polls its file.
'''),
])
patch("gateway/apps.go", [
    ("\t\twho = appMode\n\t\t// stop a model only if it is this app's; another app's model is not ours to stop\n",
     "\t\twho = appMode\n\t\tstopJobs() // before the model: a worker left alive would only start the next piece\n"
     "\t\t// stop a model only if it is this app's; another app's model is not ours to stop\n"),
])
print("ok")
