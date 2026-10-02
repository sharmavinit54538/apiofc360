#!/usr/bin/env python3
"""Wait for database readiness before executing migrations or starting application."""

import asyncio
import os
import sys

# Ensure repository root is on sys.path
sys.path.insert(0, os.getcwd())

from app.db.database import get_asyncpg_connection


async def wait_for_database(max_attempts: int = 15, delay_seconds: float = 2.0) -> int:
    for attempt in range(1, max_attempts + 1):
        try:
            conn = await get_asyncpg_connection()
            await conn.close()
            print(f"[Entrypoint] Database connectivity confirmed on attempt {attempt}/{max_attempts}.")
            return 0
        except Exception as err:
            print(
                f"[Entrypoint] Waiting for database readiness (attempt {attempt}/{max_attempts})... ({err})"
            )
            await asyncio.sleep(delay_seconds)
    print(f"[Entrypoint] ERROR: Database connection timed out after {max_attempts} attempts.")
    return 1


def main() -> int:
    return asyncio.run(wait_for_database())


if __name__ == "__main__":
    sys.exit(main())
