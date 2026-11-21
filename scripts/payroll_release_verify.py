"""Run tests against an explicitly named disposable loopback database; retain evidence."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('tests', nargs='*')
    args = parser.parse_args()
    url = urlsplit(args.database_url)
    if (url.scheme != 'postgresql+asyncpg' or url.hostname != '127.0.0.1'
            or url.port != 55432 or not url.path.startswith('/payroll_verify_')):
        parser.error('Only the isolated loopback:55432/payroll_verify_* cluster is accepted')
    if not args.label.replace('_', '').replace('-', '').isalnum():
        parser.error('label must contain only letters, digits, underscore or hyphen')
    root = Path(__file__).resolve().parents[1]
    evidence = root / 'scratch' / 'payroll-release' / args.label
    evidence.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update(DATABASE_URL=args.database_url, PAYROLL_POSTGRES_TEST_URL=args.database_url,
               FIELD_ENCRYPTION_KEY='0' * 64, ENVIRONMENT='local', USE_CELERY='false',
               REDIS_URL='redis://127.0.0.1:1/0', CELERY_BROKER_URL='redis://127.0.0.1:1/1',
               SMTP_HOST='127.0.0.1', SMTP_PORT='1', RAZORPAY_KEY_ID='', RAZORPAY_KEY_SECRET='',
               PYTHONIOENCODING='utf-8', PYTHONUTF8='1')
    env['PYTHONPATH'] = os.pathsep.join([str(root), str(root / '.venv-payroll-verify/Lib/site-packages')])
    command = [sys.executable, '-m', 'pytest', '-q', '--tb=short',
               '--basetemp', str(evidence / 'tmp'), '--junitxml', str(evidence / 'results.xml'),
               *(args.tests or ['tests'])]
    (evidence / 'command.json').write_text(json.dumps(command, indent=2), encoding='utf-8')
    start = time.monotonic()
    with (evidence / 'pytest.log').open('wb') as log:
        process = subprocess.run(command, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT)
    summary = {'exit_code': process.returncode, 'seconds': round(time.monotonic() - start, 3),
               'passed': 0, 'failed': 0, 'errors': 0, 'skipped': 0, 'classification': {}}
    failures = []
    report = evidence / 'results.xml'
    if report.exists():
        for case in ET.parse(report).iter('testcase'):
            failure = case.find('failure')
            error = case.find('error')
            node = failure if failure is not None else error
            if node is not None:
                kind = 'failed' if failure is not None else 'errors'
                summary[kind] += 1
                message = (node.get('message', '') + '\n' + (node.text or ''))
                category = 'application_or_test_contract'
                for needle, group in [('PermissionError', 'filesystem_permissions'),
                                      ('ConnectionRefusedError', 'service_unavailable'),
                                      ('UndefinedTableError', 'schema_missing_table'),
                                      ('UndefinedColumnError', 'schema_missing_column'),
                                      ('ModuleNotFoundError', 'missing_dependency'),
                                      ('IntegrityError', 'constraint_or_fixture'),
                                      ('assert 404', 'route_contract'),
                                      ('OperationalError', 'database_operation')]:
                    if needle in message:
                        category = group
                        break
                summary['classification'][category] = summary['classification'].get(category, 0) + 1
                failures.append([case.get('classname'), case.get('name'), kind, category,
                                 'Unknown: original 197-test report and clean baseline unavailable', message])
            elif case.find('skipped') is not None:
                summary['skipped'] += 1
            else:
                summary['passed'] += 1
    with (evidence / 'failures.csv').open('w', encoding='utf-8', newline='') as output:
        writer = csv.writer(output)
        writer.writerow(['module', 'test', 'outcome', 'classification', 'baseline_ownership', 'evidence'])
        writer.writerows(failures)
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2), flush=True)
    return process.returncode


if __name__ == '__main__':
    raise SystemExit(main())
