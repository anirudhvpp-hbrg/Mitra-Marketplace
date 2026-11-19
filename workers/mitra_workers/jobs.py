"""Long-running work. The gateway starts the worker detached and the browser polls the job file."""
import json
import time

from . import memory, paths


class Job:
    def __init__(self, job_id: str, app: str):
        self.id, self.app = job_id, app
        self.file = paths.HOME / "run" / "jobs" / f"{job_id}.json"
        self.state = {"id": job_id, "status": "running", "steps": [], "result": None, "error": None, "started": time.time()}
        self.save()

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False, default=str), "utf-8")
        paths.replace(tmp, self.file)

    def step(self, stage: str, status: str, note: str = ""):
        for s in self.state["steps"]:
            if s["stage"] == stage:
                s.update(status=status, note=note)
                break
        else:
            self.state["steps"].append({"stage": stage, "status": status, "note": note})
        self.save()

    def finish(self, result=None, error=None):
        self.state.update(status="failed" if error else "done", result=result, error=error,
                          seconds=round(time.time() - self.state["started"], 1))
        self.save()
        memory.log(self.app, "job.finish", {"status": self.state["status"], "seconds": self.state["seconds"]})
