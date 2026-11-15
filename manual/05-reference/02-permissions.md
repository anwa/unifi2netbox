# Permissions

Use dedicated tokens and keys with the least permissions that work.

## NetBox API token

**To review** the token needs read access (`view`) to:

- DCIM: devices, device types, device roles, sites, manufacturers,
  interfaces, inventory items
- IPAM: VLAN groups, VLANs, prefixes, IP addresses, IP ranges
- Wireless: wireless LANs
- Extras: custom fields

Missing optional read permissions (for example wireless LANs) only disable
that part of the review; it shows a note.

**To apply** it additionally needs, depending on what you write:

| What you write | Permissions |
| --- | --- |
| Devices | DCIM device: add, change |
| Firmware Custom Field (once) | Extras custom field: add |
| Networks | IPAM VLAN group, VLAN, prefix: add, change |
| Interfaces | DCIM interface: change (add for the `Management` interface) |
| Management IPs | IPAM IP address: add, change; DCIM device: change |
| Cables | DCIM cable: add |
| Wireless LANs | Wireless LAN: add, change |
| IP ranges, reserved IPs | IPAM IP range and IP address: add, change |
| Drive and SFP items | DCIM inventory item: add, change |

The app never needs `delete` permissions.

## UniFi keys

- **UniFi Network**: a local API key of the console. It must be able to read
  the devices of the chosen site.
- **UniFi Protect**: a local API key of the Protect console.
- **UniFi Access**: an Access API token with device-read permission only.
- **UniFi Drive**: a local API key of the UNAS.

The app only sends read requests to UniFi. If a key was ever exposed (for
example pasted into a ticket), revoke it in the console and create a new one.
