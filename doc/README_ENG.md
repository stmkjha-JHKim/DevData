# OraPulse

OraPulse is an **Oracle Database monitoring client** that runs directly on a Windows PC. The local application connects directly to an Oracle Database specified by the user, without requiring a central server or account system. Its management interface opens in the default web browser.

![OraPulse Oracle Database connection screen](screenshots/OraPulse-connect.png)

## Key Features

- View instance information, CPU and memory usage, sessions, blocking sessions, long-running sessions, and wait events
- Check table statistics collection status, invalid objects, and the alert log
- Review top SQL statements, instance efficiency, load profiles, key parameters, Undo, TEMP, Redo, and I/O status
- Monitor FRA usage and recent DML activity
- Run read-only queries with the SELECT-only SQL Query Runner
- Switch between Korean and English interfaces
- Store frequently used connection details locally in encrypted form

## System Requirements

- 64-bit Windows 10 or Windows 11
- Oracle Database 12.1 or later
- Network access from the PC to the target Oracle Listener IP address and port
- The Oracle privileges required to view the desired monitoring data

No separate installation of Python, Node.js, or Oracle Instant Client is required.

## Installation and Launch

1. Download `OraPulse_Windows.zip` from the Releases page.
2. Extract the ZIP file to a folder of your choice. Do not run the application directly from inside the ZIP file.
3. Double-click `OraPulse.exe`.
4. The Oracle Database connection screen will open automatically in your default browser.
5. Enter the DB Host/IP, Port, SID/Instance, Oracle account, and password, then select **Start Oracle DB Connection**.

While the application is running, an OraPulse icon appears in the Windows notification area. Select **Open OraPulse** from the icon menu to reopen the interface, or select **Exit** to close the application.

## Windows Security Warning

The current distribution is not digitally signed. As a result, Microsoft Defender SmartScreen may display an “unrecognized app” warning the first time you run it.

Make sure the file was downloaded from the official distribution page, and run it only if its SHA-256 value matches the value below. Do not run files obtained from untrusted sources.

```text
20B3EE8F31FF918F913C2B29C4AA19B36137E0D002A4ECDD6CB07308CEA2A28E  OraPulse.exe
```

To verify the file in PowerShell:

```powershell
Get-FileHash .\OraPulse.exe -Algorithm SHA256
```

## Oracle Database Connection Privileges

OraPulse connects using the Oracle account you provide. Although a standard account can be used, SYSTEM-level read privileges are recommended because most monitoring features query `V$` and `DBA_` views. If the account lacks the required privileges, the affected section will display a permission notice.

Operations that change the database state, such as terminating a session or collecting table statistics, require additional Oracle privileges. These operations are performed only when explicitly initiated by the user through the interface. The SQL Query Runner permits SELECT statements only.

## Privacy and Connection Information

- The application server listens only on `127.0.0.1`, on a free port picked automatically each time it starts, and is not exposed to other computers.
- Database connection details entered in OraPulse are not transmitted to external services.
- When a favorite is saved, its connection details—including the password—are encrypted and stored in the `data` folder next to the executable.
- Saving favorites on a shared or public computer is not recommended. Do not copy or share the `data` folder together with its encryption key.

## Exiting and Uninstalling

Right-click the OraPulse icon in the Windows notification area and select **Exit**. To uninstall OraPulse, exit the application and delete the folder where the ZIP file was extracted. Deleting the `data` folder also removes saved favorites and local history.

## Known Limitations

- Oracle Database 11g and earlier versions are not supported.
- The Check Report feature is not currently included in the Windows executable release.
- Because the executable is not digitally signed, Windows may display a security warning on first launch.

## Support and Bug Reports

Open a new request under the **Issues** tab on the distribution page. Including the following information will help us investigate the issue more quickly:

- OraPulse version
- Windows version
- Oracle Database version
- The screen where the issue occurred and the steps required to reproduce it
- The complete error message or a screenshot that does not reveal the password

Do not submit database passwords, actual internal IP addresses, personal information, or confidential business data.
