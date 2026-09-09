# OraPulse

**Oracle Database Monitoring(ODM)** -- a small, standalone Oracle Database
monitoring app that runs entirely on the user's own machine. There is no
shared backend, no central server, and no app-level login: each user runs
their own local instance, points it at an Oracle DB by typing in connection
details, and opens the dashboard in a browser -- exactly like using a
desktop DB client (SQL Developer, Toad, etc.), except the "client" happens
to be a small local web server.

## Overview

- **No login of its own.** The Oracle account/password typed into the
  connect screen is the only credential involved, and it never leaves the
  machine OraPulse is running on. The server binds to `127.0.0.1` only.
- **Single Python backend.** `main.py` (FastAPI + `python-oracledb`) serves
  both the REST API and the static frontend in `public/`. Earlier in
  development, the exact same feature set was also maintained in parallel as
  a Node.js/Express implementation; that original implementation is kept for
  reference under `legacy-nodejs/` but is no longer built, run, or tested --
  the Python backend is the only one that ships in the packaged Windows
  build and the only one this README describes below.
- **Works on any Oracle edition/version 12.1+.** Every feature is built on
  plain `V$`/`DBA_` views reachable with an ordinary account (SYSTEM-level
  read access is recommended so every card actually has data to show, but
  isn't required for the app to run). Nothing requires the Diagnostics or
  Tuning Pack.

## Features

### DashBoard tab
- Instance Information (name, status, host, full version via
  `V$INSTANCE.VERSION_FULL`, startup time, uptime)
- CPU / Memory usage
- Current Session List -- ACTIVE sessions first, then oldest-login-first;
  Status/Machine/Program filters; right-click a row to **Kill Session
  (IMMEDIATE)**, view its running query, or view wait detail (with a
  file/block object lookup against `DBA_EXTENTS` for file/block-based waits);
  excludes OraPulse's own brief monitoring connections from the list/count
- Blocking Session list
- Long Running Session progress bars (`V$SESSION_LONGOPS`)
- Table Statistics Collection, including a batch "gather stats for selected
  tables" action, and a **Table Properties** view (columns, indexes) from a
  table's right-click menu
- Scheduler/Job Failures -- `DBMS_SCHEDULER` run history (any outcome other
  than SUCCEEDED) plus a live snapshot of broken/failing legacy `DBMS_JOB`
  jobs, with a schema filter
- Account Security -- currently locked accounts, and accounts whose
  password has already expired or is expiring soon, from `DBA_USERS`
- Alert Log Analysis (`V$DIAG_ALERT_EXT`)

### Ops tab
Key Instance Parameters and Undo Configuration & Status side by side;
Instance Efficiency % and Load Profile side by side; then, one per row:
TEMP Tablespace Usage, TEMP Usage by Session, Datafile Autoextend Status
(MAXSIZE proximity), Redo Log Status, Tablespace I/O Stats (sorted by
physical reads), Top 5 Long-Running Queries, Top 5 SQL by CPU Time, Top 5
SQL by Buffer Gets, and Top 5 Wait Events. Every card here is freely
drag-and-drop reorderable (including across tabs), with the layout
persisted to `localStorage` and merged against the app's own default order
on load, so an app update that changes the default doesn't get silently
overridden by an old saved layout, and a card missing from an old saved
layout still lands in its correct place instead of jumping to one end.

### Recovery tab
Recent DML (top 50, most recent first, with Type/Schema filters), Fast
Recovery Area overview, and FRA usage by file type.

### Tuning tab
A rule-based tuning advisor -- no AWR/ASH, no Diagnostics/Tuning Pack
license needed. Runs a fixed set of checks (buffer/library cache hit
ratio, hard parse ratio, disk sorts, wait event increases, tablespace
free-space usage, invalid objects, blocking sessions, slow SQL) against
`V$SYSSTAT`, `V$LIBRARYCACHE`, `V$SYSTEM_EVENT`, `V$SQL`, `DBA_DATA_FILES`/
`DBA_FREE_SPACE`, `DBA_OBJECTS`, and `V$SESSION` only. Rate-based checks
compare against an encrypted local snapshot of the previous check (a tiny,
statspack-style delta, not a real AWR history), so the first check on a
database shows "not enough history yet" for those specific checks until
run again. Same-type findings are grouped into one item with a table
(e.g. one "Tablespace Usage" item listing every low-space tablespace) and
a Slow SQL row's SQL_ID is clickable to view the full query text.

### Obj View/SQL tab
A SQL Developer-style object explorer on the left (owner dropdown, type
filter, text filter, tree grouped by object type) -- clicking an object
fetches its DDL via `DBMS_METADATA.GET_DDL` and shows it on the right.
Below it, a read-only **SQL Query Runner**: single-statement `SELECT`
only, capped at 200 rows, CLOBs rendered as text (BLOBs are out of scope).

### Weekly DB Health Report
A **Report** button generates a self-contained HTML report (inline SVG
charts, no external dependencies) covering the trailing N days of the
connected DB's status. Since most of what a report needs comes from `V$`
views with no history behind them, a lightweight snapshot collector runs
every 15 minutes in the background (started as soon as a connection
succeeds, independent of the browser staying open) and appends to an
AES-256-GCM-encrypted local history file -- a tiny, license-free stand-in
for an AWR repository. Clicking Report writes the finished HTML to a
`report/<YYYY-MM-DD>/` folder created next to the running app.

### Favorites
Save a connection's IP/Port/SID/account (password included) to a local,
AES-256-GCM-encrypted store. Clicking a saved favorite on the connect
screen connects immediately, no extra click needed.

### Reducing DB load
The DashBoard tab's data is split into independently-timed auto-refresh
tiers instead of one fixed interval for everything: session list/blocking
sessions every 15s, CPU/memory every 30s, instance info every 5 minutes;
the Ops tab (while it's the active tab) every 5 minutes, and the Tuning
tab (while active) every 10 minutes. All of these pause automatically
while the browser tab is hidden or minimized, and only one tab/window
actually polls if OraPulse is open in more than one at once (leader
election via the Web Locks API) -- catching up immediately once the tab
becomes visible/leader again. On top of that, the server itself caches
(15s) an identical request against the same DB target, so a burst of
near-simultaneous requests (a manual refresh racing an auto-tick, for
example) only actually queries Oracle once.

### Desktop packaging (Windows)
The packaged build runs windowed (no console), with a system tray icon
(Open / Exit) as the only way to bring the window back or quit. A fresh,
OS-assigned free port is picked on every launch (never a fixed port), so
independent launches never collide; a relaunch while an instance is
already up detects it via a small lock file naming the live port --
verified by actually asking that port for `/api/version`, not just
assumed -- and jumps to it instead of starting a second server. The app
window itself opens in a dedicated, isolated Chrome/Edge profile (in
`--app` mode -- no address bar/tabs) with password-saving turned off for
that profile, so Chrome's "Save password?" prompt -- which would
otherwise reappear on every launch, since the port (and therefore the
origin a per-site "don't save" choice is remembered against) changes
every time -- doesn't come up; falls back to the OS default browser if
neither Chrome nor Edge is found.

### Help tab
A built-in, illustrated user manual (bilingual, with real screenshots of
every card) covering every feature above -- no internet connection or
external docs needed, since it's bundled straight into the app. Includes
a search box that highlights every match in the manual and steps through
them (Enter, or the up/down buttons).

### Other
- English / Korean language toggle (persisted; a few labels -- "DashBoard",
  "Obj View/SQL" -- are deliberately kept identical in both languages).
- Dark / Light theme toggle (persisted; pure CSS custom-property swap, no
  re-render needed).

## Requirements

- Oracle Database 12.1 or later. (`VERSION_FULL` in the Instance
  Information card needs 12.2+ to populate; earlier 12.1 instances will
  show a permission-style error on that one card only.)
- Network access from wherever OraPulse runs to the target Oracle
  Listener's host and port.
- No Oracle Instant Client install needed -- `python-oracledb`'s pure-Python
  "thin mode" is used exclusively.

## Project layout

```
orapulse/
├── main.py                 # Entry point: creates the app, registers routes, launches the server
├── backend/                # FastAPI route modules, one file per tab/feature
│   ├── core.py             # Shared infra: app instance, DB connection helper, session store
│   ├── routes_connect.py   # Version, connect/disconnect lifecycle, Favorites, DashBoard's /api/db-status
│   ├── routes_session.py   # Session List row actions (wait detail, view SQL, kill session)
│   ├── routes_table_stats.py  # Table Statistics Collection + Table Properties
│   ├── routes_object_view.py  # Obj View/SQL tab's object explorer
│   ├── routes_sql_runner.py   # Obj View/SQL tab's SQL Query Runner + Cancel
│   ├── routes_tuning.py    # Tuning tab
│   ├── routes_jobs.py      # Scheduler/Job Failures card
│   ├── routes_account_security.py  # Account Security card
│   ├── routes_alert_log.py # Alert Log Analysis
│   ├── routes_ops.py       # Ops tab
│   ├── routes_recovery.py  # Recovery tab
│   └── routes_report.py    # Weekly DB Health Report generation
├── report.py                # Weekly DB Health Report: snapshot collector + HTML renderer
├── favorites.py              # Encrypted local favorites store
├── tuning.py                 # Rule-based Tuning Advisor
├── browser.py               # Opens the isolated browser profile at launch (see Desktop packaging)
├── tray.py                 # Windows system tray icon (packaged build only)
├── paths.py                # Shared path helpers (source run vs. frozen .exe)
├── requirements.txt        # Python dependencies
├── VERSION                 # Plain-text app version (1.NNNN)
├── OraPulse.spec / OraPulse-Folder.spec  # PyInstaller build specs
├── installer.iss           # Inno Setup installer script
├── build.ps1 / build-folder.ps1 / build-installer.ps1  # Build scripts
├── data/                   # Created at runtime: encrypted favorites/snapshots (gitignored)
├── report/                 # Created at runtime: generated report HTML files, by date
├── legacy-nodejs/          # Archived original Node.js/Express implementation (unmaintained, see its own README)
└── public/                 # Browser frontend
    ├── index.html          # Connect screen
    ├── dashboard.html      # The dashboard shell (markup only -- styles/scripts below)
    ├── troubleshooting.html
    ├── favicon.svg / favicon.ico
    ├── images/help/        # Screenshots embedded in the Help tab's user manual
    ├── css/dashboard.css   # All dashboard styling
    └── js/                 # Dashboard scripts, loaded in this order
        ├── i18n.js         # I18N dictionary, t(), applyStaticI18n()
        ├── cards.js        # DashBoard/Ops/Recovery/Tuning/SQL Runner data loading + rendering
        └── app-shell.js    # Tab switching, card drag-and-drop, modals/context menus, Obj View tab, bootstrap
```

## Running from source

```bash
pip install -r requirements.txt
python main.py
```

This picks a free port automatically and opens it in your default browser
(the console output also prints the address, e.g. `http://127.0.0.1:54231`).
Set `PORT=<n>` to pin a specific port instead (mainly useful for
scripting/testing against a known address).

## Building the Windows distributable

```powershell
.\build.ps1             # single-file OraPulse_ver_<version>.exe (PyInstaller --onefile)
.\build-installer.ps1   # also builds the folder distribution and the Inno Setup installer
```

Both read the version from the `VERSION` file. `build-installer.ps1` runs
`build-folder.ps1` first, then compiles `installer.iss` into
`dist\OraPulse-Setup_ver_<version>.exe`, which installs to
`C:\Program Files (x86)\OraPulse_Windows_x86` (requires admin/UAC).

## Installing via MSI (Windows)

A second, independent installer format alongside the Inno Setup one
above: a proper per-machine Windows Installer package, built with the
[WiX Toolset](https://wixtoolset.org/) v3.14.

```powershell
.\build-msi.ps1
```

Requires WiX Toolset v3.14 (`candle.exe`/`light.exe`/`heat.exe`) -- install
it first with `winget install --id WiXToolset.WiXToolset -e` (this needs
the .NET Framework 3.5 Windows feature enabled and admin/UAC approval the
first time). The script never installs WiX itself; it fails with these
same instructions if it can't find it.

`build-msi.ps1` rebuilds the folder distribution fresh (`build-folder.ps1`),
stages it together with `favicon.ico` and a generated
`THIRD-PARTY-NOTICES.txt` (aggregated from this project's own dependencies'
license files), validates every required file is present, has `heat.exe`
harvest `lib/`/`public/` into WiX components, and compiles/links the
result with `candle.exe`/`light.exe`. Output:

```
setup\<version>\OraPulse_ODM_Setup_ver_<version>.msi
```

Intermediate files stay under `setup\<version>\work\`, never scattered
across the repo root. A SHA-256 of both the MSI and the bundled
`OraPulse.exe` is written alongside it, and a handful of read-only checks
(64-bit package, install path, Add/Remove Programs metadata, upgrade
table, silent-install feature list, file count) run automatically against
the built MSI -- see the script's own console output for the full list.

The MSI installs to `C:\Program Files\OraPulse(ODM)` (a real 64-bit
install, never Program Files (x86)), requires administrator privileges (a
per-machine install, same as the Inno installer), registers correctly in
Programs and Features (name, version, publisher, working uninstaller),
creates a Start Menu shortcut, and offers an optional Desktop shortcut. If
OraPulse is running when Setup starts, it's asked to close gracefully
first; if it can't close in time, Windows Installer's own standard
"close these programs" prompt appears instead of anything being force-
killed. Upgrading to a newer MSI automatically removes the old version
first (`UpgradeCode` is fixed forever across every version); installing
an *older* MSI over a newer one is blocked with a clear message. No
reboot is ever required.

Unattended install/uninstall:

```powershell
msiexec /i "OraPulse_ODM_Setup_ver_<version>.msi" /qn
msiexec /x "OraPulse_ODM_Setup_ver_<version>.msi" /qn
```

Neither launches the app or opens a browser. Pass
`ADDLOCAL=MainFeature` to a silent install to skip the optional Desktop
shortcut (default, with no `ADDLOCAL` override, installs it).

This MSI's own 4-part display version (`MSI_VERSION` file at the repo
root, e.g. `1.0.0.1`) is tracked independently from the portable/Inno
builds' `VERSION` file (`1.NNNN` scheme) -- bumping one never affects the
other; edit `MSI_VERSION` by hand before running `build-msi.ps1` again for
a new release. Windows Installer's own `ProductVersion` property can only
hold 3 numeric fields, so the 4-part display version is mapped down by
dropping the *third* field (kept at 0 by convention): `1.0.0.1` becomes
MSI `ProductVersion` `1.0.1`, `1.0.0.2` becomes `1.0.2`, and so on. The
full 4-part version still appears in the installer's filename and in
Programs and Features' "More info" (`ARPCOMMENTS`).

**The existing Inno Setup installer is unaffected** -- this MSI is an
additional option, not a replacement.

## Data storage & privacy

Where OraPulse stores its data depends on how it's running:

- **Running from source, or the portable exe/folder/Inno-installed
  build:** everything lives in a `data/` folder created next to the
  running app (the exe, or `main.py` when run from source) -- exactly as
  before.
- **Installed via the MSI** (see above), which installs to
  `C:\Program Files\OraPulse(ODM)`: a non-admin user can't write there at
  runtime, so a frozen build instead stores everything under
  `%LOCALAPPDATA%\OraPulse\`:
  - `%LOCALAPPDATA%\OraPulse\data\` -- the same files as the portable
    build's `data/` folder (see the list below)
  - `%LOCALAPPDATA%\OraPulse\reports\` -- Weekly DB Health Report output
    (was `report/` next to the exe)
  - `%LOCALAPPDATA%\OraPulse\logs\` -- reserved for future use; nothing
    writes here yet

  If an older portable/Inno-installed copy's `data/`/`report/` folder is
  found next to a newer, frozen build's own exe on first launch, it's
  moved (not copied) into the new `%LOCALAPPDATA%\OraPulse\` location
  automatically -- a one-time, safe migration (any failure along the way
  is logged and simply leaves the old folder exactly where it was, rather
  than risking data loss).

Either way, nothing is ever transmitted anywhere except directly to the
Oracle DB the user connects to:

- `favorites.enc` / `.favorites-key` -- saved connections, AES-256-GCM
- `snapshot-history.jsonl` / `.snapshot-key` -- Weekly Report history
- `tuning-last-snapshot.enc` / `.tuning-key` -- Tuning Advisor's previous check
- `.instance-port` -- the port the currently running instance is
  listening on, used only to detect/redirect to an already-running
  instance on relaunch; not sensitive, safe to delete while the app isn't
  running
- `browser-profile/` -- the dedicated Chrome/Edge profile OraPulse opens
  itself in (see Desktop packaging above); ordinary browser profile data,
  unrelated to Oracle credentials, and likewise safe to delete

Each store uses its own key file and is otherwise self-contained. Deleting
the whole `data/` folder (or `%LOCALAPPDATA%\OraPulse\data\`) removes all
of it and is always safe (each file is recreated empty on next use).

**Uninstalling the MSI leaves `%LOCALAPPDATA%\OraPulse\` in place by
design** (same reasoning as the Inno installer never touching `data/`) --
a reinstall or upgrade picks up right where a previous install left off.
To remove everything, including saved favorites and report history, after
uninstalling: delete `%LOCALAPPDATA%\OraPulse\` by hand, e.g.

```powershell
Remove-Item "$env:LOCALAPPDATA\OraPulse" -Recurse -Force
```

## Known limitations

- Oracle Database 11g and earlier are not supported (thin-mode driver
  limitation).
- `V$INSTANCE.VERSION_FULL` (Instance Information's version display) isn't
  populated on Oracle 12.1 specifically -- that one card shows a
  permission-style error there, though every other feature still works.
- The SQL Query Runner has no bind-variable UI; a query needing one must
  have the literal value inlined by hand. BLOB columns aren't rendered.
- No OS-level host metrics (disk/filesystem free space, CPU load outside
  what Oracle itself reports) -- everything comes from what's reachable
  over the DB connection alone, by design.
- The dedicated-profile/no-password-prompt behavior (see Desktop
  packaging) only applies when Chrome or Edge is installed at one of
  their standard Windows locations; otherwise the app opens in the OS
  default browser instead, without that fix.
- The MSI installer's own setup wizard UI (WiX's standard dialogs) is
  English-only; the installed app itself remains fully bilingual as
  always. It also has no formal end-user license agreement -- the license
  step just links back to this README.
