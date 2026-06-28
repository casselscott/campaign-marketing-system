"""Thread-safe, campaign-isolated in-memory queue registry."""

import queue
import threading
from datetime import datetime, timezone


_campaign_queues = {}
_active_workers = {}
_manager_lock = threading.RLock()
_stats = {
    "processed": 0,
    "failed": 0,
    "enqueued": 0,
    "started_at": datetime.now(timezone.utc).isoformat(),
}
_campaign_stats = {}


def _now():
    return datetime.now(timezone.utc)


def get_queue(campaign_id):
    if campaign_id is None:
        raise ValueError("campaign_id is required for queue isolation")
    with _manager_lock:
        return _campaign_queues.setdefault(campaign_id, queue.Queue())


def enqueue(campaign_id, recipient):
    get_queue(campaign_id).put(recipient)
    with _manager_lock:
        _stats["enqueued"] += 1
        campaign = _campaign_stats.setdefault(campaign_id, {"processed": 0, "failed": 0, "enqueued": 0})
        campaign["enqueued"] += 1


def dequeue(campaign_id, block=False, timeout=None):
    q = get_queue(campaign_id)
    try:
        return q.get(block=block, timeout=timeout) if block else q.get_nowait()
    except queue.Empty:
        return None


def queue_size(campaign_id):
    return get_queue(campaign_id).qsize()


def queue_empty(campaign_id):
    return get_queue(campaign_id).empty()


def register_worker(campaign_id, worker):
    with _manager_lock:
        current = _active_workers.get(campaign_id)
        if current and (current["worker"].is_alive() or current["status"] == "starting"):
            return False
        now = _now()
        _active_workers[campaign_id] = {
            "worker": worker,
            "started": now,
            "heartbeat": now,
            "status": "starting",
        }
        return True


def launch_campaign_worker(worker):
    campaign_id = worker.campaign_id
    if not register_worker(campaign_id, worker):
        return False
    try:
        worker.start()
        mark_worker_status(campaign_id, "running")
        return True
    except Exception:
        unregister_worker(campaign_id, worker)
        raise


def unregister_worker(campaign_id, worker=None):
    with _manager_lock:
        current = _active_workers.get(campaign_id)
        if current and (worker is None or current["worker"] is worker):
            del _active_workers[campaign_id]


def mark_worker_status(campaign_id, status):
    with _manager_lock:
        if campaign_id in _active_workers:
            _active_workers[campaign_id]["status"] = status
            _active_workers[campaign_id]["heartbeat"] = _now()


def worker_heartbeat(campaign_id):
    with _manager_lock:
        if campaign_id in _active_workers:
            _active_workers[campaign_id]["heartbeat"] = _now()


def get_active_workers():
    workers = []
    with _manager_lock:
        for campaign_id, info in _active_workers.items():
            thread = info["worker"]
            workers.append({
                "campaign_id": campaign_id,
                "started": info["started"],
                "started_at": info["started"].isoformat(),
                "heartbeat": info["heartbeat"].isoformat(),
                "status": info["status"],
                "alive": thread.is_alive(),
                "queue_depth": _campaign_queues.get(campaign_id, queue.Queue()).qsize(),
            })
    return workers


def active_workers():
    return get_active_workers()


def increment_processed(campaign_id=None):
    with _manager_lock:
        _stats["processed"] += 1
        if campaign_id is not None:
            _campaign_stats.setdefault(campaign_id, {"processed": 0, "failed": 0, "enqueued": 0})["processed"] += 1


def increment_sent(campaign_id=None):
    increment_processed(campaign_id)


def increment_failed(campaign_id=None):
    with _manager_lock:
        _stats["failed"] += 1
        if campaign_id is not None:
            _campaign_stats.setdefault(campaign_id, {"processed": 0, "failed": 0, "enqueued": 0})["failed"] += 1


def queue_statistics(campaign_id=None):
    with _manager_lock:
        if campaign_id is not None:
            stats = dict(_campaign_stats.get(campaign_id, {"processed": 0, "failed": 0, "enqueued": 0}))
            stats.update({
                "queued": stats["enqueued"],
                "queue_depth": _campaign_queues.get(campaign_id, queue.Queue()).qsize(),
                "worker_active": campaign_id in _active_workers and _active_workers[campaign_id]["worker"].is_alive(),
            })
            return stats
        return {
            "processed": _stats["processed"],
            "failed": _stats["failed"],
            "queued": _stats["enqueued"],
            "queue_depth": sum(q.qsize() for q in _campaign_queues.values()),
            "workers": sum(1 for item in _active_workers.values() if item["worker"].is_alive()),
            "started_at": _stats["started_at"],
        }


def worker_status():
    stats = queue_statistics()
    workers = get_active_workers()
    return {
        "active_campaigns": sum(1 for worker in workers if worker["alive"]),
        "total_processed": stats["processed"],
        "total_failed": stats["failed"],
        "queue_depth": stats["queue_depth"],
        "started_at": stats["started_at"],
        "workers": workers,
    }


def stop_campaign_worker(campaign_id):
    with _manager_lock:
        info = _active_workers.get(campaign_id)
        if not info:
            return False
        stop = getattr(info["worker"], "stop", None)
        if stop:
            stop()
        info["status"] = "stopping"
        return True


def clear_campaign_queue(campaign_id):
    q = get_queue(campaign_id)
    while True:
        try:
            q.get_nowait()
            q.task_done()
        except queue.Empty:
            break


def campaign_overview():
    with _manager_lock:
        campaign_ids = set(_campaign_queues) | set(_active_workers)
    return [
        {
            "campaign": campaign_id,
            "queue": queue_size(campaign_id),
            "statistics": queue_statistics(campaign_id),
        }
        for campaign_id in sorted(campaign_ids)
    ]
