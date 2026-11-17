# Changelog

All application changes are documented here. Versions use `vx.y.z`: patch for
ordinary code commits, minor for an approved functional milestone merge, major
only on explicit user instruction. Documentation-only changes have no release tag.

## Unreleased

### Added

- M13 slice 1: local device type files may carry every NetBox 4.7 device type
	field (owner, default platform, tags, custom fields, cooling method, end of
	life, exclude from utilization) and every template kind and field,
	including cooling intakes and outflows, interface channels and parents,
	bay states, inventory item roles and components. Validation uses the
	devicetype-library schema extended with NetBox field metadata, bundled
	from the API of NetBox 4.7.3 (`tools/update_netbox_metadata.py`). The
	library itself is only read.

### Changed

- Device type editor: the heights of Attributes, Comments, Components and
	Validation are set by dragging the lines between them; the section
	heights, the tree width and the window size and position are remembered
	(`[ui]` in the configuration). Saving the theme keeps these values.

## v1.2.0

### Summary

- Milestone M12 (device types): new devices choose their NetBox device type
	in a picker modeled on NetBox's that searches NetBox, a local type folder
	and netbox-community/devicetype-library; a device type editor writes
	definitions in the library format (validated against its schema and
	CONTRIBUTING rules) with data from UniFi and techspecs.ui.com; a chosen
	definition that NetBox lacks is imported as a visible, selectable write
	step. Manufacturers, sites and roles are still never created.

### Added

- M12 slice 1: device type definitions in the netbox-community
	devicetype-library format: YAML load and save in the library style (an
	existing library file is written back byte for byte), validation against
	the library's JSON schema (bundled, CC0) and its CONTRIBUTING rules (file
	name, folder, slug, empty values, duplicates; weight, weight unit and
	airflow as recommendations), and a local type folder
	`device-types/<Manufacturer>/<model or part number>.yaml`. New
	dependencies: ruamel.yaml and jsonschema.
- M12 slice 2: device type search across NetBox, the local type folder and
	netbox-community/devicetype-library (index of `device-types/` read from
	GitHub on request and cached next to the configuration, files downloaded
	on demand and cached by blob SHA), ranked by UniFi model aliases and
	filterable by manufacturer, source, part number, rack height, airflow,
	weight and components. New Settings page **Device types**: local type
	folder, library on/off with repository, branch and **Refresh index**,
	techspecs lookups on/off (`[device_types]`).
- M12 slice 3: UniFi product specifications from techspecs.ui.com (found by
	part number or model, or from a page URL the user enters; only the product
	slug is sent): SKU without regional suffix, title, rack height,
	dimensions, weight, power, PoE and port layout. Drafts of device type
	definitions from a UniFi device: interfaces from its UniFi ports
	(`Port N`, `SFP+ N`, ... with NetBox types and PoE), else from techspecs
	(`eth0`, PoE powered), with notes about differences and missing data.
- M12 slice 4: device type editor (**Device types** in the header and the
	More menu), laid out like the manual: the local type folder as a tree on
	the left, the definition on the right as **Table** (attributes with
	explanations, comments, one tab per component kind with choice lists from
	the library schema) or raw **YAML**; unchanged values keep their original
	spelling. New, Save (library file name, renames when the model changes),
	Revert, Delete, Validate, Open folder, and for Ubiquiti models **Look up
	specs** on techspecs.ui.com (by part number or model, or from a page URL),
	which only fills gaps.
- M12 slice 5: the long device type drop-down of new devices is replaced by
	**Choose...**, which opens a picker modeled on NetBox's: filter criteria
	on the left (search, manufacturer, source, part number, rack height,
	full depth, airflow, components, weight), filter rows with operators,
	**Search**, and results from NetBox, the local type folder and the
	devicetype-library with the UniFi model's matches first. **Refresh
	library** loads the library index; **New** opens the editor with a draft
	from the device's UniFi data (and a techspecs lookup for Ubiquiti), and
	the saved file becomes the device's type. Local and library types are
	marked "imported on apply".
- M12 slice 6: a chosen local or library definition is imported into NetBox
	as a visible, selectable write step right after the Custom Field: the
	device type and its component templates (interfaces, console and power
	ports, outlets, module and device bays, inventory items) are created,
	an existing slug or an equal manufacturer/model or part number is reused
	instead, a missing manufacturer or front/rear ports block the import (the
	app never creates manufacturers). Interrupted creates are looked up, the
	type is read back and its templates counted; device creates that depend
	on a type that was not imported are skipped with the reason. The detail
	panel offers "Import this device type into NetBox", the apply bar and
	confirmation count device types. techspecs also reads single ports
	without a count ("10/100 MbE RJ45 port"); drafts without a UniFi
	manufacturer leave it empty.
- M12 slice 7: manual chapter **Device types** (choosing, editor, local folder
	and library with contribution steps, import) plus a Settings page, updated
	reference pages and new demo screenshots.

### Fixed

- The header no longer overflows on narrow windows: when space is short the
	connection chips show only the service name (version and details in the
	tooltip), **Manual** and **Device types** become icons and the app name
	gives way to the logo.

### Validation

- Offline gate: 668 passed, 2 skipped; Ruff lint and format pass.
- Live on the developer workstation (NetBox 4.7.3, UniFi Network 11.0.99,
	2026-11-16): library index and techspecs lookups read-only, an import dry
	run for four definitions, and an approved write test: the UA-Intercom
	device type imported and the device created with it, both verified, a
	second apply a no-op. The data stays in NetBox as real data.
- Packaged builds of this version are not verified yet (new dependencies
	ruamel.yaml and jsonschema; bundled schema resources).

## v1.1.2

### Summary

- Patch release: windows that are opened a second time, such as the manual,
	keep the themed title bar on Windows. No other change.

### Fixed

- A window that is closed and opened again (for example the manual) keeps
	the themed title bar on Windows. The second opening used a stale native
	handle, so the title bar fell back to the default Windows colors.

### Validation

- Offline gate: 614 passed, 2 skipped; Ruff lint and format pass.
- Native check on Windows 11: the manual window opened twice reports the
	app's dark or light title bar setting on both openings.

## v1.1.1

### Summary

- Patch release with the user manual: a **Manual** button (F1) opens the
	manual inside the app, with the chapter tree on the left and the page on
	the right, starting at the overview. No change to what the app reads or
	writes.

### Added

- User manual in `manual/` (Markdown pages in chapter folders with
	screenshots): overview, getting started, settings for every service, the
	review window and each filter, applying changes, and reference pages
	(what is written, permissions, files and data, troubleshooting,
	diagnostics).
- **Manual** button in the header (also F1 and the More menu) opens a manual
	window with the chapter tree on the left and the page on the right,
	starting at the overview; links, Back, Forward and Overview navigate,
	screenshots scale to the page width. Windows and Linux builds bundle the
	manual.
- `tools/build_manual_screenshots.py` renders all manual screenshots offscreen
	from a fictional demo network through the real pipeline (no connection,
	placeholder tokens, neutral paths).

### Fixed

- The review filters use two rows (devices, then networks and objects), so
	every filter label stays readable at the default window width.
- The UniFi Drive settings text now says that the drive bays are read with
	the key.

### Validation

- Offline gate: 613 passed, 2 skipped; Ruff lint and format pass; GitHub
	Actions Offline Tests and Packages workflows run for main and the tag.
- The manual tests check structure, titles, every link and image, and drive
	the manual window offscreen. Screenshots come from fictional demo data.
- The manual window was not checked in a packaged build beyond the bundle
	check (the build scripts fail without `manual/index.md`).

## v1.1.0

### Summary

- Milestone M11 (extended UniFi details): firmware, management IPs, port
	details, SFP modules, wireless LANs, DHCP ranges and DHCP reservations
	from UniFi are previewed and, when selected, written to NetBox with the
	same re-read, drift, read-back and journal safeguards as device writes.
	The app may create one Custom Field, `firmware`, as a visible and
	selectable operation; it never creates other Custom Fields or
	manufacturers and never deletes anything.

### Added

- M11 slice 1 (read and show only, nothing is written yet): the management IP
	and firmware version of UniFi devices (official API); SFP modules,
	configured fixed port speed and duplex, DHCP ranges, wireless LANs and
	fixed-IP reservations (internal Network API, allow-listed fields only,
	never passphrases or other secrets); NetBox primary IPv4, the `firmware`
	Custom Field, interface description and duplex, IP addresses, IP ranges,
	wireless LANs, manufacturers and Custom Field definitions (each optional).
	The device detail panel shows management IP and firmware, the port list
	shows SFP modules and fixed speeds, and the preview summary counts the new
	details. Diagnostic exports only count the new lists.
- M11 slice 2: firmware is a device field written into the NetBox Custom
	Field `firmware`. When the field is missing, the app plans its creation
	(text, devices) as a visible, selectable first operation: the detail panel
	shows a checkbox, the apply bar and confirmation count it, unchecking it
	also unchecks every firmware value, and selecting a firmware value selects
	it again. A field with another type or object type is never changed and
	blocks firmware. Creation never duplicates the field, reconciles an
	interrupted create by name and is read back; firmware updates PATCH only
	the Custom Field, are drift-checked and read back.
- M11 slice 3: the management IP of matched devices becomes the NetBox
	primary IPv4. The prefix length comes from the UniFi network that contains
	the IP; the IP goes onto the management-only interface, an interface named
	`Management`, or a new virtual management-only `Management` interface.
	Missing IPs are created, unassigned ones assigned; an IP on another
	object, duplicate IPs, several management interfaces or another primary
	IPv4 are conflicts and never overwritten. Public (WAN) addresses are not
	used. The detail panel offers one checkbox per device; writes run after
	device writes with UniFi and NetBox re-reads, lookup of interrupted
	creates and read-back.
- M11 slice 4: the Interfaces plan also covers the description (the UniFi
	port name, unless it is a default name such as `Port 3`), a fixed speed
	and duplex (only when auto-negotiation is off in UniFi; link speed stays
	display-only) and the PoE capability (`pse` with the official PoE type).
	Empty NetBox values are preselected; other existing values (for example
	PoE from the device type or a hand-written description) are shown but
	replaced only when checked. A PoE type always goes with the PoE mode.
- M11 slice 5: SFP modules of matched devices become NetBox inventory items
	`Transceiver <interface>`, linked to the paired interface, with part ID,
	serial, description (compliance and revision) and the NetBox manufacturer
	when exactly one matches the vendor (`UBNT` and `Ubiquiti Inc.` match
	`Ubiquiti`; none is created). Create and update only; items of removed
	modules are kept. The detail panel lists them with checkboxes; they are
	written last with a UniFi module re-read. Drive items and SFP items now
	share one inventory-item writer.
- M11 slice 6 (pipeline only; the review window offers these rows from slice
	7 on): wireless LANs (SSID, status, authentication type and cipher, the
	VLAN of the site VLAN group, site scope; never a passphrase; disabled
	WLANs not preselected), DHCP pools as IP ranges (`DHCP <network>`, prefix
	length of the network) and fixed client IPs as unassigned reserved IP
	addresses (DNS name only from an enabled local DNS record, description
	from the client name or hostname). Existing objects are only completed:
	authentication and status follow UniFi, empty fields are filled, a
	different VLAN, scope, DNS name or reservation description is a
	conflict, overlapping ranges and duplicates are conflicts. Wireless LANs
	and ranges are written after networks, reservations after management
	IPs, with UniFi and NetBox re-reads and read-back. Inventory items and
	the new objects share one object writer.
- M11 slice 7: the review window has **Addresses** (management IPs, IP
	ranges, reserved IPs), **Wireless** and **Modules** (SFP) filters with a
	checkbox per entry, a detail panel that shows planned fields with names
	instead of NetBox IDs, select all/none for the visible list, and counts
	in the apply bar and the confirmation. Wireless LANs, ranges and
	reservations are written on a full apply only.

### Validation

- Offline gate: 606 passed, 2 skipped; Ruff lint and format pass.
- Live on the developer workstation (UniFi Network 11.0.99, NetBox 4.7.3,
	2026-11-15): read-only probes and dry runs for every slice, and approved
	write tests for one object of each kind (Custom Field and firmware,
	management IP, interface details, SFP item, wireless LAN, IP range,
	reserved IP), each read back as verified with a no-op second apply. The
	written objects stay in NetBox as real data.
- Linux and the packaged builds of this version are not verified yet.

## v1.0.0

### Summary

- First stable release, completing the deployment and platform acceptance
	milestone (M10). The user authorized the major version on 2026-11-14; M10
	is released as v1.0.0 instead of the planned v0.11.0.
- Includes all milestones M1 to M10: NetBox and UniFi Network connections,
	inventory snapshots, matching and preview, approved NetBox writes with
	read-back and history, VLANs, prefixes, interfaces and cables, and the
	optional UniFi Protect, Access and Drive (UNAS) inventories.

### Added

- Per-user Windows installer (Inno Setup): no administrator rights, Start
	menu entry, in-place upgrades, uninstall keeps settings and data;
	`tools/build_windows.ps1` builds exe and installer with a bundle check and
	smoke test.
- Linux packages: Ubuntu `.deb` (`/opt/unifi2netbox`, launcher, desktop entry,
	icons) and a standalone tarball, built and smoke-tested by the Packages
	GitHub Actions workflow.
- Application icon for windows, taskbar, executable and Linux desktop entry;
	native Windows title bars follow the app theme.
- Hidden `--smoke-test` option for packaging checks.

### Fixed

- The Offline Tests workflow now passes on Ubuntu and Windows (it never
	passed on Ubuntu before because Qt runtime libraries were missing).
- Header chips stay readable with five connections at the default width.

### Validation

- Offline gate: 540 passed, 2 skipped; Ruff lint and format pass; GitHub
	Actions Offline Tests and Packages workflows pass.
- Windows 11 acceptance on the developer workstation: installer install,
	in-place upgrade and uninstall; the installed app connected to all five
	services and refreshed the preview read-only; settings were preserved.
- Linux: verified only offscreen in GitHub Actions (Ubuntu 24.04); a real
	Linux desktop and Ubuntu/Kubuntu 26.04 are not verified.

### Compatibility

- No configuration change is required. Settings stay in
	`%LOCALAPPDATA%\unifi2netbox` (Windows) or `~/.config/unifi2netbox`
	(Linux).

## v0.10.5

### Fixed

- Header chips are no longer squeezed or overlapping at the default window
  width with five connections: the bold chip text comes from the style
  sheet and each chip reserves its full width; the UniFi site moved from the
  chip text into its tooltip (it stays in the detail card).

### Validation

- M10 acceptance on the developer workstation (Windows 11, 2026-11-14): the
  0.10.3 installer was installed per user with a Start menu entry, the 0.10.4
  installer upgraded it in place (one Apps entry, new version, smoke test of
  the installed exe passed) and the configuration folder stayed unchanged.
  The installed 0.10.4 app started with the real configuration, connected to
  NetBox 4.7.3, UniFi 11.0.99, Protect 7.3.74, Access and Drive, refreshed the
  preview read-only (32 UniFi devices: 4 in sync, 28 new, 19 interface
  changes, 1 cable suggestion) and closed with exit code 0. The overlapping
  UniFi chip seen there is fixed in this version (checked on screen).

## v0.10.4

### Added

- M10 slice 2: Linux packages. `tools/build_linux.sh` builds the PyInstaller
  standalone folder, `unifi2netbox-<version>-linux-x86_64.tar.gz` and
  `unifi2netbox_<version>_amd64.deb` (installs to `/opt/unifi2netbox` with
  `/usr/bin/unifi2netbox`, a desktop entry and hicolor icons; settings stay
  in `~/.config/unifi2netbox`). The new **Packages** workflow builds both on
  Ubuntu, smoke-tests the build and the installed `.deb` offscreen, removes
  the package again and keeps the files as workflow artifacts (nothing is
  published).
- Hidden `--smoke-test` option: shows the main window, prints its title and
  exits with 0; used by the Linux package test.

### Fixed

- The **Offline Tests** workflow never passed on Ubuntu (PySide6 needs
  `libEGL` and related libraries, which the runner lacks), and the matrix
  cancelled the Windows job with it. Both jobs now install their
  prerequisites and report independently; both pass.

### Validation

- GitHub Actions on 2026-11-14 (commit c6b183d, Ubuntu 24.04 runner): offline
  tests pass on Ubuntu and Windows; the Packages workflow built the `.deb`
  and tarball for 0.10.4, both smoke tests passed, `apt install` and
  `apt remove` worked. Ubuntu/Kubuntu 26.04 and a real Linux desktop remain
  unverified.

## v0.10.3

### Fixed

- The Windows build script finds `ISCC.exe` under PowerShell strict mode.

### Validation

- `tools/build_windows.ps1` built the exe and
  `unifi2netbox-0.10.3-setup.exe` (43.5 MB) from a clean tree; bundle
  hygiene and the native smoke test passed. A silent per-user install into a
  test folder, a reinstall over it (stale files of the old build removed),
  the smoke test of the installed exe and a silent uninstall passed; the
  per-user configuration folder was unchanged throughout.

## v0.10.2

### Added

- M10 slice 1: per-user Windows installer (`packaging/windows/unifi2netbox.iss`,
  Inno Setup 6): installs without administrator rights to
  `%LOCALAPPDATA%\Programs\unifi2netbox`, Start menu entry (optional desktop
  icon), app icon, license page, English or German wizard, in-place upgrades
  by a fixed AppId that remove files of the previous build, and an
  uninstaller that keeps `%LOCALAPPDATA%\unifi2netbox` (settings, tokens,
  snapshots, write history).
- `tools/build_windows.ps1`: one command for exe and installer; refuses a
  dirty tree, reads the version from `pyproject.toml`, checks that no
  configuration, cache, journal or capture file is bundled and that the
  license notices are, and runs the native smoke test before compiling.

## v0.10.1

### Added

- Application icon (SVG source plus PNG sizes 16-256 px and a multi-size
  Windows `.ico`; a simplified variant keeps 16-24 px legible), used for all
  windows, the header logo, the Windows taskbar (own AppUserModelID) and the
  packaged executable. `tools/build_icons.py` regenerates the files with Qt.

### Changed

- Native title bars follow the app theme on Windows: dark mode for all
  windows and dialogs when the app is dark, and on Windows 11 the app's own
  caption, text and border colors, so the main window title bar blends into
  the header. Theme switches restyle open windows; the native frame
  (snapping, resizing) is kept.

### Validation

- Added icon, `.ico` structure, caption color and theme-listener tests.
  Checked on the real Windows 11 desktop (light and dark) and in a test
  PyInstaller build with the icon embedded (native smoke test passed).

## v0.10.0

### Summary

- UniFi Drive / UNAS inventory milestone (M9): the UNAS joins the review as
	one device and its drives become NetBox inventory items.

### Added

- Optional `[unifi_drive]` connection (UNAS console URL and local API key), a
	settings page and a header chip. Ubiquiti documents no Drive API; the
	check reads the public UniFi OS system information.
- The UNAS is read as one device (name, model, system MAC) and its drive bays
	from the internal Drive storage endpoint (GET, local API key,
	allow-listed fields); bays are listed display-only in the details.
- Drives of a matched UNAS are planned and written as NetBox inventory items
	`Disk <slot>` (part ID, serial, description) after device writes, with a
	fresh bay check, duplicate-safe creates, drift-checked updates and
	read-back; items are never deleted.
- NetBox inventory items are read with the inventory (optional permission).

### Validation

- Milestone-wide offline gate: 531 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): UNAS Pro Online, read as
	one device with 7 bays (5 HDDs, 2 empty); approved NetBox
	developer-instance write test of the UNAS and its five drive items (9/9,
	verified, in sync after refresh, test objects removed). The internal
	storage endpoint is undocumented and may change with Drive updates.

### Compatibility

- No configuration change is required; Drive stays off until `[unifi_drive]`
	is set. Snapshots gain a `unifi_drive` source, drive bays and NetBox
	inventory items; older snapshots load without migration.

## v0.9.3

### Added

- M9 slice 3: drive inventory items. For a UNAS matched to a NetBox device,
  each populated drive bay is planned as the inventory item `Disk <slot>`
  with part ID (model), serial and description (type, size, firmware);
  creates and updates are preselected, equal items are in sync, duplicate
  names are conflicts, empty bays keep their NetBox item (never deleted) and
  empty UniFi values never clear NetBox values. The UNAS detail panel lists
  these items with checkboxes; the apply bar and confirmation count them.
- Drive items are written after device writes: UniFi Drive is re-read and
  the bay must still hold the same drive, creates never duplicate an item of
  the same name, interrupted creates are looked up by name, updates re-read
  the item and PATCH only unchanged-since-preview fields, every write is read
  back and dry runs write nothing.
- NetBox inventory items are read with the inventory (optional: a missing
  permission only disables drive planning).

### Validation

- Added plan, execution, NetBox reader, merge, preview, ordering and GUI
  tests. Live read-only on 2026-11-14: NetBox inventory items were read
  (none yet); the UNAS is not in NetBox yet, so the drive plan explains that
  it must be created and refreshed first.

## v0.9.2

### Added

- M9 slice 2: Drive inventory. A configured Drive connection is read on every
  refresh into a `unifi_drive` snapshot: the UNAS as one device (name, model,
  system MAC from the public system information, manufacturer Ubiquiti) and
  its drive bays from the internal Drive storage endpoint, read GET-only with
  the local API key and limited to allow-listed fields (slot, model, serial,
  firmware, type, size, state, temperature, health, pool). Fresh UNAS data
  joins matching with the `drive:` prefix after Network, Access and Protect;
  stale data never authorizes writes and the pre-write re-read includes it.
  The detail panel lists the drive bays (display only, serials hidden). A
  failed storage read keeps the device and explains the missing bays. A
  single role named like "NAS" or "Storage" is preselected.

### Validation

- Added Drive reader, snapshot round trip, refresh, preview, re-read, role
  and detail-panel tests. Live read-only on 2026-11-14: the UNAS Pro was read
  as one device with 7 bays (5 HDDs with model, serial and firmware, 2 empty);
  the preview showed it as a create row with the NetBox type "UNAS Pro"
  preselected. UniFi OS reports `deviceState` "setup", so the device state is
  shown as online after a successful read instead.

## v0.9.1

### Added

- M9 slice 1: optional UniFi Drive connection. A new `[unifi_drive]` section
  stores the UNAS console URL (management address), its local API key and
  TLS options, edited on a new **UniFi Drive** settings page with a header
  chip that appears once configured. Ubiquiti documents no Drive device API
  yet, so the check reads only the public UniFi OS system information
  (`/api/system`, GET, no key sent) and confirms a UNAS model; the key is
  stored for future Drive APIs. File contents are never accessed.

### Validation

- Added Drive check tests (online without sending the key, unconfigured
  without requests, non-UNAS consoles, HTML, HTTP errors, timeout, URL rule),
  a config round trip and GUI tests for the settings page and chip; five
  chips fit the 1180 px header (offscreen render). Live read-only probe
  without credentials: the UNAS Pro answers `/api/system` with model
  `UNASPRO` and its system MAC; every `/proxy/drive/...` path, even a
  nonexistent one, answers 401, so no Drive API can be confirmed.

## v0.9.0

### Summary

- UniFi Access inventory milestone (M8): hubs, readers and intercoms of an
	optional Access connection join the same review and approved NetBox write
	flow.

### Added

- Optional `[unifi_access]` connection (Access API URL with port 12445 and an
	Access API token with device-read permission), a settings page and a
	header chip; GET-only reads of `/api/v1/developer/devices`. Users, logs and
	doors are never requested.
- Access hardware is stored in its own snapshot with name, model, MAC (from
	the device ID), kind and online state; unadopted devices are skipped.
- Fresh Access devices are matched, previewed and written like Network
	devices with precedence Network, then Access, then Protect for the same
	MAC; stale Access data never authorizes writes; Access is re-read before
	writing. Access devices never inherit the default network role; a single
	fitting role ("Access Control", "Door", "Reader", "Intercom") is
	preselected, never "Access Point".

### Changed

- Optional service chips appear only once configured; unconfigured required
	connections read "Not set". A rejected Access URL without a port points to
	port 12445.

### Validation

- Milestone-wide offline gate: 488 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): Access on the UDM Online
	with its own token, 2 devices read (UAH hub, UA-Intercom); the intercom
	comes from Access instead of Protect; approved NetBox developer-instance
	write test of the hub with a test role and test device type (7/7,
	verified, matched after refresh, test objects removed). Failing Access
	re-reads and stale Access snapshots are covered by offline tests only.

### Compatibility

- No configuration change is required; Access stays off until
	`[unifi_access]` is set. Snapshots gain a `unifi_access` source; older
	snapshots load without migration. Access reports no serial numbers,
	firmware or IP addresses.

## v0.8.3

### Added

- M8 slice 3: Access devices join matching and the review with the ID prefix
  `access:`. Source precedence for the same MAC is Network, then Access, then
  Protect; the preview reports how many duplicates were dropped. Only a fresh
  Access read joins the preview; a stale snapshot never authorizes writes.
  The detail panel shows "from UniFi Access (hub, online)". Access devices
  never inherit the default network role; a single role named like
  "Access Control", "Door", "Reader" or "Intercom" is preselected (never
  "Access Point").
- The pre-write re-read includes Access (as for Protect); an Access failure
  only skips Access device writes.

### Validation

- Added merge precedence, fresh/stale preview, re-read, write wiring, role
  and origin tests. Live read-only preview on 2026-11-14: 31 UniFi devices
  (19 Network, 2 Access, 10 Protect); the UA-Intercom comes from Access and
  its Protect copy is dropped; hub and intercom are create rows without a
  device type or role because NetBox has neither for Access hardware.

## v0.8.2

### Added

- M8 slice 2: Access inventory. A configured Access connection is read on
  every refresh into its own `unifi_access` snapshot (GET `devices` only):
  name (alias first), model (`type`), manufacturer Ubiquiti, the MAC taken
  from the device ID, kind (hub, reader, intercom or other Access hardware)
  and online state. Unadopted devices are skipped. Failures keep the last
  snapshot as stale and never block NetBox or Network; the preview reports
  the Access device count. Access devices join matching in slice 3.

### Changed

- A rejected Access token on a URL without a port now points to port 12445,
  because such requests reach UniFi OS on port 443 instead of Access.

### Validation

- Added Access reader, refresh, preview and port-hint tests. Live read-only
  on 2026-11-14: the saved URL lacked `:12445` (check now explains this);
  with the port the reader returned a UAH hub and a UA-Intercom, both
  online, MACs derived from the IDs; the intercom MAC equals its Protect
  MAC, the hub is new to both other sources.

## v0.8.1

### Added

- M8 slice 1: optional UniFi Access connection. A new `[unifi_access]` section
  stores the Access API URL (console running Access, port 12445), an Access API
  token and TLS options, edited on a new **UniFi Access** settings page. The
  check reads `/api/v1/developer/devices` with a Bearer token (GET only, no
  redirects, no proxy environment), accepts the grouped or flat device list of
  the `SUCCESS` envelope and reports rejected tokens, missing APIs (HTML or
  404) and error codes without echoing secrets.

### Changed

- Settings pages and header chips for optional UniFi applications (Protect,
  Access) share one description; their chips appear only once a service is
  configured, and unconfigured required connections read "Not set" so four
  chips fit. A connection without a reported version shows no version text.

### Validation

- Added Access check tests (online with Bearer token, unconfigured without
  requests, HTTP and envelope failures, timeout, list shapes, URL rule), a
  config round trip next to Protect and GUI tests for the settings page and
  chips. Live read-only: the UNVR answers Access paths with HTML; on the UDM
  the Access proxy answers JSON 404 and port 12445 answers 401 without an
  Access token, so Access runs on the UDM and needs its own token.

## v0.8.0

### Summary

- UniFi Protect inventory milestone (M7): the NVR and cameras of an optional
	Protect console join the same review and approved NetBox write flow.

### Added

- Optional `[unifi_protect]` connection with its own console URL and local API
	key, a settings page and a header chip; GET-only reads of `meta/info`,
	`nvrs` and `cameras`, gated to the Protect 7.3 series. Consoles without
	Protect are reported as unsupported.
- NVR and cameras are stored in their own snapshot with name, MAC, model, kind
	and live state only; recordings, snapshots and streams are never requested.
- Fresh Protect devices are matched, previewed and written like Network
	devices; devices also seen in Network are taken from Network (MAC); stale
	Protect data never authorizes writes; Protect is re-read before writing.
- Protect model codes map to NetBox part numbers; unknown vendors (third-party
	cameras) only get exact type matches; cameras and NVRs never inherit the
	default network role.

### Fixed

- Create choices show a "Choose a ..." placeholder instead of an unchosen first
	value.

### Validation

- Milestone-wide offline gate: 454 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): Protect 7.3.74 on the UNVR
	Online with its own key, 11 devices read (1 NVR, 10 cameras), preview with
	6 preselected device types; approved NetBox developer-instance write test of
	one camera with a test role (7/7, verified, matched after refresh, test
	objects removed). A failing Protect re-read and stale Protect snapshots are
	covered by offline tests only.

### Compatibility

- No configuration change is required; Protect stays off until
	`[unifi_protect]` is set. Snapshots gain a `unifi_protect` source and device
	`kind`/`state` fields; older snapshots load without migration.

## v0.7.4

### Added

- M7 slice 4: the detail panel of a Protect device shows its live Protect
  state, for example "from UniFi Protect (camera, connected)". The state is
  operational and never written.

### Validation

- Approved live write test of a Protect camera create against the NetBox
  developer instance (7/7, see `docs/TESTING.md`); review test for the state.

## v0.7.3

### Added

- M7 slice 3: a fresh Protect read joins matching, preview and write plan.
  Protect devices get `protect:`-prefixed IDs; a Protect device whose MAC is
  also a Network device is dropped (Network data wins) and counted in the
  Protect status line. Protect devices take the most common Network site, then
  the NetBox site mapping applies. A cached Protect snapshot after a failed
  refresh never joins the preview, so it cannot authorize writes.
- Before writing, Protect is re-read and merged like Network; if only Protect
  fails, its devices are skipped while Network writes proceed.
- Device type suggestions understand Protect model codes (`UNVR4` is part
  number `UNVR`, `UVC G4 Instant` is `UVC-G4-INS`); devices without a known
  manufacturer only get exact model or part-number matches.
- Cameras and NVRs never inherit the default device role; a NetBox role whose
  name fits (camera/kamera/CCTV/surveillance, NVR/recorder) is preselected,
  otherwise the role must be chosen. The detail panel shows "from UniFi
  Protect (camera)".

### Fixed

- Role, site and status choices no longer display the first NetBox value
  when nothing is chosen; a "Choose a ..." placeholder is shown instead.

### Validation

- Added merge, fresh-only, re-read, role, alias, exact-match and placeholder
  tests. Live read-only preview: 11 Protect devices as create rows, 6 with a
  preselected device type (NVR, G4 Instant, G6 Bullet x2, G3 Flex x2), 5
  without (G5 Bullet, UA Intercom and three third-party CAM-PT2);
  roles stay open because NetBox has no camera or NVR role yet.

## v0.7.2

### Added

- M7 slice 2: when Protect is configured, a refresh also reads the NVR and
  cameras from the Protect Integration API (GET only) into their own snapshot
  (`unifi_protect`, current and previous, stale on failure). Devices keep only
  name, MAC, model, kind (`nvr`/`camera`) and the operational connection state.
  The manufacturer is Ubiquiti only for known Ubiquiti model prefixes; other
  models such as third-party cameras keep it empty. A Protect failure keeps the
  last good snapshot and never blocks NetBox or Network; the preview result
  carries the Protect devices and a one-line Protect status.

### Validation

- Added reader tests (identity fields, vendor rule, settings not copied,
  malformed entries, failures), refresh tests (optional, soft failure with
  cache), a pipeline status test and a snapshot round trip. Live read-only:
  Protect 7.3.74 returned 11 devices (1 NVR, 10 cameras, 3 third-party without
  manufacturer) in 0.36 s; a full preview stored them as a Protect snapshot.

## v0.7.1

### Added

- M7 slice 1: optional UniFi Protect connection. A new `[unifi_protect]`
  section stores the URL, local API key and TLS options of the console running
  Protect (for example a UNVR), edited on a new **UniFi Protect** settings page.
  The check reads `meta/info`, `nvrs` and `cameras` of the Protect local
  Integration API (GET only, no redirects, no proxy environment), accepts the
  Protect 7.3 series and reports a console without Protect (HTML answer) as
  unsupported. A header chip shows the state ("Protect · Off" while
  unconfigured); an unconfigured Protect never blocks NetBox or Network work.

### Validation

- Added Protect check tests (online, unconfigured without requests, HTML
  answer, HTTP failures, version gate, response shapes, timeout), config round
  trips that keep other sections, and GUI tests for the settings page and the
  chip. Live read-only: the UDM (Network console) answers the Protect paths
  with its HTML page, confirming that Protect needs its own connection.

## v0.7.0

### Summary

- Switch ports and VLANs milestone (M6): ports, port configuration, networks,
	interfaces and cables are compared with NetBox and can be written with the
	same safeguards as devices.

### Added

- Ports of matched devices are paired with NetBox interfaces; link state and
	speed are shown as live values and never written.
- UniFi networks become a site-scoped VLAN group "UniFi <site>", VLANs and
	prefixes linked to their VLAN (Networks view).
- Effective port configuration (name, enable state, profile, mode, native and
	tagged VLANs, LAG) is read from internal UniFi Network 11.0 endpoints, GET
	only, with an allow-list that keeps network secrets out of all models.
- Interface configuration (enabled, 802.1Q mode, untagged and tagged VLANs) is
	planned and written field by field (Interfaces view); LAG stays display-only.
- Cables are suggested only from agreeing LLDP and uplink evidence between
	interfaces without a cable, and are only created (Cables view).
- Write order in one run: networks, interfaces, cables, devices; every write
	is re-checked against UniFi and NetBox, read back and recorded.

### Validation

- Milestone-wide offline gate: 415 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): read-only checks of ports
	(195), networks (16), port configuration (195 of 195 resolved) and link
	evidence (53 observations); dry runs of 31 network, 19 interface and 1 cable
	operations; approved NetBox developer-instance write tests for networks
	(10/10), interfaces (8/8) and cables (7/7), each with a no-op second apply
	and all test objects restored or removed. LAG, tagged VLAN lists and
	interrupted creates are covered by offline tests only.

### Compatibility

- Requires no configuration changes. Snapshots gain ports, interfaces,
	networks, IPAM objects, port configuration and links; older snapshots load
	without migration. Internal endpoints are only read for UniFi Network 11.0.

## v0.6.13

### Added

- M6 slice 5, review window: a **Cables** filter and summary card list every
  link UniFi reports between devices with its evidence, change type (new
  cable, in sync, conflict, reference) and status. The detail panel shows the
  observations, notes and a checkbox for creatable cables. Selected cables
  count in the apply bar, appear in the confirmation dialog and run with the
  other writes.

### Validation

- Added GUI tests for the cables table, preselection, reference rows without
  a checkbox, apply counts and the confirmation summary; offscreen render with
  live data reviewed.

## v0.6.12

### Added

- M6 slice 5, execution: selected cable suggestions are created in NetBox
  after interface writes and before device writes. UniFi must still report the
  link; both interfaces are re-read, a cable that already joins them counts as
  done and any other cable skips the row (never replaced). Interrupted creates
  are looked up on the interface instead of retried; every cable is read back.
  Dry runs run all checks. Cables are never changed or deleted.

### Validation

- Added executor tests (create and verify, existing cable, other cable, dry
  run, vanished evidence, unreadable UniFi, interrupted create found or lost,
  transport failure) and pipeline ordering.

## v0.6.11

### Added

- M6 slice 5, planning: link evidence between UniFi devices is read from the
  internal `stat/device` payload (wired `uplink` and `lldp_table`), resolved
  from MAC to device IDs without storing MACs. NetBox interfaces carry their
  cable and interface link peers. A cable plan groups the evidence per device
  pair and suggests a cable only when all observations agree on the ports, no
  port is claimed by another neighbor, both devices are matched and both ports
  map to NetBox interfaces (port pairing, or the only physical interface of a
  device without port data), and neither interface has another cable.
  Two or more observations preselect a suggestion; single observations stay
  unchecked. Existing cables are never replaced.

### Validation

- Added link reader, cable planner, interface cable and snapshot tests. Live
  read-only: 53 observations (35 LLDP, 18 uplink) on 18 device pairs without
  disagreement; one cable suggested (UDM port.5 to RPS, LLDP and uplink), 17
  pairs reference-only because a device is not in NetBox.

## v0.6.10

### Added

- M6 slice 4, review window: an **Interfaces** filter and summary card list
  paired UniFi ports and NetBox interfaces of matched devices with port name,
  effective configuration, change and status. The detail panel shows one
  checkbox per field change (enabled, 802.1Q mode, untagged VLAN, tagged VLANs)
  with current and target values; VLAN fields follow the mode selection and
  the panel updates immediately. Selected interface writes count in the apply
  bar, appear in the confirmation dialog and run with the other writes.

### Validation

- Added review and GUI tests for interface rows, field selection and
  dependencies, apply counts, the blocker message and the confirmation
  summary; offscreen render with live data reviewed.

## v0.6.9

### Added

- M6 slice 4, execution: selected interface changes are written with one PATCH
  per interface after the network writes and before device writes. UniFi is
  re-read and rows whose port configuration changed are skipped; each NetBox
  interface is re-read and skipped when a selected field no longer has its
  preview value; dry runs run all checks; every write is read back as
  verified, mismatch or unverified and recorded in the write history.
  Interfaces are never created or deleted.

### Validation

- Added executor tests (payload of selected fields only, verification, second
  run without changes, dry run, NetBox and UniFi drift, missing interface,
  transport failure, read-back mismatch) and pipeline ordering.

## v0.6.8

### Added

- M6 slice 4, planning: NetBox interfaces now carry their untagged VLAN,
  tagged VLANs and LAG. A new interface plan compares each paired UniFi port of
  a matched device with its NetBox interface field by field (enabled, 802.1Q
  mode, untagged VLAN, tagged VLANs). VLANs come only from the site's
  "UniFi <site>" VLAN group; missing VLANs or a missing group become notes
  instead of writes. `tagged-all` ports get no VLAN list, leftover tagged VLANs
  are cleared outside `tagged` mode, disabled ports only change `enabled`,
  unknown configurations never clear NetBox values, and LAG membership is shown
  but not written. VLAN fields follow the mode selection.

### Validation

- Added planner tests and an interface VLAN snapshot round trip. Live
  read-only: 19 interfaces on 2 matched devices planned (13 mode, 6 enabled);
  VLAN fields wait for the VLAN group as expected.

## v0.6.7

### Added

- M6 slice 3, review window: the port list in the detail panel shows the UniFi
  port name and the effective configuration per port (for example `access 20`,
  `tagged-all, native 1`, `disabled`, `off`, `LAG 7`); the port profile and
  resolution notes appear as tooltips and in the notes list. When the internal
  endpoints were not read, the reason is shown above the list.

### Validation

- Added review and GUI tests for per-device port configuration, profile
  tooltips, notes and the missing-configuration message; offscreen render
  with live data reviewed (UDM Pro Max, 11 ports).

## v0.6.6

### Added

- M6 slice 3: effective UniFi port configuration is read from the internal
  Network endpoints `stat/device`, `rest/portconf` and `rest/networkconf`
  (GET only, UniFi Network 11.0 only). Per port: name, configured enable state,
  profile, mode (`disabled`, `access`, `tagged`, `tagged-all`, `unknown`),
  native VLAN, tagged VLANs and LAG membership. Profiles take precedence over
  port overrides; trunks carrying every VLAN stay explicit `tagged-all` and are
  never expanded. Unknown profiles, networks or rules are reported instead of
  guessed. Only allow-listed fields leave the raw payloads, so network secrets
  are never stored; failures keep the official inventory and are recorded.

### Validation

- Added resolver tests (forwarding rules, profile precedence, disabled versus
  down, unknown inputs, LAG, secret exclusion), reader tests for the version
  gate and tolerant failures, and a snapshot round trip. Live read-only check:
  195 of 195 ports resolved on 17 devices without notes.

## v0.6.5

### Added

- M6 slice 2, review window: a **Networks** filter and summary card show the
	UniFi networks with VLAN, subnet, change type and status. The detail panel
	explains what is created or aligned (VLAN group, VLAN, prefix) with separate
	checkboxes for the VLAN and the prefix, or shows why planning is blocked.
	Selected network writes count in the apply bar, are listed in the
	confirmation dialog and run with the device writes; results appear per
	network.

### Validation

- Added review and GUI tests for network rows, selection, apply counts, the
	blocker message and the confirmation summary; offscreen render with live
	data reviewed (16 networks, 31 planned writes).

## v0.6.4

### Added

- M6 slice 2, execution: the new `network_execute` module writes the selected
	parts of the network plan in the order VLAN group, VLANs, prefixes (a new
	prefix links the VLAN created in the same run). It applies the device-write
	safeguards: UniFi networks are re-read and changed ones skipped, NetBox is
	checked before each write (objects that appeared are not duplicated, an
	existing VLAN group is reused, changed baselines are skipped), interrupted
	creates are looked up instead of retried, and every write is read back.
	Dry runs perform all checks without writing.
- Network writes run before device writes in one run; their outcomes share
	the run summary and the write history. UniFi is re-read once per run.

### Validation

- Added executor tests (order and linking, dry run, appeared objects, update
	baselines, interrupted create, UniFi changes) and pipeline tests.

## v0.6.3

### Added

- M6 slice 2, planning: the new `networks` module compares UniFi networks with
	NetBox IPAM for the configured NetBox site. It plans one site-scoped VLAN
	group ("UniFi <site>"), a VLAN per enabled network and a site-scoped prefix
	per subnet linked to its VLAN. Existing VLAN names are aligned and missing
	prefix VLANs filled in; prefixes pointing at another VLAN, duplicate
	prefixes and duplicate UniFi VLAN IDs are conflicts and never selected.
	Disabled networks are reference-only. The plan is part of the preview
	result; without a NetBox site setting or IPAM access, planning is blocked
	with the reason.

### Validation

- Added planner tests (create, in-sync, completion, conflicts, disabled
	networks, blockers, selection) and a pipeline test.
- Live read-only check: 16 networks planned against the empty NetBox IPAM
	(VLAN group plus 15 VLANs and 15 prefixes selected, 31 operations; the
	disabled network is reference-only).

## v0.6.2

### Added

- M6 slice 2, reading: UniFi networks (name, VLAN ID, enabled, default flag
	and IPv4 subnet from the official network details) and NetBox VLAN groups,
	VLANs and prefixes are read into the snapshots. A NetBox token without IPAM
	rights no longer breaks the refresh; the IPAM error is recorded instead.

### Validation

- Added network/IPAM normalization, missing-permission and snapshot tests.
- Live read-only check: 16 UniFi networks (15 enabled, all with a subnet, no
	duplicate VLAN IDs) read in 0.49 s; NetBox IPAM readable and still empty.

## v0.6.1

### Added

- M6 slice 1: UniFi switch ports (official device details: index, connector,
	maximum speed, PoE, live link state and speed) and NetBox interfaces are read
	into the snapshots. For matched devices, ports are paired with NetBox
	interfaces by exact connector kind (RJ45, SFP, SFP+, SFP28), then by copper
	or optical family, in numbering order. The detail panel lists the ports with
	their NetBox interface and notes for speed or PoE differences and unpaired
	ports or interfaces. Link state and speed are display-only and never written.

### Validation

- Added inventory, snapshot, port matching, review and GUI tests.
- Live read-only check: 195 UniFi ports on 17 devices and 47 NetBox interfaces
	read; the UDM Pro Max pairs 11/11 ports, and a USW Aggregation pairs 8 SFP+
	ports while its NetBox device has 24 further interfaces from another device
	type.

## v0.6.0

### Summary

- Approved NetBox writes milestone (M5): writes are now guarded before, during
	and after execution and every run is recorded.

### Added

- UniFi is re-read right before writing; devices whose selected UniFi values
	changed or vanished are skipped, and nothing is written if UniFi is
	unreachable. NetBox is re-read before every write as before.
- Interrupted creates (timeout, dropped connection, HTTP 502/503/504) are
	reconciled by name in NetBox instead of being retried.
- Successful writes are read back and marked Verified, Mismatch or Not verified,
	without automatic rewrites.
- Every run is saved to `write-journal.sqlite3`; **More > Write history** lists
	recent runs with per-device results.

### Validation

- Milestone-wide offline gate: 281 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): read-only UniFi re-read and a
	dry run over all 15 planned creates, plus an approved NetBox developer-
	instance write test (create and site update verified, history saved, 6/6,
	test objects removed). Interrupted creates and changed UniFi values are
	covered by offline tests only.

### Compatibility

- New local file `write-journal.sqlite3` next to the configuration; existing
	configuration and snapshots load without migration.

## v0.5.4

### Added

- Every write run and dry run is saved to `write-journal.sqlite3` next to the
	configuration (outside the repository), with start/finish time, dry-run flag
	and per-device result, NetBox ID and read-back state. **More > Write
	history** lists recent runs and their results. A failed save is reported in
	the run summary and never affects the writes.

### Fixed

- The journal finish time is now taken after the run instead of before it.

### Validation

- Added journal store tests (ordering, empty history, schema and corrupt data
	errors), pipeline tests for saving and save failures, and GUI tests for the
	history dialog and the journal path passed to write jobs.

## v0.5.3

### Added

- UniFi is re-read right before writing (with the configured NetBox site
	mapping). Operations whose selected UniFi values changed since the preview,
	or whose device UniFi no longer reports, are skipped with the reason; if
	UniFi cannot be read, nothing is written. Dry runs run the same check.

### Validation

- Added executor tests for unchanged, changed, missing and unreadable UniFi
	sources, pipeline tests for the re-read and its site mapping, and a GUI test
	that the UniFi settings reach the write job.

## v0.5.2

### Added

- Interrupted creates are reconciled instead of retried. After a timeout, a
	dropped connection, HTTP 502/503/504 or a create response without an ID,
	the app looks the device up by name: exactly one match counts as created
	(with its ID, then read back), no match fails with "Refresh, then retry",
	and several matches or a failed lookup ask for a manual check in NetBox.

### Validation

- Added executor tests for found, missing, duplicated and unverifiable
	interrupted creates (each with a single create call) and backend tests for
	which NetBox answers count as ambiguous.

## v0.5.1

### Added

- Successful writes are read back from NetBox and compared with the written
	values (plain fields directly, site/role/device type by ID, status by value).
	Each result is marked verified, mismatch or unverified; mismatches and read
	errors never trigger another write. The table shows Verified, Mismatch or
	Not verified, the detail panel and copied details include the read-back
	detail, and the run summary counts verified writes. Dry runs are not
	read back.

### Validation

- Added executor tests for verified creates and updates, mismatches, read-back
	failures and dry runs, a read-back value test and a GUI status test.

## v0.5.0

### Summary

- GUI redesign milestone (M4.5): a modern, review-centric window. Matching,
	preview and write behavior are unchanged.

### Changed

- Fusion theme that follows the system light/dark mode, with a theme button
	next to Settings (Follow system, Light, Dark) saved as `[ui] theme`.
- Header with connection status chips, summary cards and filter chips, a
	review table with per-device checkboxes, a detail panel with field-level
	selection and create choices, and an apply bar with dry run. Replaces the
	`Show all rows` dialog and the highlight list.
- One confirmation dialog with grouped warnings and blockers; per-device
	results in the table and a banner with **Refresh now** after real writes.
- Settings dialog with NetBox, UniFi Network and Sync defaults pages.

### Validation

- Milestone-wide offline gate: 249 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass, with the native and the offscreen Qt platform.
- Offscreen light and dark screenshots reviewed. On 2026-11-14 the user ran the
	redesigned app on the developer workstation and approved the look; this is
	user feedback, not an assistant-driven GUI walkthrough.

### Compatibility

- New optional `[ui] theme` setting; existing configuration and snapshots load
	without migration.

## v0.4.2

### Added

- Theme button next to Settings: one click switches between light and dark,
	its menu offers Follow system, Light and Dark. The choice is saved in the new
	`[ui] theme` setting and applied at startup.

### Validation

- Added GUI tests for toggling and saving the theme and a config roundtrip test
	for the `[ui]` section; offscreen light and dark header renders reviewed.

## v0.4.1

### Changed

- Redesigned GUI (M4.5): Fusion-based theme that follows the system light or
	dark mode, connection status chips in a header, summary cards, filter chips
	and search, a review table with per-device checkboxes and badges, a detail
	panel with field-level selection and create choices, and an apply bar with
	dry run. The `Show all rows` dialog and the highlight list are replaced.
- Settings dialog with NetBox, UniFi Network and Sync defaults pages.
- One confirmation dialog summarizes the selected writes, groups warnings and
	disables applying while blockers (for example a missing device role) exist.
- Write results appear per device in the table and in a banner, with
	**Refresh now** after real writes.

### Added

- Qt-free `review` module holding device and field selection, create choices
	and write outcomes; `WriteExecutionReport` now carries per-device outcomes.
- `theme` module with light/dark palettes, semantic tones and native theme
	icons (Segoe Fluent on Windows 11) with style fallbacks.

### Validation

- Rewrote the GUI preview tests for the review window and added review-state
	and theme tests; settings and connection tests are unchanged.
- Light and dark screenshots rendered offscreen with synthetic data were
	reviewed; the real Windows desktop rendering was not inspected here.

## v0.4.0

### Summary

- Fourth functional milestone: matching and difference preview (M4). The
	release also contains early M5 write slices; M5 itself remains open.

### Added

- Ranked matching (confirmed mappings, then name, serial, MAC) with explicit
	ambiguity conflicts and site-scoped NetBox-only delete proposals.
- Device Type suggestions by model, NetBox part number and UniFi aliases, with
	port-count and manufacturer guards and preselection of unambiguous matches.
- Difference and change previews with provenance, configured/operational
	categories, field/device/batch selection and explicit dependencies.
- Inventory Preview in the main window with highlights, copy actions and the
	`Show all rows` dialog including per-row role, site, status and type choices.
- Approved NetBox writes (M5 slices): ordered write plan with preflight
	blockers, one confirmation, dry run, single-row execution, outcome journal,
	read-back planning and a NetBox re-read before every write.
- NetBox site setting for UniFi devices, UniFi API dump exports and UniFi
	Network 11.0 support in the connection gate.
- Qt-free `pipeline` module for preview and write orchestration.

### Fixed

- Update previews only preselect writable fields and never clear NetBox values
	from empty UniFi fields.

### Validation

- Milestone-wide offline gate: 237 passed, 1 skipped, 0 failed; Ruff lint and
	format checks pass.
- Live on the developer workstation (2026-11-14): read-only checks against
	NetBox 4.7.3 and UniFi Network 11.0.99, plus an approved write test against
	the NetBox developer instance (9/9 checks); see `docs/TESTING.md`.
- The GUI was started on the developer workstation; GUI workflows were not
	driven by the assistant. Linux and packaged builds remain unverified.

### Compatibility

- New optional `[behavior] netbox_site_name` setting; existing configuration
	and snapshots load without migration (`part_number` defaults to empty).

## v0.3.40

### Changed

- Device Type suggestions now compare UniFi model names with NetBox device-type
	models and part numbers (`part_number` is read from NetBox), plus two UniFi
	aliases: `AC ...` models map to `UAP-AC-...` and a `PoE` token next to a
	wattage is dropped (`US 16 PoE 150W` -> `US-16-150W`).
- Fuzzy candidates with different port counts and candidates that only share
	the manufacturer are no longer suggested.
- An unambiguous exact, part-number or alias suggestion is preselected as the
	`Device type` of a create row; it stays editable before confirmation.

### Validation

- Added matching tests with NetBox device-type library names, port-count and
	manufacturer guards, preselection rules and a GUI preselection test.
- Live read-only check: all 11 UniFi models in this installation get the
	correct NetBox type preselected (15 of 15 create rows); before, only 1 model
	matched exactly.

## v0.3.39

### Added

- New Settings field `NetBox site for UniFi devices` (`[behavior]
	netbox_site_name`). When set, it replaces the UniFi site name of every UniFi
	device before matching, so creates use that NetBox site, matched devices no
	longer propose site changes and delete scoping compares NetBox sites.

### Fixed

- A UniFi site name that does not exist in NetBox is no longer selected for
	updates (shown as preview-only with a hint), and create rows using it get an
	`unknown_netbox_site` warning with the reason in `Show all rows`. The guard
	is skipped when the NetBox site catalog is empty.

### Validation

- Added config, settings, preview, write-plan and pipeline tests for the site
	mapping and the unknown-site guard.
- Live read-only check: without mapping 15 creates with site warnings and no
	site updates; with the mapping 15 creates without warnings.

## v0.3.38

### Changed

- The UniFi connection gate now accepts the stable Network 11.0 series in
	addition to 10.6. Other versions and pre-releases still report Unsupported.

### Validation

- Added connection tests for 11.0.99 (Online) and for 10.5, 12.0, 11.1 and
	pre-release versions (Unsupported).
- Live read-only check on the developer workstation: Network 11.0.99 now
	reports Online with one automatically selected site.

## v0.3.37

### Fixed

- Update previews only preselect fields the update executor can write (`name`,
	`serial`, `site`). Changed `model`, `manufacturer` and `mac_address` values
	stay visible as preview-only, so naming differences between UniFi models and
	NetBox device types no longer block the whole write plan.
- Empty UniFi values are never selected for updates, so missing source fields
	can no longer clear existing NetBox values (for example serial numbers).

### Validation

- Added preview tests for preview-only fields and empty source values; the
	model/manufacturer dependency tests now force the selection explicitly.
- Live read-only check on the developer workstation: the plan changed from
	3 dependency blockers to executable with 15 creates and 4 updates.

## v0.3.36

### Changed

- Move the inventory preview and write-execution orchestration out of the GUI
	into the new Qt-free `pipeline` module. GUI worker jobs now only call
	`build_inventory_preview` / `run_write_execution`. No behavior change; the
	UniFi API dump fields are carried through the pipeline result.
- Rename the write-execution display result to `WriteExecutionReport`.

### Validation

- Added Qt-free pipeline tests for ready and partial refresh results; GUI tests
	now import preview helpers from the pipeline module.

## v0.3.35

### Changed

- Apply `ruff format` to modules with merged implicit string concatenations
	and trailing whitespace so the CI format check passes again. No behavior
	change.

## v0.3.34

### Added

- Write execution now re-reads NetBox before every operation. Updates are
	skipped when the target device was deleted or any selected field changed in
	NetBox since the preview; creates are skipped when a device with the same
	name or serial now exists. Skipped operations name the reason and ask for a
	preview refresh. Dry runs perform the same read-only check.

### Validation

- Added write-execution tests for changed/deleted update targets, unselected
	field changes, newly appeared create duplicates, dry-run staleness and
	failing pre-write reads.

## v0.3.33

### Added

- Add export of full UniFi Network API feedback from the current preview state
	as JSON dump (`api_feedback` plus raw device rows).
- Add per-row UniFi raw payload export in `Show all rows` for selected
	UniFi-backed preview rows.

### Changed

- UniFi inventory snapshots now retain raw API page payloads and raw device
	entries to support post-refresh dump export workflows.

### Validation

- Extended inventory, snapshot and GUI tests for raw payload persistence and
	UniFi row/source-id mapping helpers used by row-level dump export.

## v0.3.32

### Changed

- NetBox create payload now uses `role` (NetBox API field) instead of
	`device_role`, improving compatibility with NetBox 4.x create validation.
- Create/update failures now include parsed NetBox response details in error
	messages (for example field-level validation output), not just HTTP status.

### Validation

- Updated write-execution tests to assert the `role` payload field and reran
	focused write-execution checks.

## v0.3.31

### Added

- Add a per-row `Device type` dropdown for create rows in `Show all rows`,
	sourced from the current NetBox device-type catalog and including type IDs.

### Changed

- Create execution now accepts row-level device-type ID overrides; selected
	values are written directly into the create payload and bypass ambiguous
	manufacturer/model auto-resolution.

### Validation

- Extended GUI and write-execution tests for device-type dropdown rendering and
	create execution with explicit device-type ID overrides.

## v0.3.30

### Changed

- Keep NetBox inventory refresh successful when `dcim/devices/_choices/` is
	unavailable or restricted; treat status-choice loading as optional enrichment.
- Infer available device status values from NetBox device rows as a fallback,
	so the create-row `Device status` selector can still be populated in
	read-only/restricted API setups.

### Validation

- Added regression coverage for unavailable status-choice endpoint with
	successful refresh and inferred status catalog fallback.

## v0.3.29

### Added

- Read NetBox device status choices from `dcim/devices/_choices/` during
	inventory refresh and persist them in snapshot state.
- Add a per-row `Device status` dropdown for create rows in `Show all rows`,
	populated from the current NetBox status choices.

### Changed

- Use the selected row status for create execution as an explicit override;
	fallback to NetBox API defaults when no row-specific status is set.

### Validation

- Extended inventory, GUI and write-execution tests for status ingestion,
	row-level status selection and create-status override execution.

## v0.3.28

### Added

- Read NetBox sites from `dcim/sites` during inventory refresh and persist
	them in snapshot state.
- Add a per-row `Device site` dropdown for create rows in `Show all rows`,
	populated from the current NetBox site catalog.

### Changed

- Use the selected row site for create execution as an explicit override;
	fallback to the preview source site when no row-specific site is set.

### Validation

- Extended inventory, GUI and write-execution tests for site ingestion,
	row-level site selection and create-site override execution.

## v0.3.27

### Added

- Read NetBox device roles from `dcim/device-roles` during inventory refresh
	and persist them in snapshot state.
- Add a per-row `Device role` dropdown for create rows in `Show all rows`,
	populated from the current NetBox role catalog.

### Changed

- Use the selected row role for create execution as an explicit override;
	fallback to the configured default role when no row-specific role is set.

### Validation

- Extended inventory, GUI and write-execution tests for role ingestion,
	row-level role selection and create-role override execution.

## v0.3.26

### Changed

- Default UniFi device manufacturer values to `Ubiquiti` when the local API
	payload does not provide a manufacturer field, preventing false
	`missing manufacturer` create blockers.

## v0.3.25

### Changed

- Improve non-executable row diagnostics to prefer row-specific dependency
  context (for example missing required identity fields) over generic plan
  blocker wording.

### Added

- Add per-row `Suggested Device Types` output for create rows in the
  `Show all rows` dialog, based on unmatched UniFi observations and the current
  NetBox device-type catalog.

## v0.3.24

### Added

- Add a `Reason` column in the `Show all rows` dialog so non-executable preview
	rows explain why execution is blocked.
- Show the same row-specific reason in the status bar when executing a selected
	non-executable row is attempted.

### Validation

- Extended GUI coverage for blocked-row reason rendering in
	`tests/test_gui.py`.

## v0.3.22

### Added

- Integrate write execution into the main GUI preview section with a dedicated
	"Execute write plan" action, one confirmation dialog and optional dry-run mode.
- Surface write execution outcomes directly in preview highlights so success,
	failure and skipped operations are visible without leaving the main window.
- Add per-row execution from the `Show all rows` dialog for selected executable
	rows, enabling targeted writes when full-batch execution is blocked.

### Validation

- GUI apply-flow coverage added in `tests/test_gui.py`.

## v0.3.21

### Added

- Add a service-level NetBox write executor for device create/update operations
	with immutable journal outcomes and optional dry-run mode.
- Add behavior setting `default_device_role_name` to support create execution
	with explicit NetBox role resolution.

### Validation

- Added focused executor/config/GUI tests:
	`tests/test_write_execute.py`, `tests/test_unifi_config.py`,
	`tests/test_gui.py`.

### Added

- Extend M5 offline contract coverage for write-plan/read-back behavior:
	idempotent planning, partial-failure read-back filtering, zero read-back on
	cancel without successes, and explicit skips for missing operation sequences.
- Add a behavior setting to include all NetBox devices for delete proposals;
	default behavior keeps NetBox-only delete candidates limited to UniFi site
	scope for safer device-lifecycle review.

### Documentation

- Update implementation/testing docs to mark the M5 cancel/partial-failure/
	concurrent-edit/idempotence test item as completed with focused offline tests.

## v0.3.19

### Changed

- Change deduplication pass order for UniFi observations to strict candidate
	lookup by name, then serial, then MAC (after optional confirmed mappings).
- Treat duplicate candidates inside the active pass as ambiguity conflicts and
	stop fallback escalation for that observation.
- Extend NetBox inventory reads to include paginated `dcim/device-types` data
	and use that template catalog for unmatched create suggestions.

### Validation

- Matching/preview/inventory/snapshot suites cover ordered matching reasons,
	ambiguity behavior and device-type ingestion:
	`tests/test_matching.py`, `tests/test_preview.py`, `tests/test_inventory.py`,
	`tests/test_snapshots.py`.

## v0.3.18

### Added

- Extend deduplication with a normalized-name fallback pass for still-unpaired
	UniFi observations after confirmed and serial/MAC identity passes.
- Keep fallback safe by emitting ambiguity conflicts instead of auto-pairing
	when multiple NetBox devices share the same normalized name.

### Validation

- Matching and GUI suites pass with new name-fallback tests:
	`tests/test_matching.py`, `tests/test_gui.py`.
- Ruff checks pass for matching and GUI modules/tests.

## v0.3.17

### Fixed

- Fix preview-row generation in the GUI by using executable state from
	change-preview items instead of a non-existent write-plan attribute.
- Restore row results in the `Show all rows` dialog after the previous commit
	regression that could suppress all matches/rows.

### Validation

- GUI suite passes with dedicated regression coverage: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.16

### Added

- Add filtering controls to the `Show all rows` dialog: action filter
	(`All/Create/Update/Target only`) and `Executable only` toggle.
- Keep filtering local to the dialog so users can quickly narrow larger
	preview tables without refreshing inventory data.

### Validation

- GUI suite passes with row-filter behavior checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.15

### Added

- Add a non-modal `Show all rows` dialog for inventory preview data.
- Display complete preview rows in a table with device key, action, labels,
  selected fields and executable state.

### Validation

- GUI suite passes with dialog/table checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.14

### Added

- Add `Copy selected` and `Copy all` actions for inventory preview highlights.
- Write copied highlight text directly to the system clipboard and report the
	action in the status bar for immediate feedback.

### Validation

- GUI suite passes with clipboard interaction tests: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.13

### Added

- Ensure inventory preview highlights always include at least one visible detail
	line for `Partial`/`Unavailable` states.
- Add explicit empty-NetBox guidance and unmatched/plan-issue fallback lines so
	users see why no direct matches are shown yet.
- Set a minimum list height for preview highlights to avoid collapsed rendering.

### Validation

- GUI suite passes with new fallback-detail test: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.12

### Added

- Replace the inventory preview action icon with a clearer info-style symbol to
	distinguish it from connection checks.
- Add a clickable inventory highlight list with a dedicated detail field so
	users can inspect preview items directly in the main window.

### Validation

- GUI suite passes with interactive highlight selection checks:
	`tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.11

### Added

- Extend the GUI inventory preview with structured highlight lines for matched
	pairs, detected conflicts and planned write operations.
- Keep preview highlights read-only and capped to concise top entries so results
	remain scannable in the main window.

### Validation

- GUI suite passes with highlight rendering checks: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.10

### Added

- Add a visible Inventory Preview section in the main GUI with counts for
	NetBox/UniFi devices, matches, conflicts, preview rows and executable
	operations.
- Add a background "Refresh Inventory Preview" action that reads snapshots,
	computes dedup/preview/write-plan summaries and updates UI state safely.

### Validation

- GUI suite passes with new preview-state tests: `tests/test_gui.py`.
- Ruff checks pass for `gui.py` and GUI tests.

## v0.3.9

### Added

- Add a read-only read-back planner for successful M5 operations that resolves
	NetBox object IDs for create/update verification reads.
- Skip successful create outcomes without object IDs so unresolved results stay
	explicit and can be reconciled manually.

### Validation

- Focused offline suite passes: `tests/test_write_readback.py`.
- Ruff checks pass for `write_readback.py` and read-back tests.

## v0.3.8

### Added

- Add a write-journal reconcile helper that flags ambiguous successful create
	outcomes when NetBox object IDs are missing or duplicated.
- Keep reconcile evaluation read-only and deterministic for later manual
	resolution and read-back slices.

### Validation

- Focused offline suite passes: `tests/test_write_journal.py`.
- Ruff checks pass for `write_journal.py` and journal tests.

## v0.3.7

### Added

- Add an immutable write journal model for M5 operation outcomes (`pending`,
	`success`, `failed`, `skipped`) without introducing API write execution.
- Add journal initialization, per-operation result updates, finalization and
	summary counters for later M5 execution/reconciliation slices.

### Validation

- Focused offline suite passes: `tests/test_write_journal.py`.
- Ruff checks pass for `write_journal.py` and journal tests.

## v0.3.6

### Added

- Add a write-plan confirmation summary model with operation totals, blocker
	counts, blocked device keys and a single user-facing confirmation message.
- Keep M5 execution planning immutable and read-only while making confirmation
	readiness explicit (`requires_confirmation` vs `executable`).

### Validation

- Focused offline suite passes: `tests/test_write_plan.py`.
- Ruff checks pass for `write_plan.py` and write-plan tests.

## v0.3.5

### Added

- Add a read-only write-planning service model that derives ordered create/update
	operations from immutable M4 change previews.
- Add M5 preflight blockers for dependency failures, duplicate create labels and
	duplicate update targets before any write execution layer exists.
- Add deterministic operation sequencing (create before update) to prepare a
	single summary confirmation flow in later M5 slices.

### Validation

- Focused offline suite passes: `tests/test_write_plan.py`.
- Ruff checks pass for `write_plan.py` and write-plan tests.

## v0.3.4

### Added

- Add immutable change-preview summaries with explicit dependency contracts per
	device action.
- Add create prerequisites (`name`, `site`) and model/manufacturer dependency
	rules without introducing write paths.
- Add executable versus blocked change state to expose write readiness decisions.

### Validation

- Focused offline suite passes: `tests/test_preview.py`.
- Ruff checks pass for `preview.py` and preview tests.

## v0.3.3

### Added

- Add a difference-preview service model with source/target values and explicit
	provenance for matched, create and target-only device views.
- Add configured/operational field categories and unsupported field markers for
	preview-only visibility.
- Add batch, device and field selection helpers for immutable preview state.

### Validation

- Focused offline suite passes: `tests/test_preview.py`.
- Ruff checks pass for `preview.py` and preview tests.

## v0.3.2

### Added

- Add explainable Device Type suggestions for unmatched UniFi observations only.
- Rank suggestions by manufacturer/model similarity against existing NetBox
	manufacturer/model combinations.
- Keep suggestions read-only and exclude already matched observations.

### Validation

- Focused offline suite passes: `tests/test_matching.py`.
- Ruff checks pass for updated matching service and tests.

## v0.3.1

### Added

- Add an identity deduplication service for cross-source NetBox/UniFi matching.
- Add confirmed mapping support with explicit conflict detection for duplicate
	targets and missing mapping endpoints.
- Add ambiguity diagnostics when one UniFi observation matches multiple NetBox
	candidates by identity evidence.

### Validation

- Focused offline suite passes: `tests/test_matching.py`.
- Ruff checks pass for `matching.py` and matching tests.

## v0.3.0

### Summary

- Third functional milestone: inventory snapshots and diagnostics foundations.

### Added

- Read-only paginated NetBox/UniFi inventory readers with normalized timestamped
	snapshot models.
- Versioned SQLite snapshot state with current/previous records and refresh
	service foundations.
- Stale/offline cache browsing plus partial-read diagnostics without write paths.
- Explicit opt-in sanitized fixture/report export with deterministic
	pseudonymization for sensitive identifiers.
- Installed-version capability matrix for ports, profiles, overrides, VLAN,
	PoE, speed/duplex, LAG and LLDP.

### Validation

- Milestone-wide offline gate: 130 passed, 1 skipped, 0 failed.
- Ruff lint and format checks pass for the full workspace.

### Compatibility

- Existing settings and snapshot schema remain compatible without migration.
- Linux and exact target-platform verification remain unreported.

## v0.2.5

### Added

- Add an installed-version capability matrix builder for ports, profiles,
	overrides, VLAN, PoE, speed/duplex, LAG and LLDP.
- Add per-field status mapping (`Verified`, `Unverified`, `Missing`) with
	UniFi evidence hints and intended NetBox targets.
- Add markdown rendering support for capability-matrix reporting.

### Validation

- Focused offline suite passes: `tests/test_capabilities.py`.
- Ruff checks pass for `capabilities.py` and matrix tests.

## v0.2.4

### Added

- Add an explicit opt-in snapshot fixture/report export service for target-PC sharing.
- Add deterministic pseudonymization for source IDs, names, serials, MAC addresses,
  sites and snapshot scope in exported fixtures.
- Add export controls for including or omitting previous snapshots per source.

### Validation

- Focused offline suite passes: `tests/test_reporting.py`.
- Ruff checks pass for `reporting.py` and export tests.

## v0.2.3

### Added

- Add stale/offline cache browsing based on stored current/previous snapshots.
- Add partial-refresh diagnostics that preserve and reuse the last successful
	cached snapshot when a source refresh fails.
- Add freshness checks for cached snapshots and expose stale indicators in the
	refresh/browse service results.

### Validation

- Focused offline suite passes: `tests/test_refresh.py` and `tests/test_snapshots.py`.
- Ruff checks pass for updated refresh/snapshot services and tests.

## v0.2.2

### Added

- Add a versioned SQLite snapshot store for per-source current/previous inventory snapshots.
- Add an internal refresh service that persists successful reads and reports per-source failures.
- Add offline contract tests for schema checks, current/previous rollover and refresh behavior.

### Validation

- Focused offline suite passes: `tests/test_snapshots.py` and `tests/test_refresh.py`.
- Ruff checks pass for `snapshots.py`, `refresh.py` and the new tests.

## v0.2.1

### Added

- Add M3 inventory-reader foundations with normalized timestamped snapshot models.
- Add read-only paginated NetBox and UniFi Network inventory readers with bounded
	pagination checks and schema validation.
- Add offline contract tests for normalized pagination reads and failure handling.

### Validation

- Focused offline suite passes: `tests/test_inventory.py`, `tests/test_netbox.py`
	and `tests/test_unifi.py` (51 tests).
- Ruff checks pass for the new inventory reader and its tests.

## v0.2.0 - 2026-10-28

### Summary

- Second approved functional milestone: UniFi Network connection status with the
	shared NetBox/UniFi Settings and Check Connections workflow.

### Changed

- Promote the accepted M2 milestone from development version 0.1.4 to 0.2.0.

### Documentation

- Record user-reported target-PC confirmation of the revised 0.1.4 unified
	Settings and shared Check Connections workflow on 2026-10-28.
- Record the approved M2 merge to main and v0.2.0 release preparation.

### Validation

- M2 local gates remained green at release preparation: 109 offline tests pass,
	optional native package test skipped by default.
- Fresh Windows standalone 0.1.4 startup/shutdown passed in its separately
	enabled native test.
- Ruff lint/format and editor diagnostics remained clean for the milestone slice.

### Compatibility

- Existing TOML files need no migration; API endpoints and authentication are unchanged.
- Linux and exact target-platform coverage remain unverified.

## v0.1.4

### Changed

- Replace separate service dialogs with one Settings dialog and NetBox/UniFi tabs.
- Use one Check Connections action in the main window and one shared test command
	in Settings; both test all connections while reporting separate results.
- Validate both tabs before a single atomic save; Cancel preserves both sections.
- Wait for both settings checks before enabling controls or completing a close.

### Documentation

- Record user-reported success of the preceding M2 online tests on 2026-10-25.
- Update the unified-settings workflow and targeted confirmation checklist.

### Validation

- 109 offline tests pass; the optional native package test is skipped by default.
- Fresh Windows standalone 0.1.4 passes its separately enabled startup/shutdown test.
- Ruff lint/format and editor diagnostics pass; both tabs and compact layout reviewed.

### Compatibility

- Existing TOML files need no migration; API endpoints and authentication are unchanged.
- The user reported revised GUI target-PC acceptance passed on 2026-10-28.
- Linux remained unverified at this development patch level.

## v0.1.3

### Added

- Independent NetBox/UniFi status areas, startup checks and settings actions.
- UniFi API-key masking, independent TLS/CA settings and editable discovered-site selection.
- Shared status workflow with stale-result rejection and shutdown of both workers.

### Documentation

- Document both GUI workflows and the UniFi target-PC acceptance checklist.

### Validation

- 101 offline tests pass; the optional native package test is skipped by default.
- A fresh Windows standalone 0.1.3 build passes its separately enabled startup/shutdown test.
- Ruff lint/format and editor diagnostics pass; normal/compact Qt screenshots reviewed.

### Compatibility

- The user subsequently reported the M2 online tests passed on 2026-10-25.
- Linux remains unverified; M2 is not merged or tagged.

## v0.1.2

### Added

- Read-only local UniFi Network API checks for version, sites and device access.
- Bounded site discovery, explicit multi-site selection and endpoint capability errors.
- Independent TLS/timeout handling and synthetic HTTP contract tests; no login fallback.

### Validation

- 94 offline tests pass, including both API adapters; optional package test skipped.
- TLS configuration, private CA, pagination limits and sanitized failures covered.

### Compatibility

- Target Network 10.6 with live 10.6.100 verification still pending. Public 10.6.106
	schemas are a reference only. GUI integration follows in the next patch.

## v0.1.1

### Added

- Independent UniFi Network TOML settings for console URL, API key, site and TLS.
- Preserve NetBox settings, unknown tables and comments when editing either service.

### Validation

- 62 offline tests pass; the optional native package test is skipped by default.
- Ruff lint/format and editor diagnostics pass for the configuration slice.

### Compatibility

- Existing NetBox-only configuration works without migration. UniFi GUI/API follow
	in the next M2 patch; no UniFi live connectivity is claimed yet.

## v0.1.0 - 2026-10-25

### Summary

- First approved functional milestone: NetBox connection status in a desktop GUI.

### Added

- Authenticated read-only NetBox checks, editable TOML settings and background jobs.
- TLS/CA options, masked tokens, startup/manual checks and a Windows build recipe.

### Changed

- Promote the accepted NetBox milestone from development version 0.0.2 to 0.1.0.

### Fixed

- No additional behavior fixes in this release-preparation change.

### Documentation

- Record binding project rules, milestone branches and acceptance criteria.
- Document the agreed read-only UniFi and explicitly approved NetBox workflow.
- Record the user's successful NetBox online acceptance on 2026-10-25.
- Keep unreported environment details and pending Linux coverage explicit.

### Validation

- Release 0.1.0: 50 offline tests passed; the opt-in package test is skipped by default.
- The separately enabled native Windows EXE startup/shutdown test passed for 0.1.0.
- Release metadata, Ruff lint and Ruff format checks passed.
- NetBox online acceptance passed according to the user on 2026-10-25.

### Compatibility

- Python >=3.15.1, PySide6 6.12.0, pynetbox 7.9.0 and the NetBox 4.7 API.
- Linux and exact target-OS coverage remain unverified. UniFi is not implemented.
- The user explicitly approved the main merge and v0.1.0 release on 2026-10-25.

## v0.0.2

### Added

- PySide6 window showing NetBox status, endpoint, version and last check.
- Editable settings with masked tokens, CA file selection, TLS warnings and timeout.
- Test unsaved connections, save atomically or cancel without changing settings.
- Background startup/manual checks, stale-result protection and safe worker shutdown.
- Module and installed command entry points, including explicit config path/version.
- Pinned Windows standalone build recipe, license notices and opt-in native smoke test.
- Windows/Linux offline CI definition; no infrastructure credentials required.

### Documentation

- Describe GUI startup, configuration recovery and target-PC acceptance steps.

### Validation

- 50 offline tests pass; opt-in package test is skipped in the normal suite.
- Native Windows standalone EXE window startup and graceful shutdown pass separately.
- Ruff lint/format and editor diagnostics pass. GUI screenshots checked with synthetic data.

### Compatibility

- Python 3.15.1 / Qt 6.12 source and standalone checks on local Windows 11.
- NetBox online acceptance reported passed by the user on 2026-10-25.
- Linux and exact target-OS coverage remain unverified; no merge/tag created.

## v0.0.1

### Added

- Validated NetBox settings with atomic TOML saves and per-user configuration paths.
- Read-only authenticated NetBox 4.7 inventory check with timeouts and redirect refusal.
- Explicit connection outcomes and independent TLS/CA configuration.

### Documentation

- Document the isolated environment, offline tests and target-PC acceptance process.

### Validation

- Add synthetic adapter and configuration tests; default tests forbid live sockets.

### Compatibility

- Python >=3.15.1, PySide6 6.12.0 and pynetbox 7.9.0. GUI arrives in the next patch.