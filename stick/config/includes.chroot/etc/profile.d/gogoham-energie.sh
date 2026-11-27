# GoGoHam-Live-Stick: Energieverwaltung von LXQt bei jeder Anmeldung passend zum Rechner einstellen –
# derselbe Stick steckt mal am Laptop, mal am Desktop-PC. Akku-Anzeige nur mit Akku (sonst meldet
# LXQt bei jedem Start „Keine Batterie“), kein Ruhezustand beim Zuklappen, keine Aktion bei
# Untätigkeit, kein „erster Start“-Hinweis (runCheckLevel). Läuft vor der Sitzung (/etc/profile).
if [ -n "$HOME" ] && [ "$(id -un 2>/dev/null)" = gogoham ]; then
    _akku=false
    for _d in /sys/class/power_supply/*; do
        [ "$(cat "$_d/type" 2>/dev/null)" = Battery ] && [ "$(cat "$_d/scope" 2>/dev/null)" != Device ] \
            && _akku=true
    done
    mkdir -p "$HOME/.config/lxqt" 2>/dev/null && cat > "$HOME/.config/lxqt/lxqt-powermanagement.conf" <<EOT 2>/dev/null
[General]
__userfile__=true
runCheckLevel=1
enableBatteryWatcher=$_akku
enableLidWatcher=false
enableIdlenessWatcher=false
enableIdlenessBacklightWatcher=false
showIcon=true
EOT
    unset _akku _d
fi
