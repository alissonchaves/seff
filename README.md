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

This installs `seff` only for the current user. The executable is normally
placed in `~/.local/bin`, which must be in that user's `PATH`.

By default, this installation is available only to the current user. To make
the command available to all Linux users:

```bash
sudo pipx install --global git+https://github.com/alissonchaves/seff.git
```

Add the global `pipx` binary directory to the system `PATH`:

```bash
sudo pipx ensurepath --global
```

Open a new login session after running this command.

Do not omit `--global`: running `pipx install` as `root` installs the command
only for `root`, usually in `/root/.local/bin`.

For a cluster installation, use the included installer. It applies a safe
umask and fixes the permissions of the global pipx environment so compute
node users can execute `seff`:

```bash
curl -fsSL https://raw.githubusercontent.com/alissonchaves/seff/main/install-global.sh | sudo bash
```

Run this on every compute node, unless `/opt/pipx` is shared between nodes.

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

## Allocated resources

The report includes the resources allocated to each job:

- `Allocated CPUs`: the number of CPUs from Slurm's `AllocCPUS`.
- `Allocated Memory`: the requested memory from `ReqMem`, including whether it
  is allocated per node (`/node`) or per CPU (`/CPU`).
- `Allocated GPUs`: the GPU count from `AllocTRES`, including typed GPU GRES
  such as `gres/gpu:rtx4000=2`.

These fields are shown for completed, running and pending jobs. The JSON output
also includes the original `cpus`, `req_mem_kb`, `req_mem` and `gpus` fields.

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

Each live snapshot includes the allocated CPU count, allocated memory limit and
allocated GPU count, as well as current CPU, memory and GPU usage. The web page
displays these values in separate allocated and usage columns.

`--monitor` does not take a job ID. It must run inside a Slurm job and uses
the `SLURM_JOB_ID` and cgroup supplied by Slurm. When monitors are started
automatically for all jobs, the dashboard can aggregate the JSON files for
the user's jobs across all compute nodes.

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

To synchronize the dashboard automatically whenever a user starts a login
shell, install the included profile script:

```bash
sudo install -m 755 update-user-web.sh /etc/profile.d/seff-web.sh
```

The script compares `/etc/skel/public_html/seff/index.html` with the user's
copy and only copies it when the template changed. It does not overwrite job
metric JSON files. This applies to shell logins that source `/etc/profile.d`;
non-shell services do not run profile scripts.

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
