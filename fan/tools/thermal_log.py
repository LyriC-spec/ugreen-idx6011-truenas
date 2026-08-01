#!/usr/bin/env python3
"""Protokolliert Temperaturen und Luefterdrehzahlen. NUR LESEND, kein Eingriff."""
import os, time, subprocess
DATA, CMD, EC_READ = 0x62, 0x66, 0x80
OUT = "/mnt/nvme-tank/scripts/fancontrol/thermal-baseline.log"
fd = os.open("/dev/port", os.O_RDWR)
def outb(p,v): os.pwrite(fd, bytes([v]), p)
def inb(p):    return os.pread(fd, 1, p)[0]
def w(mask, want, t=1.0):
    s=time.time()
    while time.time()-s<t:
        if bool(inb(CMD)&mask)==want: return True
        time.sleep(0.001)
    return False
def ec_read(a):
    if not w(0x02, False): return None
    outb(CMD, EC_READ)
    if not w(0x02, False): return None
    outb(DATA, a)
    if not w(0x01, True):  return None
    return inb(DATA)
def hw(name):
    best=-1; base="/sys/class/hwmon"
    for d in os.listdir(base):
        try:
            if open(f"{base}/{d}/name").read().strip()!=name: continue
            for f in os.listdir(f"{base}/{d}"):
                if f.startswith("temp") and f.endswith("_input"):
                    v=int(open(f"{base}/{d}/{f}").read().strip())//1000
                    if 0<v<150: best=max(best,v)
        except Exception: pass
    return best
def net():
    b=-1
    for i in os.listdir("/sys/class/net"):
        if i!="lo": b=max(b, hw(i))
    return b
def gpu():
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=temperature.gpu",
                          "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10)
        return int(r.stdout.strip().split("\n")[0])
    except Exception: return -1

start=time.time()
with open(OUT,"a",buffering=1) as f:
    f.write(f"\n# Start {time.strftime('%Y-%m-%d %H:%M:%S')} - Leerlauf, Gehaeuse geschlossen\n")
    f.write(f"{'min':>5} {'CPU':>4} {'NVMe':>5} {'SATA':>5} {'Net':>4} {'GPU':>4} {'Fan1':>6} {'Fan2':>6}\n")
    while time.time()-start < 3600:
        r={a:ec_read(a) for a in (0x96,0x97,0x98,0x99)}
        f1=((r[0x96]<<8)|r[0x97]) if None not in r.values() else -1
        f2=((r[0x98]<<8)|r[0x99]) if None not in r.values() else -1
        f.write(f"{(time.time()-start)/60:>5.1f} {hw('coretemp'):>4} {hw('nvme'):>5} "
                f"{hw('drivetemp'):>5} {net():>4} {gpu():>4} {f1:>6} {f2:>6}\n")
        time.sleep(30)
os.close(fd)
