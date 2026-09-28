<#
.SYNOPSIS
    Build ObsOverlay.exe with PyInstaller.

.DESCRIPTION
    Creates an isolated build virtual environment, installs the runtime and
    build dependencies into it, regenerates the icon and produces a one-dir
    bundle under packaging/dist/ObsOverlay.

    The venv is deliberately separate from any development environment:
    PyInstaller aborts the build if hooks for two Qt bindings run, so a stray
    PyQt5 or PySide6 in the active environment would break it.

.PARAMETER Clean
    Remove previous build output and the build venv first.

.PARAMETER SkipVenv
    Build with the current interpreter instead of creating a venv. Use this
    only when you know the environment is clean.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File packaging/build.ps1
    powershell -ExecutionPolicy Bypass -File packaging/build.ps1 -Clean
#>
[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$SkipVenv
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$PackagingDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$ProjectRoot = Split-Path -Parent $PackagingDir
$VenvDir = Join-Path $PackagingDir '.buildenv'
$DistDir = Join-Path $PackagingDir 'dist'
$WorkDir = Join-Path $PackagingDir 'build'
$SpecFile = Join-Path $PackagingDir 'ObsOverlay.spec'

function Write-Step([string]$Message) {
    Write-Host ''
    Write-Host "==> $Message" -ForegroundColor Cyan
}

Push-Location $ProjectRoot
try {
    if ($Clean) {
        Write-Step 'Removing previous build output'
        foreach ($path in @($DistDir, $WorkDir, $VenvDir)) {
            if (Test-Path $path) {
                Remove-Item -Recurse -Force $path
                Write-Host "    removed $path"
            }
        }
    }

    if ($SkipVenv) {
        $Python = 'python'
    }
    else {
        if (-not (Test-Path $VenvDir)) {
            Write-Step 'Creating the build virtual environment'
            python -m venv $VenvDir
        }
        $Python = Join-Path $VenvDir 'Scripts\python.exe'
        if (-not (Test-Path $Python)) {
            throw "Build venv is broken: $Python not found. Re-run with -Clean."
        }
    }

    # SpoutGL ships wheels only up to CPython 3.13, and numpy 2.5 needs >= 3.12.
    Write-Step 'Checking the interpreter version'
    $versionInfo = & $Python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    Write-Host "    Python $versionInfo"
    $parts = $versionInfo.Split('.')
    $major = [int]$parts[0]
    $minor = [int]$parts[1]
    if ($major -ne 3 -or $minor -lt 9 -or $minor -gt 13) {
        Write-Warning "Python $versionInfo is outside the tested range (3.9-3.13). SpoutGL has no wheel above 3.13."
    }

    Write-Step 'Installing dependencies'
    & $Python -m pip install --upgrade pip --quiet
    & $Python -m pip install --upgrade ".[build]" --quiet
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }

    Write-Step 'Generating the application icon'
    & $Python (Join-Path $PackagingDir 'make_icon.py')
    if ($LASTEXITCODE -ne 0) { throw 'Icon generation failed.' }

    Write-Step 'Running PyInstaller'
    & $Python -m PyInstaller $SpecFile `
        --noconfirm `
        --distpath $DistDir `
        --workpath $WorkDir
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed.' }

    $ExePath = Join-Path $DistDir 'ObsOverlay\ObsOverlay.exe'
    if (-not (Test-Path $ExePath)) {
        throw "Build reported success but $ExePath is missing."
    }

    # A smoke test that exercises the frozen import graph without opening a
    # window: if a hidden import or a native DLL is missing, this is where it
    # shows up rather than on a user's machine.
    Write-Step 'Smoke-testing the bundle'
    & $ExePath --list-profiles | Out-Null
    if ($LASTEXITCODE -gt 1) {
        throw "The built executable failed to start (exit code $LASTEXITCODE)."
    }

    $size = (Get-ChildItem -Recurse (Join-Path $DistDir 'ObsOverlay') |
        Measure-Object -Property Length -Sum).Sum / 1MB
    Write-Step 'Build complete'
    Write-Host ("    {0}" -f $ExePath) -ForegroundColor Green
    Write-Host ("    bundle size: {0:N1} MB" -f $size)
}
finally {
    Pop-Location
}
