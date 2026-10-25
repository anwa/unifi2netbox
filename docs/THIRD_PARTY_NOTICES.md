# Third-Party Notices

unifi2netbox is MIT-licensed. Third-party dependencies keep their own licenses;
the application's MIT license does not relicense Qt or other components.

- [Qt for Python / PySide6](https://www.qt.io/qt-for-python): LGPL/GPL/commercial
  options depending on modules and distribution. This application uses Qt Widgets,
  Qt GUI and Qt Core, with shared libraries in the standalone directory.
- [pynetbox](https://github.com/netbox-community/pynetbox): Apache-2.0.
- [Requests](https://github.com/psf/requests): Apache-2.0.
- [Packaging](https://github.com/pypa/packaging): Apache-2.0 / BSD-2-Clause.
- [TOML Kit](https://github.com/python-poetry/tomlkit): MIT.
- [platformdirs](https://github.com/tox-dev/platformdirs): MIT.
- [Python](https://www.python.org/): Python Software Foundation license.

Transitive dependencies have additional notices. The build recipe copies runtime
distribution metadata recursively, including available license files. Inspect the
actual artifact and preserve required license texts/notices when distributing it.
Obtain corresponding dependency source and LGPL compliance information from the
upstream projects/Qt distribution matching the packaged versions. Do not remove
or conceal dependency notices. Release packaging must complete a license review;
the initial smoke build is not a compliance certification.