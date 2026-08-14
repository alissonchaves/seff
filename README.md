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
seff --monitor --output-dir ~/public_html/seff --interval 10 &
MONITOR_PID=$!

# Run the actual workload here.
srun ./my-program

kill "$MONITOR_PID" 2>/dev/null || true
```

The `seff --monitor` mode writes `<job-id>.<hostname>.json` in
`~/public_html/seff/` by
default. This allows several compute nodes to publish metrics for the same
job without overwriting one another. It also maintains a small
`metrics-index.json` using a file lock and atomic replacement, so the web page
can discover and aggregate all nodes.

The dashboard is a simple static HTML page. It can be copied to the login
node's public directory or installed in Linux's
`/etc/skel` so that new users receive it automatically when their home
directory is created:

```bash
sudo mkdir -p /etc/skel/public_html/seff
sudo cp web/index.html /etc/skel/public_html/seff/
```

For an existing user, install it directly in that user's home directory:

```bash
sudo mkdir -p /home/<user>/public_html/seff
sudo cp web/index.html /home/<user>/public_html/seff/
sudo chown -R <user>:<user> /home/<user>/public_html/seff
```

The page is available at `~/public_html/seff/index.html` and reads
the JSON snapshots directly from the same directory. The directory must be
shared between the login node and compute nodes, or exposed at the same web
URL. It has no backend dependencies and refreshes every 10 seconds.

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
