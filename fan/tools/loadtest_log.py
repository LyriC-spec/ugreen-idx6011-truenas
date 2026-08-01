#!/usr/bin/env python3
"""Protokolliert waehrend des GPU-Lasttests. NUR LESEND."""
import os, time, subprocess
DATA, CMD, EC_READ = 0x62, 0x66, 0x80
OUT = "/mnt/nvme-tank/scripts/fancontrol/loadtest.log"
fd = os.open("/dev/port", os.O_RDWR)
def outb(p,v): os.pwrite(fd, bytes([v]), p)
def inb(p):    return os.pread(fd, 1, p)[0]
def wt(mask, want, t=1.0):
    s=time.time()
    while time.time()-s<t:
        if bool(inb(CMD)&mask)==want: return True
        time.sleep(0.001)
    return False
def ec_read(a):
    if not wt(0x02, False): return None
    outb(CMD, EC_READ)
    if not wt(0x02, False): return None
    outb(DATA, a)
    if not wt(0x01, True):  return None
    return inb(DATA)
def hw(name):
    best, base = -1, "/sys/class/hwmon"
    for d in os.listdir(base):
        try:
            if open(base+"/"+d+"/name").read().strip()!=name: continue
            for f in os.listdir(base+"/"+d):
                if f.startswith("temp") and f.endswith("_input"):
                    v=int(open(base+"/"+d+"/"+f).read().strip())//1000
                    if 0<v<150: best=max(best,v)
        except Exception: pass
    return best
def nvme_comp():
    best, base = -1, "/sys/class/hwmon"
    for d in os.listdir(base):
        try:
            if open(base+"/"+d+"/name").read().strip()!="nvme": continue
            for f in os.listdir(base+"/"+d):
                if not (f.startswith("temp") and f.endswith("_label")): continue
                if open(base+"/"+d+"/"+f).read().strip()!="Composite": continue
                v=int(open(base+"/"+d+"/"+f[:-6]+"_input").read().strip())//1000
                best=max(best,v)
        except Exception: pass
    return best
def net():
    b=-1
    for i in os.listdir("/sys/class/net"):
        if i!="lo": b=max(b, hw(i))
    return b
def gpu():
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=temperature.gpu,power.draw,utilization.gpu,clocks.sm",
                          "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10)
        p=[x.strip() for x in r.stdout.strip().split(",")]
        return int(p[0]), float(p[1]), int(p[2]), int(p[3])
    except Exception:
        return -1,-1.0,-1,-1

start=time.time()
with open(OUT,"a",buffering=1) as f:
    f.write("\n# GPU-Lasttest %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
    f.write("%5s %4s %5s %4s %5s %7s %5s %6s %6s %6s %6s\n" %
            ("min","CPU","NVMe","Net","GPU","Watt","Util","MHz","duty1","Fan1","Fan2"))
    while time.time()-start < 2400:
        g,w,u,mhz = gpu()
        r={a:ec_read(a) for a in (0x96,0x97,0x98,0x99,0x9d,0x9f)}
        ok = None not in r.values()
        f1=((r[0x96]<<8)|r[0x97]) if ok else -1
        f2=((r[0x98]<<8)|r[0x99]) if ok else -1
        d1=r[0x9d] if ok else -1
        f.write("%5.1f %4d %5d %4d %5d %7.1f %5d %6d %6d %6d %6d\n" %
                ((time.time()-start)/60, hw("coretemp"), nvme_comp(), net(),
                 g, w, u, mhz, d1, f1, f2))
        time.sleep(10)
os.close(fd)
