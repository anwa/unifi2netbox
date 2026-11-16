# Importing into NetBox

A new device whose chosen type is a local or library definition shows the
type as *imported on apply*, with a checkbox **Import this device type into
NetBox**.

![A chosen local type, imported on apply](../images/review-device-type-import.png)

## What happens on apply

The import runs right after the Custom Field and before any device is
written:

1. NetBox is read again. If a type with the same slug exists by now, it is
   used and nothing is created.
2. The device type is created with model, slug, part number, height, depth,
   airflow, weight, description and comments.
3. Its component templates are created: interfaces (with PoE), console and
   console server ports, power ports and outlets, module bays, device bays
   and inventory items.
4. The type is read back and its templates are counted (*Verified* or
   *Mismatch*).
5. The new devices are created with the new type.

The apply bar and the confirmation count the device types. A dry run checks
everything and creates nothing.

## When the app does not import

| Situation | What you see |
| --- | --- |
| NetBox already has the same manufacturer and model or part number | The existing type is used; nothing is imported. |
| The manufacturer is missing in NetBox | Blocked: create the manufacturer in NetBox first (the app never creates manufacturers). |
| The definition has front or rear ports or port mappings | Blocked: import this type in NetBox (Device Types > Import). |
| The definition is invalid | Blocked: fix it in the editor. |
| The import is unchecked | The devices that need the type are not written. |

If the import fails, the devices that depend on it are skipped with the
reason, so no device is created with a wrong type. An interrupted create is
looked up in NetBox, never repeated blindly.
