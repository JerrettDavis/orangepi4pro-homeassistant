# Optional public software vendoring

No archive is bundled in this source release. `opiha vendor-hacs --version EXPLICIT_RELEASE` downloads an official HACS release ZIP and writes a SHA256 lock. The image overlay can seed that archive only into a new config. It does not replace a restored integration or authenticate HACS. Review upstream licenses before redistributing software. Never put household state, keys or private package credentials in this directory.

## Bundled in the Home Assistant panel

`homeassistant/custom_components/opiha_apps/xterm.js`, `xterm.css` and `xterm-addon-fit.js` are unmodified builds of xterm.js 5.5.0 and its fit addon 0.10.0 (MIT, license in `vendor/xterm/LICENSE`, source https://github.com/xtermjs/xterm.js), vendored so the host terminal needs no CDN. Source maps are removed.
