# UGREEN NASync iDX6011 (non-Pro) on TrueNAS SCALE

LED and fan control for the UGREEN iDX6011 **non-Pro** running TrueNAS SCALE.
Both run entirely in userspace — **no kernel module required**, which keeps them
independent of the TrueNAS version and safe across updates.

Tested on TrueNAS SCALE 26.0.0-BETA.2 (kernel 6.18.23-production+truenas).

> **Why custom scripts instead of the existing projects?**
> The common solutions either don't fit this model or only cover half of it.
> The reasons are in [docs/findings.md](docs/findings.md) — please read that
> before trying one of the standard routes. It will save you hours.

## What it does

**LEDs** — power, network, and six drive LEDs on the front panel:

| LED | Behaviour |
|---|---|
| power | Blue = all pools ONLINE · Amber blinking = degraded/faulted |
| network | Colour by link speed, blink rate by **actual throughput** |
| disk1–6 | Green = drive present and healthy · Red blinking = ZFS errors · Off = empty bay |

**Fans** — the two headers are controlled **independently**:

| Header | Driven by |
|---|---|
| Fan 1 (chassis) | highest demand across CPU, drives, and network controllers |
| Fan 2 | GPU temperature (here: a dedicated fan for a Tesla T4) |

With smoothing to prevent speed hunting, and emergency thresholds that override
everything else.

## Layout

```
leds/
  ugreen-led-lib.sh   Library: colour, brightness, blinking via i2cset
  led-update.sh       Power and drive LEDs (cron, every 5 min)
  led-network.sh      Network LED with throughput display (daemon, 2s interval)
fan/
  fan-control.py      Fan daemon with independent curves
  tools/              Diagnostic and measurement tools (see below)
docs/
  hardware.md         Registers, indices, mappings, measured curves
  findings.md         What doesn't work, and why
```

## Installation

The scripts belong on a **dataset in the pool**, not in a system directory —
the TrueNAS root filesystem is read-only and gets replaced on updates.

```bash
zfs create <pool>/scripts
mkdir -p /mnt/<pool>/scripts/{leds_controller,fancontrol}
```

Copy the scripts there, make them executable, then register them in the web UI
under **System Settings → Advanced**:

| Type | When | Command |
|---|---|---|
| Command | PREINIT | `modprobe i2c-i801 && modprobe i2c-dev` |
| Command | POSTINIT | `/mnt/<pool>/scripts/leds_controller/led-update.sh` |
| Command | POSTINIT | `setsid nohup /mnt/<pool>/scripts/leds_controller/led-network.sh > /dev/null 2>&1 < /dev/null &` |
| Command | POSTINIT | `setsid nohup /mnt/<pool>/scripts/fancontrol/fan-control.py > /dev/null 2>&1 < /dev/null &` |

Plus a cron job running as `root` every 5 minutes:
`/mnt/<pool>/scripts/leds_controller/led-update.sh`

**Adjust the paths:** the scripts have `/mnt/nvme-tank/scripts/...` hardcoded
near the top of each file.

## Tuning

Colours, thresholds, and curves are constants at the top of each file. The fan
curves in `fan-control.py` are deliberately conservative — the NVMe drives in
this machine only become critical at 87 °C, while the curve already reaches full
speed at 58 °C. If you value quiet over cooling headroom, raise the thresholds
considerably.

## Tools

| Tool | Purpose |
|---|---|
| `fan/tools/ec_read.py` | Read current fan speeds and control values |
| `fan/tools/ec_calib.py` | Record a duty-to-RPM curve, with a temperature abort |
| `fan/tools/thermal_log.py` | Log temperatures over time |
| `fan/tools/loadtest_log.py` | Record measurements during a load test |
| `fan/tools/ab_test.py` | A/B comparison of two fan settings |

Every tool except `ec_calib.py` and `ab_test.py` is read-only.

## Safety note

Wrong values in fan registers can overheat hardware. These scripts always fall
back to **full speed** on error, on shutdown, and above the emergency thresholds
— verify that this still holds after your own changes. Only record a curve with
temperature monitoring and an abort condition in place.

The EC firmware additionally enforces a minimum fan speed once things get warm
(see [docs/findings.md](docs/findings.md)) — a safety net underneath everything
running here.

## License and credits

The LED protocol knowledge comes from the reverse-engineering work in
[miskcoo/ugreen_leds_controller](https://github.com/miskcoo/ugreen_leds_controller)
and the iDX fork by
[klein0r](https://github.com/klein0r/ugreen_leds_controller);
the EC register map comes from
[ugreen-idx6011-panel](https://github.com/Reevoy24/ugreen-idx6011-panel).
Thanks to their authors — none of this would have been possible without that
groundwork.
