#!/bin/bash
# led-network.sh - Netzwerk-LED mit echter Durchsatzanzeige (UGREEN iDX6011 non-Pro)
#
# Farbe  = Link-Geschwindigkeit bzw. Bond-Modus
# Blinken= tatsaechlicher Durchsatz (rx+tx), je mehr Traffic desto schneller
#
# Laeuft als Daemon, wird per POSTINIT gestartet.

SCRIPTPATH=$(dirname "$(readlink -f "$0")")
source "$SCRIPTPATH/ugreen-led-lib.sh"

BRIGHTNESS=64
INTERVAL=2              # Abtastintervall in Sekunden

COLOR_10G="255 255 255"   # Weiss
COLOR_5G="0 255 255"      # Cyan
COLOR_25G="255 200 0"     # Gelb
COLOR_1G="255 128 0"      # Orange
COLOR_BOND="255 0 255"    # Magenta - Bond/LACP aktiv
COLOR_NOLINK="255 0 0"    # Rot

# Durchsatz-Schwellen in Bytes/s -> Blinkzeiten (an/aus in ms)
# Unterhalb der ersten Schwelle: Dauerlicht ohne Blinken.
THRESH_IDLE=$((    50 * 1024 ))   #  50 KB/s
THRESH_LOW=$((   2 * 1024 * 1024 ))   #   2 MB/s
THRESH_MED=$((  20 * 1024 * 1024 ))   #  20 MB/s
THRESH_HIGH=$(( 80 * 1024 * 1024 ))   #  80 MB/s

PIDFILE=/var/run/led-network.pid

# --- Einzelinstanz sicherstellen ---
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE" 2>/dev/null)" 2>/dev/null; then
    echo "led-network laeuft bereits (PID $(cat "$PIDFILE"))"
    exit 0
fi
echo $$ > "$PIDFILE"
trap 'rm -f "$PIDFILE"' EXIT

# Ermittelt die zu ueberwachenden Interfaces und die Farbe.
# Setzt globale Variablen: MON_IFACES, LINK_COLOR
detect_link() {
    MON_IFACES=""
    LINK_COLOR=""
    local bond_active=0

    for b in /proc/net/bonding/*; do
        [ -e "$b" ] || continue
        if grep -q "802.3ad" "$b" 2>/dev/null && grep -q "MII Status: up" "$b" 2>/dev/null; then
            bond_active=1
            local bname
            bname=$(basename "$b")
            [ -e "/sys/class/net/$bname/statistics/rx_bytes" ] && MON_IFACES="$bname"
        fi
    done

    if [ "$bond_active" = "1" ] && [ -n "$MON_IFACES" ]; then
        LINK_COLOR=$COLOR_BOND
        return
    fi

    local max_speed=0
    for intf in /sys/class/net/e*; do
        [ -e "$intf/carrier" ] || continue
        [ "$(cat "$intf/carrier" 2>/dev/null)" = "1" ] || continue
        MON_IFACES="$MON_IFACES $(basename "$intf")"
        local s
        s=$(cat "$intf/speed" 2>/dev/null)
        if [[ "$s" =~ ^[0-9]+$ ]] && [ "$s" -gt "$max_speed" ]; then
            max_speed=$s
        fi
    done

    if [ -z "$MON_IFACES" ]; then
        LINK_COLOR=""            # kein Link
    elif [ "$max_speed" -ge 10000 ]; then
        LINK_COLOR=$COLOR_10G
    elif [ "$max_speed" -ge 5000 ]; then
        LINK_COLOR=$COLOR_5G
    elif [ "$max_speed" -ge 2500 ]; then
        LINK_COLOR=$COLOR_25G
    elif [ "$max_speed" -gt 0 ]; then
        LINK_COLOR=$COLOR_1G
    else
        LINK_COLOR=$COLOR_1G
    fi
}

# Summiert rx+tx ueber alle ueberwachten Interfaces
read_bytes() {
    local total=0 i v
    for i in $MON_IFACES; do
        for v in rx_bytes tx_bytes; do
            local n
            n=$(cat "/sys/class/net/$i/statistics/$v" 2>/dev/null || echo 0)
            total=$(( total + n ))
        done
    done
    echo "$total"
}

# Ordnet Durchsatz einer Blink-Stufe zu (0 = Dauerlicht)
rate_bucket() {
    local bps=$1
    if   [ "$bps" -lt "$THRESH_IDLE" ]; then echo 0
    elif [ "$bps" -lt "$THRESH_LOW"  ]; then echo 1
    elif [ "$bps" -lt "$THRESH_MED"  ]; then echo 2
    elif [ "$bps" -lt "$THRESH_HIGH" ]; then echo 3
    else echo 4
    fi
}

apply_bucket() {
    case $1 in
        0) return 1 ;;              # Dauerlicht, kein Blink-Kommando
        1) echo "500 500" ;;
        2) echo "250 250" ;;
        3) echo "120 120" ;;
        4) echo "60 60"   ;;
    esac
}

LAST_BYTES=""
LAST_COLOR="__init__"
LAST_BUCKET="__init__"

while true; do
    detect_link

    if [ -z "$LINK_COLOR" ]; then
        # Kein Link -> rot, langsames Warnblinken
        if [ "$LAST_COLOR" != "nolink" ]; then
            led_set network $COLOR_NOLINK $BRIGHTNESS
            led_blink network 400 600
            LAST_COLOR="nolink"
            LAST_BUCKET="__init__"
        fi
        LAST_BYTES=""
        sleep "$INTERVAL"
        continue
    fi

    NOW_BYTES=$(read_bytes)

    if [ -n "$LAST_BYTES" ] && [ "$NOW_BYTES" -ge "$LAST_BYTES" ]; then
        DELTA=$(( (NOW_BYTES - LAST_BYTES) / INTERVAL ))
    else
        DELTA=0
    fi
    LAST_BYTES=$NOW_BYTES

    BUCKET=$(rate_bucket "$DELTA")

    # Nur bei tatsaechlicher Aenderung auf den Bus schreiben
    if [ "$LINK_COLOR" != "$LAST_COLOR" ] || [ "$BUCKET" != "$LAST_BUCKET" ]; then
        if BLINKARGS=$(apply_bucket "$BUCKET"); then
            led_set network $LINK_COLOR $BRIGHTNESS
            led_blink network $BLINKARGS
        else
            # Stufe 0: Blinken aktiv beenden, sonst laeuft es autonom weiter
            led_set_steady network $LINK_COLOR $BRIGHTNESS
        fi
        LAST_COLOR=$LINK_COLOR
        LAST_BUCKET=$BUCKET
    fi

    sleep "$INTERVAL"
done
