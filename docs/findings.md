# What doesn't work — and why

This document matters more than the code. It records which obvious routes were
tried and where they failed. Without these notes you end up trying the
seemingly easier path again a year from now.

Everything established on 2026-08-01 on a UGREEN iDX6011 **non-Pro** running
TrueNAS SCALE 26.0.0-BETA.2.

---

## LEDs

### `ugreen_leds_cli` sets brightness to 0

The iDX fork [klein0r/ugreen_leds_controller](https://github.com/klein0r/ugreen_leds_controller)
detects the iDX6011 correctly via DMI and reads all LEDs cleanly. However:

**Every invocation of the CLI sets the brightness of the addressed LED to 0** —
including a plain `-status`. The LED goes dark as a result.

How to observe it: set the colour via raw `i2cset`, set brightness to 255 via
`i2cset` — the LED lights up. Then run `ugreen_leds_cli power -status` — the LED
goes out. The status output consistently reports `brightness = 0` afterwards,
while the colour was applied correctly.

**Consequence:** the CLI is unusable on this model. We talk to the MCU directly
via `i2cset`. The protocol itself works perfectly — the bug is in the CLI, not
in the hardware.

The compiled binary is still kept in the repo for reference; it is useful for
inspecting the current state of all LEDs (just re-apply them afterwards).

### There are no prebuilt binaries for the iDX6011

For the DX/DXP series,
[miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller)
ships releases. The iDX series needs the klein0r fork — and that has **no
releases**. The CLI has to be built from source.

TrueNAS has no compiler. The build still works in a throwaway container:

```bash
docker run --rm -v /mnt/<pool>/scripts/leds_controller:/out debian:bookworm bash -c '
  apt-get update -qq && apt-get install -y -qq git build-essential libi2c-dev
  git clone -q --depth 1 https://github.com/klein0r/ugreen_leds_controller /src
  cd /src/cli && make && cp ugreen_leds_cli /out/'
```

The makefile already links statically. Nothing is installed on the host.

### The kernel module route is a dead end

Obvious, but wrong: the installer script
[0x556c79/install_ugreen_leds_controller](https://github.com/0x556c79/install_ugreen_leds_controller)
looks for a **prebuilt kernel module** matching the TrueNAS version. Only builds
up to Goldeye (25.10) exist — neither repository has anything for 26.0.x, and it
aborts cleanly:

```
Detected TrueNAS version: 26.0.0
Unsupported TrueNAS SCALE version: 26.0.0.
No precompiled kernel module found in repository.
```

**The module isn't needed at all.** It provides `/sys/class/leds` entries and
triggers; plain status display works fine with userspace I²C access. Skipping it
is in fact the more robust route, since no kernel update can break it.

### The non-Pro has one network LED fewer

The Pro model has two network LEDs (`network_stat`, `network_stat2`), the
non-Pro only one. This shifts the **entire drive chain by one index**, and
`0x08` does not exist.

Anyone adopting the Pro mapping will wonder about a dark first drive LED and one
that never responds. See [hardware.md](hardware.md) for the correct table.

### Blinking doesn't stop by itself

The MCU keeps blinking autonomously until actively stopped. If you simply stop
sending blink commands, you get a permanently blinking LED.

The mode reset (`0x04` with zeros) switches the LED **off** in the process — a
subsequent `0x03` with `0xFF` is mandatory to bring it back. Without it the LED
stays dark even though colour and brightness are set.

---

## Fans

### `it87` fundamentally does not work here

On the DXP6800 Pro, fan control goes through an `it8613` Super I/O chip and the
[IT-Kuny driver](https://github.com/IT-Kuny/UGREEN-DXP-FAN-NAS-Driver). That
**cannot** be transferred to the iDX6011.

The iDX6011 has no Super I/O chip but an **ITE IT5571 embedded controller**.
`modprobe it87` accordingly returns `No such device` — including the `it87.ko`
already shipped in the TrueNAS kernel. The IT-Kuny repository consistently does
not list the iDX6011 as supported.

As an aside: kernel headers *are* present on TrueNAS
(`/usr/src/linux-headers-truenas-production-amd64`, `hwmon-vid.ko`, BTF under
`/sys/kernel/btf/vmlinux`) — so building a module would be technically possible.
It just wouldn't help here.

### `ug-fand` drives both fans in lockstep

[ug-fand](https://github.com/Reevoy24/ugreen-idx6011-panel) works and is cleanly
built — it is where the EC register map came from. But it drives **both fans
with the same value** and has no notion of GPU temperature.

For the standard case (two equivalent chassis fans) that is correct. Anyone with
a dedicated fan for an expansion card on one header needs independent control —
hence the custom daemon.

Two pitfalls when trying it out:
* The binary has **no `--help` option**. It immediately starts as a daemon and
  takes over the fans instead.
* After termination the last written values persist — the fans do **not**
  automatically return to a safe value.

### The enable byte is easy to miss

The most striking mistake in our own development: we only wrote the duty
registers (`0x9d`/`0x9f`), not the enable bytes (`0x9c`/`0x9e`).

The EC then only partially accepts the value. Measured concretely: duty 198
produced **5557 RPM instead of 7435 RPM** — roughly a quarter of the speed given
away while the GPU was under full load. From the outside it looks as if the
control loop were "tuned too quiet".

After a reboot the enable bytes sit at `0`. That does **not** mean "fans off",
it means "firmware controls this itself" — the fans do spin.

### The firmware enforces a minimum speed

The EC does not hand over control entirely. Once things get warm (CPU from
around 55 °C), it holds fan 1 near full speed regardless of the lower value we
write. Only with a cool CPU does our value take effect.

Measured under full GPU load: duty 150 and duty 195 produced **1918 and 1916
RPM** respectively — practically identical. With a cold CPU, duty 150 yields
around 1530 RPM instead.

Two consequences:
* The measured curve only holds in the cool state.
* An explicit "fan 1 at least X % of fan 2" coupling is unnecessary — the
  hardware already does it. When the GPU gets hot, the CPU is under load too and
  fan 1 is already up.

This is a useful safety net: even a crashed daemon or a badly designed curve
will not lead to overheating.

**In everyday operation this rarely kicks in.** An analysis of 10,104 log lines
from normal operation found CPU temperatures between 38 and 91 °C, but only
**1.9 % of samples above 55 °C**. The only duty value that occurred often enough
with both a cool and a warm CPU showed no difference:

| Duty | CPU < 55 °C | CPU ≥ 55 °C |
|---:|---:|---:|
| 119 | 1278 RPM (n=41) | 1256 RPM (n=6) |

That does not disprove the effect described above — the A/B test ran under full
GPU load, where the CPU sits well above 55 °C. But the threshold at which the
firmware noticeably overrides appears to be higher than 55 °C, and in ordinary
operation the daemon controls fan 1 unimpeded. Measuring the effect properly
requires deliberate load rather than production data.

### NVMe: only evaluate `Composite`

NVMe drives report several sensors. `Composite` is the official value with
warning and critical thresholds — the one SMART and the TrueNAS reports display.
Alongside it are `Sensor 1`/`Sensor 2` (internal measurement points, usually the
controller).

On this machine the cheap boot NVMe (YSO128) reports a `Sensor 1` sitting at
~51 °C permanently, while its `Composite` reads 35 °C — **a 16-degree gap, with
no defined limit for the hotter sensor**.

Taking the maximum across all sensors means controlling on a meaningless value
from the least important drive in the system: fan 1 ran at duty 96–110 instead
of an appropriate 52, while the actual pool drives sat comfortably at 37 °C.

This only becomes apparent when comparing against the TrueNAS reports — their
values differed noticeably from the daemon's.

---

## Tesla T4 in this chassis

Notes on a passively cooled Tesla T4 in the iDX6011, cooled by a dedicated fan
on the second header.

**The slot reports `SlotPowerLimit 25W`** — with no consequence. `nvidia-smi`
reports a 70 W limit, and the card draws it. The PCIe link runs at x8 instead of
x16 (`Width x8 (downgraded)`), which is functionally uncritical.

**Driver:** do not install manually. TrueNAS ships suitable drivers, enabled via
`midclt call --job docker.update '{"nvidia": true}'` or the web UI. Here: driver
590.44.01, CUDA 13.1.

**Load test (`gpu-burn`, 10 minutes, closed chassis):** the card settles at
**76–78 °C** with the GPU fan at full speed.

What matters is the cause of the clock drop from 1590 to ~765 MHz:

```
SW Power Cap:          Active
HW Thermal Slowdown:   Not Active
SW Thermal Slowdown:   Not Active
```

The card is **power-limited, not thermally limited**; all thermal slowdown
counters read 0 µs. Cooling is therefore adequate, and lowering the power limit
(`nvidia-smi -pl`) would solve a problem that does not exist.

Looking at temperature alone leads easily to the opposite conclusion — querying
the throttle reasons is the only reliable way to tell.
