# Home Assistant authentication hardening

Home Assistant here can reach many devices, so account takeover is the main
network-compromise path. Phases: **1. MFA (this document)**, 2. a dedicated
administrator account, 3. no admin rights for remote/everyday users.

## Phase 1: MFA

`homeassistant/configuration.yaml` (seed for new installs only) declares the
TOTP module and enables IP banning after 5 failed logins. MFA is enforced per
user: HA only asks for a code once that user has enrolled.

### Apply to the deployed (Supervised) instance

`/srv/homeassistant/ha` is root-only and `opiha-admin` is a fixed-command
wrapper, so this needs an interactive root session on the host:

```bash
sudoedit /srv/homeassistant/ha/configuration.yaml   # merge the blocks from the seed
# homeassistant:
#   auth_mfa_modules:
#     - type: totp
#       name: Authenticator app
# http:
#   ip_ban_enabled: true
#   login_attempts_threshold: 5
```

If `http:` already exists (for example `use_x_forwarded_for` /
`trusted_proxies` behind a reverse proxy), add the two ban keys to it rather
than duplicating the block. Keep `trusted_proxies` as narrow as possible, or
ip-banning will count the proxy address. Then **Developer tools > Check
configuration**, and restart Core.

### Enroll every user (cannot be scripted)

For each user, signed in as that user: **Profile > Security > Multi-factor
Authentication > Enable**, scan the QR code, enter the code. Save the
authenticator backup/recovery method; there is no recovery email. Enroll the
administrator first, test logout/login, then the rest. Enable it for the kiosk
account only if the kiosk browser can tolerate a login prompt; otherwise keep
that account non-admin, local-only, and with a long random password.

Long-lived access tokens and the Companion app's refresh tokens bypass MFA.
Review and revoke unused ones under each user's **Security** tab.

### Verify

- Log out; a login now asks for the authenticator code.
- `ha core check` (or Check configuration) passes after the restart.
- Failed-login ban works: 5 bad attempts record an entry in
  `ip_bans.yaml` (clear it afterwards if you banned yourself).
- Exposure: confirm the HA port is not forwarded from the internet; use VPN
  or an authenticated reverse proxy for remote access.

## Passkeys and security keys (multiple second factors)

Home Assistant Core only ships TOTP and the weaker `notify` module as MFA
(`auth_mfa_modules`); it has no native WebAuthn/FIDO2. Options, strongest
first:

1. **Phishing-resistant gate in front of HA** (recommended for remote access):
   an identity-aware proxy (Authelia, Authentik, Cloudflare Access, or a
   Tailscale/WireGuard VPN with a hardware-key IdP) enforcing passkey/YubiKey,
   with HA reachable only through it. This protects HA even if its own login
   has a flaw. Keep HA's TOTP as a second, independent layer. If using
   `use_x_forwarded_for`, set `trusted_proxies` to the proxy address only.
2. **Community integration** `Anrolosia/ha-webauthn-mfa` (HACS; needs HA
   2026.4+, HTTPS, `rp_id`/`expected_origin` set to the real hostname; the
   Companion app webview cannot use WebAuthn). It is unreviewed third-party
   code that hooks the login flow, so it is **not** installed or enabled by this
   repo. Review the source, pin a release, and trial it on a spare instance
   with a backup before use. Register at least two authenticators per user
   (for example a YubiKey plus a password-manager passkey) and keep TOTP as
   fallback so a lost key cannot lock you out.
3. TOTP only (current baseline).

Whatever is chosen, enrol a second hardware key and store it offline.

## Phase 2 and 3 (preparation)

- Create a dedicated administrator (for example `ha-admin`) used only for
  administration, with MFA and a unique password in a password manager.
- Demote day-to-day, remote, and kiosk users to non-admin (Settings > People >
  user > Administrator off). Rename/disable the original admin afterwards.
- The Orange Pi panel (`opiha_apps`) is registered with `require_admin=True`
  and re-checks `is_admin`/`is_active` server side in its views, so non-admin
  users cannot reach host/Docker/terminal functions. Docker socket and
  terminal add-ons are root-equivalent: only the dedicated admin should have
  access.
- Keep the Supervisor/Core/OS updated; the host exposes only SSH and port 8123
  to the LAN and the OPNsense VLAN design limits what HA may reach.
