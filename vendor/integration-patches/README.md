# Deployed integration compatibility patches

The November 27, 2026 audit found local modifications in Govee 2025.1.1,
LocalTuya 5.2.3 and Wyze 0.1.38. The adjacent unified diffs preserve those
changes; they are not new upstream releases.

`integration-audit.json` records exact upstream repositories, refs, commit
IDs, comparisons, release-asset checksums where applicable, patch hashes,
and original license texts. Govee is MIT, LocalTuya carries the upstream
GNU GPL version 3 license, and Wyze is Apache-2.0. These third-party changes
retain their respective upstream licenses, not this repository's MIT license.
Modification notice: these patches describe locally deployed HA compatibility
changes captured on November 27, 2026; see each diff and its manifest entry.

Restore the matching upstream integration into a staging directory first,
then run `git apply --check /path/to/NAME.patch` and `git apply` from the directory
containing `custom_components`. Check HA configuration before restarting Core.
Never apply a patch blindly to a newer release or to running Core.

Govee updates HA platform forwarding, moves YAML storage I/O off the event
loop, and reports light color modes. LocalTuya updates service registration,
platform setup, options flow and vacuum activity compatibility. Wyze retains
TLS certificate verification while adding the DigiCert root needed by its
legacy dependency. No private credentials or integration config entries are
included.

HACS can overwrite these changes. Review and revalidate the patches when
upgrading. The renamed `dwains_dashboard_old` directory also contains two
extra generated gzip assets of unresolved release provenance; their upstream
blob identities are recorded rather than silently treating that directory
as an active supported integration.
