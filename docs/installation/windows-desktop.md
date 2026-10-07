# ImageDupe for Windows

## Install and use

Supported target: Windows 10/11, x64. Download `ImageDupe-Setup.exe`, run the installer, and open ImageDupe using the desktop or Start menu shortcut. Installation is per-user in `%USERPROFILE%\Applications\ImageDupe` and does not require administrator access. The program bundles Python, NumPy, SciPy, Pillow, FastAPI, SQLite, and the Qt WebEngine desktop renderer; nothing is downloaded when you run it.

1. ImageDupe opens its own desktop window; its private backend runs locally.
2. Opening the shortcut again brings the existing window forward.
3. Choose **Image folders → Add image folder → Choose folder…**.
4. Select your local image folder and choose **Add folder & scan images**. Scanning and search preparation happen automatically.
5. Choose **Search this folder**, select a reference image, and search. The default 60% minimum fingerprint similarity filters weaker results.
6. Close the window to stop ImageDupe. If a scan is running, the app asks before cancelling it.

The folder picker appears inside the app window. Cancel leaves the current path unchanged. Manual folder paths remain supported. Images are read-only; collection removal and uninstall do not delete original images.

## Storage, upgrades, and uninstall

New desktop installations store catalogs, indexes, and thumbnails in `%LOCALAPPDATA%\ImageDupe\data`, outside the program installation directory. If an existing CLI catalog is found at `%USERPROFILE%\.local\share\imagedupe\catalog.sqlite3`, the desktop app reuses that catalog. `IMAGEDUPE_HOME` remains an explicit override.

Close ImageDupe before installing an update. For versions installed under AppData, uninstall the old program first, then run the new installer; saved collection data and photos are preserved. Later updates install over the application in the Applications folder. Close the window, then uninstall using Windows Settings or the Start menu shortcut. Uninstall removes the application and shortcuts while preserving collection data and original photos. Logs are in the `logs` directory next to the chosen data directory.

Portable use: extract **all** files from `ImageDupe-Portable.zip`, then run `ImageDupe\ImageDupe.exe`. Do not move the EXE away from its `_internal` folder. Portable mode uses the same per-user data location.

The installer is unsigned. Windows may show an unknown-publisher/SmartScreen prompt; this release does not claim Microsoft publisher verification. Verify the SHA-256 checksum and obtain the download from the project's own release. Paid signing is not required to build or use this application.

## Build on Windows

Build prerequisites: Python 3.12 x64, PowerShell, and the free NSIS compiler. Build dependencies are downloaded during development; users do not need these tools.

From the project directory:

```powershell
powershell -ExecutionPolicy Bypass -File packaging\windows\build.ps1
```

For a portable NSIS compiler, pass `-MakeNsis C:\path\to\makensis.exe`.

The build script creates an isolated `.build-venv`, installs the recorded CPU dependencies, compiles a windowed PyInstaller bundle, runs the **actual bundled EXE's self-test**, compiles and validates the installer in an isolated directory, and writes:

- `release/ImageDupe-Setup.exe`
- `release/ImageDupe-Portable.zip`
- SHA-256 files for both downloads
- `release/self-test.json`

A Windows build is required; PyInstaller does not cross-compile Windows executables from Linux. Multiprocessing `freeze_support()` runs before application imports so image hashing workers do not relaunch the desktop UI.

The bundled self-test checks the real embedded Qt UI, the window icon, native folder/export dialog bridges, packaged UI assets, authenticated loopback APIs, image scanning using spawned workers, index construction, search, and thumbnails. Test data is temporary and does not touch personal collections.

## GitHub release downloads

Commit the source and packaging scripts; do not commit `.build-venv`, `build`, `dist`, or `release`. The **Windows offline application** Actions workflow runs manually or when a `v*` tag is pushed. It builds and tests on a Windows runner and attaches the resulting files as a workflow artifact. Upload the EXE, ZIP, and checksums to a GitHub Release to create public download links. The workflow does not automatically publish a release.

For public repositories, standard GitHub-hosted Actions runner usage is free within GitHub's applicable service limits. No server runs after the installer is downloaded.

## Release checks

Before a broad public release, verify interactive installation, folder selection, scan/search, restart persistence, and uninstall on a clean Windows 10/11 x64 PC or VM with no Python installed. The automated installer test can use `/S /TEST /D=C:\temporary\ImageDupe` to avoid shortcuts and registry entries; `/D` must be the last argument. The `/TEST` flag is for isolated packaging validation, not normal installation.

Android is not included in this release. It needs its own storage-permission and packaging work.

## Desktop dependencies

For source development, install `pip install ".[desktop]"`, then run `imagedupe-desktop`. The CLI and server do not require Qt. Qt WebEngine is bundled in both downloads, so users do not need Chrome, Python, or a separately installed WebView runtime. This makes the downloads larger than the previous browser launcher.

Qt/PySide6 uses its open-source LGPL license; its libraries remain separate, replaceable files under `_internal`. Dependency notices are included under `_internal/licenses`. Qt source and license information: https://www.qt.io/qt-for-python and https://code.qt.io/cgit/pyside/pyside-setup.git/ (v6.8.3); Qt sources: https://download.qt.io/archive/qt/6.8/6.8.3/single/.

## Display recovery and shortcuts

Version 1.1.1 defaults to Windows software rendering for the photo interface, avoiding dependence on GPU acceleration. The renderer sandbox remains enabled. If the display fails, a single recovery screen offers **Try again**; renderer exit details are written to `desktop.log`. The backend and saved collection data remain separate from the display. Developers can opt into GPU rendering with `IMAGEDUPE_RENDER_MODE=hardware`.

The installer includes a dedicated overlapping-photo icon and sets the desktop and Start menu shortcuts to use it explicitly, then asks Windows to refresh icons. It tests normal GUI startup from the installation directory as well as backend scan/search and export functions.

The application installs outside AppData to avoid inherited AppContainer permissions that can block the sandboxed renderer from loading DLLs (Windows exit code 0xC0000135). This changes only where program files live. Catalogs, images, system permissions and renderer sandbox settings are preserved. Older default AppData installations are offered the new application location on upgrade; custom installation folders remain supported.
