#!/usr/bin/env python3
"""Alembic migration graph and heads validator for CI/CD guard.

Verifies:
1. Exactly one head exists (no branches / multiple heads).
2. Every migration's down_revision resolves to an existing file (no missing parents).
Exits with 0 on success, 1 on failure.
"""

import sys
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.util.exc import CommandError


def main() -> int:
    print("[Migration Guard] Checking Alembic migration graph integrity...")
    try:
        config = Config("alembic.ini")
        script_dir = ScriptDirectory.from_config(config)
    except Exception as exc:
        print(f"[Migration Guard] ERROR: Failed to load alembic.ini or script directory: {exc}")
        return 1

    # 1. Inspect heads
    heads = script_dir.get_heads()
    print(f"[Migration Guard] Detected head(s): {heads}")

    if len(heads) == 0:
        print("[Migration Guard] ERROR: No Alembic heads found in alembic/versions.")
        return 1
    elif len(heads) > 1:
        print(f"[Migration Guard] ERROR: Multiple Alembic heads detected ({len(heads)} heads):")
        for h in heads:
            try:
                rev = script_dir.get_revision(h)
                doc = rev.doc if rev else ""
                print(f"  - {h}: {doc}")
            except Exception:
                print(f"  - {h}")
        print("[Migration Guard] Migration branches have diverged. Merge heads with `alembic merge heads`.")
        return 1

    # 2. Inspect graph: verify every revision down_revision exists
    errors = []
    total_revisions = 0
    try:
        for rev in script_dir.walk_revisions():
            total_revisions += 1
            downs = rev.down_revision
            if downs is None:
                continue
            if isinstance(downs, str):
                down_list = [downs]
            else:
                down_list = list(downs)

            for down in down_list:
                try:
                    script_dir.get_revision(down)
                except CommandError:
                    errors.append(
                        f"Revision '{rev.revision}' ({rev.doc}) references missing parent revision '{down}'"
                    )
    except Exception as exc:
        print(f"[Migration Guard] ERROR traversing revision graph: {exc}")
        return 1

    print(f"[Migration Guard] Verified {total_revisions} revisions in migration graph.")

    if errors:
        print(f"[Migration Guard] ERROR: Found {len(errors)} broken parent references:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(f"[Migration Guard] SUCCESS: Single head '{heads[0]}' verified with complete parent chain.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
