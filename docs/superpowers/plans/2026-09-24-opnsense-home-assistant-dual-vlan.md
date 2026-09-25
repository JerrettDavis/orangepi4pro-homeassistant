# OPNsense Home Assistant Dual-VLAN Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Home Assistant at `10.0.0.19` the inventoried discovery, control, event, and callback flows it needs across OPNsense while preserving the IoT VLAN's inability to enumerate or generally access the trusted VLAN.

**Architecture:** Keep the Orange Pi single-homed on `10.0.0.0/24` and keep OPNsense as the sole router to `10.0.107.0/24`. Derive aliases, ports, interface assignments, IPv6 treatment, and discovery services from authenticated live inspection; apply one logged, stateful, least-privilege slice at a time and require both positive application tests and negative isolation tests at every gate.

**Tech Stack:** OPNsense web administration, Packet Filter states/logs, OPNsense configuration export, Home Assistant 2026.9.3, Linux `ip`/`sysctl`/NetworkManager/nftables, Docker host networking, PowerShell evidence capture, mDNS and SSDP only when observed requirements justify them

**Spec:** `docs/superpowers/specs/2026-09-24-opnsense-home-assistant-dual-vlan-design.md`

## Global Constraints

- Home Assistant remains single-homed at `10.0.0.19`; do not add an IoT address, VLAN subinterface, bridge, second active uplink, or second default route to the Orange Pi.
- OPNsense remains the only Layer 3 path between `10.0.0.0/24` and `10.0.107.0/24`.
- “Full communication” means only inventoried discovery, HA-initiated control, state/event delivery, reconnect, and documented callback flows; it never means general IoT access to the trusted LAN.
- Do not invent OPNsense interface names, IPv6 prefixes, plugins, device addresses, or ports. Discover and record them before using them.
- Do not commit OPNsense exports, packet captures, IP/device inventories, credentials, tokens, cookies, raw logs, or private Home Assistant data. Keep all runtime evidence under the per-run temporary directory created in Task 1.
- No mutation is allowed until authenticated OPNsense administration, a verified configuration export, and console or out-of-band recovery are all available.
- Rules are placed on the interface where traffic enters OPNsense. Stateful replies never justify a broad reverse allow.
- IoT-initiated exceptions must constrain source alias, destination alias, protocol, and port. An IoT-subnet-to-HA-any rule is forbidden.
- Keep the effective final IoT-to-trusted deny. Audit floating, quick, interface-group, automatically generated, NAT, and IPv6 behavior before changing rules.
- mDNS is considered before SSDP. Enable either only when the private inventory proves it is required and static configuration is inadequate. Generic broadcast forwarding and unrestricted UPnP are forbidden.
- IPv6 must receive equivalent least-privilege rules and tests or have inter-VLAN forwarding disabled. An IPv4-only success is not acceptance.
- Do not improvise an Orange Pi host-firewall change. Any host-firewall hardening requires its own console-safe review of Docker and reverse-proxy behavior.
- Existing IoT DNS, NTP, and Internet policy remains unchanged.
- Stop rollout immediately on a failed isolation test, loss of management access, unexplained rule match, HA health regression, or contradiction with the approved spec.
- Preserve the user's existing dirty `docs/HOST-INSTALL.md` and `scripts/proxy-cert-deploy.sh`; do not stage, modify, or revert them.

## File Map and Runtime Interfaces

- Create `docs/NETWORK-SEGMENTATION.md`: sanitized operator runbook describing the final observed architecture, rule intent, test procedure, and rollback without private addresses beyond the two approved subnets and HA address, device identities, ports, exports, or captures.
- Modify `docs/ACCEPTANCE.md`: link the runbook and record only sanitized pass/fail gates after live acceptance.
- Private runtime directory `%TEMP%\opiha-dual-vlan-20260924`: configuration exports, checksums, screenshots, command output, captures, inventories, and the execution journal. This path is outside the repository and must not be staged.
- Private `execution-journal.md`: one row per mutation with time, operator, object identifier, before/after state, test result, and rollback action.
- Private `flow-inventory.csv`: exact interface/device/port/service facts consumed by the rule tasks. Required columns are defined in Task 3.
- OPNsense interface: consumes live aliases, interface assignments, rules, NAT, state/log, installed plugin, routing, RA/DHCPv6, and config-export data; produces logged aliases/rules/relay configuration whose live-generated identifiers are recorded privately.
- Orange Pi inspection interface: consumes an authenticated shell; produces routes, addresses, forwarding, bridge, NetworkManager, nftables, Docker network, HA status, and reboot-persistence evidence. It does not mutate networking in this plan.

## Review Focus

- **Hidden policy bypass:** A floating/quick/group/NAT rule or stale state must not make an intended deny pass; Task 2 inventories precedence and Tasks 4–8 test the matched rule and state before approval.
- **IPv6 escape path:** An IoT client must not reach a trusted target over IPv6 when IPv4 is denied; Tasks 2 and 7 discover the live IPv6 mode and run paired IPv4/IPv6 negative tests.
- **Discovery overexposure:** mDNS or SSDP must not expose unrelated trusted services to IoT; Task 6 inventories before/after service enumeration from the IoT test client.
- **Dynamic or infrequent callback loss:** Device events, reconnects, broker delivery, and negotiated ports must keep working after idle periods and restarts; Tasks 3, 5, and 7 exercise every critical flow and inspect states/logs.
- **Dual attachment after reboot:** The fallback Wi-Fi profile, Ethernet, Docker, or forwarding must not make the Orange Pi present on both VLANs; Tasks 2 and 7 repeat address/route/bridge/forwarding checks before and after reboot.

---

### Task 1: Establish private evidence and recovery prerequisites

**Files:**
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\execution-journal.md`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\opnsense-before.xml`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\opnsense-before.xml.sha256`

**Interfaces:**
- Consumes: Existing authorized OPNsense administrative access and console/out-of-band recovery access.
- Produces: `$RunRoot`, verified pre-change configuration export, recovery confirmation, and private mutation journal used by every later task.

- [ ] **Step 1: Create the fixed private evidence directory and prove it is outside the repository**

Run in PowerShell from the repository:

```powershell
$RepoRoot = (Resolve-Path .).Path
$RunRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'opiha-dual-vlan-20260924'
New-Item -ItemType Directory -Force -Path $RunRoot | Out-Null
$ResolvedRunRoot = (Resolve-Path $RunRoot).Path
if ($ResolvedRunRoot.StartsWith($RepoRoot, [System.StringComparison]::OrdinalIgnoreCase)) { throw 'Private evidence directory is inside repository' }
"run_root=$ResolvedRunRoot" | Set-Content -Encoding utf8 (Join-Path $RunRoot 'execution-journal.md')
git status --short
```

Expected: the run directory resolves under the Windows temporary directory; Git shows no evidence file and still shows only pre-existing dirty files plus work from this plan.

- [ ] **Step 2: Prove both administrative and recovery access without changing policy**

Authenticate through the existing OPNsense administrative URL, record the displayed OPNsense version and current time in `execution-journal.md`, then open the actual console or out-of-band session and navigate only as far as the OPNsense console menu. Do not restart or select a menu action.

Expected: both sessions are live concurrently. Record `admin_access=pass`, `recovery_access=pass`, session method, OPNsense version, and time. Stop the plan if either session is unavailable.

- [ ] **Step 3: Export the complete OPNsense configuration**

In OPNsense, use **System → Configuration → Backups**, download the complete configuration without RRD data, and save it exactly as `$RunRoot\opnsense-before.xml`. Do not commit or print the XML.

Run:

```powershell
$Export = Join-Path $RunRoot 'opnsense-before.xml'
if (-not (Test-Path -LiteralPath $Export)) { throw 'OPNsense export missing' }
if ((Get-Item -LiteralPath $Export).Length -lt 1024) { throw 'OPNsense export unexpectedly small' }
Get-FileHash -Algorithm SHA256 -LiteralPath $Export |
  Format-List Algorithm,Hash,Path |
  Set-Content -Encoding utf8 (Join-Path $RunRoot 'opnsense-before.xml.sha256')
Select-String -LiteralPath $Export -Pattern '[<]opnsense[>]' -Quiet
```

Expected: final command returns `True`; checksum file exists. Do not expose XML content in shared output.

- [ ] **Step 4: Review Gate 1 — authorize read-only discovery only**

Confirm `execution-journal.md` contains the OPNsense version, authenticated admin result, recovery result, export byte length, and SHA-256. Confirm `git status --short` shows neither export nor journal.

Expected: reviewer approves read-only discovery. No firewall, alias, NAT, plugin, interface, switch, or Orange Pi state has changed.

### Task 2: Capture the authoritative OPNsense, switch, and Orange Pi baseline

**Files:**
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\opnsense-audit.md`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\orangepi-network-before.txt`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\baseline-tests.md`

**Interfaces:**
- Consumes: Verified Task 1 export and access sessions.
- Produces: Authoritative live interface names, rule order, NAT behavior, plugin availability, IPv6 mode, host safety state, and baseline positive/negative results. Later tasks may use only values recorded here.

- [ ] **Step 1: Inventory exact OPNsense interface and policy fields**

Using read-only OPNsense pages, record these fields in `opnsense-audit.md`:

```text
OPNsense version and timestamp
Interface display name, internal identifier, parent/tag, IPv4 address/prefix, IPv6 address/prefix, gateway, enabled state
Trusted and IoT interface identity selected by matching 10.0.0.0/24 and 10.0.107.0/24
All rules on those interfaces in evaluated order: rule identifier, enabled, quick/floating/group status, action, direction, IP version, protocol, source, source port, destination, destination port, gateway, logging, description
Floating and interface-group rules that can match either subnet
Outbound/inbound/port-forward NAT entries that can translate either subnet or 10.0.0.19
Current state-policy mode and relevant live states involving 10.0.0.19 or 10.0.107.0/24
Installed plugin/package names and versions relevant to mDNS, SSDP, multicast, or broadcast relay
Routes for both IPv4 subnets and all IPv6 routes
RA mode, DHCPv6 mode, delegated/static prefixes, and firewall defaults for both VLANs
Current mDNS, SSDP, UPnP, multicast, and broadcast relay service status and participating interfaces
Existing effective IoT-to-trusted deny identifier and every higher-priority rule that could supersede it
```

Use **Interfaces → Overview**, **Firewall → Rules**, **Firewall → NAT**, **Firewall → Diagnostics → States**, **Firewall → Log Files → Live View**, **System → Firmware → Plugins/Packages**, **System → Routes → Status**, and the live **Services** pages. Menu labels may vary by observed OPNsense version; record the actual page label used rather than guessing a configuration value.

Expected: both VLANs map to one unambiguous live interface each, or the plan stops for design reconciliation. No setting is saved or applied.

- [ ] **Step 2: Verify managed-switch topology without changing it**

From the existing switch administration interface, record privately the Orange Pi's switch port or wireless path, access/trunk mode, allowed VLANs, native VLAN, and the OPNsense uplink VLAN membership.

Expected: the Orange Pi path is not concurrently attached to both VLANs, and OPNsense is the routed VLAN boundary. Stop if the topology contradicts the spec.

- [ ] **Step 3: Capture Orange Pi addressing, forwarding, bridge, firewall, and service state**

In the existing authenticated Orange Pi shell, run this read-only block and save its output locally as `orangepi-network-before.txt`:

```bash
date --iso-8601=seconds
ip -br link
ip -br address
ip -4 route show table all
ip -6 route show table all
ip rule show
sysctl net.ipv4.ip_forward net.ipv6.conf.all.forwarding
bridge link show
bridge vlan show
nmcli -f NAME,UUID,TYPE,DEVICE,AUTOCONNECT,AUTOCONNECT-PRIORITY connection show
nmcli -f GENERAL,IP4,IP6 device show
sudo nft list ruleset
docker network ls
docker inspect homeassistant --format '{{.HostConfig.NetworkMode}}' 2>/dev/null || true
systemctl is-active avahi-daemon.service 2>/dev/null || true
sudo opiha status
```

Expected: `10.0.0.19` is present; no `10.0.107.0/24` address is active; there is one intended default route; IPv4 and IPv6 forwarding report `0`; no active bridge joins the VLANs; HA uses host networking and is healthy. Any contradiction stops mutation.

- [ ] **Step 4: Record baseline positive and negative connectivity**

From a trusted test client, verify the supported HA HTTPS URL and at least two currently working trusted-LAN integrations. From the authorized IoT test client, run:

```bash
ip -br address
ip -4 route
ip -6 route
nmap -Pn -T3 --top-ports 100 10.0.0.19
nmap -Pn -T3 --top-ports 100 10.0.0.1
```

For each additional representative trusted host approved for testing, run `nmap -Pn -T3 --top-ports 100` against its exact audited address. If the IoT client has a global/ULA IPv6 address and the trusted VLAN has an audited IPv6 prefix, create private `/tmp/opiha-trusted-ipv6-targets.txt` on the IoT test client containing one literal, previously audited IPv6 address per line for HA, OPNsense's trusted interface, and each approved representative trusted host. Record the source inventory row and SHA-256 of that file, then run:

```bash
test -s /tmp/opiha-trusted-ipv6-targets.txt
while IFS= read -r address; do
  printf 'IPv6 target: %s\n' "$address"
  nmap -6 -Pn -T3 --top-ports 100 "$address"
done < /tmp/opiha-trusted-ipv6-targets.txt
```

The target file must be populated only after Gate 2 confirms the exact values; an empty, malformed, link-local, multicast, or unrecorded address stops the test. If no routed IPv6 exists, record `ipv6_inter_vlan=not_routed` with OPNsense route/RA evidence instead of creating the target file.

Expected: results establish the actual baseline. Any existing unexpected IoT access is a pre-existing security finding and blocks new passes until resolved. Record open HA ports without treating them as authorization.

- [ ] **Step 5: Review Gate 2 — approve authoritative topology and IPv6 disposition**

Reviewer checks every required audit field, confirms OPNsense is the sole router, identifies the actual trusted and IoT ingress interfaces, identifies the final deny and possible shadowing rules, and selects exactly one IPv6 disposition: equivalent least-privilege policy or confirmed-disabled inter-VLAN routing.

Expected: signed private gate entry. No live state changed.

### Task 3: Build and approve the private integration flow inventory

**Files:**
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\ha-inventory.json`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\flow-inventory.csv`

**Interfaces:**
- Consumes: Task 2 live interface/IPv6 data, HA configuration and registries, integration documentation, OPNsense logs/states, and controlled captures.
- Produces: Reviewed rows that are the sole source for device aliases, port aliases, callback rules, and discovery decisions.

- [ ] **Step 1: Capture the private Home Assistant inventory**

On the Orange Pi, create an output path outside the repository and run:

```bash
sudo install -d -m 0700 /var/lib/orangepi-homeassistant/private-network-review
sudo opiha inventory --output /var/lib/orangepi-homeassistant/private-network-review/ha-inventory.json
sudo chmod 0600 /var/lib/orangepi-homeassistant/private-network-review/ha-inventory.json
```

Copy it through the existing authenticated channel to `$RunRoot\ha-inventory.json`, verify the file is non-empty, and do not print or commit it.

Expected: inventory contains the current integration/device registry evidence needed for reconciliation.

- [ ] **Step 2: Create the inventory schema and one row per required flow**

Create `flow-inventory.csv` with this exact header:

```csv
integration,owner,criticality,device_group,source_addresses,destination_addresses,ip_version,protocol,destination_ports,initiator,discovery_method,service_types,callback_behavior,dynamic_port_behavior,dependencies,positive_test,negative_test,rollback_condition,evidence_source,approval
```

Populate rows from the HA inventory, stable DHCP reservations, vendor/official integration documentation, observed OPNsense states/logs, and short captures while actively exercising the integration. Use literal observed values in the private file. Use `none` where a field is proven inapplicable; do not leave blanks.

Expected: every critical integration has at least one row and every row cites its evidence source.

- [ ] **Step 3: Test discovery-free/static configuration first**

For each integration currently failing across the VLAN boundary, determine from its supported configuration whether a stable IP or unicast hostname provides complete control and event behavior. Record `static`, `mdns`, `ssdp`, `proprietary`, or `none` in `discovery_method`; record advertised service types only when captured or documented.

Expected: mDNS and SSDP rows exist only for integrations proven to require them. Matter/Thread rows explicitly record IPv6 and border-router dependencies and are not generalized from IPv4 tests.

- [ ] **Step 4: Classify initiator and callbacks from exercised evidence**

Exercise control, state refresh, unsolicited event, device reconnect, HA reconnect, and broker delivery as applicable. In OPNsense Live View/States or an authorized packet capture, record source, destination, IP version, protocol, source port, destination port, time, and integration action.

Expected: every requested pass is tied to a demonstrated action. Background telemetry and scans remain excluded. Infrequent callback uncertainty is recorded as a failed gate, not converted to `any`.

- [ ] **Step 5: Review Gate 3 — approve the one-device pilot and rule objects**

Select one representative IoT device with a stable address and a deterministic positive test. Reviewer approves its exact HA-initiated rows, any callback rows, alias membership, and IPv4/IPv6 treatment. Separately approve proposed alias names according to the observed OPNsense naming convention.

Expected: no row with `approval` other than `approved` can generate a live object. mDNS and SSDP remain deferred.

### Task 4: Create disabled aliases and run the one-device routed pilot

**Files:**
- Update privately: `%TEMP%\opiha-dual-vlan-20260924\execution-journal.md`
- Update privately: `%TEMP%\opiha-dual-vlan-20260924\baseline-tests.md`

**Interfaces:**
- Consumes: Approved pilot rows and live interface names from Tasks 2–3.
- Produces: OPNsense aliases and one logged trusted-ingress pass whose exact generated identifiers are recorded privately.

- [ ] **Step 1: Create and inspect aliases before any pass rule**

In OPNsense, create the approved HA host, pilot device, subnet, and protocol/port aliases using only literal values from approved inventory rows. Before applying any rule, inspect alias expansion and record name, type, members, description, and generated object identifier in the journal.

Expected: HA alias expands only to `10.0.0.19`; pilot alias expands only to the stable device address; each port alias contains only approved protocol-compatible ports. No secret or device identity is copied into the repository.

- [ ] **Step 2: Create the pilot rule disabled**

On the live trusted ingress interface identified in Task 2, create one disabled, logged pass rule with source HA alias, destination pilot-device alias, exact protocol and destination-port alias, default gateway behavior, and a description containing the run date and integration purpose.

Expected: previewed placement is above only the rules it must precede and does not alter IoT ingress. Reviewer confirms no floating rule, `any` source/destination/port, or NAT change is involved.

- [ ] **Step 3: Enable the pilot and prove stateful directionality**

Enable/apply only the pilot rule, initiate the approved control action from HA, and inspect OPNsense Live View and States.

Expected: the rule log shows `10.0.0.19` as initiator, the state uses the expected destination/protocol/port, the action succeeds, and replies use that state. There is no reverse IoT pass rule.

- [ ] **Step 4: Run the pilot negative suite**

Repeat the Task 2 IoT scans against `10.0.0.19`, the OPNsense trusted address, and representative trusted hosts. From a non-approved IoT device, attempt the pilot destination port toward `10.0.0.19`. For routed IPv6, repeat the equivalent IPv6 attempts.

Expected: no new trusted service becomes reachable; the non-approved device cannot borrow the pilot flow; the effective deny logs the probes where logging is enabled.

- [ ] **Step 5: Review Gate 4 — accept or roll back the pilot**

Record exact rule/alias identifiers, positive result, negative result, and matched state/rule. If any result is unexpected, disable the pilot rule, clear only its source/destination/protocol states through **Firewall → Diagnostics → States**, re-run the baseline, and stop.

Expected: reviewer approves expansion only when both suites pass.

### Task 5: Add source-constrained callbacks and expand integration groups

**Files:**
- Update privately: `%TEMP%\opiha-dual-vlan-20260924\execution-journal.md`
- Update privately: `%TEMP%\opiha-dual-vlan-20260924\flow-inventory.csv`

**Interfaces:**
- Consumes: Approved callback rows and device groups from Task 3 plus the proven Task 4 rule pattern.
- Produces: Logged IoT-ingress callback rules and incremental HA-to-IoT group rules with per-slice acceptance evidence.

- [ ] **Step 1: Add one callback rule disabled and inspect ordering**

For the first approved unsolicited callback, create a disabled, logged rule on the audited IoT ingress interface. Set source to its approved stable device alias, destination to the HA/broker/proxy alias, and protocol/port to the approved row. Place it before the effective IoT-to-trusted deny without changing the deny.

Expected: no field is `any` unless the approved protocol itself has no port concept and the reviewer documented why. The rule cannot match a second IoT device.

- [ ] **Step 2: Enable and test the callback in both directions of evidence**

Enable/apply only that rule, trigger the device-originated event, verify HA receives the event, and match the event time to the OPNsense log/state. Then attempt the same destination/port from the non-approved IoT device and attempt two unapproved HA ports from the approved device.

Expected: required event passes; all three unauthorized attempts fail.

- [ ] **Step 3: Exercise idle and reconnect behavior**

After the normal integration idle interval, repeat the event. Restart only the representative device, wait for its supported recovery interval, and repeat control and callback tests. Do not restart OPNsense or HA in this step.

Expected: events and HA state recover without broadening the rule or manually seeding an unrelated state.

- [ ] **Step 4: Repeat the reviewed slice for each approved group**

For each additional approved inventory group, create aliases and disabled rules, review expansion/order, enable only that slice, run its positive tests, then run the shared IPv4 and applicable IPv6 negative suite before continuing.

Expected: each journal row references literal object identifiers and inventory rows. A failed slice is disabled and its associated states are cleared before the next slice; rollout does not continue through a failure.

- [ ] **Step 5: Review Gate 5 — callback and routed-flow completeness**

Reconcile live enabled objects back to approved inventory rows. Confirm there is no IoT-subnet-to-HA-any pass, no generic trusted-to-IoT pass, no new NAT, and no orphan alias/rule.

Expected: reviewer approves routed flows before any discovery relay is considered.

### Task 6: Add narrowly scoped discovery only where observed requirements remain

**Files:**
- Update privately: `%TEMP%\opiha-dual-vlan-20260924\execution-journal.md`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\discovery-before.txt`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\discovery-after.txt`

**Interfaces:**
- Consumes: Approved discovery rows, audited installed plugin/service capabilities, and static-configuration results.
- Produces: At most one reviewed discovery mechanism per slice, with enumeration-delta evidence. mDNS precedes SSDP.

- [ ] **Step 1: Capture pre-relay discovery exposure from the IoT client**

On the authorized IoT Linux test client, run and save bounded output:

```bash
timeout 20s avahi-browse --all --terminate --resolve 2>&1 | sort
timeout 20s gssdp-discover --timeout=5 2>&1 | sort
```

If either utility is absent, record its absence and use the already installed, approved equivalent identified in Task 2; do not install software during the firewall change window. Record service type, instance, hostname, address, port, and originating VLAN for every observed entry.

Expected: `discovery-before.txt` establishes current exposure.

- [ ] **Step 2: Configure mDNS only if an approved row requires it**

If and only if Task 3 contains an approved `mdns` row, use the supported OPNsense mechanism audited in Task 2. Select only the actual trusted and IoT interfaces. Apply service-type filtering when the audited mechanism supports it; otherwise obtain explicit reviewer acceptance of bidirectional metadata disclosure before enabling it. Add only firewall treatment documented by that exact installed mechanism.

Expected: no Avahi change occurs on the Orange Pi, no third interface participates, and no generic broadcast relay is enabled. If no approved mDNS row exists, record `mdns=not_required` and make no change.

- [ ] **Step 3: Test mDNS function and disclosure before considering SSDP**

Trigger the HA discovery flow, verify the integration's control/event behavior, and repeat the bounded `avahi-browse` capture from the IoT client.

Expected: required HA service discovery works; unrelated trusted services do not newly appear beyond the disclosure explicitly approved in Step 2. On excess disclosure, disable the reflector, clear its affected states if present, prefer static configuration, and stop this slice.

- [ ] **Step 4: Configure and test SSDP only if an approved row still requires it**

If and only if Task 3 contains an approved `ssdp` row that mDNS/static handling did not satisfy, configure the audited supported OPNsense SSDP relay for only the trusted and IoT interfaces and UDP 1900 behavior documented by that implementation. Do not enable unrestricted UPnP or a generic UDP/broadcast relay. Trigger discovery/control, repeat `gssdp-discover`, and inspect multicast request plus unicast response logs/capture.

Expected: the required integration works and unrelated trusted UPnP services are not newly exposed beyond explicit approval. If no approved SSDP row exists, record `ssdp=not_required` and make no change.

- [ ] **Step 5: Review Gate 6 — approve discovery exposure**

Diff `discovery-before.txt` and `discovery-after.txt`, map every new service to an approved row, and repeat the unicast IPv4/IPv6 negative scans.

Expected: reviewer accepts the exact exposure. Any unexplained service or newly reachable unicast endpoint rolls back the discovery slice.

### Task 7: Validate host safety, IPv4/IPv6 isolation, application behavior, and reboot persistence

**Files:**
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\orangepi-network-after.txt`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\acceptance-results.md`

**Interfaces:**
- Consumes: All enabled Task 4–6 objects and the complete approved flow inventory.
- Produces: Full positive/negative acceptance evidence after controlled restarts and the decision whether host-firewall work needs a separate design.

- [ ] **Step 1: Repeat the Orange Pi single-homing safety audit**

Run the exact Task 2 Orange Pi command block and save it as `orangepi-network-after.txt`. Compare addresses, routes, rules, forwarding, bridges, NetworkManager profiles, nftables, Docker network mode, Avahi, and HA health.

Expected: no active IoT address, extra default route, bridge, forwarding, or unexpected host-firewall change; HA remains on host networking. If the existing host firewall does not provide useful defense in depth, record a separate follow-up design requirement rather than changing it now.

- [ ] **Step 2: Run every inventory positive test**

For every row marked `approved`, run its literal `positive_test`: discovery where required, control, state refresh, unsolicited callback, broker event, and critical automation. Record start time, observed HA result, OPNsense matched rule/state, and latency/recovery result.

Expected: every critical row passes; no duplicate or stale automation action occurs.

- [ ] **Step 3: Run the complete IPv4 and IPv6 negative enumeration suite**

From the IoT client, repeat the Task 2 top-100 scans, add the exact documented HA callback ports and two unapproved HA ports, test from a non-approved device, and enumerate mDNS/SSDP. For routed IPv6, repeat equivalent scans against HA, OPNsense trusted address, and representative trusted hosts using their audited literal IPv6 addresses.

Expected: only explicitly approved source-constrained endpoints pass. If IPv6 inter-VLAN routing is disabled, verify absence of a route and confirm OPNsense logs/configuration show no forwarding path.

- [ ] **Step 4: Validate HA and device restart recovery**

During the approved maintenance window, restart Home Assistant using the repository-supported service path:

```bash
sudo systemctl restart opiha-stack.service
sudo opiha status
```

Then restart one representative device per critical group. Repeat each group's control, state, callback, and automation tests after supported recovery intervals.

Expected: all critical integrations recover without manual rule/state manipulation.

- [ ] **Step 5: Validate OPNsense filter reload and reboot persistence**

First use the normal OPNsense apply/filter-reload path and repeat HA health plus the negative suite. Only after that passes and console recovery remains active, reboot OPNsense in the approved window. Confirm interfaces, routes, aliases, rule order, relays, IPv6 disposition, and services return, then repeat all critical positives and the full negative suite.

Expected: configuration persists and recovery does not depend on a stale state. The Orange Pi remains single-homed after network recovery.

- [ ] **Step 6: Review Gate 7 — final technical acceptance**

Reviewer maps every spec positive and negative acceptance requirement to a timestamped result and confirms each Review Focus item has its corresponding passing test.

Expected: no missing critical row, unexplained pass, broad diagnostic rule, excess discovery service, or unresolved IPv6 path.

### Task 8: Tighten, document, export final state, and rehearse rollback

**Files:**
- Create: `docs/NETWORK-SEGMENTATION.md`
- Modify: `docs/ACCEPTANCE.md`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\opnsense-after.xml`
- Create privately, do not commit: `%TEMP%\opiha-dual-vlan-20260924\opnsense-after.xml.sha256`

**Interfaces:**
- Consumes: Accepted live objects and evidence from Tasks 1–7.
- Produces: Least-privilege final state, sanitized repository runbook, final private export, and proven targeted rollback sequence.

- [ ] **Step 1: Remove time-bounded and orphaned objects**

Compare enabled aliases/rules/relays to approved inventory rows. Disable and then remove every diagnostic broad rule, unused alias member, orphan rule, unused plugin configuration, and unneeded discovery mechanism. Confirm no remaining object lacks an owner, positive test, negative test, and removal condition.

Expected: HA-to-IoT is limited to approved device/port groups; IoT callbacks are source constrained; final deny and existing DNS/NTP/Internet behavior remain intact.

- [ ] **Step 2: Prove targeted rollback and state-clearing behavior**

Select the representative pilot rule. Disable it, identify only states matching its audited source, destination, IP version, protocol, and port in **Firewall → Diagnostics → States**, clear those states, and run its positive test plus shared negative test.

Expected: only the pilot function fails; isolation remains intact. Re-enable the rule, repeat the positive test, and record exact rollback/recovery steps. Do not perform a global state reset.

- [ ] **Step 3: Export and hash the accepted OPNsense configuration**

Download the complete accepted configuration as `$RunRoot\opnsense-after.xml` and run:

```powershell
$FinalExport = Join-Path $RunRoot 'opnsense-after.xml'
if (-not (Test-Path -LiteralPath $FinalExport)) { throw 'Final OPNsense export missing' }
Get-FileHash -Algorithm SHA256 -LiteralPath $FinalExport |
  Format-List Algorithm,Hash,Path |
  Set-Content -Encoding utf8 (Join-Path $RunRoot 'opnsense-after.xml.sha256')
```

Expected: final export and checksum exist privately; neither appears in Git.

- [ ] **Step 4: Write the sanitized operator runbook**

Create `docs/NETWORK-SEGMENTATION.md` with: purpose and definition of full communication; single-homed topology; OPNsense rule-direction/order principles; alias classes without private member lists; mDNS/SSDP decision and exposure boundary; IPv6 disposition; host forwarding/bridge invariants; positive/negative validation procedure; targeted state clearing; reverse-order rollback; locations of private evidence by policy, not by copied secrets; and dated observed acceptance summary.

Expected: no credentials, device names, MAC addresses, non-approved host addresses, literal private port inventory, XML, logs, captures, or screenshots are present.

- [ ] **Step 5: Update repository acceptance status**

Add a concise dated entry to `docs/ACCEPTANCE.md` linking `docs/NETWORK-SEGMENTATION.md`. Mark only gates supported by Task 7 evidence as passed; list any optional integration not exercised as not validated rather than implying full household coverage.

Expected: documentation distinguishes architecture completion, live rule deployment, critical integration coverage, and optional integration gaps.

- [ ] **Step 6: Run documentation and secret-safety checks**

Run:

```powershell
git diff --check -- docs/NETWORK-SEGMENTATION.md docs/ACCEPTANCE.md
Select-String -Path docs/NETWORK-SEGMENTATION.md,docs/ACCEPTANCE.md -Pattern 'password|token|cookie|BEGIN .*PRIVATE KEY|[<]opnsense[>]|10\.0\.107\.(?:[1-9]|[1-9][0-9]|1[0-9]{2}|2(?:[0-4][0-9]|5[0-4]))\b' -CaseSensitive:$false
python scripts/validate.py
git status --short
```

Expected: diff check and validation pass; search has no secret material or individual IoT addresses; Git contains only the intended documentation changes plus pre-existing user changes.

- [ ] **Step 7: Commit only sanitized documentation**

```powershell
git add -- docs/NETWORK-SEGMENTATION.md docs/ACCEPTANCE.md
git diff --cached --check
git diff --cached --name-only
git commit -m "docs: record segmented Home Assistant network"
```

Expected: staged-name output lists exactly the two documentation files. Private runtime evidence and the pre-existing dirty files remain untracked or unstaged.

- [ ] **Step 8: Review Gate 8 — operational handoff**

Reviewer verifies the final OPNsense export checksum, console recovery path, live rule/alias identifiers, discovery exposure, IPv6 disposition, full acceptance matrix, targeted rollback rehearsal, and sanitized documentation.

Expected: handoff names the maintainer and review date for every exception. Full completion is claimed only for inventoried and tested integrations; future devices require the same gated inventory process.
