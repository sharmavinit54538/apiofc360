"""Pytest suite to enforce Alembic migration graph integrity.

Verifies:
1. Exactly one head exists (no branches / multiple heads).
2. Exactly one base exists (no multiple disconnected roots).
3. Every migration's down_revision resolves to a valid existing revision.
"""

from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory


def get_alembic_script_dir() -> ScriptDirectory:
    """Load Alembic ScriptDirectory from alembic.ini."""
    # Find alembic.ini relative to this test file or current working directory
    base_dir = Path(__file__).resolve().parent.parent
    alembic_ini_path = base_dir / "alembic.ini"
    if not alembic_ini_path.exists():
        alembic_ini_path = Path("alembic.ini").resolve()
    
    config = Config(str(alembic_ini_path))
    return ScriptDirectory.from_config(config)


def test_alembic_single_head():
    """Assert that the migration tree has exactly one head revision."""
    script_dir = get_alembic_script_dir()
    heads = script_dir.get_heads()
    assert len(heads) == 1, (
        f"Expected exactly 1 Alembic head, but found {len(heads)}: {heads}. "
        "Run `alembic merge heads` to combine diverging heads into a single head."
    )


def test_alembic_single_base():
    """Assert that the migration tree has exactly one base / root revision."""
    script_dir = get_alembic_script_dir()
    bases = script_dir.get_bases()
    assert len(bases) == 1, (
        f"Expected exactly 1 Alembic base (root), but found {len(bases)}: {bases}. "
        "All migrations should trace back to a single root revision."
    )


def test_alembic_migration_graph_continuity():
    """Assert that all down_revisions resolve to existing migrations."""
    script_dir = get_alembic_script_dir()
    missing_parents = []
    
    for rev in script_dir.walk_revisions():
        down_revs = rev.down_revision
        if down_revs is None:
            continue
        if isinstance(down_revs, str):
            down_revs = [down_revs]
        
        for parent_id in down_revs:
            try:
                parent_rev = script_dir.get_revision(parent_id)
                if parent_rev is None:
                    missing_parents.append((rev.revision, parent_id))
            except Exception:
                missing_parents.append((rev.revision, parent_id))
    
    assert not missing_parents, (
        f"Found migrations referencing missing parent revisions: {missing_parents}"
    )
