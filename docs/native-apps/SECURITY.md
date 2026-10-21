# Security model

The native manager controls Docker and is therefore a high-trust, root-equivalent component. A narrow API reduces exposure; it does not make a privileged control service harmless. Review it before exposing the HA instance to untrusted users or the public internet.

## Authentication and capabilities

The daemon binds only IPv4 loopback, requires a high-entropy bearer credential, rejects browser Origin/CORS access, and does not log request bodies or credentials. HA holds that credential in a mode-0600 private connection file. Every HA WebSocket management operation independently requires an active administrator. Merely hiding a sidebar entry is not the authorization check.

The API accepts only bundled catalog app IDs and typed options. No arbitrary images, Docker arguments, filesystem paths, Compose documents or shell commands are accepted. Container ownership is verified on mutations. App processes have dropped capabilities and no-new-privileges; only the radio adapter has a specific optional device mapping. Home Assistant receives no Docker socket.

The host, Docker daemon, host root and trusted native app publishers remain inside the trust boundary. The app containers share a dedicated bridge network and can communicate with one another. Some app HTTP services are unauthenticated on that private bridge and loopback. This is not hostile multi-tenant isolation. Never expose those ports or place untrusted containers on that bridge as a shortcut.

## Embedded applications

The three reviewed routes use a short-lived, HttpOnly, same-site cookie bound to an active HA administrator refresh token. HTTP and WebSocket authorization is rechecked. Unsafe cross-origin requests, traversal and unsupported redirects are rejected. Only selected headers and scoped backend cookies are forwarded; no HA authorization header, HA cookie or manager token reaches the upstream application.

Embedded app pages share the HA browser origin. **Trusted app code is mandatory.** A malicious Node-RED palette package, app publisher or administrator-installed frontend could abuse that shared origin. This is not a sandbox protecting HA from a malicious application UI. Do not install untrusted packages or flows just because a management panel makes them easy to reach.

The API and proxy have body, response, cookie, session, WebSocket and archive bounds. These are practical limits, not a formal security audit. The original application may have vulnerabilities unrelated to the manager. Review releases and advisories when changing a pin.

## Private state

`/srv/orangepi-apps`, `/etc/orangepi-apps`, HA's connection file, application configuration, Z-Wave stores, MQTT credentials, logs, rollback copies and backups are private. They must not enter Git or a public image. Logs and the optional credential-reveal dialog are explicit administrator actions and can display secrets on the screen.

Age encryption provides confidentiality; a detached signature verifies the bundle source. Internal checksums alone are not authentication. The recovery workflow does not implement anti-replay or automatically decide which old recovery point is correct. Keep private keys off public images and ideally separate from the medium containing encrypted backups.

The public-image staging command copies only source assets and emits no token. It does not certify that an arbitrary base image contains no SSH keys, Wi-Fi passwords or household data. Use the existing clean-base/sanitization pipeline and audit its final output.
