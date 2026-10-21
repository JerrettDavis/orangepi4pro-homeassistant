# Installation on the current cyberdeck appliance

## Preconditions

The inspected upstream baseline uses Ubuntu 22.04 ARM64, the existing `5.15.147-sun60iw2-cyberdeck` kernel, Docker, Home Assistant Container in host networking, and an appliance configuration at `/etc/orangepi-homeassistant/appliance.json`. Confirm the live system rather than treating a repository report as a current observation. This layer is not for the earlier HAOS VM path.

Keep the existing kernel, Firefox/X11/touch setup, Nginx Proxy Manager configuration, Z-Wave stack and networking. There is no flashing step.

Before installing, save an existing HA backup and record `docker ps`, failed services, and the output of the read-only benchmark. Keep these privately, outside Git. The installer needs root to access the private configuration and install a privileged host service.

## Review and install

```bash
sudo python3 bin/opiha-apps install-host
sudo python3 bin/opiha-apps install-host --apply
sudo systemctl daemon-reload
sudo systemctl enable --now orangepi-apps.service
sudo systemctl status orangepi-apps.service --no-pager
sudo python3 /opt/orangepi-apps/current/bin/opiha-apps doctor
```

Pass `--appliance-config /actual/path/appliance.json` to both installation commands when needed. The ordinary manager `--config` option belongs **before** its subcommand and refers to the manager's own JSON, not the old appliance JSON.

The default installed paths are:

```text
/opt/orangepi-apps/releases/0.2.0-alpha.2/  immutable installed source
/opt/orangepi-apps/current                owned release selector
/etc/orangepi-apps/config.json            manager settings
/etc/orangepi-apps/token                  private manager credential
/etc/orangepi-apps/deployment.json        installation ownership/checksums
/srv/orangepi-apps/                       app state, jobs and retained rollbacks
<existing data_dir>/ha/custom_components/opiha_apps/
<existing data_dir>/ha/opiha-apps-connection.json
```

No app container is installed by host installation. `doctor` returning an engine error is not success; inspect Docker availability, native architecture and cgroup memory support before proceeding.

## Enable the HA panel

The installer keeps the original `configuration.yaml` bytes, saves a private pre-change copy under `/etc/orangepi-apps/`, and appends an empty `opiha_apps:` key. It does not rewrite HTTP/proxy settings, auth configuration, `.storage`, HACS or the entity registry.

Use the current HA configuration validation procedure, then restart HA once. Do not restart the entire Compose stack just to load one integration. Open the sidebar as an administrator. A non-admin tablet user should remain non-admin; switch to a maintenance account when managing apps.

The panel's API uses the HA login. Its private host credential is only read by the backend integration. Do not copy it into a dashboard URL, browser storage, frontend JavaScript or public YAML example.

## First app

Node-RED is a useful blank acceptance target. Review the memory ceiling, loopback port, image version and network-access warning. Install, wait for completion, then separately Start. Open the editor from the panel, create an innocuous inject/debug flow, and confirm that editor changes survive a container recreation. Do not connect production automations until the blank test is stable.

An existing app with the same upstream image repository is marked externally managed. This is deliberate: the new manager will not adopt or duplicate the original broker, proxy or radio server. Keep those services in their current stack until a separate migration is reviewed.

## Troubleshooting

A missing sidebar typically means HA has not restarted, the account is not an administrator, or the custom integration failed to load. Check HA's private logs and `/etc/orangepi-apps/deployment.json`. The connection JSON must be a small regular file with mode `0600` and an IPv4-loopback URL. HA must use host networking for `127.0.0.1` to reach the host manager.

A manager error must not be “fixed” by exposing port 8098 on all interfaces or mounting the Docker socket into HA. The expected listener is `127.0.0.1:8098`. Keep the existing HTTPS route to Home Assistant; no new public reverse-proxy route is required for the three supported embedded UIs.

An edited managed file or same-version release conflict is a deliberate upgrade stop. Preserve the local change, reconcile it, and bump the native module version for a real new release rather than deleting the ownership marker to force an overwrite.
