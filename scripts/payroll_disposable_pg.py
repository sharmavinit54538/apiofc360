"""Provision and run verification in a new, private local PostgreSQL cluster.

Never reads .env credentials or connects to an existing cluster. Credentials and
data live under ignored scratch/. Re-running init refuses to replace any files.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / "scratch" / "payroll-verification-20261115"
BIN = Path(r"C:\Program Files\PostgreSQL\18\bin")
PORT = 55441
DATABASES = ("payroll_verify_focused", "payroll_verify_suite", "payroll_verify_stress")


def execute(command, **kwargs):
    return subprocess.run([str(value) for value in command], check=True, **kwargs)


async def provision(credentials):
    import asyncpg

    conn = await asyncpg.connect(host="127.0.0.1", port=PORT, database="postgres",
                                user="payroll_verify_admin", password=credentials["admin_password"])
    try:
        # Passwords are locally generated hex, never user-controlled SQL.
        await conn.execute("CREATE ROLE payroll_verify_runner LOGIN NOSUPERUSER NOCREATEDB "
                           "NOCREATEROLE PASSWORD '" + credentials["test_password"] + "'")
        for database in DATABASES:
            await conn.execute(f'CREATE DATABASE "{database}" OWNER payroll_verify_runner')
            await conn.execute(f'REVOKE CONNECT ON DATABASE "{database}" FROM PUBLIC')
        print(await conn.fetchval("SELECT version()"))
    finally:
        await conn.close()
    conn = await asyncpg.connect(host="127.0.0.1", port=PORT, database=DATABASES[0],
                                user="payroll_verify_runner", password=credentials["test_password"])
    try:
        identity = dict(await conn.fetchrow("SELECT current_user, current_database(), "
                                           "inet_server_addr()::text AS address, inet_server_port() AS port"))
        identity["role"] = dict(await conn.fetchrow("SELECT rolsuper, rolcreatedb, rolcreaterole "
                                                  "FROM pg_roles WHERE rolname=current_user"))
        (STATE / "identity.json").write_text(json.dumps(identity, indent=2))
        print(json.dumps(identity, indent=2))
    finally:
        await conn.close()


def initialize():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", PORT))
    STATE.mkdir(parents=True, exist_ok=False)
    credentials = {"admin_password": secrets.token_hex(32), "test_password": secrets.token_hex(32)}
    (STATE / "credentials.json").write_text(json.dumps(credentials), encoding="utf-8")
    password_file = STATE / "init-password.txt"
    password_file.write_text(credentials["admin_password"] + "\n", encoding="ascii")
    try:
        execute([BIN / "initdb.exe", "-D", STATE / "pgdata", "-U", "payroll_verify_admin",
                 "--pwfile", password_file, "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C"])
    finally:
        password_file.unlink(missing_ok=True)
    with (STATE / "pgdata" / "postgresql.conf").open("a", encoding="utf-8") as output:
        output.write(f"\nlisten_addresses = '127.0.0.1'\nport = {PORT}\nmax_connections = 100\n")
    execute([BIN / "pg_ctl.exe", "-D", STATE / "pgdata", "-l", STATE / "postgres.log", "-w", "start"])
    asyncio.run(provision(credentials))


def environment(database):
    if database not in DATABASES:
        raise ValueError("Only this script's three disposable databases are allowed")
    credentials = json.loads((STATE / "credentials.json").read_text(encoding="utf-8"))
    url = f"postgresql+asyncpg://payroll_verify_runner:{credentials['test_password']}@127.0.0.1:{PORT}/{database}"
    env = os.environ.copy()
    env.update(DATABASE_URL=url, PAYROLL_POSTGRES_TEST_URL=url, EXPENSES_TEST_DATABASE_URL=url,
               PAYROLL_TEST_DISPOSABLE="1", PAYROLL_USE_MIGRATED_DB="1", FIELD_ENCRYPTION_KEY="0" * 64,
               SECRET_KEY="disposable-payroll-verification-only-key", ENVIRONMENT="local",
               USE_CELERY="false", REDIS_URL="redis://127.0.0.1:1/0",
               CELERY_BROKER_URL="redis://127.0.0.1:1/1", CELERY_RESULT_BACKEND="redis://127.0.0.1:1/2",
               SMTP_HOST="127.0.0.1", SMTP_PORT="1", RAZORPAY_KEY_ID="", RAZORPAY_KEY_SECRET="",
               PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    # Use the trusted system native packages, with missing pure-Python packages
    # supplied by the verification venv. Child interpreters inherit the same path.
    runtime = STATE / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / "sitecustomize.py").write_text(
        "import sys\nsys.path.append(" + repr(str(ROOT / ".venv-payroll-verify/Lib/site-packages")) + ")\n",
        encoding="utf-8")
    env["PYTHONPATH"] = os.pathsep.join((str(runtime), str(ROOT)))
    return env


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "run", "stop"))
    parser.add_argument("--database", choices=DATABASES, default=DATABASES[0])
    parser.add_argument("--label")
    args, command = parser.parse_known_args()
    if args.action == "init":
        initialize()
    elif args.action == "stop":
        execute([BIN / "pg_ctl.exe", "-D", STATE / "pgdata", "-w", "stop"])
    else:
        if command and command[0] == "--":
            command.pop(0)
        if not command:
            parser.error("run requires a command after --")
        env = environment(args.database)
        if not args.label:
            return subprocess.call(command, cwd=ROOT, env=env)
        if not args.label.replace("-", "").replace("_", "").isalnum():
            parser.error("label must contain only letters, digits, underscore or hyphen")
        evidence = ROOT / "verification" / "payroll-pg-20261115" / args.label
        evidence.mkdir(parents=True, exist_ok=False)
        if "pytest" in command:
            command += ["--junitxml=" + str(evidence / "results.xml"),
                        "--basetemp=" + str(STATE / (args.label + "-tmp"))]
        (evidence / "command.json").write_text(json.dumps(command, indent=2))
        start = time.monotonic()
        with (evidence / "execution.log").open("w", encoding="utf-8") as output:
            result = subprocess.call(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        summary = {"command": command, "database": args.database, "port": PORT,
                   "exit_code": result, "seconds": round(time.monotonic() - start, 3)}
        if (evidence / "results.xml").exists():
            cases = list(ET.parse(evidence / "results.xml").iter("testcase"))
            summary.update(tests=len(cases), failed=sum(c.find("failure") is not None for c in cases),
                           errors=sum(c.find("error") is not None for c in cases),
                           skipped=sum(c.find("skipped") is not None for c in cases))
            summary["passed"] = summary["tests"] - summary["failed"] - summary["errors"] - summary["skipped"]
        (evidence / "summary.json").write_text(json.dumps(summary, indent=2))
        print(json.dumps(summary, indent=2))
        return result
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
