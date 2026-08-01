#!/bin/bash
# led-update.sh - LED-Status fuer UGREEN iDX6011 (non-Pro) unter TrueNAS SCALE
# Wird per Cron alle 5 Minuten aufgerufen.

SCRIPTPATH=$(dirname "$(readlink -f "$0")")
source "$SCRIPTPATH/ugreen-led-lib.sh"

# --- KONFIGURATION ---
BRIGHTNESS=64              # Helligkeit (0-255)
COLOR_POWER_OK="0 0 255"   # Blau  - System gesund
COLOR_POWER_WARN="255 128 0" # Orange - Pool degraded
COLOR_NET_10G="255 255 255"  # Weiss  - 10 Gbit
COLOR_NET_25G="255 200 0"    # Gelb   - 2.5/5 Gbit
COLOR_NET_NORM="255 128 0"   # Orange - 1 Gbit
COLOR_NET_LACP="128 0 255"   # Violett - LACP aktiv
COLOR_OK="0 255 0"         # Gruen - Platte OK
COLOR_ERROR="255 0 0"      # Rot   - Fehler

BLINK_ON=500
BLINK_OFF=500

# HCTL-Mapping Schacht -> SCSI-Adresse.
# Noch nicht ermittelt: aktuell sind keine SATA-Platten verbaut.
# Zum Ermitteln: Platte in Schacht stecken und `lsblk -S -o NAME,HCTL` pruefen.
declare -A hctl_map
# Am 2026-08-01 auf iDX6011 non-Pro durch Umstecken einer Platte verifiziert.
# Schacht -> ata -> HCTL:  1->ata3, 2->ata4, 3->ata5, 4->ata6, 5->ata1, 6->ata2
hctl_map[disk1]="2:0:0:0"
hctl_map[disk2]="3:0:0:0"
hctl_map[disk3]="4:0:0:0"
hctl_map[disk4]="5:0:0:0"
hctl_map[disk5]="0:0:0:0"
hctl_map[disk6]="1:0:0:0"

ZPOOL_STATUS=$(zpool status 2>/dev/null)

# --- 1. Power-LED: Gesamtzustand der Pools ---
if echo "$ZPOOL_STATUS" | grep -qE "state: (DEGRADED|FAULTED|OFFLINE|UNAVAIL|REMOVED)"; then
    led_set power $COLOR_POWER_WARN $BRIGHTNESS
    led_blink power $BLINK_ON $BLINK_OFF
else
    led_set_steady power $COLOR_POWER_OK $BRIGHTNESS
fi

# --- 2. Netzwerk-LED ---
# Wird NICHT hier gesetzt, sondern von led-network.sh (Daemon, 2s-Takt),
# damit die Blinkfrequenz den tatsaechlichen Durchsatz abbilden kann.

# --- 3. Platten-LEDs ---
for led in disk1 disk2 disk3 disk4 disk5 disk6; do
    hctl_port="${hctl_map[$led]}"

    if [ -z "$hctl_port" ]; then
        # Kein Mapping hinterlegt -> LED aus
        led_off "$led"
        continue
    fi

    dev=$(lsblk -S -n -o NAME,HCTL 2>/dev/null | awk -v h="$hctl_port" '$2 == h {print $1}')

    if [ -z "$dev" ]; then
        # Schacht leer
        led_off "$led"
        continue
    fi

    DISK_COLOR=$COLOR_OK
    DISK_FAULT=0

    uuids=$(lsblk -n -o PARTUUID "/dev/$dev" 2>/dev/null | grep -v "^$")
    for id in $dev ${dev}1 ${dev}2 $uuids; do
        line=$(echo "$ZPOOL_STATUS" | grep -w "$id")
        if [ -n "$line" ]; then
            if ! echo "$line" | grep -Eq "ONLINE[[:space:]]+0[[:space:]]+0[[:space:]]+0"; then
                DISK_COLOR=$COLOR_ERROR
                DISK_FAULT=1
            fi
        fi
    done

    if [ "$DISK_FAULT" = "1" ]; then
        led_set "$led" $DISK_COLOR $BRIGHTNESS
        led_blink "$led" $BLINK_ON $BLINK_OFF
    else
        led_set_steady "$led" $DISK_COLOR $BRIGHTNESS
    fi
done

exit 0
