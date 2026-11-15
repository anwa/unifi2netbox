# Troubleshooting

## Connections

**The NetBox or UniFi chip is red.** Click the chip to see the reason.

- *Unauthorized / forbidden*: the token or key is wrong, expired or lacks
  read permission.
- *TLS / certificate error*: the server uses a certificate your system does
  not trust. Select the CA file under **CA bundle** instead of switching
  verification off.
- *Timeout*: the server does not answer in time; check the URL and the
  network, or raise **Request timeout**.
- *Redirect*: the URL points to a login page or another address. Use the
  base URL of the API host itself.

**The UniFi chip asks for a site.** The key can see several sites. Choose one
on the [UniFi Network](../02-settings/02-unifi-network.md) page.

**The chip is amber.** The connection works, but with a security warning,
usually because TLS verification is off or the URL uses `http://`.

## Refresh

**"Configure NetBox and UniFi Network in Settings before refreshing."** Both
required connections need a URL and a token.

**The review shows stale data.** A source could not be read; the last good
snapshot is shown. Fix the connection and refresh. Stale data never
authorizes a write.

**Port configuration, SFP modules, WLANs or DHCP data are missing.** These
come from additional UniFi endpoints read only for UniFi Network 11.0. A note
in the review says which read failed.

## Review

**A new device shows "Needs attention".** Choose a device type and a role.
If no device type fits, add it in NetBox and refresh.

**A device is not matched.** Matching uses name, serial and MAC. Align the
name or serial in NetBox, or check for duplicates (two hits are a conflict).

**Networks, wireless LANs or addresses say "Set 'NetBox site for UniFi
devices'".** Choose an existing NetBox site on
[Sync defaults](../02-settings/06-sync-defaults.md).

**Interface or WLAN VLANs are missing.** The VLANs are not in NetBox yet.
Write the [networks](../03-review/03-networks.md), refresh and the VLANs are
planned.

**A row shows a conflict.** NetBox holds data the app does not overwrite.
Read the note in the detail panel, fix the object in NetBox if the UniFi
value is right, and refresh.

## Apply

**"Refresh before applying changes."** The review is not current. Refresh.

**Changes are skipped with "changed since the preview".** UniFi or NetBox
changed between refresh and apply. Refresh and review again.

**A write failed with HTTP 403.** The token lacks write permission for that
object; see [Permissions](02-permissions.md).

**Read-back shows "Mismatch".** NetBox holds other values than written,
for example because a script or webhook changed them. Check the object.
