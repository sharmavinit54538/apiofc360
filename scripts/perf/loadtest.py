#!/usr/bin/env python3
"""
Load test script for performance baseline measurement.

Usage:
    python scripts/perf/loadtest.py --duration 60 --concurrency 10 --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import sys
import time
from dataclasses import dataclass, field
from typing import Any

import httpx


@dataclass
class EndpointResult:
    name: str
    method: str
    url: str
    latencies: list[float] = field(default_factory=list)
    db_queries: list[int] = field(default_factory=list)
    db_times: list[float] = field(default_factory=list)
    redis_calls: list[int] = field(default_factory=list)
    redis_times: list[float] = field(default_factory=list)
    errors: int = 0
    status_codes: dict[int, int] = field(default_factory=dict)

    def add_request(
        self,
        latency: float,
        db_queries: int,
        db_time: float,
        redis_calls: int,
        redis_time: float,
        status_code: int,
    ):
        self.latencies.append(latency)
        self.db_queries.append(db_queries)
        self.db_times.append(db_time)
        self.redis_calls.append(redis_calls)
        self.redis_times.append(redis_time)
        self.status_codes[status_code] = self.status_codes.get(status_code, 0) + 1
        if status_code >= 400:
            self.errors += 1

    def percentiles(self, data: list[float], percentiles: list[int]) -> dict[int, float]:
        if not data:
            return {p: 0.0 for p in percentiles}
        sorted_data = sorted(data)
        result = {}
        for p in percentiles:
            idx = int(len(sorted_data) * p / 100)
            idx = min(idx, len(sorted_data) - 1)
            result[p] = sorted_data[idx]
        return result

    def summary(self) -> dict[str, Any]:
        p50, p95, p99 = self.percentiles(self.latencies, [50, 95, 99]).values()
        avg_db_q = statistics.mean(self.db_queries) if self.db_queries else 0
        avg_db_t = statistics.mean(self.db_times) if self.db_times else 0
        avg_redis_c = statistics.mean(self.redis_calls) if self.redis_calls else 0
        avg_redis_t = statistics.mean(self.redis_times) if self.redis_times else 0
        total = len(self.latencies)
        error_rate = self.errors / total * 100 if total > 0 else 0

        return {
            "endpoint": f"{self.method} {self.url}",
            "requests": total,
            "errors": self.errors,
            "error_rate_pct": round(error_rate, 2),
            "status_codes": self.status_codes,
            "latency_ms": {
                "p50": round(p50, 1),
                "p95": round(p95, 1),
                "p99": round(p99, 1),
                "avg": round(statistics.mean(self.latencies), 1) if self.latencies else 0,
            },
            "db": {
                "avg_queries": round(avg_db_q, 1),
                "avg_time_ms": round(avg_db_t, 1),
                "max_queries": max(self.db_queries) if self.db_queries else 0,
            },
            "redis": {
                "avg_calls": round(avg_redis_c, 1),
                "avg_time_ms": round(avg_redis_t, 1),
                "max_calls": max(self.redis_calls) if self.redis_calls else 0,
            },
        }


class LoadTester:
    ENDPOINTS = [
        # (name, method, path, requires_auth, payload_factory)
        ("login", "POST", "/api/v1/auth/login", False, lambda: {"email": "test@example.com", "password": "password123"}),
        ("token_refresh", "POST", "/api/v1/auth/refresh", True, lambda: {}),
        ("sidebar_permissions", "GET", "/api/v1/sidebar/permissions", True, None),
        ("employees_list", "GET", "/api/v1/employees?page=1&limit=25", True, None),
        ("attendance_today", "GET", "/api/v1/attendance/face/me", True, None),
        ("attendance_analytics", "GET", "/api/v1/attendance/analytics", True, None),
        ("notifications_list", "GET", "/api/v1/notifications?limit=20", True, None),
        ("notifications_unread", "GET", "/api/v1/notifications/unread-count", True, None),
        ("leaves_list", "GET", "/api/v1/leaves?page=1&limit=20", True, None),
        ("payroll_list", "GET", "/api/v1/payroll?page=1&limit=20", True, None),
        ("executive_dashboard", "GET", "/api/v1/dashboard/executive", True, None),
        ("shifts_list", "GET", "/api/v1/shifts?page=1&limit=20", True, None),
        ("shifts_options", "GET", "/api/v1/shifts/options", True, None),
        ("holidays_list", "GET", "/api/v1/calendar/holidays", True, None),
    ]

    def __init__(
        self,
        base_url: str,
        concurrency: int,
        duration: int,
        username: str = "test@example.com",
        password: str = "password123",
    ):
        self.base_url = base_url.rstrip("/")
        self.concurrency = concurrency
        self.duration = duration
        self.username = username
        self.password = password
        self.results: dict[str, EndpointResult] = {}
        self.access_token: str | None = None
        self._client: httpx.AsyncClient | None = None
        self._stop_event = asyncio.Event()

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        await self._login()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()

    async def _login(self):
        """Login and get access token."""
        resp = await self._client.post(
            "/api/v1/auth/login",
            json={"email": self.username, "password": self.password},
        )
        if resp.status_code == 200:
            data = resp.json()
            self.access_token = data.get("data", {}).get("access_token")
            if self.access_token:
                print(f"✓ Logged in as {self.username}")
            else:
                print(f"✗ Login succeeded but no access token: {data}")
        else:
            print(f"✗ Login failed: {resp.status_code} {resp.text}")
            # Try to continue without auth for public endpoints

    def _auth_headers(self) -> dict[str, str]:
        if self.access_token:
            return {"Authorization": f"Bearer {self.access_token}"}
        return {}

    def _get_result(self, name: str, method: str, url: str) -> EndpointResult:
        key = f"{method}:{url}"
        if key not in self.results:
            self.results[key] = EndpointResult(name, method, url)
        return self.results[key]

    async def _make_request(
        self,
        method: str,
        path: str,
        requires_auth: bool,
        payload: dict | None,
    ) -> tuple[float, int, float, int, float, int]:
        """Make a single request and return metrics."""
        url = f"{self.base_url}{path}"
        headers = self._auth_headers() if requires_auth else {}

        start = time.perf_counter()
        try:
            if method == "GET":
                resp = await self._client.get(url, headers=headers)
            elif method == "POST":
                resp = await self._client.post(url, headers=headers, json=payload or {})
            else:
                raise ValueError(f"Unsupported method: {method}")
            latency = (time.perf_counter() - start) * 1000

            # Parse performance headers
            db_queries = int(resp.headers.get("x-db-queries", "0"))
            db_time_ms = float(resp.headers.get("x-db-time-ms", "0"))
            redis_calls = int(resp.headers.get("x-redis-calls", "0"))
            redis_time_ms = float(resp.headers.get("x-redis-time-ms", "0"))

            return latency, db_queries, db_time_ms, redis_calls, redis_time_ms, resp.status_code
        except Exception as e:
            latency = (time.perf_counter() - start) * 1000
            print(f"Request error: {method} {path} - {e}")
            return latency, 0, 0.0, 0, 0.0, 0

    async def _worker(self, worker_id: int):
        """Worker that continuously makes requests."""
        print(f"Worker {worker_id} started")
        while not self._stop_event.is_set():
            for name, method, path, requires_auth, payload_factory in self.ENDPOINTS:
                if self._stop_event.is_set():
                    break
                if requires_auth and not self.access_token:
                    continue

                payload = payload_factory() if payload_factory else None
                latency, db_q, db_t, redis_c, redis_t, status = await self._make_request(
                    method, path, requires_auth, payload
                )

                result = self._get_result(name, method, path)
                result.add_request(latency, db_q, db_t / 1000, redis_c, redis_t / 1000, status)

                # Small delay to avoid overwhelming
                await asyncio.sleep(0.01)

    async def run(self):
        """Run the load test."""
        print(f"Starting load test: {self.concurrency} workers for {self.duration}s")
        print(f"Target: {self.base_url}")
        print(f"Endpoints: {len(self.ENDPOINTS)}")
        print("-" * 60)

        workers = [asyncio.create_task(self._worker(i)) for i in range(self.concurrency)]

        # Run for specified duration
        await asyncio.sleep(self.duration)
        self._stop_event.set()

        # Wait for workers to finish
        await asyncio.gather(*workers, return_exceptions=True)

        print("-" * 60)
        print("Load test complete. Generating report...")
        return self.generate_report()

    def generate_report(self) -> dict[str, Any]:
        """Generate summary report."""
        report = {
            "config": {
                "base_url": self.base_url,
                "concurrency": self.concurrency,
                "duration_seconds": self.duration,
                "endpoints_tested": len(self.ENDPOINTS),
            },
            "endpoints": {},
            "overall": {
                "total_requests": 0,
                "total_errors": 0,
                "avg_latency_ms": 0,
                "p95_latency_ms": 0,
            },
        }

        all_latencies = []
        total_requests = 0
        total_errors = 0

        for key, result in self.results.items():
            summary = result.summary()
            report["endpoints"][key] = summary
            all_latencies.extend(result.latencies)
            total_requests += summary["requests"]
            total_errors += summary["errors"]

        if all_latencies:
            p50, p95, p99 = EndpointResult("", "", "").percentiles(all_latencies, [50, 95, 99]).values()
            report["overall"]["total_requests"] = total_requests
            report["overall"]["total_errors"] = total_errors
            report["overall"]["error_rate_pct"] = round(total_errors / total_requests * 100, 2) if total_requests > 0 else 0
            report["overall"]["avg_latency_ms"] = round(statistics.mean(all_latencies), 1)
            report["overall"]["p50_latency_ms"] = round(p50, 1)
            report["overall"]["p95_latency_ms"] = round(p95, 1)
            report["overall"]["p99_latency_ms"] = round(p99, 1)

        return report

    def print_report(self, report: dict[str, Any]):
        """Print formatted report."""
        print("\n" + "=" * 80)
        print("LOAD TEST REPORT")
        print("=" * 80)
        print(f"Base URL: {report['config']['base_url']}")
        print(f"Concurrency: {report['config']['concurrency']}")
        print(f"Duration: {report['config']['duration_seconds']}s")
        print("-" * 80)

        overall = report["overall"]
        print(f"Total Requests: {overall['total_requests']}")
        print(f"Total Errors: {overall['total_errors']} ({overall.get('error_rate_pct', 0)}%)")
        print(f"Latency - Avg: {overall['avg_latency_ms']}ms, P50: {overall['p50_latency_ms']}ms, P95: {overall['p95_latency_ms']}ms, P99: {overall['p99_latency_ms']}ms")
        print("-" * 80)

        print("\nPER ENDPOINT:")
        for key, ep in report["endpoints"].items():
            print(f"\n  {ep['endpoint']}")
            print(f"    Requests: {ep['requests']}, Errors: {ep['errors']} ({ep['error_rate_pct']}%)")
            print(f"    Latency:  P50={ep['latency_ms']['p50']}ms P95={ep['latency_ms']['p95']}ms P99={ep['latency_ms']['p99']}ms")
            print(f"    DB:       Avg {ep['db']['avg_queries']} queries, {ep['db']['avg_time_ms']}ms")
            print(f"    Redis:    Avg {ep['redis']['avg_calls']} calls, {ep['redis']['avg_time_ms']}ms")


async def main():
    parser = argparse.ArgumentParser(description="OFC360 Load Test")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Base URL of the API")
    parser.add_argument("--concurrency", type=int, default=10, help="Number of concurrent workers")
    parser.add_argument("--duration", type=int, default=60, help="Test duration in seconds")
    parser.add_argument("--username", default="test@example.com", help="Login username")
    parser.add_argument("--password", default="password123", help="Login password")
    parser.add_argument("--output", help="Output JSON file for report")
    args = parser.parse_args()

    async with LoadTester(
        base_url=args.base_url,
        concurrency=args.concurrency,
        duration=args.duration,
        username=args.username,
        password=args.password,
    ) as tester:
        report = await tester.run()
        tester.print_report(report)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(report, f, indent=2)
            print(f"\nReport saved to {args.output}")

        # Save baseline report
        baseline_path = "docs/perf/backend-baseline.md"
        save_baseline_markdown(report, baseline_path)
        print(f"Baseline report saved to {baseline_path}")


def save_baseline_markdown(report: dict[str, Any], path: str):
    """Save report as markdown for documentation."""
    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)

    with open(path, "w") as f:
        f.write("# Backend Performance Baseline\n\n")
        f.write(f"**Generated:** {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        f.write("## Configuration\n\n")
        for k, v in report["config"].items():
            f.write(f"- **{k}**: {v}\n")

        f.write("\n## Overall Summary\n\n")
        overall = report["overall"]
        f.write(f"| Metric | Value |\n|--------|-------|\n")
        f.write(f"| Total Requests | {overall['total_requests']} |\n")
        f.write(f"| Total Errors | {overall['total_errors']} |\n")
        f.write(f"| Error Rate | {overall.get('error_rate_pct', 0)}% |\n")
        f.write(f"| Avg Latency | {overall['avg_latency_ms']}ms |\n")
        f.write(f"| P50 Latency | {overall['p50_latency_ms']}ms |\n")
        f.write(f"| P95 Latency | {overall['p95_latency_ms']}ms |\n")
        f.write(f"| P99 Latency | {overall['p99_latency_ms']}ms |\n")

        f.write("\n## Per-Endpoint Results\n\n")
        f.write("| Endpoint | Requests | Errors | Error% | P50 | P95 | P99 | Avg DB Q | Avg DB Time | Avg Redis C | Avg Redis Time |\n")
        f.write("|----------|----------|--------|--------|-----|-----|-----|----------|-------------|-------------|----------------|\n")

        for key, ep in sorted(report["endpoints"].items()):
            f.write(f"| {ep['endpoint']} | {ep['requests']} | {ep['errors']} | {ep['error_rate_pct']}% | "
                    f"{ep['latency_ms']['p50']}ms | {ep['latency_ms']['p95']}ms | {ep['latency_ms']['p99']}ms | "
                    f"{ep['db']['avg_queries']} | {ep['db']['avg_time_ms']}ms | "
                    f"{ep['redis']['avg_calls']} | {ep['redis']['avg_time_ms']}ms |\n")


if __name__ == "__main__":
    asyncio.run(main())