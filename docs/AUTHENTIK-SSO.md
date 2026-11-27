# Authentik single sign-on for Home Assistant

## Reflash and recovery

The verified upstream v1.3.0 release and its MIT license are shipped in
`vendor/`. New image-seeded configurations install the integration code
automatically; the image does not contain passwords, tokens, user credentials,
or fabricated Home Assistant storage entries.

The safest recovery is to restore a **private, verified Supervisor backup**
containing the existing HA configuration, `custom_components` and `.storage`.
That preserves the OIDC configuration and the existing user-to-credential
links. Restore authentik and the HTTPS proxy separately as needed. Do not copy
the fresh seed over restored configuration. Test SSO and local login after
restoring. Host units and proxy state may require separate backups.

On a new, un-restored HA configuration, the integration code is installed, but
onboarding and an administrator token still require a human. Once HA is running
and its administrator exists, provision a root-only token file outside the
repository and run:

```bash
sudo chmod 600 /etc/opiha/auth-oidc-token
sudo /opt/orangepi4pro-homeassistant/bin/opiha auth-oidc configure \
  --token-file /etc/opiha/auth-oidc-token --apply
```

The image enables `opiha-auth-oidc.service` for automatic configuration when
that private token file exists. It runs after stack startup, retries bounded
startup failures, and logs failures to the journal. If the file is provisioned
after boot, start the unit explicitly. Remove the token file and revoke its
long-lived access token after setup. Never put a token in the image or Git.

For the real Supervisor installation, which the image builder does not itself
install, stop Core before installing the component into its mounted HA config:

```bash
sudo /opt/orangepi-homeassistant/current/bin/opiha auth-oidc install \
  --ha-config /usr/share/hassio/homeassistant --source-stopped --apply
```

Then start Core and use the same `auth-oidc configure` command from that
installation's `bin/opiha`. The command uses HA's supported UI configuration
flow, preserving existing entries rather than modifying `.storage`. It defaults
to the public client and discovery URL in `config/authentik-sso.json`, and
disables automatic linking and role mapping while requiring existing users.
Use `--ha-url` to select a trusted HTTPS HA origin, or loopback HTTP.

A fresh HA install has no existing link. Re-establish it only during a
controlled linking window after verifying account ownership and Authentik MFA,
then disable linking again. The repository does not recreate Authentik's
provider or its application policy: retain or separately restore those.
Existing companion and kiosk sessions require their own verification.

Home Assistant does not provide built-in OIDC login. Authentik documents the
community-maintained [hass-oidc-auth integration](https://github.com/christiaangoossens/hass-oidc-auth)
for this purpose; it supports linking existing Home Assistant accounts. This
procedure targets its [v1.3.0 release](https://github.com/christiaangoossens/hass-oidc-auth/releases/tag/v1.3.0),
which includes security fixes and declares Home Assistant 2025.11 or newer. Review
newer releases and security advisories before deploying.

## Before making changes

1. Make and verify a restorable Home Assistant backup, including its
   configuration and authentication data. Retain the backup and its
   encryption key privately. Back up authentik separately.
2. Keep an existing Home Assistant administrator session open, and verify a
   separate local username/password administrator login and recovery path.
   Do not remove the Home Assistant authentication provider or force an
   automatic OIDC redirect. Existing companion app and kiosk sessions must
   remain usable.
3. Inventory the exact local **login usernames**, account owners and existing
   privileges for accounts to link. A display name is not necessarily a login
   username. Confirm the corresponding authentik `preferred_username` values
   match exactly and that those identities are controlled by the same people.
4. Require strong MFA in authentik's authorization flow and restrict the
   application to the intended users. Username-based linking can grant the
   matched account's privileges without prompting for Home Assistant's MFA:
   authentik's authentication and its user-administration policies are the
   security boundary for SSO.

## Configure authentik

In the authentik administrator interface, create an application and an
OAuth2/OpenID Connect provider. Choose a public client with PKCE, an
appropriate MFA-enforcing authorization flow, and an RS256 signing key. Add
this exact **Strict Authorization** redirect URI:

```text
https://homeassistant.jerrettdavis.com/auth/oidc/callback
```

In authentik versions before 2026.5 the redirect URI has no type selector.
Bind access to only the intended users or groups. The application slug and
public client ID are not secrets. The discovery URL is:

```text
https://auth.jerrettdavis.com/application/o/<application-slug>/.well-known/openid-configuration
```

Do not use a secret for a public client. If a confidential client is chosen
instead, keep its secret out of the repository, shell history, and transcripts.
Use valid TLS verification; do not disable PKCE or certificate verification.
See [authentik's integration guide](https://integrations.goauthentik.io/miscellaneous/home-assistant/)
and the [upstream authentik guide](https://github.com/christiaangoossens/hass-oidc-auth/blob/v1.3.0/docs/provider-configurations/authentik.md).

## Install and configure Home Assistant

The image includes v1.3.0. For other installations, install the
reviewed release using HACS, if HACS is deliberately installed. Otherwise
download the release's `hass-oidc-auth.zip` (not GitHub's source
archive), verify it against the release's published SHA-256 digest, and unpack
its contents into a new `custom_components/auth_oidc` directory. The archive
contains the integration files at its root. This Supervisor installation
mounts `/srv/homeassistant/ha` as its config directory. Do not replace other
custom components or the existing configuration. Restart Core as required,
keeping the recovery session available.

The vendored integration is not managed by HACS. Monitor upstream
security advisories and update it deliberately with a backup; the existing
HACS update automation does not update this manually installed copy.

In **Settings > Devices & services**, add **OpenID Connect/SSO Authentication**,
select authentik, validate the discovery URL, and enter the client ID. Use
only one configuration method: UI or YAML, not both. For the initial migration:

* Leave group-based role assignment disabled; verify existing HA privileges
  rather than inadvertently granting admin rights through an IdP group.
* Enable **Prevent creation of new Home Assistant users**.
* Temporarily enable **automatic user linking**, only after the username and
  authentik access checks above. Restart Core when prompted.

The integration's default is to create new users if existing-user enforcement
is off. Automatic linking is not proof of identity: anyone permitted by
authentik to authenticate with a matching username can acquire that HA
account's permissions. Restrict application access and the linking window.

## Verify and close the migration window

1. In a separate private browser session, sign in at
   `https://homeassistant.jerrettdavis.com/` using OIDC. Confirm the redirect
   reaches authentik over HTTPS, requires the intended MFA, and returns to HA.
2. For each intended user, verify the linked HA user ID, existing dashboards
   and permissions, not merely the displayed name. Test an unapproved
   authentik user and an unmatched username are denied. Avoid repeated failed
   attempts that could trigger HA IP banning.
3. Disable automatic linking in the integration options, keep **Prevent
   creation of new Home Assistant users** enabled, and restart Core. Verify
   linked users can still sign in, and an unlinked identity cannot. Adding
   another user later requires a new controlled linking window.
4. Test the separate local administrator login, existing companion apps and
   kiosk access. Review Core logs for OIDC errors and retain the backup until
   recovery and login checks succeed.

Upstream does not implement OIDC session management or back-channel logout;
disabling an authentik user does not immediately revoke existing HA sessions.
When removing access, disable the HA user and revoke its sessions and tokens
in Home Assistant as well. IdP role changes are not continuously synchronized.
See the [upstream FAQ](https://github.com/christiaangoossens/hass-oidc-auth/blob/v1.3.0/docs/faq.md).

## Rollback

Use the retained local administrator login. Disable or remove the OIDC
configuration, restart Core, and confirm local login and companion access.
If that is insufficient, restore the verified pre-change backup using the
normal Supervisor recovery procedure. Remove or disable the authentik
application after confirming it is no longer needed. Do not remove HA's
built-in authentication provider or revoke unrelated tokens as part of this
rollback.
