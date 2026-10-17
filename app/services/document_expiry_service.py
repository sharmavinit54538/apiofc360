"""Document Expiry Tracking Background Service (Rule 3.6)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
import logging
import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.database import AsyncSessionLocal
from app.models.document.expiry import DocumentExpiryTracking
from app.models.employee_document import EmployeeDocument

logger = logging.getLogger(__name__)

EXPIRY_THRESHOLDS = [30, 15, 7, 1, 0]


async def process_document_expiry_alerts(session: AsyncSession) -> int:
    """Find employee documents approaching expiry or expired and record expiry tracking rows idempotently."""
    today = date.today()
    tracked_count = 0

    try:
        # Load all active documents with expiry dates, excluding rejected and deleted
        stmt = (
            select(EmployeeDocument)
            .options(
                selectinload(EmployeeDocument.employee),
                selectinload(EmployeeDocument.expiry_tracks),
            )
            .where(
                and_(
                    EmployeeDocument.is_deleted == False,  # noqa: E712
                    EmployeeDocument.status != "REJECTED",
                    EmployeeDocument.expiry_date != None,  # noqa: E711
                )
            )
        )
        res = await session.execute(stmt)
        docs = res.scalars().all()

        for doc in docs:
            if not doc.expiry_date:
                continue

            delta_days = (doc.expiry_date - today).days

            # Existing tracked thresholds for this document
            existing_thresholds = {track.days_remaining for track in (doc.expiry_tracks or [])}

            for threshold in EXPIRY_THRESHOLDS:
                should_alert = False
                if threshold == 0 and delta_days <= 0:
                    should_alert = True
                elif threshold > 0 and 0 < delta_days <= threshold:
                    should_alert = True

                if should_alert and threshold not in existing_thresholds:
                    track_record = DocumentExpiryTracking(
                        employee_doc_id=doc.id,
                        days_remaining=threshold,
                        notified_at=datetime.now(timezone.utc),
                    )
                    session.add(track_record)
                    existing_thresholds.add(threshold)
                    tracked_count += 1
                    logger.info(
                        "Document expiry alert logged: doc_id=%s, title='%s', days_remaining=%d",
                        doc.id,
                        doc.title,
                        threshold,
                    )

                    try:
                        from app.services import notification_service
                        if doc.employee and doc.employee.user_id and doc.company_id:
                            is_expired = threshold == 0
                            notif_type = "documents.expired" if is_expired else "documents.expiring_soon"
                            notif_title = f"Document Expired: {doc.title}" if is_expired else f"Document Expiring Soon: {doc.title}"
                            notif_body = (
                                f"Your document '{doc.title}' has expired on {doc.expiry_date.isoformat()}."
                                if is_expired
                                else f"Your document '{doc.title}' will expire in {delta_days} day(s) on {doc.expiry_date.isoformat()}."
                            )
                            await notification_service.notify(
                                session,
                                company_id=doc.company_id,
                                recipient_ids=[doc.employee.user_id],
                                type=notif_type,
                                category="documents",
                                module="documents",
                                title=notif_title,
                                body=notif_body,
                                link="/dashboard/people",
                                priority="high" if is_expired else "normal",
                                entity={"type": "employee_document", "id": str(doc.id)},
                                dedupe_key=f"doc:{doc.id}:expiry:{threshold}",
                            )
                    except Exception as notif_err:
                        logger.warning("Failed to emit document expiry notification for doc=%s: %s", doc.id, notif_err)

        if tracked_count > 0:
            await session.commit()
            logger.info("Committed %d document expiry tracking alerts.", tracked_count)

    except Exception as exc:
        await session.rollback()
        logger.error("Error processing document expiry alerts: %s", exc)

    return tracked_count


async def run_document_expiry_scheduler() -> None:
    """Daily background task to monitor and record document expiry alerts."""
    logger.info("Starting document expiry background scheduler...")
    # Initial brief sleep to allow server and DB to initialize
    await asyncio.sleep(5)

    while True:
        try:
            async with AsyncSessionLocal() as session:
                await process_document_expiry_alerts(session)
        except Exception as exc:
            logger.error("Unhandled error in document expiry scheduler loop: %s", exc)

        # Run once daily (24 hours = 86400 seconds)
        await asyncio.sleep(86400)
