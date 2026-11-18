"""Real notification event handling and scheduled dispatch."""
import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import select, func
from app.models.automation_jobs import NotificationAutomationRule as Rule
from app.models.user import User
from app.models.notification import UserNotification
from app.services.automation_queue import enqueue


async def record_event(db, company_id, actor_id, event, event_key):
    rules = (await db.scalars(select(Rule).where(Rule.company_id == company_id,
        Rule.trigger_event == event, Rule.is_enabled.is_(True)))).all()
    for rule in rules:
        await enqueue(db, company_id=company_id, actor_id=actor_id, kind="notification",
                      key=f"{rule.id}:{event_key}"[:200], rule_id=rule.id, payload={},
                      delay=rule.configuration.get("delay_minutes", 0))


async def schedule_due(db):
    now = datetime.now(timezone.utc)
    rules = (await db.scalars(select(Rule).where(Rule.is_enabled.is_(True),
        Rule.next_run_at <= now).with_for_update(skip_locked=True).limit(100))).all()
    for rule in rules:
        await enqueue(db, company_id=rule.company_id, actor_id=rule.created_by,
            kind="notification", key=f"{rule.id}:{rule.next_run_at.isoformat()}", rule_id=rule.id, payload={})
        rule.next_run_at = now + timedelta(minutes=rule.interval_minutes) if rule.interval_minutes else None


async def execute_notification(db, job):
    from app.services.notification_service import notify
    rule = await db.scalar(select(Rule).where(Rule.id == job.rule_id, Rule.company_id == job.company_id))
    if not rule:
        raise LookupError("Automation rule no longer exists")
    if not rule.is_enabled and not job.payload.get("test"):
        return {"skipped": True, "reason": "rule_disabled", "delivered": 0}
    recipients = job.payload.get("recipient_ids") or rule.configuration["recipients"]
    query = select(User.id).where(User.company_id == job.company_id, User.is_active.is_(True), User.is_deleted.is_(False))
    if "ALL_EMPLOYEES" not in recipients:
        query = query.where(User.id.in_([uuid.UUID(value) for value in recipients]))
    else:
        query = query.where(User.role == "employee")
    users = (await db.scalars(query)).all()
    if not users:
        return {"delivered": 0, "reason": "no_authorized_recipients"}
    key = f"automation:{job.id}"
    await notify(db, company_id=job.company_id, recipient_ids=users, type=rule.trigger_event,
        category="system", module="automation", title=rule.name, body=rule.configuration["template"],
        link="/dashboard/notifications", dedupe_key=key, actor_id=job.actor_id, mandatory=True)
    count = await db.scalar(select(func.count()).select_from(UserNotification).where(
        UserNotification.company_id == job.company_id, UserNotification.dedupe_key == key))
    if count != len(users):
        raise RuntimeError("Notification persistence did not complete")
    rule.last_triggered = datetime.now(timezone.utc)
    return {"delivered": count, "channel": "IN_APP"}
