param(
    [switch]$SkipTests,
    [switch]$NoClean,
    [switch]$StopRunning,
    [switch]$SmokeTest
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Resolve-WorkspacePath {
    param(
        [string]$Root,
        [string]$RelativePath
    )
    return Join-Path $Root $RelativePath
}

function Remove-WorkspaceItem {
    param(
        [string]$Root,
        [string]$RelativePath,
        [switch]$Recurse
    )

    $target = Resolve-WorkspacePath -Root $Root -RelativePath $RelativePath
    if (-not (Test-Path -LiteralPath $target)) {
        return
    }

    $resolved = (Resolve-Path -LiteralPath $target).Path
    if (-not $resolved.StartsWith($Root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove path outside workspace: $resolved"
    }

    if ($Recurse) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    else {
        Remove-Item -LiteralPath $resolved -Force
    }
}

function Assert-CommandExists {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command '$Name' was not found. Please install it first."
    }
}

function Get-PackagedExecutableProcesses {
    param([string]$ExePath)

    $expectedPath = [System.IO.Path]::GetFullPath($ExePath)
    return @(
        Get-Process -Name "optionsentry-gui" -ErrorAction SilentlyContinue |
            Where-Object {
                try {
                    if (-not $_.Path) {
                        return $true
                    }
                    [System.IO.Path]::GetFullPath($_.Path) -eq $expectedPath
                }
                catch {
                    $false
                }
            }
    )
}

function Stop-PackagedExecutableProcesses {
    param([string]$ExePath)

    $processes = Get-PackagedExecutableProcesses -ExePath $ExePath
    if (-not $processes) {
        return
    }
    $processes | Stop-Process -Force
    $processes | Wait-Process
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$SpecPath = Resolve-WorkspacePath -Root $Root -RelativePath "optionsentry-gui.spec"
$DistPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist"
$ExePath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui.exe"
$ConfigPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\config.toml"
$ExampleConfigPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\config.example.toml"

Write-Step "Checking prerequisites"
Assert-CommandExists "uv"
if (-not (Test-Path -LiteralPath $SpecPath)) {
    throw "PyInstaller spec file not found: $SpecPath"
}

$running = Get-PackagedExecutableProcesses -ExePath $ExePath
if ($running) {
    if (-not $StopRunning) {
        throw "dist\optionsentry-gui.exe is running. Please close it before packaging, or rerun this script with -StopRunning."
    }
    Write-Step "Stopping running packaged executable"
    Stop-PackagedExecutableProcesses -ExePath $ExePath
}

if (-not $SkipTests) {
    Write-Step "Running tests"
    uv run pytest
}
else {
    Write-Step "Skipping tests"
}

if (-not $NoClean) {
    Write-Step "Cleaning previous build output"
    Remove-WorkspaceItem -Root $Root -RelativePath "build" -Recurse
    Remove-WorkspaceItem -Root $Root -RelativePath "dist\optionsentry-gui" -Recurse
    Remove-WorkspaceItem -Root $Root -RelativePath "dist\optionsentry-gui.exe"
    Remove-WorkspaceItem -Root $Root -RelativePath "dist\config.example.toml"
    Remove-WorkspaceItem -Root $Root -RelativePath "dist\optionsentry.zip"
}
else {
    Write-Step "Keeping previous build output"
}

Write-Step "Building one-file executable"
uv run pyinstaller --noconfirm --clean $SpecPath

Write-Step "Verifying package output"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Executable was not generated: $ExePath"
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "External config file was not generated: $ConfigPath"
}
if (-not (Test-Path -LiteralPath $ExampleConfigPath)) {
    throw "Example config file was not generated: $ExampleConfigPath"
}
if (Test-Path -LiteralPath (Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui")) {
    throw "Unexpected one-dir output still exists: dist\optionsentry-gui"
}

if ($SmokeTest) {
    Write-Step "Starting executable smoke test"
    $process = Start-Process -FilePath $ExePath -WorkingDirectory $DistPath -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 10
    $process.Refresh()
    $smokeProcesses = Get-PackagedExecutableProcesses -ExePath $ExePath
    if (-not $smokeProcesses) {
        throw "Smoke test failed: optionsentry-gui.exe exited early with code $($process.ExitCode)."
    }
    Stop-PackagedExecutableProcesses -ExePath $ExePath
    Write-Host "Smoke test passed."
}

Write-Step "Package ready"
Get-ChildItem -LiteralPath $DistPath -File |
    Where-Object { $_.Name -in @("optionsentry-gui.exe", "config.toml", "config.example.toml") } |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize
