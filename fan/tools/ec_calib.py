#!/usr/bin/env python3
# Nimmt die Luefter-Kennlinie des ITE IT5571 EC auf (UGREEN iDX6011 non-Pro).
# Sicherheit: Abbruch bei GPU>70C oder CPU>75C, am Ende IMMER zurueck auf Vollast.
import os, time, subprocess, sys

DATA, CMD = 0x62, 0x66
EC_READ, EC_WRITE = 0x80, 0x81
SPEED_MAX = 198
DUTY1, DUTY2 = 0x9d, 0x9f     # Geschwindigkeit Luefter 1 / 2
GPU_ABORT, CPU_ABORT = 70, 75

fd = os.open("/dev/port", os.O_RDWR)
def outb(p,v): os.pwrite(fd, bytes([v]), p)
def inb(p):    return os.pread(fd, 1, p)[0]

def w_ibf(t=1.0):
    s=time.time()
    while time.time()-s<t:
        if not (inb(CMD)&0x02): return True
        time.sleep(0.001)
    return False

def w_obf(t=1.0):
    s=time.time()
    while time.time()-s<t:
        if inb(CMD)&0x01: return True
        time.sleep(0.001)
    return False

def ec_read(a):
    if not w_ibf(): return None
    outb(CMD, EC_READ)
    if not w_ibf(): return None
    outb(DATA, a)
    if not w_obf(): return None
    return inb(DATA)

def ec_write(a, v):
    if not w_ibf(): return False
    outb(CMD, EC_WRITE)
    if not w_ibf(): return False
    outb(DATA, a)
    if not w_ibf(): return False
    outb(DATA, v)
    return w_ibf()

def rpm(hi, lo):
    h, l = ec_read(hi), ec_read(lo)
    return (h<<8)|l if h is not None and l is not None else -1

def gpu_temp():
    try:
        out = subprocess.run(["nvidia-smi","--query-gpu=temperature.gpu",
                              "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().split("\n")[0])
    except Exception:
        return -1

def cpu_temp():
    best = -1
    for d in os.listdir("/sys/class/hwmon"):
        p = f"/sys/class/hwmon/{d}/name"
        try:
            if open(p).read().strip() != "coretemp": continue
            for f in os.listdir(f"/sys/class/hwmon/{d}"):
                if f.startswith("temp") and f.endswith("_input"):
                    v = int(open(f"/sys/class/hwmon/{d}/{f}").read().strip())//1000
                    best = max(best, v)
        except Exception:
            pass
    return best

def restore():
    print("\n>>> Setze beide Luefter auf Vollast zurueck ...")
    for _ in range(3):
        ec_write(DUTY1, SPEED_MAX)
        ec_write(DUTY2, SPEED_MAX)
        time.sleep(0.3)
    print(f">>> duty1={ec_read(DUTY1)}  duty2={ec_read(DUTY2)}")

steps = [198, 180, 160, 140, 120, 100, 80, 60, 40]
try:
    print(f"Start: GPU={gpu_temp()}C  CPU={cpu_temp()}C")
    print(f"{'duty':>5} {'Fan1 RPM':>9} {'Fan2 RPM':>9} {'GPU':>5} {'CPU':>5}")
    print("-"*42)
    for s in steps:
        if not ec_write(DUTY1, s) or not ec_write(DUTY2, s):
            print(f"  Schreibfehler bei duty={s}"); break
        time.sleep(8)
        g, c = gpu_temp(), cpu_temp()
        f1 = rpm(0x96, 0x97)
        f2 = rpm(0x98, 0x99)
        print(f"{s:>5} {f1:>9} {f2:>9} {g:>4}C {c:>4}C")
        if g >= GPU_ABORT or c >= CPU_ABORT:
            print(f"\n!!! ABBRUCH: Temperaturgrenze erreicht (GPU {g}C / CPU {c}C)")
            break
finally:
    restore()
    os.close(fd)
