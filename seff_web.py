#!/usr/bin/env python3
"""Install a dependency-free static dashboard for live seff metrics."""

import argparse
import pathlib


PAGE = r'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>seff live metrics</title>
  <style>
    body{font:16px system-ui,sans-serif;max-width:760px;margin:2rem auto;padding:0 1rem;color:#17202a}
    input,button{font:inherit;padding:.5rem}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1rem;margin-top:1.5rem}
    .card{border:1px solid #ddd;border-radius:8px;padding:1rem}.value{font-size:1.7rem;font-weight:700;margin-top:.4rem}
    #status{color:#666}.error{color:#a00}
  </style>
</head>
<body>
  <h1>seff live metrics</h1>
  <form id="form"><input id="job" placeholder="Job ID" required><button>Load</button></form>
  <p id="status">Enter a job ID. Refresh interval: 10 seconds.</p>
  <div class="grid">
    <div class="card">CPU<div class="value" id="cpu">—</div></div>
    <div class="card">Memory<div class="value" id="memory">—</div></div>
    <div class="card">GPU utilization<div class="value" id="gpu">—</div></div>
    <div class="card">GPU memory<div class="value" id="gpumem">—</div></div>
  </div>
  <script>
    const q=id=>document.getElementById(id); let timer;
    function formatMemory(kb){if(!kb)return '—';let n=kb,u='KB';if(n>1024){n/=1024;u='MB'}if(n>1024){n/=1024;u='GB'}return n.toFixed(2)+' '+u}
    async function load(){const id=q('job').value.trim();if(!id)return;try{
      const r=await fetch('metrics/'+encodeURIComponent(id)+'.json?'+Date.now());if(!r.ok)throw Error('metrics not found');const d=await r.json();
      q('cpu').textContent=d.cpu_percent==null?'—':d.cpu_percent.toFixed(2)+'%';q('memory').textContent=formatMemory(d.memory_used_kb);
      q('gpu').textContent=d.gpu.utilization_percent==null?'—':d.gpu.utilization_percent.toFixed(2)+'%';q('gpumem').textContent=d.gpu.memory_used_mb==null?'—':d.gpu.memory_used_mb+' MB';
      q('status').textContent='Job '+d.job_id+' · '+d.user+' · updated '+d.updated_at;q('status').className='';
    }catch(e){q('status').textContent=e.message;q('status').className='error'} }
    q('form').addEventListener('submit',e=>{e.preventDefault();clearInterval(timer);load();timer=setInterval(load,10000)});
    const id=new URLSearchParams(location.search).get('job');if(id){q('job').value=id;q('form').requestSubmit()}
  </script>
</body></html>
'''


def main():
    parser = argparse.ArgumentParser(description="Install the seff live metrics dashboard")
    parser.add_argument("output_dir", help="Directory served as public_html/seff")
    args = parser.parse_args()
    target = pathlib.Path(args.output_dir).expanduser()
    (target / "metrics").mkdir(parents=True, exist_ok=True)
    (target / "index.html").write_text(PAGE)
    print(f"Installed seff dashboard in {target}")


if __name__ == "__main__":
    main()
