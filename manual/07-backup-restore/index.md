# Backup and restore

The app can save a whole NetBox into one file and restore such a file into a
NetBox, for example to move to a new server, to rebuild a test instance or
to return to a known state.

- [Backup](01-backup.md): read all data of the configured NetBox into a JSON
  or YAML file you choose.
- [Restore](02-restore.md): write a backup into a NetBox you enter in the
  dialog, in the right order, with a check first.

## What a backup contains

All objects of the NetBox apps circuits, DCIM (sites, racks, devices,
device types and their templates, interfaces, cables, ...), extras (tags,
custom fields, config contexts, webhooks, ...), IPAM, tenancy,
virtualization, VPN and wireless, plus owners and owner groups. Images
(device type images, image attachments) are included when **Include
images** is checked.

Never included:

- users, groups, tokens and permissions;
- secrets, for example a webhook secret or a wireless pre-shared key (the
  backup lists the fields it left out);
- the change log, jobs and other system data;
- plugin data, journal entries and personal objects (bookmarks,
  notifications, subscriptions, dashboards, saved filters).

A backup file contains your network's data (names, addresses, serials).
Keep it private.
