# Getting started

This part takes you from the download to the first comparison of UniFi and
NetBox. Nothing is written to NetBox along the way.

1. [Installation](01-installation.md): Windows installer, Ubuntu package,
   Linux tarball or running from source.
2. [First start](02-first-start.md): enter the connections and check them.
3. [Your first refresh](03-first-refresh.md): read both inventories and read
   the summary.

## What you need

- **NetBox** 4.7 with an API token. Reading is enough to look around; to
  apply changes the token needs write permissions (see
  [Permissions](../05-reference/02-permissions.md)).
- **UniFi Network** with a local API key of the console (UniFi Network 11.0
  is needed for port configuration, SFP modules, wireless LANs and DHCP data).
- Optional: UniFi Protect, UniFi Access and a UniFi UNAS with their own keys.
- In NetBox, ideally a **site** for your UniFi devices and the **device
  types** and **roles** you want to use. The app never creates sites, device
  types, roles or manufacturers.
