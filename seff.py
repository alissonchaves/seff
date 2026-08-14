#!/usr/bin/env python3
import subprocess
import sys
import argparse
import json
import re
import math
import os
from dataclasses import dataclass, asdict
from typing import List, Dict, Any
from seff_monitor import collect as collect_live_metrics

# Terminal Colors
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    RESET = '\033[0m'

@dataclass
class JobMetrics:
    job_id: str
    user: str
    group: str
    state: str
    cluster: str
    cpus: int
    nodes: int
    req_mem_kb: float
    walltime_sec: float
    cpu_util_sec: float
    max_rss_kb: float
    gpus: float
    gpu_utilization: float
    exit_code: str
    cpu_efficiency: float = 0.0
    mem_efficiency: float = 0.0

class SeffParser:
    """Responsible for executing sacct and parsing Slurm job data."""
    
    # JobID,User,Group,State,Cluster,AllocCPUS,ReqMem,Elapsed,ExitCode,
    # MaxRSS,TotalCPU,AllocTRES,TRESUsageInAve,TRESUsageInTot,TRESUsageInMax
    SACCT_FORMAT = ("JobID,User,Group,State,Cluster,AllocCPUS,ReqMem,Elapsed,"
                    "ExitCode,MaxRSS,TotalCPU,AllocTRES,TRESUsageInAve,"
                    "TRESUsageInTot,TRESUsageInMax")

    def __init__(self, debug: bool = False):
        self.debug = debug

    def _run_sacct(self, job_ids: List[str]) -> str:
        # We do NOT use -X so we can capture sub-steps (like .batch) where usage is recorded
        cmd = [
            "sacct", "-p", "-n", 
            "--format", self.SACCT_FORMAT,
            "-j"
        ] + job_ids
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError as e:
            print(f"{Colors.RED}Error executing sacct:{Colors.RESET} {e.stderr}", file=sys.stderr)
            sys.exit(1)
        except FileNotFoundError:
            print(f"{Colors.RED}Error:{Colors.RESET} 'sacct' command not found. Is Slurm installed?", file=sys.stderr)
            sys.exit(1)

    def parse_time(self, time_str: str) -> float:
        """Converts HH:MM:SS or D-HH:MM:SS to seconds (supports sub-seconds)."""
        if not time_str or time_str in ["0", "N/A", "None", "00:00:00"]:
            return 0.0
        
        try:
            days = 0
            if '-' in time_str:
                days_part, time_part = time_str.split('-')
                days = int(days_part)
                time_str = time_part
            
            parts = time_str.split(':')
            if len(parts) == 3:
                h, m, s = int(parts[0]), int(parts[1]), float(parts[2])
                return days * 86400 + h * 3600 + m * 60 + s
            elif len(parts) == 2:
                h, m = int(parts[0]), int(parts[1])
                return days * 86400 + h * 3600 + m * 60
            return 0.0
        except (ValueError, IndexError):
            return 0.0

    def parse_memory(self, mem_str: str) -> float:
        """Converts memory strings (e.g., 500M, 1G) to Kilobytes."""
        mem_str = (mem_str or "").strip()
        if not mem_str or mem_str in ["0", "N/A", "None", "Unknown"]:
            return 0.0
        
        # ReqMem may have a scope suffix (for example, 15Gn or 2Gc).
        # MaxRSS normally has no scope suffix, but accepting it here makes
        # the parser work with both fields.
        match = re.match(r"^(\d+(?:\.\d+)?)([KMGTP]?)(?:[CN])?$", mem_str.upper())
        if not match:
            return 0.0
        
        val, unit = match.groups()
        val = float(val)
        
        if not unit: return val
            
        units = {'K': 1, 'M': 1024, 'G': 1024**2, 'T': 1024**3, 'P': 1024**4}
        return val * units.get(unit, 1)

    def parse_tres_memory(self, tres_str: str) -> float:
        """Extracts the memory value from a Slurm TRES usage string."""
        if not tres_str:
            return 0.0

        match = re.search(r"(?:^|,)MEM=(\d+(?:\.\d+)?)([KMGTP]?)", tres_str.upper())
        if not match:
            return 0.0
        return self.parse_memory(''.join(match.groups()))

    def parse_tres_number(self, tres_str: str, name: str) -> float:
        """Extracts a numeric value from a Slurm TRES usage string."""
        if not tres_str:
            return 0.0
        match = re.search(
            rf"(?:^|,){re.escape(name.upper())}=(\d+(?:\.\d+)?)",
            tres_str.upper()
        )
        return float(match.group(1)) if match else 0.0

    def parse_gpu_count(self, tres_str: str) -> float:
        return max(
            self.parse_tres_number(tres_str, "GRES/GPU"),
            self.parse_tres_number(tres_str, "GPU")
        )

    def parse_gpu_utilization(self, tres_str: str) -> float:
        return max(
            self.parse_tres_number(tres_str, "GRES/GPUUTIL"),
            self.parse_tres_number(tres_str, "GPUUTIL")
        )

    def get_jobs(self, job_ids: List[str]) -> List[JobMetrics]:
        output = self._run_sacct(job_ids)
        if not output.strip():
            return []

        jobs_map: Dict[str, Dict[str, Any]] = {}
        
        for line in output.strip().split('\n'):
            parts = [part.strip() for part in line.split('|')]
            if len(parts) < 15:
                continue

            full_id = parts[0]
            base_id = full_id.split('.')[0]
            
            if base_id not in jobs_map:
                jobs_map[base_id] = {
                    'job_id': base_id, 'user': 'unknown', 'group': 'unknown',
                    'state': 'unknown', 'cluster': 'unknown', 'cpus': 1,
                    'nodes': 1, 'req_mem_kb': 0.0, 'walltime_sec': 0.0,
                    'cpu_util_sec': 0.0, 'max_rss_kb': 0.0, 'exit_code': '0',
                    # The main sacct record is an aggregate on some Slurm
                    # versions, while on others the values are only present
                    # in the individual steps. Keep both representations and
                    # choose the appropriate one after all rows are read.
                    'main_cpu_sec': 0.0, 'step_cpu_sec': 0.0,
                    'step_cpu_found': False, 'tres_mem_kb': 0.0,
                    'gpus': 0.0, 'gpu_utilization': 0.0
                }

            if '.' in full_id:
                # Sub-step (e.g., .batch): contains usage metrics
                step_rss = self.parse_memory(parts[9])
                jobs_map[base_id]['max_rss_kb'] = max(
                    jobs_map[base_id]['max_rss_kb'], step_rss,
                    self.parse_tres_memory(parts[14]),
                    self.parse_tres_memory(parts[13])
                )
                ave_gpu = self.parse_gpu_utilization(parts[12])
                if ave_gpu > 0:
                    jobs_map[base_id]['gpu_utilization'] = ave_gpu
                step_cpu = self.parse_time(parts[10])
                if step_cpu > 0:
                    jobs_map[base_id]['step_cpu_sec'] += step_cpu
                    jobs_map[base_id]['step_cpu_found'] = True
            else:
                # Main Job record: contains metadata
                jobs_map[base_id].update({
                    'user': parts[1] if parts[1] else 'unknown',
                    'group': parts[2] if parts[2] else 'unknown',
                    'state': parts[3] if parts[3] else 'unknown',
                    'cluster': parts[4] if parts[4] else 'unknown',
                    'cpus': int(parts[5]) if (parts[5] and parts[5].isdigit()) else 1,
                    'req_mem_kb': self.parse_memory(parts[6]),
                    'walltime_sec': self.parse_time(parts[7]),
                    'exit_code': parts[8] if parts[8] else '0'
                })
                jobs_map[base_id]['main_cpu_sec'] = self.parse_time(parts[10])

                # MaxRSS is often present on the main record instead of the
                # step records. Do not replace a larger step value.
                jobs_map[base_id]['max_rss_kb'] = max(
                    jobs_map[base_id]['max_rss_kb'], self.parse_memory(parts[9]),
                    self.parse_tres_memory(parts[14]),
                    self.parse_tres_memory(parts[13])
                )
                jobs_map[base_id]['gpus'] = self.parse_gpu_count(parts[11])
                ave_gpu = self.parse_gpu_utilization(parts[12])
                if ave_gpu > 0:
                    jobs_map[base_id]['gpu_utilization'] = ave_gpu

        results = []
        for b_id, data in jobs_map.items():
            # Only include if we actually found a job record (has state/user)
            if data['user'] == 'unknown' and data['state'] == 'unknown':
                continue

            m = JobMetrics(
                job_id=data['job_id'], user=data['user'], group=data['group'],
                state=data['state'], cluster=data['cluster'], cpus=data['cpus'],
                nodes=data['nodes'], req_mem_kb=data['req_mem_kb'],
                walltime_sec=data['walltime_sec'],
                cpu_util_sec=(data['step_cpu_sec'] if data['step_cpu_found']
                              else data['main_cpu_sec']),
                max_rss_kb=data['max_rss_kb'], gpus=data['gpus'],
                gpu_utilization=data['gpu_utilization'],
                exit_code=data['exit_code']
            )

            # Calculate efficiencies
            if m.walltime_sec > 0 and m.cpus > 0:
                m.cpu_efficiency = (m.cpu_util_sec / (m.walltime_sec * m.cpus)) * 100
            if m.req_mem_kb > 0:
                m.mem_efficiency = (m.max_rss_kb / m.req_mem_kb) * 100
            
            results.append(m)
            
        return results

def format_seconds_to_time(seconds: float) -> str:
    if seconds <= 0: return "00:00:00"
    days = int(seconds // 86400)
    seconds %= 86400
    hours = int(seconds // 3600)
    seconds %= 3600
    minutes = int(seconds // 60)
    seconds %= 60
    day_str = f"{days}-" if days > 0 else ""
    return f"{day_str}{hours:02}:{minutes:02}:{seconds:02.0f}"

def format_bytes_to_human(kb: float) -> str:
    if kb <= 0: return "0.00 B"
    units = ['K', 'M', 'G', 'T', 'P']
    exp = int(math.floor(math.log(kb, 1024))) if kb > 0 else 0
    exp = min(exp, len(units) - 1)
    val = kb / (1024**exp)
    return f"{val:.2f} {units[exp]}B"

def print_job_report(job: JobMetrics):
    print(f"\n{Colors.BOLD}Job ID:{Colors.RESET} {job.job_id}")
    if job.state.startswith("COMPLETED"):
        state_str = f"{Colors.GREEN}{job.state}{Colors.RESET}"
    elif job.state.startswith("FAILED"):
        state_str = f"{Colors.RED}{job.state} (exit code {job.exit_code}){Colors.RESET}"
    elif job.state.startswith("RUNNING"):
        state_str = f"{Colors.YELLOW}{job.state}{Colors.RESET}"
    else:
        state_str = job.state

    print(f"{Colors.BOLD}Cluster:{Colors.RESET} {job.cluster}")
    print(f"{Colors.BOLD}User/Group:{Colors.RESET} {job.user}/{job.group}")
    print(f"{Colors.BOLD}State:{Colors.RESET} {state_str}")

    if job.state in ["PENDING", "RUNNING"]:
        print(f"{Colors.YELLOW}Warning: Efficiency statistics only available after job ends.{Colors.RESET}")
        return

    print(f"{Colors.BOLD}Cores:{Colors.RESET} {job.cpus}")
    if job.walltime_sec > 0:
        print(f"{Colors.BOLD}CPU Utilized:{Colors.RESET} {format_seconds_to_time(job.cpu_util_sec)}")
        print(f"{Colors.BOLD}CPU Efficiency:{Colors.RESET} {job.cpu_efficiency:.2f}% of {format_seconds_to_time(job.walltime_sec * job.cpus)} core-walltime")
        print(f"{Colors.BOLD}Job Wall-clock time:{Colors.RESET} {format_seconds_to_time(job.walltime_sec)}")
        print(f"{Colors.BOLD}Memory Utilized:{Colors.RESET} {format_bytes_to_human(job.max_rss_kb)}")
        if job.req_mem_kb > 0:
            print(f"{Colors.BOLD}Memory Efficiency:{Colors.RESET} {job.mem_efficiency:.2f}% of {format_bytes_to_human(job.req_mem_kb)}")
    if job.gpus > 0:
        print(f"{Colors.BOLD}GPUs:{Colors.RESET} {job.gpus:g}")
        if job.gpu_utilization > 0:
            print(f"{Colors.BOLD}GPU Efficiency:{Colors.RESET} {job.gpu_utilization:.2f}%")
        else:
            print(f"{Colors.YELLOW}GPU utilization statistics are not available.{Colors.RESET}")

def main():
    parser = argparse.ArgumentParser(description="Seff: Slurm efficiency tool (Python version)")
    parser.add_argument('job_ids', nargs='*', help='One or more Slurm Job IDs')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')
    parser.add_argument('--monitor', action='store_true',
                        help='Collect live CPU, memory and GPU metrics')
    parser.add_argument('--output-dir', default='~/public_html/seff',
                        help='Directory for live metric JSON files')
    parser.add_argument('--interval', type=float, default=10,
                        help='Live monitoring interval in seconds')
    
    args = parser.parse_args()

    if args.monitor:
        if len(args.job_ids) > 1:
            parser.error('--monitor accepts at most one job ID')
        job_id = args.job_ids[0] if args.job_ids else os.environ.get('SLURM_JOB_ID')
        if not job_id:
            parser.error('--monitor requires a job ID or SLURM_JOB_ID')
        if args.interval <= 0:
            parser.error('--interval must be greater than zero')
        collect_live_metrics(job_id, args.output_dir, args.interval)
        return

    if not args.job_ids:
        parser.error('at least one job ID is required unless --monitor is used')

    parser_obj = SeffParser(debug=args.debug)
    jobs = parser_obj.get_jobs(args.job_ids)

    if not jobs:
        print(f"{Colors.RED}No jobs found or error processing data.{Colors.RESET}")
        sys.exit(1)

    if args.json:
        print(json.dumps([asdict(j) for j in jobs], indent=2))
    else:
        for job in jobs:
            print_job_report(job)

if __name__ == "__main__":
    main()
