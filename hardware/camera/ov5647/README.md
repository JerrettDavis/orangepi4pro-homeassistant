# OV5647 (Raspberry Pi camera v1 / Arducam 5MP) on the Orange Pi 4 Pro

The Allwinner VIN BSP (`orange-pi-5.15-sun60iw2`) has no OV5647 sensor driver.
`ov5647_mipi.c` is a port of the BSP's `ov5648_mipi.c` template using the
mainline `ov5647.c` register tables (1920x1080, 1296x972, 640x480; 2-lane,
SBGGR10, 24 MHz MCLK). **Status: builds and installs; not yet verified on the
sensor** (needs the DT change below and a reboot).

## Build (on the Pi, against the matching BSP tree)

    git clone --depth 1 -b orange-pi-5.15-sun60iw2 https://github.com/orangepi-xunlong/linux-orangepi linux
    cd linux && cp /boot/config-$(uname -r) .config && make -j8 olddefconfig modules_prepare
    mkdir ../mod && cp <repo>/hardware/camera/ov5647/ov5647_mipi.c ../mod/
    # ../mod/Makefile: obj-m += ov5647_mipi.o  and ccflags-y -I for bsp/drivers/vin{,/modules/sensor,/utility,/vin-cci,/platform} bsp/include, -DCONFIG_SAME_I2C
    make M=$PWD/../mod modules
    sudo install -D ../mod/ov5647_mipi.ko /lib/modules/$(uname -r)/extra/ov5647_mipi.ko && sudo depmod -a

(No MODVERSIONS; vermagic must be `5.15.147-sun60iw2-cyberdeck`.)

## Device tree

Boot DTB `sensor0` is declared as `imx219` at `0x20`. For this module change
`sensor0_mname = "ov5647_mipi"` and `sensor0_twi_addr = <0x6c>` (CCI 8, mclk 1,
pwdn PD8 stay). Staged at `.../allwinner/sun60i-a733-orangepi-4-pro-ov5647.dtb`;
the boot DTB is unchanged (original md5 2aa9637bef1f69a8eb9311c83af67289).
To apply: back up the boot DTB, copy the staged file over it, reboot. To revert:
copy the backup back.

## Load / test

    sudo modprobe vin_v4l2 ov5647_mipi   # vin_io loads as a dependency of vin_v4l2
    dmesg | grep -i -E "vin|ov5647"; ls /dev/video*; v4l2-ctl --list-devices

The module has no declared dependency on `vin_io`; load `vin_v4l2` first.
Open risks: CSI-2 clock/PHY bring-up errors seen earlier, no ISP tuning for this
sensor, and PD8 must be the RPi module's CAM_GPIO (power enable).

## Findings from the first on-hardware test (2026-10-21)

- **Which DTB boots:** the boot script reads the DTB from the SD card
  (`/mnt/opisd-check/boot/dtb-5.15.147-sun60iw2-cyberdeck/allwinner/`), not from
  `/boot` or `/boot/efi` on the NVMe. Patching only the NVMe copies did nothing.
  Back up (`.pre-ov5647`) and patch the SD copy; the NVMe copies were patched too.
- **Driver status:** with the patched DTB the kernel reports `sensor0_mname =
  ov5647_mipi`, `twi_addr 0x6c`, the module probes and `/dev/video0` appears.
- **Sensor does not ACK:** the chip-ID read (0x300a/0x300b) at 0x36 on i2c-8 gets
  no answer, also with `/dev/video0` held open. Not yet known whether this is
  the wrong connector (the board has a 2-lane and a 4-lane CSI port; the DT only
  routes `sensor0`/CSI2 here), PD8 not being the module's power enable, no MCLK
  on the pin, or the adapter cable.
- **Driver bug fixed:** `cci_lock()` holds the I2C adapter lock, so any I2C
  transfer inside it (including `cci_write`) deadlocks the bus and wedges
  `modprobe`. Do I2C writes after `cci_unlock()`. `sensor_write()` additionally
  refuses while the entity is unused ("sensor is not used").
- **Do not `reboot --force`:** skips unmounting and caused "failed to finalize
  file system" on the console.

## Both slots tested, no ACK (2026-10-21/22)

- The driver now registers two names (`ov5647_mipi` for `sensor0`, `ov5647_mipi_2`
  for `sensor1`), like the BSP `imx219`/`imx219_2` pair. With one shared name the
  VIN core applies sensor0's pins/clock to both clients and the test is invalid.
- Slot 0 (i2c-8: PD8 enable, MCLK1 on PE5) and slot 1 (i2c-9: PE6 pwdn, PE13 reset,
  MCLK0 on PE0) were each powered and held (`hold_power=1`, `only_bus=N` debug
  parameters). Pins and `csi-master*` clocks verified active. The camera pinctrl
  is a single handle, so only one slot's MCLK pin is active at a time: never probe
  two sensors at once, and keep the stock `ov13850_mipi`/`imx219` modules out
  (`/etc/modprobe.d/zz-ov5647-test.conf`, temporary) or they release the MCLK pin.
- Neither bus gets an ACK at 0x36 (transfer returns -EINVAL = NACK in this TWI
  driver). Enabling the PMIC's unused LDOs (ALDO2-6, DLDO2-5) changed nothing.
- Remaining suspects are physical: the 22-pin "DSI-style" adapter cable pinout vs
  the board's CAM connector, the module's 3V3/CAM_GPIO feed, or a wrong port.
- Never `rmmod vin_v4l2`/`ov5647_mipi` with `hold_power` set: it hung the kernel.
  Change module parameters via modprobe.d and reboot.

## CAM1 pinout (from OPi 4 Pro V1.3.2 schematic, sheet "VI-Cam MIPI CSIA-RX")

CAM1 is a 30-contact 0.5 mm FFC socket whose contacts are tied in pairs, i.e.
electrically the **Pi 15-pin 1.0 mm pinout**, so the stock Pi ribbon is correct
(its 15 traces land on the 15 odd contacts, as seen in the photos):

| Pi pin | Net |
|---|---|
| 1 | GND |
| 2,3 | MCSIC-D0N, D0P (2-lane port) |
| 4 | GND |
| 5,6 | MCSIC-D1N, D1P |
| 7 | GND |
| 8,9 | MCSIC-CKN, CKP |
| 10 | GND |
| 11 | MCSIB-PWDN (Pi CAM_GPIO; DT: `sensor0_pwdn` = PD8) |
| 12 | MCSIB-MCLK (DT: `sensor0_mclk_id` = 1) |
| 13 | TWI8_SCK (PB10, 4.7k pull-up to VCC_3V3_S3) |
| 14 | TWI8_SDA (PB9) |
| 15 | VCC_3V3_S3 |

CAM2 is the 4-lane 30-pin port (MCSIB lanes, TWI9, MCSIA-RESET/PWDN/MCLK).
Earlier notes guessing a 24/30-pin mismatch were wrong and are withdrawn. With
PD8 or any of PE0..PE13 driven high alone, i2c-8/i2c-9 still NACK 0x36.

## LED mapping, confirmed on hardware (2026-10-22)

- The camera module's LED is on ribbon pin 12 (Arducam table: "LED indicator").
  **PE5 (gpio 133, the board's MCSIB-MCLK/mclk1 pin) drives it**: PE5 high alone =
  LED on, confirmed by eye. PE4 alone and PE6 alone do not light it. (An earlier
  note that said PE6 lights the LED was wrong: PE5 was also being driven low then.)
- This confirms the ribbon sits on CAM1 = DT sensor0 (twi8 on PB9/PB10, enable PD8,
  mclk1 on PE5), and that the pin mapping on the ribbon matches the schematic.
- Still no ACK at 0x36: tried PD8 + PE5 high with kernel i2c-8/9 and with a slow
  bit-bang scan of PB9/PB10/PE14/PE15 (all pairs, both orders). LED lighting only
  proves pin 12; the module's 3V3 (pin 15) and I2C (13/14) are not yet verified.
