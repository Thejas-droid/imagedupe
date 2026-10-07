param([string]$MakeNsis = "makensis")
$ErrorActionPreference = "Stop"
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
Push-Location $projectRoot
try {
    if (!(Test-Path ".build-venv\Scripts\python.exe")) {
        py -3.12 -m venv .build-venv
        if ($LASTEXITCODE -ne 0) { throw "Install Python 3.12 x64 to build ImageDupe." }
    }
    $buildPython = Join-Path $projectRoot ".build-venv\Scripts\python.exe"
    & $buildPython -m pip install -r requirements.lock pyinstaller==6.16.0 PySide6==6.8.3 wheel
    if ($LASTEXITCODE -ne 0) { throw "Build dependency installation failed." }
    & $buildPython -m pip install . --no-deps
    if ($LASTEXITCODE -ne 0) { throw "Application installation failed." }
    & $buildPython packaging/windows/test_launcher.py
    if ($LASTEXITCODE -ne 0) { throw "Windows launcher lifecycle test failed." }
    & $buildPython -m PyInstaller --noconfirm --clean packaging/windows/imagedupe.spec
    if ($LASTEXITCODE -ne 0) { throw "Executable build failed." }
    New-Item -ItemType Directory -Force release | Out-Null
    $process = Start-Process -FilePath "$projectRoot\dist\ImageDupe\ImageDupe.exe" -ArgumentList '--self-test', '--report', 'release\self-test.json' -PassThru
    if (!$process.WaitForExit(180000)) { $process.Kill(); throw "Packaged self-test timed out." }
    if ($process.ExitCode -ne 0) { throw "Packaged self-test failed. Read release/self-test.json." }
    $result = Get-Content release/self-test.json -Raw | ConvertFrom-Json
    if (!$result.ok) { throw "Packaged self-test did not pass." }
    $probeDirectory = Join-Path $projectRoot "release\probe-data"
    $previousHome = $env:IMAGEDUPE_HOME
    try {
        $env:IMAGEDUPE_HOME = $probeDirectory
        $probeReport = Join-Path $projectRoot "release\window-test.json"
        $process = Start-Process -FilePath "$projectRoot\dist\ImageDupe\ImageDupe.exe" -WorkingDirectory "$projectRoot\dist\ImageDupe" -ArgumentList '--window-test', '--report', "`"$probeReport`"" -PassThru
        if (!$process.WaitForExit(90000)) { $process.Kill(); throw "Desktop startup test timed out." }
        if ($process.ExitCode -ne 0) { throw "Desktop startup test failed. Read release/window-test.json." }
    } finally {
        $env:IMAGEDUPE_HOME = $previousHome
        Remove-Item -Recurse -Force $probeDirectory -ErrorAction SilentlyContinue
    }
    $nsis = Get-Command $MakeNsis -ErrorAction SilentlyContinue
    if (!$nsis) {
        $installed = "${env:ProgramFiles(x86)}\NSIS\makensis.exe"
        if (!(Test-Path $installed)) { throw "Install NSIS (free), then rerun this script with -MakeNsis pointing to makensis.exe." }
        $MakeNsis = $installed
    }
    & $MakeNsis /V2 packaging/windows/installer.nsi
    if ($LASTEXITCODE -ne 0) { throw "Installer build failed." }
    & $buildPython packaging/windows/test_installer.py
    if ($LASTEXITCODE -ne 0) { throw "Installer validation failed." }
    Compress-Archive -Path dist/ImageDupe -DestinationPath release/ImageDupe-Portable.zip -Force
    Get-ChildItem release -File | Where-Object { $_.Extension -in '.exe','.zip' } | ForEach-Object {
        $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower()
        "$hash  $($_.Name)" | Set-Content "$($_.FullName).sha256" -Encoding ascii
    }
    Write-Host "Ready: release/ImageDupe-Setup.exe and release/ImageDupe-Portable.zip"
} finally { Pop-Location }
