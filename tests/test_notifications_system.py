"""Comprehensive pytest suite for the real DB-backed tenant-scoped notification system.

Tests:
1. Tenant and recipient data isolation (User A cannot access User B's notification, cross-company isolation -> 404).
2. Cursor pagination + unread filter + unread-count correctness.
3. Mark read / unread / mark many read / mark all read with category / archive.
4. dedupe_key prevents duplicates (ON CONFLICT DO NOTHING).
5. notify() respects inAppAlerts=false but delivers mandatory=True.
6. /settings/notifications PUT and PATCH both persist securityAlerts.
7. Legacy GET /notifications/unread compatibility.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.db.database import AsyncSessionLocal
from app.main import app
from app.middleware.auth import get_current_user_claims
from app.models.company import Company
from app.models.notification import UserNotification
from app.models.user import User
from app.models.user.role import UserRole
from app.services import notification_service


@pytest.fixture
def anyio_backend():
    return "asyncio"


async def _cleanup_test_data(company_ids: list[uuid.UUID], user_ids: list[uuid.UUID]):
    async with AsyncSessionLocal() as session:
        from sqlalchemy import delete
        await session.execute(delete(UserNotification).where(UserNotification.company_id.in_(company_ids)))
        await session.execute(delete(User).where(User.id.in_(user_ids)))
        await session.execute(delete(Company).where(Company.id.in_(company_ids)))
        await session.commit()


@pytest.mark.asyncio
async def test_notifications_lifecycle_and_isolation():
    company_a_id = uuid.uuid4()
    company_b_id = uuid.uuid4()
    user_a_id = uuid.uuid4()
    user_b_id = uuid.uuid4()
    user_c_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        # Create test companies
        comp_a = Company(
            id=company_a_id,
            name="Test Corp A",
            hr_settings={
                "notifications": {
                    "emailNotifications": True,
                    "inAppAlerts": True,
                    "slackAlerts": False,
                    "weeklyDigest": True,
                    "securityAlerts": True,
                }
            },
        )
        comp_b = Company(
            id=company_b_id,
            name="Test Corp B",
            hr_settings={"notifications": {"inAppAlerts": True}},
        )
        session.add_all([comp_a, comp_b])

        # Create test users
        u_a = User(
            id=user_a_id,
            company_id=company_a_id,
            name="Alice Employee",
            email=f"alice-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.EMPLOYEE,
        )
        u_b = User(
            id=user_b_id,
            company_id=company_a_id,
            name="Bob Employee",
            email=f"bob-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.EMPLOYEE,
        )
        u_c = User(
            id=user_c_id,
            company_id=company_b_id,
            name="Charlie OtherCorp",
            email=f"charlie-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.HR_ADMIN,
        )
        session.add_all([u_a, u_b, u_c])
        await session.commit()

    try:
        # Seed notifications for Alice (User A)
        async with AsyncSessionLocal() as session:
            notifs = await notification_service.notify(
                session,
                company_id=company_a_id,
                recipient_ids=[user_a_id],
                type="leave.requested",
                category="leave",
                module="leave",
                title="Leave Requested",
                body="Your casual leave was submitted.",
                link="/dashboard/leaves",
                priority="normal",
            )
            await session.commit()
            assert len(notifs) == 1
            alice_notif_id = notifs[0].id

        # 1. Tenant & Recipient Isolation
        # Bob (same company, different user) tries to read Alice's notification -> 404
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_b_id),
            "company_id": str(company_a_id),
            "role": "employee",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            res = await client.post(f"/api/v1/notifications/{alice_notif_id}/read")
            assert res.status_code == 404

            # Charlie (different company) tries to read Alice's notification -> 404
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(user_c_id),
                "company_id": str(company_b_id),
                "role": "hr_admin",
            }
            res = await client.post(f"/api/v1/notifications/{alice_notif_id}/read")
            assert res.status_code == 404

            # Alice marks her own notification as read -> 200
            app.dependency_overrides[get_current_user_claims] = lambda: {
                "sub": str(user_a_id),
                "company_id": str(company_a_id),
                "role": "employee",
            }
            res = await client.post(f"/api/v1/notifications/{alice_notif_id}/read")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["id"] == str(alice_notif_id)
            assert data["readAt"] is not None

            # Alice marks it unread -> 200
            res = await client.post(f"/api/v1/notifications/{alice_notif_id}/unread")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["readAt"] is None

            # Alice archives it -> 200
            res = await client.post(f"/api/v1/notifications/{alice_notif_id}/archive")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["archivedAt"] is not None

    finally:
        app.dependency_overrides.clear()
        await _cleanup_test_data([company_a_id, company_b_id], [user_a_id, user_b_id, user_c_id])


@pytest.mark.asyncio
async def test_pagination_and_filters_and_unread_count():
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(
            id=company_id,
            name="Pagination Corp",
            hr_settings={"notifications": {"inAppAlerts": True}},
        )
        user = User(
            id=user_id,
            company_id=company_id,
            name="Tester",
            email=f"tester-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.EMPLOYEE,
        )
        session.add_all([comp, user])
        await session.commit()

        # Seed 25 notifications across categories
        for i in range(25):
            cat = "leave" if i < 15 else "attendance"
            await notification_service.notify(
                session,
                company_id=company_id,
                recipient_ids=[user_id],
                type=f"{cat}.item_{i}",
                category=cat,
                module=cat,
                title=f"Notification {i}",
                body=f"Test body content {i}",
                link="/dashboard/leaves" if cat == "leave" else "/dashboard/attendance",
                priority="high" if i % 5 == 0 else "normal",
            )
        await session.commit()

    try:
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(user_id),
            "company_id": str(company_id),
            "role": "employee",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. Unread count check
            res = await client.get("/api/v1/notifications/unread-count")
            assert res.status_code == 200
            counts = res.json()["data"]
            assert counts["total"] == 25
            assert counts["byCategory"]["leave"] == 15
            assert counts["byCategory"]["attendance"] == 10

            # 2. First page (limit 10)
            res = await client.get("/api/v1/notifications?limit=10")
            assert res.status_code == 200
            p1 = res.json()["data"]
            assert len(p1["items"]) == 10
            assert p1["hasMore"] is True
            assert p1["totalUnread"] == 25
            cursor1 = p1["nextCursor"]
            assert cursor1 is not None

            # 3. Second page (limit 10)
            res = await client.get(f"/api/v1/notifications?limit=10&cursor={cursor1}")
            assert res.status_code == 200
            p2 = res.json()["data"]
            assert len(p2["items"]) == 10
            assert p2["hasMore"] is True
            cursor2 = p2["nextCursor"]
            assert cursor2 is not None

            # Ensure page 1 and page 2 items are distinct
            p1_ids = {item["id"] for item in p1["items"]}
            p2_ids = {item["id"] for item in p2["items"]}
            assert p1_ids.isdisjoint(p2_ids)

            # 4. Third page (limit 10) -> remaining 5 items
            res = await client.get(f"/api/v1/notifications?limit=10&cursor={cursor2}")
            assert res.status_code == 200
            p3 = res.json()["data"]
            assert len(p3["items"]) == 5
            assert p3["hasMore"] is False
            assert p3["nextCursor"] is None

            # 5. Filter by category
            res = await client.get("/api/v1/notifications?category=attendance&limit=50")
            assert res.status_code == 200
            att_items = res.json()["data"]["items"]
            assert len(att_items) == 10
            assert all(item["category"] == "attendance" for item in att_items)

            # 6. Mark all read for category "leave"
            res = await client.post("/api/v1/notifications/read-all", json={"category": "leave"})
            assert res.status_code == 200
            assert res.json()["data"]["updatedCount"] == 15

            # Re-check unread counts: leave should be 0, attendance should still be 10
            res = await client.get("/api/v1/notifications/unread-count")
            counts = res.json()["data"]
            assert counts["total"] == 10
            assert counts["byCategory"].get("leave", 0) == 0
            assert counts["byCategory"]["attendance"] == 10

            # 7. Batch mark read
            att_ids = [item["id"] for item in att_items[:3]]
            res = await client.post("/api/v1/notifications/read", json={"ids": att_ids})
            assert res.status_code == 200
            assert res.json()["data"]["updatedCount"] == 3

            # 8. Legacy unread endpoint
            res = await client.get("/api/v1/notifications/unread")
            assert res.status_code == 200
            legacy_items = res.json()["data"]
            assert len(legacy_items) == 7

    finally:
        app.dependency_overrides.clear()
        await _cleanup_test_data([company_id], [user_id])


@pytest.mark.asyncio
async def test_dedupe_key_and_in_app_alerts_and_mandatory():
    company_id = uuid.uuid4()
    user_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(
            id=company_id,
            name="Dedupe Corp",
            hr_settings={
                "notifications": {
                    "inAppAlerts": False,  # disabled in-app alerts!
                }
            },
        )
        user = User(
            id=user_id,
            company_id=company_id,
            name="Dedupe User",
            email=f"dedupe-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.EMPLOYEE,
        )
        session.add_all([comp, user])
        await session.commit()

        # 1. Non-mandatory notification when inAppAlerts is False -> skipped
        created = await notification_service.notify(
            session,
            company_id=company_id,
            recipient_ids=[user_id],
            type="leave.info",
            category="leave",
            module="leave",
            title="Normal Leave Alert",
            body="Should be skipped because inAppAlerts is False",
            link="/dashboard/leaves",
            mandatory=False,
        )
        assert len(created) == 0

        # 2. Mandatory notification when inAppAlerts is False -> DELIVERED!
        created_mandatory = await notification_service.notify(
            session,
            company_id=company_id,
            recipient_ids=[user_id],
            type="security.alert",
            category="security",
            module="security",
            title="Urgent Security Alert",
            body="Mandatory security alert delivered.",
            link="/dashboard/settings",
            mandatory=True,
            dedupe_key=f"sec:alert:{user_id}",
        )
        await session.commit()
        assert len(created_mandatory) == 1

        # 3. Dedupe key prevents second insert for same recipient
        created_duplicate = await notification_service.notify(
            session,
            company_id=company_id,
            recipient_ids=[user_id],
            type="security.alert",
            category="security",
            module="security",
            title="Urgent Security Alert Duplicate",
            body="Should not create a second row",
            link="/dashboard/settings",
            mandatory=True,
            dedupe_key=f"sec:alert:{user_id}",
        )
        await session.commit()
        assert len(created_duplicate) == 0

        # Verify only 1 notification exists in DB for this user
        res = await notification_service.list_notifications(
            session,
            company_id=company_id,
            recipient_id=user_id,
        )
        assert len(res["items"]) == 1

    await _cleanup_test_data([company_id], [user_id])


@pytest.mark.asyncio
async def test_settings_notifications_put_and_patch_security_alerts():
    company_id = uuid.uuid4()
    admin_id = uuid.uuid4()

    async with AsyncSessionLocal() as session:
        comp = Company(
            id=company_id,
            name="Settings Corp",
            hr_settings={
                "notifications": {
                    "emailNotifications": True,
                    "inAppAlerts": True,
                    "slackAlerts": False,
                    "weeklyDigest": True,
                    "securityAlerts": True,
                }
            },
        )
        admin = User(
            id=admin_id,
            company_id=company_id,
            name="HR Admin",
            email=f"admin-{uuid.uuid4().hex[:6]}@test.com",
            phone=f"{uuid.uuid4().int % 10000000000:010d}",
            password_hash="test_hash",
            role=UserRole.HR_ADMIN,
        )
        session.add_all([comp, admin])
        await session.commit()

    try:
        app.dependency_overrides[get_current_user_claims] = lambda: {
            "sub": str(admin_id),
            "company_id": str(company_id),
            "role": "hr_admin",
        }
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # 1. GET settings/notifications -> includes securityAlerts: True
            res = await client.get("/api/v1/settings/notifications")
            assert res.status_code == 200
            data = res.json()["data"]
            assert data["securityAlerts"] is True

            # 2. PUT settings/notifications with securityAlerts: False
            res = await client.put(
                "/api/v1/settings/notifications",
                json={
                    "emailNotifications": True,
                    "inAppAlerts": True,
                    "securityAlerts": False,
                },
            )
            assert res.status_code == 200
            assert res.json()["data"]["securityAlerts"] is False

            # Verify in DB via GET
            res = await client.get("/api/v1/settings/notifications")
            assert res.json()["data"]["securityAlerts"] is False

            # 3. PATCH settings/notifications with securityAlerts: True
            res = await client.patch(
                "/api/v1/settings/notifications",
                json={
                    "securityAlerts": True,
                },
            )
            assert res.status_code == 200
            assert res.json()["data"]["securityAlerts"] is True

            # Verify in DB via GET
            res = await client.get("/api/v1/settings/notifications")
            assert res.json()["data"]["securityAlerts"] is True

    finally:
        app.dependency_overrides.clear()
        await _cleanup_test_data([company_id], [admin_id])
