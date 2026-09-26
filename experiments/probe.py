import usb.core, usb.util, libusb_package, time
be = libusb_package.get_libusb1_backend()
d = usb.core.find(idVendor=0x0bda, idProduct=0x5840, backend=be)
d.set_configuration()
usb.util.claim_interface(d, 0)
def rd(t=500):
    try:
        b = bytes(d.read(0x86, 4096, t)); print("IN :", b.hex(' ')); return b
    except usb.core.USBTimeoutError:
        print("IN : (timeout)")
print("-- passive read"); rd(1500)
print("-- send iAP2 detect")
d.write(0x05, bytes.fromhex("FF55 0200 EE10".replace(" ","")))
for _ in range(5): rd(700)
