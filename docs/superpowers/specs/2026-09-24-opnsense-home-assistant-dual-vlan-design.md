# OPNsense Home Assistant dual-VLAN design

## Purpose and scope

Restore Home Assistant's ability to discover, control, and receive events from
devices on both the trusted `10.0.0.0/24` network and the IoT
`10.0.107.0/24` network without restoring the old server's dual-homed trust
boundary. Home Assistant remains single-homed at `10.0.0.19`; OPNsense remains
the sole Layer 3 path between the two VLANs.

In this design, **full communication** means the flows required for each
approved Home Assistant integration: discovery, HA-initiated control, state
updates, reconnects, and documented device-initiated callbacks. It does not
mean unrestricted connectivity from IoT devices to Home Assistant or to the
trusted LAN.

This document defines the architecture and rollout gates. It deliberately does
not invent device ports, OPNsense interface names, IPv6 prefixes, or plugin
availability that have not yet been observed.

## Authoritative current state

The following observations are authoritative for this design as of
2026-09-24:

- Home Assistant is running on the Orange Pi at `10.0.0.19` and uses host
  networking in appliance mode.
- The trusted network is `10.0.0.0/24`; the IoT network is
  `10.0.107.0/24`.
- NetworkManager manages the Orange Pi. Wi-Fi owns its default route on the
  trusted network; Ethernet is present but down. The former IoT Wi-Fi profile
  is retained only as a lower-priority fallback, not as a concurrent routed
  interface.
- The Orange Pi's Avahi service is inactive. No discovery reflector is
  currently assumed.
- OPNsense is the intended router and policy enforcement point between the
  VLANs.
- The restored Home Assistant configuration contains integrations whose exact
  cross-VLAN flow requirements have not yet been reconciled into a complete
  device/port inventory.

The live OPNsense configuration, switch configuration, IPv6 state, and packet
captures take precedence over repository documentation during planning. A
change must stop if those observations contradict this baseline.

## Selected architecture

```text
Trusted VLAN: 10.0.0.0/24
  Home Assistant: 10.0.0.19
              |
              | stateful, routed, logged policy
              v
           OPNsense
              |
              | no general IoT-to-trusted access
              v
IoT VLAN: 10.0.107.0/24
  approved devices, brokers, and gateways
```

The Orange Pi receives no IoT VLAN address, tagged IoT subinterface, bridge,
or second default route. OPNsense owns cross-VLAN routing, firewall policy,
discovery relays, state inspection, and rollback. This keeps policy in one
auditable enforcement point and avoids making a compromised Home Assistant
host a dual-homed bridge.

Protocol-specific proxies or gateways may supplement OPNsense when they expose
a smaller interface than routed access. Examples include an authenticated MQTT
broker or an ESPHome/Bluetooth proxy. They do not replace the central policy,
and there is no generic proxy that supplies all Home Assistant integration
behavior.

## Security invariants

The implementation must preserve all of these invariants:

1. OPNsense is the only router between the trusted and IoT VLANs. The Orange
   Pi neither routes nor bridges them.
2. IoT devices cannot initiate general connections to `10.0.0.0/24`.
3. An IoT-initiated exception is limited to a known source device or device
   group, destination `10.0.0.19` or another explicitly named endpoint, and
   the required protocol and port.
4. Replies belonging to an HA-initiated state are allowed by OPNsense's state
   table, not by a broad reverse rule.
5. Discovery reflection is controlled information disclosure. Only required
   protocols and participating VLANs are eligible; generic broadcast
   forwarding is prohibited.
6. IPv6 cannot provide a path that bypasses the IPv4 policy. It receives
   equivalent policy or has inter-VLAN forwarding disabled until designed and
   tested.
7. The final IoT-to-trusted deny remains effective. No floating, quick, group,
   or automatically generated rule may supersede it.
8. Every exception has an integration owner, traffic direction, source,
   destination, protocol, port or discovery service, test, and removal
   criterion.
9. Existing IoT DNS, NTP, and Internet policy is independent of this change
   and is not broadened implicitly.

## OPNsense policy model

### Aliases

Use descriptive aliases rather than embedding addresses throughout rules. The
conceptual alias set is:

- the Home Assistant host (`10.0.0.19`);
- the trusted subnet (`10.0.0.0/24`);
- the IoT subnet (`10.0.107.0/24`);
- approved IoT device groups, split further when their trust or port needs
  differ;
- integration-specific TCP and UDP port groups; and
- named brokers, proxies, DNS, or NTP endpoints where relevant.

Alias names must follow the existing OPNsense convention discovered during
implementation. Dynamic DHCP devices need stable reservations before they are
used as source-constrained aliases.

### Rule direction and order

Rules are evaluated on the interface where traffic enters OPNsense. Exact
interface names must be read from the live configuration rather than inferred.
The conceptual order is:

1. On the trusted ingress interface, allow the Home Assistant alias to the
   approved IoT device aliases on integration-required ports.
2. On the IoT ingress interface, allow only documented device-initiated flows
   from approved IoT aliases to the Home Assistant, broker, or proxy alias on
   required ports.
3. Retain the effective IoT-to-trusted deny after those narrow exceptions.
4. Preserve existing infrastructure and Internet rules that are outside this
   design.

OPNsense state permits return packets for HA-initiated TCP and UDP flows.
Creating a general IoT-to-HA rule for response traffic would defeat the
design. Rules are logged during rollout, with noise reduced only after their
behavior has been proven. Existing floating, interface-group, NAT, and IPv6
rules must be audited because rule order or translation can alter the apparent
flow.

An initial broad HA-to-IoT diagnostic rule is acceptable only when it is
explicitly time-bounded, logged, limited to source `10.0.0.19`, and paired
with a scheduled tightening gate. An IoT-subnet-to-HA-any rule is not an
acceptable steady state or default diagnostic step.

## Integration flow inventory

No production rule is created merely because a port is common for a product.
Build a private inventory from Home Assistant entries, device registries,
integration documentation, current OPNsense states, and short packet captures.
For each integration or device group, record:

- owner and operational importance;
- device address or stable reservation and VLAN;
- initiating side: HA, device, broker, or both;
- destination and TCP/UDP port;
- discovery method and advertised service type when known;
- unsolicited callback, multicast, broadcast, or dynamic-port behavior;
- cloud, DNS, NTP, broker, or gateway dependencies;
- positive functional test and negative isolation test; and
- rollback/removal condition.

Observed traffic is evidence, not automatic authorization. Background scans,
telemetry, and unrelated broadcasts remain denied. Conversely, a quiet packet
capture does not prove that infrequent callbacks, re-pairing, failover, or
firmware-update flows are unnecessary. Critical integrations must be exercised
during capture and again after device and HA reconnects.

Typical patterns guide investigation but do not pre-authorize rules:

- ESPHome normally uses HA-initiated TCP API connections and mDNS discovery.
- An MQTT device initiates a connection to its broker; broker placement,
  authentication, TLS, and client identity determine the rule.
- Some Shelly generations send unsolicited CoIoT UDP updates to HA.
- HomeKit Controller commonly uses mDNS followed by HA-initiated negotiated
  connections.
- Cast, DLNA, Matter, and proprietary media integrations may combine discovery
  with dynamic unicast flows and require integration-specific validation.

## Discovery handling

### mDNS

mDNS uses link-local multicast UDP 5353 and does not cross a routed boundary
without a reflector or repeater. If the inventory proves mDNS is required,
enable a supported OPNsense mechanism only between the trusted and IoT
interfaces. Add only the firewall treatment required by that mechanism.

Where supported, filter reflected service types to those required by Home
Assistant. If the selected implementation reflects all mDNS records in both
directions, the acceptance test must prove that an IoT client cannot use it to
enumerate unrelated trusted services. If that disclosure cannot be bounded,
prefer static integration configuration, unicast DNS, or a dedicated
integration proxy.

Avahi on the Orange Pi is not enabled for this purpose: doing so would move
the cross-VLAN function away from the sole-router design and still require a
second network presence to reflect between links.

### SSDP

SSDP uses UDP 1900 multicast and is separate from mDNS. If an integration
requires it, use a supported, narrowly scoped relay between the same two
interfaces and validate both multicast requests and unicast responses. An
mDNS plugin does not imply SSDP support. Do not enable a generic UDP broadcast
relay or UPnP control-plane exposure as a substitute.

### Static and other discovery

Prefer stable reservations and manual/static integration endpoints where they
provide complete behavior. DHCP broadcasts, subnet-directed broadcasts, Wake
on LAN, and proprietary discovery do not automatically traverse this design.
Each needs a narrow relay or local proxy justified by the inventory. If a
protocol can work only with shared Layer 2 adjacency, treat that as an explicit
exception requiring a new design review rather than dual-homing the Orange Pi
silently.

## IPv4 and IPv6

The IPv4 policy covers the two known `/24` networks. Before rollout, audit
OPNsense interface assignments, router advertisements, DHCPv6, delegated or
static prefixes, firewall defaults, and the Orange Pi and device IPv6
addresses. Choose one of two explicit states:

1. implement equivalent least-privilege inter-VLAN IPv6 rules and discovery
   handling, then test them independently; or
2. disable inter-VLAN IPv6 forwarding for this path until equivalent policy
   is ready.

Disabling only IPv6 rules while routing remains possible is not sufficient.
Matter and Thread dependencies must be assessed separately because IPv6,
link-local discovery, border routers, and fabric behavior can make an
IPv4-only success test misleading.

## Orange Pi host controls

The host must have IPv4 and IPv6 forwarding disabled and must not contain an
active bridge between trusted and IoT networks. NetworkManager profiles,
Docker networking, policy routing, and fallback Wi-Fi behavior must be checked
after reboot. The retained IoT fallback profile must never create concurrent
dual attachment during normal trusted-network operation.

Because Home Assistant uses host networking, the host firewall and Home
Assistant authentication remain security boundaries. Where practical, the
host firewall should mirror the approved IoT source and destination-port
constraints as defense in depth. A host-firewall change must account for
Docker and the reverse proxy and requires its own console-safe rollback; it
must not be improvised during the OPNsense rule change.

## Access prerequisites

Implementation cannot begin until the operator has:

- authorized administrative access to OPNsense and a current restorable
  configuration export;
- a session path that will survive a firewall mistake, preferably local or
  out-of-band console access;
- read access to firewall rules, aliases, NAT, states, logs, interface
  assignments, installed discovery plugins, and IPv6 configuration;
- access to managed-switch/VLAN configuration for verification, without a
  presumption that it must change;
- Orange Pi SSH or console access for read-only route, address, forwarding,
  firewall, NetworkManager, Docker, and HA health checks;
- representative trusted and IoT test clients plus at least one device from
  every critical integration class; and
- a private place to store address, port, device, and packet-capture evidence.

Unknown credentials, unavailable console recovery, an unexported OPNsense
configuration, or unstable device addressing blocks mutation but not further
read-only inventory.

## Phased rollout

1. **Baseline:** Export OPNsense configuration. Record rule order, aliases,
   states, routing, NAT, IPv6, discovery services, HA health, Orange Pi routes
   and forwarding, and positive/negative connectivity results.
2. **Inventory:** Reconcile every critical integration into the flow inventory.
   Assign stable device addresses where required. Resolve whether mDNS, SSDP,
   callbacks, dynamic ports, IPv6, or a broker/proxy is actually needed.
3. **One-device routed pilot:** Add disabled aliases and rules, review their
   expansion and order, then enable HA-to-one-device access. Prove stateful
   replies and unchanged IoT isolation.
4. **Callbacks:** Add one source-constrained device-to-HA callback at a time.
   Exercise the associated event path and confirm other ports remain closed.
5. **Discovery:** Enable one discovery mechanism at a time only after static
   configuration has been evaluated. Test useful discovery and unwanted
   disclosure together.
6. **Integration expansion:** Add reviewed device groups incrementally. After
   every group, run its positive tests and the shared negative suite.
7. **Persistence and tightening:** Reboot or deliberately restart the relevant
   components, test reconnect and automation behavior, inspect logs and states,
   and replace any time-bounded broad diagnostic rule with inventory-derived
   aliases and ports.
8. **Acceptance:** Preserve the final configuration export, rule/alias
   inventory, test evidence, and explicit rollback point.

Each phase is a gate. A failed isolation test stops expansion even if device
control works.

## Acceptance tests

### Positive tests

- A trusted client reaches Home Assistant through the existing supported URL,
  and HA remains healthy throughout the change.
- HA discovers each integration whose approved design requires reflected
  discovery; integrations using static endpoints reconnect without reflection.
- HA controls representative devices in every approved IoT group and receives
  their current state.
- Every documented unsolicited callback or broker-originated event reaches HA.
- Critical automations run end to end without duplicated or stale actions.
- Integrations reconnect after an HA restart, representative device restart,
  and OPNsense reboot or filter reload.
- OPNsense logs and states show the expected initiator, destination, protocol,
  and rule for each test in both IPv4 and IPv6 where IPv6 is enabled.

### Negative tests

- An IoT test client cannot scan or connect to multiple representative trusted
  hosts and services.
- The same client cannot connect to `10.0.0.19` on any port except a documented
  source-constrained callback endpoint.
- A non-approved IoT device cannot use an approved device's exception.
- IoT clients cannot enumerate unrelated trusted services through mDNS, SSDP,
  or another relay beyond the explicitly accepted disclosure of the chosen
  mechanism.
- Unsolicited packets that resemble return traffic but lack a valid state are
  denied.
- IPv6 cannot reach a destination that the equivalent IPv4 policy denies.
- Removing or disabling an integration rule breaks only its documented flow,
  demonstrating that a broader rule is not masking it.

A ping, HA dashboard load, successful discovery notification, or one working
device is not sufficient evidence for acceptance.

## Rollback

Before mutation, export the OPNsense configuration and identify the precise
new aliases, rules, relay settings, and packages. Roll back in reverse order:

1. disable the new discovery relay or reflector;
2. disable the new callback rules;
3. disable the new HA-to-IoT rules;
4. remove implementation-owned aliases or plugin changes after confirming no
   other rule references them; and
5. restore the configuration export if targeted rollback does not reproduce
   the baseline.

Clear only states associated with the changed flows when necessary; existing
states can make a reverted pass rule appear effective. Avoid a global state
reset unless its interruption has been explicitly approved. Verify HA health,
trusted access, original IoT isolation, DNS/NTP/Internet behavior, and IPv6
after rollback. This architecture requires no Orange Pi network change, so a
normal rollback does not add or remove host interfaces.

## Risks and mitigations

- **Service disclosure through reflection:** Prefer static configuration or
  service filtering; test enumeration from the IoT side.
- **Over-broad device groups or ports:** Start with one device and one flow,
  log matches, and tighten before expansion.
- **Rule-shadowing or stale state:** Audit floating/group rules and inspect the
  matched rule and state; clear only affected states during verification.
- **IPv6 bypass:** Apply equivalent policy or disable inter-VLAN IPv6 routing,
  then run independent negative tests.
- **Dynamic or undocumented protocols:** Exercise real integration functions
  and reconnect cases; do not translate every observed packet into a pass.
- **Home Assistant compromise:** Keep HA single-homed, restrict IoT initiation,
  retain host firewall/authentication, and avoid granting HA general management
  access to trusted infrastructure.
- **OPNsense or plugin upgrade behavior:** Record versions and supported
  configuration, test persistence after reload/reboot, and retain the export.
- **Lockout or household disruption:** Use staged changes, out-of-band access,
  narrow state clearing, and a defined maintenance window.

## Explicit non-goals

- Reproducing the old server's two physical NICs, dual attachment, or Layer 2
  presence on both VLANs.
- Allowing the IoT VLAN to enumerate or generally access the trusted VLAN.
- Publishing the Home Assistant UI broadly to IoT devices.
- Enabling generic broadcast forwarding, unrestricted UPnP, or an
  IoT-subnet-to-HA-any rule.
- Readdressing VLANs, replacing OPNsense, redesigning Internet egress, or
  changing trusted-client access to Home Assistant.
- Migrating MQTT, Matter, Thread, Z-Wave, ESPHome, media services, or other
  add-ons except where their network flows must be represented in the
  inventory.
- Changing Orange Pi network profiles, switch trunking, Docker topology, or
  live firewall state as part of this specification.
- Treating discovery success as proof of device control, event delivery, or
  segmentation.

## Design outcome

The accepted outcome is not that both VLANs can reach Home Assistant equally.
It is that Home Assistant can perform every inventoried household integration
flow across an OPNsense-enforced boundary while IoT devices remain unable to
enumerate or access the trusted LAN beyond narrowly documented callbacks. The
implementation is complete only when both the positive integration suite and
the negative isolation suite pass after restart and the rollback path has been
preserved.
