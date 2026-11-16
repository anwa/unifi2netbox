# Device types

A new device can only be created in NetBox with a **device type** (for
example *Ubiquiti U6 Pro*). New UniFi models are often missing in NetBox. The
app helps in three ways:

1. [Choosing a device type](01-choosing.md): a picker searches NetBox, your
   local type folder and the
   [netbox-community devicetype-library](https://github.com/netbox-community/devicetype-library).
2. [The device type editor](02-editor.md): write or complete a definition,
   with data from UniFi and techspecs.ui.com for UniFi models.
3. [Importing into NetBox](04-import.md): a chosen definition that NetBox does
   not have yet is created on apply, as a step you can see and uncheck.

[The local type folder and the library](03-folder-and-library.md) explains
where definitions are kept and how to contribute them to the library.

## Rules

- Definitions use the devicetype-library format and are checked against its
  schema and contribution rules, so you can submit them there.
- The app creates a device type in NetBox only when you chose it for a new
  device and the import step is checked; it never creates manufacturers,
  sites or roles.
- techspecs.ui.com and GitHub are only read, on your request; the app sends
  them a model name or file name, nothing about your network.
