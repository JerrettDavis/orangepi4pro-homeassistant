# Live-host rollback

The conservative host installer owns only its release tree, private appliance
configuration, generated state, private service state, and one disabled unit.
It does not own the cyberdeck kernel, boot assets, Docker installation,
networking, SSH, LightDM/XFCE, touchscreen configuration, or storage layout.

## Before the first container start

No service is enabled or started. Inspect the deployment record:

```bash
sudo python3 -m json.tool /var/lib/orangepi-homeassistant/deployment.json
sudo systemctl cat orangepi-homeassistant.service
```

If the files are wrong, leave private state in place, move the deployment
record and selected `current` symlink aside for diagnosis, and do not run the
unit. Do not recursively delete `/srv/homeassistant`; it is the recovery copy
of any state created after installation.

## After Home Assistant has started

```bash
sudo systemctl stop orangepi-homeassistant.service
sudo docker ps -a --filter label=com.docker.compose.project=opiha
```

Confirm no managed container remains. If an upgrade selected a bad release,
point `/opt/orangepi-homeassistant/current` back to the previously recorded
release using an atomic replacement symlink, run `systemctl daemon-reload`, and
start the unit again. Old releases are retained by default.

To take the appliance out of service while retaining recovery state:

```bash
sudo systemctl stop orangepi-homeassistant.service
sudo mv /etc/systemd/system/orangepi-homeassistant.service \
  /etc/systemd/system/orangepi-homeassistant.service.disabled
sudo systemctl daemon-reload
```

This does not restore or change any cyberdeck service because the installer did
not modify them. Keep `/srv/homeassistant` and
`/var/lib/orangepi-homeassistant` until backup/restore validation proves they
are disposable.

If SSH, networking, display, touch, boot, or Docker itself changes during this
slice, stop and investigate separately: none is an expected installer effect.
