# Appliance acceptance status

This checklist records evidence, not aspirations. `Pass` means the behavior
was observed on the current Orange Pi. `Pending` is not implied by a passing
unit test.

| Check | Status | Evidence or remaining action |
|---|---|---|
| Existing cyberdeck OS preserved | Pass | No boot, kernel, DTB, partition, SSH, or display-stack replacement |
| Blank HA Container starts on ARM64 | Pass | HA 2026.9.3 reached healthy state |
| Persistent config survives recreation | Pass | Container down/recreate/start retained the bind-mounted config |
| Local kiosk renders HA | Pass | 1024x600 X11 screenshot shows HA onboarding/restore UI |
| Kiosk stop/start is independent | Pass | Firefox PID ended/restarted while HA stayed healthy |
| Physical touch input in kiosk | Pending | Human acceptance tap required |
| Encrypted appliance backup verify | Pass | Signed age bundle created and verified on-device |
| Applied native HA restore | Pass | Protected HA-only backup restored through Core onboarding; recorder DB passed SQLite quick check |
| Production HA native backup staged | Pass | Fresh HA-only backup with database is root-only on the target; source and target SHA-256 matched |
| Production HA restore rehearsal | Pass | Restored auth/config/database; source HA Core stopped while HAOS/add-ons remain for rollback |
| Camera stream | Blocked | No V4L2 or media-controller endpoint enumerates |
| CPU person detector on real camera | Blocked | Detector code exists; no camera frames are available |
| Z-Wave JS UI with production stick | Pending | Controller is not attached; preserve keys/store/NVM first |
| Image build from clean cyberdeck base | Pending | No clean base image supplied to the guarded builder |
| Spare-media flash | Blocked | No positively identified disposable destination |
| Spare-media boot/power-cycle recovery | Blocked | Depends on the prior two checks |

Before retiring the source appliance, complete the production comparison in
[Migration](MIGRATION.md), recreate every required HAOS add-on as an external
service, follow the independent [Z-Wave migration](ZWAVE-MIGRATION.md), validate
touch, reboot the host, and retain a tested rollback path.
