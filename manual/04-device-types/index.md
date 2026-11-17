# Device types

A new device can only be created in NetBox with a **device type** (for
example *Ubiquiti U6 Pro*). New UniFi models are often missing in NetBox. The
app helps in three ways:

1. [Choosing a device type](01-choosing.md): a picker searches NetBox, your
   local type folder and the
   [netbox-community devicetype-library](https://github.com/netbox-community/devicetype-library).
2. [The device type editor](02-editor.md): write or complete a definition,
   with data from UniFi and techspecs.ui.com for UniFi models, and the
   [NetBox fields](05-netbox-fields.md) (owner, platform, tags, custom
   fields, images) with drop-downs read from NetBox.
3. [Importing into NetBox](04-import.md): a chosen definition that NetBox does
   not have yet is created on apply, as a step you can see and uncheck.
4. [Syncing with NetBox](06-netbox-sync.md): the editor shows how each local
   definition differs from its NetBox type and syncs them, per value or by
   overwriting NetBox, after checks that protect placed devices.

[The local type folder and the library](03-folder-and-library.md) explains
where definitions are kept and how to contribute them to the library.

## Rules

- Definitions keep the devicetype-library form (YAML layout, file names,
  slugs) and are checked against its schema and contribution rules, extended
  by every field NetBox 4.7 has for device types: owner, default platform,
  tags, custom fields, cooling, end of life, images and all template kinds.
  The library itself is only read.
- The app creates a device type in NetBox only when you chose it for a new
  device and the import step is checked, or when you sync a definition that
  NetBox does not have. It changes an existing type only through a confirmed
  sync; it never deletes types or templates and never changes existing
  devices.
- Manufacturers, owners, owner groups, tags, platforms and inventory item
  roles are created only from a **New...** dialog in the editor, after you
  click **Create** there. The app never creates sites or device roles.
- techspecs.ui.com and GitHub are only read, on your request; the app sends
  them a model name or file name, nothing about your network.
