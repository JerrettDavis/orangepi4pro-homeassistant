# Optional public software vendoring

No archive is bundled in this source release. `opiha vendor-hacs --version EXPLICIT_RELEASE` downloads an official HACS release ZIP and writes a SHA256 lock. The image overlay can seed that archive only into a new config. It does not replace a restored integration or authenticate HACS. Review upstream licenses before redistributing software. Never put household state, keys or private package credentials in this directory.
