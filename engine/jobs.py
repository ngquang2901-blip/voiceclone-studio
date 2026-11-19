"""Background jobs: one GPU lane (models cannot share a 6 GB card) and one lane for downloads."""
import threading, time, traceback, uuid
from concurrent.futures import ThreadPoolExecutor

_jobs: dict[str, "Job"] = {}
_lock = threading.Lock()
_lanes = {"gpu": ThreadPoolExecutor(1, thread_name_prefix="gpu"), "io": ThreadPoolExecutor(2, thread_name_prefix="io")}


class JobError(Exception):
    def __init__(self, code, message):
        super().__init__(message); self.code, self.message = code, message


class Job:
    def __init__(self, kind):
        self.id, self.kind, self.created = uuid.uuid4().hex[:12], kind, time.time()
        self.status, self.progress, self.message, self.result, self.error = "queued", 0.0, "Đang chờ…", None, None

    def update(self, progress=None, message=None):
        if progress is not None: self.progress = max(0.0, min(1.0, float(progress)))
        if message is not None: self.message = message

    def view(self):
        return {k: getattr(self, k) for k in ("id", "kind", "status", "progress", "message", "result", "error", "created")}


def start(kind, fn, *args, lane="gpu"):
    job = Job(kind)
    with _lock:
        _jobs[job.id] = job
        for old in sorted(_jobs.values(), key=lambda j: j.created)[:-200]: _jobs.pop(old.id, None)

    def run():
        job.status, job.message = "running", "Đang chạy…"
        try:
            job.result = fn(job, *args); job.status, job.progress, job.message = "done", 1.0, "Xong"
        except JobError as e:
            job.status, job.error, job.message = "error", {"error": e.code, "message": e.message}, e.message
        except Exception as e:  # keep the engine alive; the person sees what failed
            traceback.print_exc()
            job.status, job.error, job.message = "error", {"error": "internal", "message": f"Lỗi: {e}"}, f"Lỗi: {e}"
    _lanes[lane].submit(run)
    return {"job_id": job.id}


def get(job_id):
    return _jobs.get(job_id)


def recent(limit=20):
    return [j.view() for j in sorted(_jobs.values(), key=lambda j: j.created, reverse=True)[:limit]]
