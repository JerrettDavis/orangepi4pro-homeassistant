# Custom image build

## What the builder actually does

This repo provides an appliance overlay and a guarded **clean-base image copier**. It does not generate the Orange Pi partition table, U-Boot payload, A733 kernel, device tree or vendor camera driver. Obtain a clean boot-tested Ubuntu/Debian ARM64 base from your existing Orange Pi tooling. Its license and public redistribution permissions still apply.

The apply path copies a regular, uncompressed `.img`, attaches a loop device to the copy, mounts the explicitly selected Linux root partition, installs the overlay, optionally installs packages in a chroot, removes known machine/private state, audits selected paths, and writes a checksum/package/build manifest. It never flashes `/dev/nvme*`, edits the source file, or selects a partition automatically.

**Do not use a disk cloned from your working household.** Scrubbing known paths cannot prove that every unknown private file or previously freed filesystem block has been erased. The input must be a fresh clean image assembled without household data. Scrubbing is defense in depth, not anonymization of a used filesystem.

## Prerequisites and base selection

A native Linux ARM64 build host is preferred. An x86 host requires correctly configured qemu-user-static/binfmt for chroot commands, plus root loop/mount privileges. Docker Desktop alone is not a full image-builder environment. A WSL setup might support the necessary operations, but has not been certified here.

Inspect the base partition layout read-only with appropriate Linux tooling. Set `ROOT_PARTITION` to its actual Linux root, not to a number assumed from an older image. Preserve your known-good boot asset chain, including the distinction between an SD-provided boot script and NVMe rootfs.

Set public defaults in `config/image-defaults.json`. On first migration, its `ha_version` and HA image tag should match the source VM exactly. No feature flags, serial IDs, network credentials, tokens, SSIDs or household URLs belong in this public file.

## Optional HACS software cache

```bash
./bin/opiha vendor-hacs --version YOUR_EXPLICIT_HACS_RELEASE
```

This fetches the official release archive, records a SHA256 lock, and verifies a GitHub asset digest when one is available. The image can seed HACS code into a new HA config. It never replaces restored HACS code or writes fabricated HACS `.storage` records. GitHub OAuth/device enrollment is still required for a fresh household. For the first migration, restoring existing HACS code/state is usually preferable.

Review the archive's license before redistributing it. No archive is included in the delivered source package.

## Optional public offline container cache

```bash
./bin/opiha --config .local/image/appliance.json init --mode lab
./bin/opiha --config .local/image/appliance.json configure --ha-version YOUR_SOURCE_RELEASE
python3 scripts/cache-images.py \
  --config .local/image/appliance.json \
  --platform linux/arm64 \
  --output .build/arm64-cache
```

This pulls selected public images, verifies ARM64 metadata, saves them into `images.tar` with immutable local image-ID tags and a hash manifest. Copy the same chosen public release refs into image defaults. It does not export a running container or any mounted household directory.

The image loader checks the restored software versions, platform, archive checksum and loaded image IDs. It refuses a cache mismatch rather than silently upgrading. Cached services use `pull_policy: never` and do not need registry availability. However, custom integrations may need to download ARM64 Python dependencies; OAuth/cloud services and initial apt installation may also need networking. **A container cache is not a guarantee of an entirely offline household.**

Registry digest pinning is also available with `opiha lock-images --platform linux/arm64`. Digests are architecture/version inputs; keep lab and appliance locks separate. Do not move an AMD64-only lock into an ARM64 production image.

## Dry run

```bash
BASE=/private/clean-orangepi-a733.img
SHA256=$(sha256sum "$BASE" | awk '{print $1}')
ROOT_PARTITION=3 # EXAMPLE ONLY: inspect your actual image first

./image/build-from-base.sh \
  --base "$BASE" --sha256 "$SHA256" \
  --root-partition "$ROOT_PARTITION" \
  --output .build/orangepi4pro-homeassistant.img
```

The dry run verifies the input hash and argument guards but does not mount, inspect the partition filesystem or create an output image.

## Apply

Generate a public recovery trust key as described in [recovery](RECOVERY.md), or supply an administrative SSH public key. Never supply a private SSH key. Remove identifying comments from public keys before publishing when that matters for your image's privacy policy.

```bash
sudo ./image/build-from-base.sh \
  --base "$BASE" --sha256 "$SHA256" \
  --root-partition "$ROOT_PARTITION" \
  --output .build/orangepi4pro-homeassistant.img \
  --install-dependencies --enable-kiosk \
  --ssh-public-key /private/admin-public-key.pub \
  --recovery-trust-key config/recovery-trust.pem \
  --container-cache .build/arm64-cache \
  --attest-clean-base --apply
```

Omit cache/kiosk/trust options when not using them. At least an SSH public key or recovery trust key is required because image passwords are locked. A signed state restore alone does not create an SSH administrative credential, so keeping an authorized administrative public key is strongly recommended.

The image builder does not resize the root partition. Start with sufficient free space for packages and cached images, and size/expand storage with your tested upstream tools. Do not publish an image until the live hardware boot and recovery checklist passes.

Outputs:

```text
orangepi4pro-homeassistant.img
orangepi4pro-homeassistant.img.sha256
orangepi4pro-homeassistant.img.packages.txt
orangepi4pro-homeassistant.img.manifest.json
```

A failed build leaves a `.partial` output for diagnosis; the next run refuses to overwrite it. Ensure all temporary loop mounts are released before inspecting or deleting a partial image. The builder does not force-unmount busy filesystems.

The recorded base hash, selected source revision, explicit service versions and package inventory make builds auditable. Apt repository contents and filesystem timestamps are not fully pinned, so this alpha does **not** claim byte-for-byte reproducibility.

## GitHub automation

The included CI validates source and can run a manually selected Docker smoke test. Source-release packaging is also available. This release deliberately does not create a privileged self-hosted image-build workflow that runs arbitrary pull-request code. Once a trusted ARM64 runner and clean base artifact are established, execute the same guarded build script from a manually approved workflow with least-privilege artifact access.

A future integration with `orangepi4pro-images` should invoke this overlay at the actual rootfs hook exposed by that repository. No invented upstream command-line API is assumed here.
