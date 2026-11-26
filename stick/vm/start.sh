#!/bin/bash
# Test-Stick in QEMU starten: start.sh uefi|bios
cd "$(dirname "$0")"
MODE=${1:-uefi}
FW=()
if [ "$MODE" = uefi ]; then
    cp -n /usr/share/edk2/x64/OVMF_VARS.4m.fd vars.fd
    FW=(-drive if=pflash,format=raw,readonly=on,file=/usr/share/edk2/x64/OVMF_CODE.4m.fd
        -drive if=pflash,format=raw,file=vars.fd)
fi
rm -f mon.sock
exec qemu-system-x86_64 -enable-kvm -machine q35 -cpu host -smp 2 -m 4096 "${FW[@]}" \
    -device qemu-xhci -drive file=stick.img,format=raw,if=none,id=stick \
    -device usb-storage,drive=stick,bootindex=0 -device usb-tablet \
    ${USB2:+-drive file=$USB2,format=raw,if=none,id=stick2 -device usb-storage,drive=stick2} \
    ${EXTRA:+-drive file=$EXTRA,format=raw,if=virtio} ${RTC:+-rtc base=$RTC} \
    -vga virtio -display none -monitor unix:mon.sock,server,nowait \
    -nic user,model=virtio-net-pci -audiodev none,id=a -device ich9-intel-hda -device hda-output,audiodev=a \
    -daemonize -pidfile qemu.pid
