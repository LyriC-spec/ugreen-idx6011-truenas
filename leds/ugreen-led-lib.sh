#!/bin/bash
# ugreen-led-lib.sh - Direkte LED-Steuerung fuer UGREEN iDX6011 (non-Pro) via SMBus
#
# Warum nicht ugreen_leds_cli?
#   Das CLI aus klein0r/ugreen_leds_controller setzt auf dem iDX6011 bei JEDEM
#   Aufruf (auch bei reinem -status) die Helligkeit auf 0 -> LED geht aus.
#   Das Protokoll selbst funktioniert einwandfrei, daher sprechen wir direkt per i2cset.
#
# Protokoll: klein0r/ugreen_leds_controller docs/iDX6011Pro-LED-Protocol.md
# LED-Mapping am 2026-08-01 auf iDX6011 non-Pro durch Sichtpruefung verifiziert.

I2C_BUS="${I2C_BUS:-0}"
I2C_ADDR="0x3a"

# LED-Indizes - iDX6011 non-Pro hat nur EINE Netzwerk-LED (Pro hat zwei),
# dadurch verschiebt sich die Disk-Kette gegenueber der Pro-Variante um eins.
# Index 0x08 existiert auf dem non-Pro nicht.
declare -A LED_IDX=(
    [power]=0x00
    [network]=0x01
    [disk1]=0x02
    [disk2]=0x03
    [disk3]=0x04
    [disk4]=0x05
    [disk5]=0x06
    [disk6]=0x07
)

CMD_BRIGHTNESS=0x01
CMD_COLOR=0x02
CMD_ONOFF=0x03
CMD_BLINK=0x04
CMD_BREATH=0x05

# led_raw <index> <cmd> [p1] [p2] [p3] [p4]
led_raw() {
    local idx=$1 cmd=$2 p1=${3:-0} p2=${4:-0} p3=${5:-0} p4=${6:-0}
    local sum=$(( 0xA0 + 0x01 + cmd + p1 + p2 + p3 + p4 ))
    i2cset -y "$I2C_BUS" "$I2C_ADDR" "$idx" \
        0xa0 0x01 0x00 0x00 "$cmd" "$p1" "$p2" "$p3" "$p4" \
        $(( (sum >> 8) & 0xFF )) $(( sum & 0xFF )) s 2>/dev/null
}

led_resolve() {
    local n=$1
    if [[ -n "${LED_IDX[$n]}" ]]; then echo "${LED_IDX[$n]}"; else echo "$n"; fi
}

led_color()      { led_raw "$(led_resolve "$1")" $CMD_COLOR "$2" "$3" "$4" 0; }
led_brightness() { led_raw "$(led_resolve "$1")" $CMD_BRIGHTNESS "$2" 0 0 0; }
led_off()        { led_brightness "$1" 0; }

# led_set <led> <r> <g> <b> <brightness>
led_set() {
    led_color "$1" "$2" "$3" "$4"
    led_brightness "$1" "$5"
}

# led_blink <led> <t_on_ms> <t_off_ms>
led_blink() {
    local idx cycle on
    idx="$(led_resolve "$1")"
    cycle=$(( $2 + $3 ))
    on=$2
    led_raw "$idx" $CMD_BLINK $(( (cycle>>8)&0xFF )) $(( cycle&0xFF )) $(( (on>>8)&0xFF )) $(( on&0xFF ))
}

# led_set_steady <led> <r> <g> <b> <brightness>
# Dauerlicht ohne Blinken. Bildet exakt die dokumentierte 5-Schritt-Sequenz nach:
#   0x04 Mode-Reset -> 0x01 Helligkeit -> 0x02 Farbe -> 0x03 EIN -> 0x01 Helligkeit
# Schritt 4 (0x03) ist zwingend: der Mode-Reset schaltet die LED sonst ab.
# Zwischen den Schritten braucht die MCU laut Doku je ~50 ms.
led_set_steady() {
    local led=$1 r=$2 g=$3 b=$4 br=$5
    local idx
    idx="$(led_resolve "$led")"
    led_raw "$idx" $CMD_BLINK 0 0 0 0      ; sleep 0.05
    led_raw "$idx" $CMD_BRIGHTNESS "$br" 0 0 0 ; sleep 0.05
    led_raw "$idx" $CMD_COLOR "$r" "$g" "$b" 0 ; sleep 0.05
    led_raw "$idx" $CMD_ONOFF 0xFF 0 0 0   ; sleep 0.05
    led_raw "$idx" $CMD_BRIGHTNESS "$br" 0 0 0
}

# led_steady <led> - nur Blink-Modus beenden und LED wieder aktivieren
led_steady() {
    local idx
    idx="$(led_resolve "$1")"
    led_raw "$idx" $CMD_BLINK 0 0 0 0 ; sleep 0.05
    led_raw "$idx" $CMD_ONOFF 0xFF 0 0 0
}

# led_all_off - alle bekannten LEDs ausschalten
led_all_off() {
    local n
    for n in "${!LED_IDX[@]}"; do led_brightness "$n" 0; done
}