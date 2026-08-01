#!/usr/bin/env python3
"""A/B-Test: bringt 30% mehr Drehzahl bei Luefter 1 der GPU etwas?
Phase A: Luefter 1 auf 150 (Wert der Regelung).  Phase B: 195 (+30%).
Luefter 2 durchgehend Vollast. Abbruch bei GPU>=84C oder CPU>=92C."""
import os, time, subprocess
DATA, CMD, EC_READ, EC_WRITE = 0x62, 0x66, 0x80, 0x81
F1_EN, F1_DUTY, F2_EN, F2_DUTY = 0x9c, 0x9d, 0x9e, 0x9f
OUT = "/mnt/nvme-tank/scripts/fancontrol/ab-test.log"
SETTLE, SAMPLE = 210, 60      # Einschwingen, danach Mittelwert-Fenster

fd = os.open("/dev/port", os.O_RDWR)
def outb(p,v): os.pwrite(fd, bytes([v]), p)
def inb(p):    return os.pread(fd, 1, p)[0]
def wt(m,w,t=1.0):
    s=time.time()
    while time.time()-s<t:
        if bool(inb(CMD)&m)==w: return True
        time.sleep(0.001)
    return False
def rd(a):
    if not wt(0x02,False): return None
    outb(CMD,EC_READ);  wt(0x02,False)
    outb(DATA,a)
    if not wt(0x01,True): return None
    return inb(DATA)
def wr(a,v):
    if not wt(0x02,False): return False
    outb(CMD,EC_WRITE); wt(0x02,False)
    outb(DATA,a);       wt(0x02,False)
    outb(DATA,v)
    return wt(0x02,False)
def gpu():
    try:
        r=subprocess.run(["nvidia-smi","--query-gpu=temperature.gpu,power.draw",
                          "--format=csv,noheader,nounits"],capture_output=True,text=True,timeout=10)
        p=[x.strip() for x in r.stdout.strip().split(",")]
        return int(p[0]), float(p[1])
    except Exception: return -1,-1.0
def cpu():
    best,base=-1,"/sys/class/hwmon"
    for d in os.listdir(base):
        try:
            if open(base+"/"+d+"/name").read().strip()!="coretemp": continue
            for f in os.listdir(base+"/"+d):
                if f.startswith("temp") and f.endswith("_input"):
                    v=int(open(base+"/"+d+"/"+f).read().strip())//1000
                    if 0<v<150: best=max(best,v)
        except Exception: pass
    return best

def phase(name, duty1, f):
    wr(F2_EN,1); wr(F2_DUTY,198)
    wr(F1_EN,1); wr(F1_DUTY,duty1)
    f.write("# %s: Luefter1 duty=%d\n" % (name, duty1))
    t0=time.time(); gs=[]; cs=[]; ws=[]
    while time.time()-t0 < SETTLE+SAMPLE:
        g,w = gpu(); c = cpu()
        if time.time()-t0 >= SETTLE:
            gs.append(g); cs.append(c); ws.append(w)
        if g>=84 or c>=92:
            f.write("# ABBRUCH: GPU %d CPU %d\n" % (g,c)); return None
        time.sleep(5)
    f1=(rd(0x96)<<8)|rd(0x97); f2=(rd(0x98)<<8)|rd(0x99)
    gm=sum(gs)/len(gs); cm=sum(cs)/len(cs); wm=sum(ws)/len(ws)
    f.write("  Fan1 %d RPM | Fan2 %d RPM | GPU %.1f C | CPU %.1f C | %.1f W\n"
            % (f1,f2,gm,cm,wm))
    return gm, cm, f1

try:
    with open(OUT,"a",buffering=1) as f:
        f.write("\n# A/B-Test %s\n" % time.strftime("%Y-%m-%d %H:%M:%S"))
        a = phase("Phase A (Normalbetrieb)", 150, f)
        b = phase("Phase B (+30%)",          195, f) if a else None
        if a and b:
            f.write("\n# ERGEBNIS: GPU %.1f -> %.1f C  (Differenz %+.1f C)\n" % (a[0], b[0], b[0]-a[0]))
            f.write("#           CPU %.1f -> %.1f C  (Differenz %+.1f C)\n" % (a[1], b[1], b[1]-a[1]))
            f.write("#           Fan1 %d -> %d RPM\n" % (a[2], b[2]))
finally:
    for _ in range(3):
        wr(F1_EN,1); wr(F1_DUTY,198); wr(F2_EN,1); wr(F2_DUTY,198)
        time.sleep(0.3)
    os.close(fd)
