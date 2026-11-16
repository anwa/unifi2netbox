# What is written

Every write needs your selection and confirmation. "Create" means the object
is created when missing; "update" means existing objects are completed or
aligned as described.

| NetBox object | Create | Update | Fields |
| --- | --- | --- | --- |
| Custom Field `firmware` | yes | no | text, for devices |
| Device type (chosen definition) | yes | no | model, slug, part number, height, depth, airflow, weight, description, comments, component templates |
| Device | yes | yes | name, serial, site (update); name, device type, role, site, status, serial, firmware (create) |
| Device Custom Field | – | yes | `firmware` |
| VLAN group `UniFi <site>` | yes | no | scoped to the site |
| VLAN | yes | yes | VID, name |
| Prefix | yes | yes | prefix, site scope, VLAN (filled when empty) |
| Interface | `Management` only | yes | enabled, mode, untagged/tagged VLANs, description, speed, duplex, PoE mode and type |
| IP address (management) | yes | assign | address, status *active*, interface, device primary IPv4 |
| Cable | yes | no | between two interfaces without a cable |
| Wireless LAN | yes | yes | SSID, status, authentication type and cipher, VLAN, site scope |
| IP range | yes | yes | start, end, status *active*, description (filled when empty) |
| IP address (reserved) | yes | yes | address, status *reserved*, DNS name and description (filled when empty) |
| Inventory item (drive) | yes | yes | `Disk <slot>`: part ID, serial, description |
| Inventory item (SFP) | yes | yes | `Transceiver <interface>`: part ID, serial, description, manufacturer, interface |

Never written: anything in UniFi; deletions of any kind; sites, roles,
manufacturers, tags; device types you did not choose; the live link state and
speed of ports; LAGs; Wi-Fi passphrases.
