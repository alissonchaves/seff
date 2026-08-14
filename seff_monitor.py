#!/usr/bin/env python3
"""Collect lightweight, job-scoped Slurm metrics in a compact JSON file."""

import argparse
import fcntl
import json
import os
import pathlib
import signal
import socket
import subprocess
import time
from datetime import datetime, timezone


CGROUP_ROOT = pathlib.Path("/sys/fs/cgroup")


def cgroup_path():
    for line in pathlib.Path("/proc/self/cgroup").read_text().splitlines():
        if line.startswith("0::"):
            path = pathlib.PurePosixPath("/") / line[3:].lstrip("/")
            # A monitor started in a batch script is usually in step_batch,
            # while the workload launched with srun is in another step. Use
            # the enclosing job cgroup so both are accounted together.
            for parent in (path, *path.parents):
                if parent.name.startswith("job_"):
                    return CGROUP_ROOT / parent.relative_to("/")
            return CGROUP_ROOT / path.relative_to("/")
    return CGROUP_ROOT


def read_number(path):
    try:
        return int(path.read_text().strip())
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def read_cpu_usage(cgroup):
    try:
        values = dict(line.split() for line in (cgroup / "cpu.stat").read_text().splitlines())
        return int(values.get("usage_usec", "0"))
    except (FileNotFoundError, ValueError, PermissionError):
        return None


def memory_limit(cgroup):
    value = read_number(cgroup / "memory.max")
    return None if value is None or value >= 2**60 else value


def gpu_metrics():
    command = [
        "nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=True)
    except (FileNotFoundError, subprocess.SubprocessError):
        return {}

    rows = []
    for line in result.stdout.splitlines():
        try:
            utilization, used, total = (int(value.strip()) for value in line.split(","))
            rows.append({"util": utilization, "used_mb": used, "total_mb": total})
        except ValueError:
            continue
    if not rows:
        return {}
    return {
        "count": len(rows),
        "utilization_percent": round(sum(row["util"] for row in rows) / len(rows), 2),
        "memory_used_mb": sum(row["used_mb"] for row in rows),
        "memory_total_mb": sum(row["total_mb"] for row in rows),
    }


def write_snapshot(path, snapshot):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(snapshot, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def update_index(output_dir, snapshot, filename):
    """Publish this node's file in a small, multi-writer-safe index."""
    output_dir = pathlib.Path(output_dir)
    index_path = output_dir / "metrics-index.json"
    lock_path = output_dir / ".metrics-index.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                entries = json.loads(index_path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                entries = {}
            key = f"{snapshot['job_id']}.{snapshot['node']}"
            entries[key] = {
                "job_id": snapshot["job_id"],
                "user": snapshot["user"],
                "node": snapshot["node"],
                "file": filename,
                "updated_at": snapshot["updated_at"],
            }
            temporary = index_path.with_suffix(f".tmp.{os.getpid()}")
            temporary.write_text(json.dumps(entries, separators=(",", ":")) + "\n")
            os.replace(temporary, index_path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def remove_index_entry(output_dir, job_id, node, filename):
    output_dir = pathlib.Path(output_dir)
    index_path = output_dir / "metrics-index.json"
    lock_path = output_dir / ".metrics-index.lock"
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            try:
                entries = json.loads(index_path.read_text())
            except (FileNotFoundError, json.JSONDecodeError):
                entries = {}
            entries.pop(f"{job_id}.{node}", None)
            temporary = index_path.with_suffix(f".tmp.{os.getpid()}")
            temporary.write_text(json.dumps(entries, separators=(",", ":")) + "\n")
            os.replace(temporary, index_path)
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
    try:
        (output_dir / filename).unlink()
    except FileNotFoundError:
        pass


def collect(job_id, output_dir, interval):
    cgroup = cgroup_path()
    output_dir = pathlib.Path(output_dir).expanduser()
    node = socket.gethostname().split(".")[0]
    filename = f"{job_id}.{node}.json"
    output = output_dir / filename
    cpus = int(os.environ.get(
        "SLURM_CPUS_PER_TASK",
        os.environ.get("SLURM_CPUS_ON_NODE", os.cpu_count() or 1),
    ))
    previous_cpu = read_cpu_usage(cgroup)
    previous_time = time.monotonic()

    def cleanup(_signum=None, _frame=None):
        remove_index_entry(output_dir, str(job_id), node, filename)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    while True:
        time.sleep(interval)
        now = time.monotonic()
        current_cpu = read_cpu_usage(cgroup)
        cpu_percent = None
        if previous_cpu is not None and current_cpu is not None:
            elapsed = max(now - previous_time, 0.001)
            cpu_percent = round((current_cpu - previous_cpu) / 1_000_000 / elapsed / cpus * 100, 2)

        snapshot = {
            "job_id": str(job_id),
            "state": "RUNNING",
            "user": os.environ.get("SLURM_JOB_USER", os.environ.get("USER", "unknown")),
            "node": node,
            "cpus": cpus,
            "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cpu_percent": cpu_percent,
            "memory_used_kb": (read_number(cgroup / "memory.current") or 0) // 1024,
            "memory_limit_kb": (memory_limit(cgroup) or 0) // 1024,
            "gpu": gpu_metrics(),
        }
        write_snapshot(output, snapshot)
        update_index(output_dir, snapshot, filename)
        previous_cpu, previous_time = current_cpu, now


def main():
    parser = argparse.ArgumentParser(description="Collect live metrics for a Slurm job")
    parser.add_argument("--job-id", default=os.environ.get("SLURM_JOB_ID"), required=False)
    parser.add_argument(
        "--output-dir", default="~/public_html/seff",
        help="Shared directory for compact JSON snapshots (default: ~/public_html/seff)",
    )
    parser.add_argument("--interval", type=float, default=10, help="Sampling interval in seconds")
    args = parser.parse_args()
    if not args.job_id:
        parser.error("--job-id is required outside a Slurm job")
    if args.interval <= 0:
        parser.error("--interval must be greater than zero")
    collect(args.job_id, args.output_dir, args.interval)


if __name__ == "__main__":
    main()
