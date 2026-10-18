import re,statistics,sys
def pct(v,p):
    v=sorted(v); k=(len(v)-1)*p/100; f=int(k); c=min(f+1,len(v)-1); return v[f]+(v[c]-v[f])*(k-f)
pat=re.compile(r'fps=([\d.]+) frameP95=([\d.]+)ms submitWaitP95=([\d.]+)ms.*interpolated=(\d+) scaled=(\d+)')
fps=[];fp95=[];sp95=[];interp_total=0;scaled_seen=0;n=0
fn=sys.argv[1]
for line in open(fn):
    m=pat.search(line)
    if not m: continue
    n+=1
    fps.append(float(m.group(1))); fp95.append(float(m.group(2))); sp95.append(float(m.group(3)))
    interp_total+=int(m.group(4))
    if int(m.group(5))>0: scaled_seen+=1
if n==0:
    print(f"{fn}: no samples"); sys.exit(0)
print(f"{fn}: n={n} present_fps med={statistics.median(fps):.2f} frameP95 med={statistics.median(fp95):.3f} p95of={pct(fp95,95):.3f} submitP95 med={statistics.median(sp95):.3f} interp_total={interp_total} rows_scaled>0={scaled_seen}")
