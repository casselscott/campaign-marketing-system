"""
queue_manager.py

Replaces Celery + Redis with a Python in-process queue.
Exposes the same get_queue() interface the original code used,
plus a singleton QueueManager with a background daemon thread.

The original code called:
    queue = get_queue()
    queue.put(recipient_data)
    queue.get()

That API is preserved exactly so the worker is a minimal change.
"""
import queue
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional


# -----------------------------------
# SIMPLE QUEUE (original interface)
# -----------------------------------

_email_queue: queue.Queue = queue.Queue()


def get_queue() -> queue.Queue:
    """
    Returns the global email queue.
    Identical to the original queue_manager interface.
    """
    return _email_queue


def add_to_queue(recipient_data: dict):
    """
    Push a recipient dict onto the queue.
    Identical to the original add_to_queue().
    """
    _email_queue.put(recipient_data)


# -----------------------------------
# CAMPAIGN QUEUE MANAGER (singleton)
# -----------------------------------

_manager_lock = threading.Lock()
_active_workers: Dict[int, "CampaignWorkerHandle"] = {}

_stats = {
    "total_processed": 0,
    "total_failed": 0,
    "started_at": datetime.utcnow().isoformat(),
}


class CampaignWorkerHandle:
    """Tracks a running EmailWorker thread."""

    def __init__(self, campaign_id: int, thread: threading.Thread):
        self.campaign_id = campaign_id
        self.thread = thread
        self.started_at = datetime.utcnow().isoformat()

    def is_alive(self) -> bool:
        return self.thread.is_alive()


def launch_campaign_worker(worker_instance) -> threading.Thread:
    """
    Start an EmailWorker (from worker.py) in a daemon thread.
    Registers it in the active workers map.
    Returns the thread.
    """
    campaign_id = worker_instance.campaign_id

    thread = threading.Thread(
        target=worker_instance.run,
        daemon=True,
        name=f"EmailWorker-{campaign_id}",
    )
    thread.start()

    with _manager_lock:
        _active_workers[campaign_id] = CampaignWorkerHandle(campaign_id, thread)

    return thread


def get_active_workers() -> List[Dict]:
    """Return status of all tracked workers."""
    with _manager_lock:
        # Clean finished workers
        finished = [
            cid for cid, h in _active_workers.items()
            if not h.is_alive()
        ]
        for cid in finished:
            del _active_workers[cid]

        return [
            {
                "campaign_id": h.campaign_id,
                "started_at":  h.started_at,
                "alive":       h.is_alive(),
            }
            for h in _active_workers.values()
        ]


def worker_status() -> Dict:
    """High-level status for the Settings / Dashboard pages."""
    workers = get_active_workers()
    return {
        "active_campaigns":  len(workers),
        "workers":           workers,
        "total_processed":   _stats["total_processed"],
        "total_failed":      _stats["total_failed"],
        "started_at":        _stats["started_at"],
    }


def increment_processed():
    _stats["total_processed"] += 1


def increment_failed():
    _stats["total_failed"] += 1
