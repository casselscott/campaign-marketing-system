"""Campaign health, ETA, stalled detection, and restart recovery."""

from datetime import datetime, timezone

from app.core.queue_manager import (
    clear_campaign_queue,
    enqueue,
    get_active_workers,
    launch_campaign_worker,
    queue_statistics,
)
from app.core.worker import EmailWorker
from app.database.db import (
    get_all_campaigns,
    get_campaign_runtime_metrics,
    get_recoverable_campaigns,
    get_recovery_recipients,
    increment_recovery_count,
    update_recipient_status,
)
from app.utils.logger import logger


STALL_SECONDS = 180


def _parse_utc(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def get_campaign_health(campaign_id):
    metrics = get_campaign_runtime_metrics(campaign_id)
    if not metrics:
        return None
    workers = {worker["campaign_id"]: worker for worker in get_active_workers()}
    worker = workers.get(campaign_id)
    heartbeat = _parse_utc(metrics.get("worker_heartbeat"))
    heartbeat_age = (datetime.now(timezone.utc) - heartbeat).total_seconds() if heartbeat else None
    total = metrics.get("total_emails") or 0
    sent = metrics.get("sent_count") or 0
    failed = metrics.get("failed_count") or 0
    remaining = (metrics.get("unbatched") or 0) + (metrics.get("in_flight") or 0)
    throughput = round((metrics.get("sent_last_5m") or 0) / 5.0, 2)
    attempted = sent + failed
    failure_rate = failed / attempted if attempted else 0.0
    eta_minutes = round(remaining / throughput, 1) if throughput > 0 else None

    stalled = (
        metrics["status"] in {"sending", "recovering"}
        and (metrics.get("in_flight") or 0) > 0
        and (not worker or not worker["alive"] or (heartbeat_age is not None and heartbeat_age > STALL_SECONDS))
    )
    if stalled:
        health = "critical"
        recommendation = "Recover the campaign worker"
    elif failure_rate >= 0.20:
        health = "warning"
        recommendation = "Review SMTP failures before continuing"
    elif metrics["status"] == "completed":
        health = "healthy"
        recommendation = "Campaign completed"
    else:
        health = "healthy"
        recommendation = (
            "Ready for the next manual batch"
            if (metrics.get("unbatched") or 0) > 0 and not worker
            else "No action required"
        )

    return {
        "campaign_id": campaign_id,
        "name": metrics["name"],
        "status": metrics["status"],
        "health": health,
        "stalled": stalled,
        "worker_status": worker["status"] if worker else "stopped",
        "worker_alive": bool(worker and worker["alive"]),
        "heartbeat_age_seconds": round(heartbeat_age, 1) if heartbeat_age is not None else None,
        "queue_depth": queue_statistics(campaign_id)["queue_depth"],
        "remaining": remaining,
        "throughput_per_minute": throughput,
        "eta_minutes": eta_minutes,
        "success_rate": round(sent / attempted * 100, 1) if attempted else 0.0,
        "failure_rate": round(failure_rate * 100, 1),
        "recovery_count": metrics.get("recovery_count") or 0,
        "recommendation": recommendation,
    }


def get_system_health():
    campaigns = [get_campaign_health(row["id"]) for row in get_all_campaigns()]
    campaigns = [item for item in campaigns if item]
    active = [item for item in campaigns if item["status"] not in {"completed", "cancelled"}]
    if any(item["health"] == "critical" for item in active):
        health = "critical"
    elif any(item["health"] == "warning" for item in active):
        health = "warning"
    else:
        health = "healthy"
    return {
        "health": health,
        "campaigns": campaigns,
        "active_campaigns": len(active),
        "stalled_campaigns": sum(item["stalled"] for item in active),
        "queue_depth": queue_statistics()["queue_depth"],
    }


def recover_campaign(campaign_id):
    metrics = get_campaign_runtime_metrics(campaign_id)
    if not metrics:
        return False
    if any(w["campaign_id"] == campaign_id and w["alive"] for w in get_active_workers()):
        return False
    recipients = get_recovery_recipients(campaign_id)
    if not recipients:
        return False

    clear_campaign_queue(campaign_id)
    for recipient in recipients:
        update_recipient_status(
            recipient["work_email"], "pending", campaign_id=campaign_id,
            recipient_id=recipient["id"],
        )
        recipient["status"] = "pending"
        enqueue(campaign_id, recipient)
    increment_recovery_count(campaign_id)
    launched = launch_campaign_worker(EmailWorker(
        campaign_id, metrics["subject"],
        template_name=metrics.get("template_name") or "campaign.html",
    ))
    if launched:
        logger.info("Recovered campaign %s with %s pending recipients", campaign_id, len(recipients))
    return launched


def recover_incomplete_campaigns():
    recovered = []
    for campaign in get_recoverable_campaigns():
        try:
            if recover_campaign(campaign["id"]):
                recovered.append(campaign["id"])
        except Exception:
            logger.exception("Automatic recovery failed for campaign %s", campaign["id"])
    return recovered
