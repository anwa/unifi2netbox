# Write order and safeguards

## Order within one run

1. Custom Field `firmware` (if missing and checked)
2. Device types chosen from the local folder or the library, with their
   component templates
3. VLAN group, VLANs and prefixes
4. Wireless LANs and IP ranges
5. Interfaces (mode, VLANs, description, speed, PoE)
6. Cables
7. Devices (creates first, then updates, including firmware)
8. Management IPs (interface, IP, primary IPv4) and reserved IPs
9. Inventory items: UNAS drives and SFP modules

## Before each write

- **UniFi is read again once.** A change whose UniFi values differ from the
  preview, or whose device UniFi no longer reports, is skipped. If UniFi
  cannot be read, nothing that depends on it is written.
- **NetBox is read again per change.** An update is skipped if the object was
  deleted or a planned field changed since the preview; a create is skipped
  if an object with the same name, address or SSID appeared meanwhile.
- Skipped changes say why. Refresh, review the row and apply again.

## Interrupted creates

If a create is interrupted (timeout, lost connection, HTTP 502/503/504), the
app never retries it blindly. It looks the object up in NetBox and reports it
as created (with its ID), as safe to retry after a refresh, or as needing a
manual check.

## After each write

Every written object is read back from NetBox:

- **Verified**: NetBox holds the written values.
- **Mismatch**: NetBox holds other values (for example changed by a NetBox
  script); check the object.
- **Not verified**: the read-back failed.

The app never writes again on its own.

## Things the app never does

- write to UniFi,
- delete anything in NetBox,
- clear a NetBox value because UniFi has none,
- create sites, roles, manufacturers or Custom Fields other than
  `firmware`, or a device type you did not choose,
- overwrite another primary IPv4, a prefix VLAN, a WLAN VLAN or a cable.
