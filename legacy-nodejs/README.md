# legacy-nodejs/

This is OraPulse's original Node.js/Express backend (`main.js`, `report.js`,
`favorites.js`, `tuning.js`), kept in strict feature parity with the Python
backend throughout early development. As of this move, **the Python backend
(`main.py`, at the project root) is the sole backend** -- this folder is kept
only as a historical reference and is no longer maintained or tested. The
packaged Windows distribution (`build.ps1`/`build-installer.ps1`) has always
built from the Python backend only.

Safe to delete entirely if you don't need the reference.
