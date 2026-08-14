import asyncio
import os
import sys

sys.path.insert(0, os.getcwd())

from app.core.config import settings
from app.services.email_service import EmailService, send_email

async def test_smtp():
    print(f"SMTP_HOST: {settings.SMTP_HOST}")
    print(f"SMTP_PORT: {settings.SMTP_PORT}")
    print(f"SMTP_USERNAME: {settings.SMTP_USERNAME}")
    print(f"SMTP_FROM_EMAIL: {settings.SMTP_FROM_EMAIL}")
    print(f"SMTP_USE_TLS: {settings.SMTP_USE_TLS}")
    print(f"SMTP_USE_SSL: {settings.SMTP_USE_SSL}")
    print(f"ENVIRONMENT: {settings.ENVIRONMENT}")
    print(f"DEBUG: {settings.DEBUG}")

    try:
        print("\nAttempting to send test email to sy5438066@gmail.com...")
        await send_email(
            to_email="sy5438066@gmail.com",
            subject="Test Email from OFC HR System",
            html_content="<h1>Test Email</h1><p>This is a test email to verify SMTP configuration.</p>",
        )
        print("SUCCESS: send_email completed without error!")
    except Exception as e:
        print(f"ERROR: send_email failed with exception: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_smtp())
