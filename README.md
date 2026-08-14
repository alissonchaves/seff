# seff

Slurm job efficiency reporter with CPU, memory, and GPU metrics when Slurm
accounting is configured.

## Requirements

- Linux with Python 3.9 or newer;
- Slurm installed with the `sacct` command available;
- permission to query jobs in Slurm.

## Installation

Using `pipx` (recommended):

```bash
pipx install git+https://github.com/alissonchaves/seff.git
```

By default, this installation is available only to the current user. To make
the command available to all Linux users:

```bash
sudo pipx install --global git+https://github.com/alissonchaves/seff.git
```

Make sure `/usr/local/bin` is in each user's `PATH`:

```bash
which seff
```

The global installation provides the executable, but Slurm permissions still
determine which jobs each user can query.

Or install directly with `pip`:

```bash
python3 -m pip install git+https://github.com/alissonchaves/seff.git
```

To install a local copy for development:

```bash
python3 -m pip install .
```

After installation, the `seff` command is available in the `PATH`:

```bash
seff 6683
```

Multiple jobs can also be queried:

```bash
seff 6683 6685
```

## JSON output

```bash
seff --json 6683
```

## GPU metrics

To display GPUs and GPU efficiency, Slurm must have GRES configured
(`GresTypes=gpu` and a `gres.conf`) and collect `gres/gpuutil` through
accounting. Without this data, the program reports that utilization is
unavailable.

## Memory metrics

`Memory Efficiency` depends on `MaxRSS` or `TRESUsageIn*` recorded by Slurm.
If these fields are empty in `sacct`, the metric cannot be reconstructed for
an already completed job.

## Live metrics module

The package also provides a lightweight monitor that runs inside the Slurm
job and writes one compact JSON snapshot every 10 seconds. It reads CPU and
memory from the job cgroup and GPU utilization from `nvidia-smi`:

```bash
seff-monitor --output-dir /shared/seff-metrics --interval 10 &
MONITOR_PID=$!

# Run the actual workload here.
srun ./my-program

kill "$MONITOR_PID" 2>/dev/null || true
```

The monitor writes `<job-id>.json` using an atomic replacement, so the web
page never reads a partially written file.

Install the static dashboard in the login node's public directory:

```bash
seff-web ~/public_html/seff
```

The dashboard is then available at `~/public_html/seff/index.html` and reads
snapshots from `~/public_html/seff/metrics/`. To use a shared metrics
directory, publish or mount that directory as the dashboard's `metrics/`
directory. The dashboard is intentionally dependency-free and refreshes every
10 seconds.

The GPU values represent the GPUs visible to the job/node. For strict
per-process GPU accounting, Slurm GRES accounting must be configured and GPU
allocations should be exclusive.

## Development

```bash
python3 -m py_compile seff.py
python3 seff.py --help
```

## License

MIT
