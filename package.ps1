param(
    [switch]$SkipTests,
    [switch]$NoClean,
    [switch]$StopRunning,
    [switch]$SmokeTest,
    [string]$SignThumbprint = "",
    [string]$TimestampUrl = "http://timestamp.digicert.com"
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

function Assert-IsWorkspacePath {
    param(
        [string]$Root,
        [string]$Path
    )

    $rootPath = [System.IO.Path]::GetFullPath($Root).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
    $candidatePath = [System.IO.Path]::GetFullPath($Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)

    if ($candidatePath -ne $rootPath -and -not $candidatePath.StartsWith("$rootPath$([System.IO.Path]::DirectorySeparatorChar)", [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to operate on path outside workspace: $candidatePath"
    }
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
    Assert-IsWorkspacePath -Root $Root -Path $resolved

    if ($Recurse) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
    else {
        Remove-Item -LiteralPath $resolved -Force
    }
}

function Remove-WorkspaceItemsByFilter {
    param(
        [string]$Root,
        [string]$DirectoryRelativePath,
        [string]$Filter
    )

    $directory = Resolve-WorkspacePath -Root $Root -RelativePath $DirectoryRelativePath
    if (-not (Test-Path -LiteralPath $directory)) {
        return
    }

    $resolvedDirectory = (Resolve-Path -LiteralPath $directory).Path
    Assert-IsWorkspacePath -Root $Root -Path $resolvedDirectory

    Get-ChildItem -LiteralPath $resolvedDirectory -Filter $Filter -Force |
        ForEach-Object {
            Assert-IsWorkspacePath -Root $Root -Path $_.FullName
            Remove-Item -LiteralPath $_.FullName -Recurse:$_.PSIsContainer -Force
        }
}

function Assert-CommandExists {
    param([string]$Name)
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Command '$Name' was not found. Please install it first."
    }
}

function Get-ProjectVersion {
    param([string]$PyprojectPath)

    $content = Get-Content -LiteralPath $PyprojectPath -Raw
    if ($content -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
        throw "Could not find project version in $PyprojectPath"
    }
    return $Matches[1]
}

function Get-PackagedExecutableProcesses {
    param([string[]]$ExePath)

    $expectedPaths = @($ExePath | ForEach-Object { [System.IO.Path]::GetFullPath($_) })
    return @(
        Get-Process -Name "optionsentry-gui" -ErrorAction SilentlyContinue |
            Where-Object {
                try {
                    if (-not $_.Path) {
                        return $true
                    }
                    $processPath = [System.IO.Path]::GetFullPath($_.Path)
                    $expectedPaths -contains $processPath
                }
                catch {
                    $false
                }
            }
    )
}

function Stop-PackagedExecutableProcesses {
    param([string[]]$ExePath)

    $processes = Get-PackagedExecutableProcesses -ExePath $ExePath
    if (-not $processes) {
        return
    }
    $processes | Stop-Process -Force
    $processes | Wait-Process
}

function Write-SignatureStatus {
    param([string]$ExePath)

    $signature = Get-AuthenticodeSignature -LiteralPath $ExePath
    Write-Host "Signature status: $($signature.Status)"
    if ($signature.SignerCertificate) {
        Write-Host "Signer: $($signature.SignerCertificate.Subject)"
    }
}

function Invoke-CodeSigning {
    param(
        [string]$ExePath,
        [string]$Thumbprint,
        [string]$TimestampUrl
    )

    if ([string]::IsNullOrWhiteSpace($Thumbprint)) {
        Write-Step "Skipping code signing"
        Write-SignatureStatus -ExePath $ExePath
        return
    }

    Write-Step "Signing executable"
    Assert-CommandExists "signtool"
    & signtool sign /fd SHA256 /sha1 $Thumbprint /tr $TimestampUrl /td SHA256 $ExePath
    if ($LASTEXITCODE -ne 0) {
        throw "signtool failed with exit code $LASTEXITCODE."
    }
    Write-SignatureStatus -ExePath $ExePath
}

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$SpecPath = Resolve-WorkspacePath -Root $Root -RelativePath "optionsentry-gui.spec"
$PyprojectPath = Resolve-WorkspacePath -Root $Root -RelativePath "pyproject.toml"
$ProjectVersion = Get-ProjectVersion -PyprojectPath $PyprojectPath
$PackageBaseName = "OptionSentry-v$ProjectVersion-windows-x64"
$DistPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist"
$OnedirPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui"
$ExePath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui\optionsentry-gui.exe"
$LegacyExePath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui.exe"
$ConfigPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui\config.toml"
$ExampleConfigPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\optionsentry-gui\config.example.toml"
$StagingPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\$PackageBaseName"
$ZipPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\$PackageBaseName.zip"
$HashPath = Resolve-WorkspacePath -Root $Root -RelativePath "dist\$PackageBaseName.zip.sha256.txt"

Write-Step "Checking prerequisites"
Assert-CommandExists "uv"
if (-not (Test-Path -LiteralPath $SpecPath)) {
    throw "PyInstaller spec file not found: $SpecPath"
}

$packagedExecutablePaths = @($ExePath, $LegacyExePath)
$running = Get-PackagedExecutableProcesses -ExePath $packagedExecutablePaths
if ($running) {
    if (-not $StopRunning) {
        throw "A packaged optionsentry-gui.exe is running. Please close it before packaging, or rerun this script with -StopRunning."
    }
    Write-Step "Stopping running packaged executable"
    Stop-PackagedExecutableProcesses -ExePath $packagedExecutablePaths
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
    Remove-WorkspaceItem -Root $Root -RelativePath "dist\$PackageBaseName" -Recurse
    Remove-WorkspaceItemsByFilter -Root $Root -DirectoryRelativePath "dist" -Filter "OptionSentry-v*-windows-x64.zip"
    Remove-WorkspaceItemsByFilter -Root $Root -DirectoryRelativePath "dist" -Filter "OptionSentry-v*-windows-x64.zip.sha256.txt"
}
else {
    Write-Step "Keeping previous build output"
}

Write-Step "Building one-dir executable"
uv run pyinstaller --noconfirm --clean $SpecPath

Write-Step "Verifying package output"
if (-not (Test-Path -LiteralPath $ExePath)) {
    throw "Executable was not generated: $ExePath"
}
if (Test-Path -LiteralPath $LegacyExePath) {
    throw "Unexpected root-level one-file executable still exists: $LegacyExePath"
}
if (-not (Test-Path -LiteralPath $ConfigPath)) {
    throw "External config file was not generated: $ConfigPath"
}
if (-not (Test-Path -LiteralPath $ExampleConfigPath)) {
    throw "Example config file was not generated: $ExampleConfigPath"
}

Invoke-CodeSigning -ExePath $ExePath -Thumbprint $SignThumbprint -TimestampUrl $TimestampUrl

if ($SmokeTest) {
    Write-Step "Starting executable smoke test"
    $process = Start-Process -FilePath $ExePath -WorkingDirectory $OnedirPath -PassThru -WindowStyle Hidden
    Start-Sleep -Seconds 10
    $process.Refresh()
    $smokeProcesses = Get-PackagedExecutableProcesses -ExePath $ExePath
    if (-not $smokeProcesses) {
        throw "Smoke test failed: optionsentry-gui.exe exited early with code $($process.ExitCode)."
    }
    Stop-PackagedExecutableProcesses -ExePath $ExePath
    Write-Host "Smoke test passed."
}

Write-Step "Creating versioned zip package"
Remove-WorkspaceItem -Root $Root -RelativePath "dist\$PackageBaseName" -Recurse
Remove-WorkspaceItem -Root $Root -RelativePath "dist\$PackageBaseName.zip"
Remove-WorkspaceItem -Root $Root -RelativePath "dist\$PackageBaseName.zip.sha256.txt"
New-Item -ItemType Directory -Path $StagingPath | Out-Null
Get-ChildItem -LiteralPath $OnedirPath -Force |
    Copy-Item -Destination $StagingPath -Recurse -Force
Compress-Archive -LiteralPath $StagingPath -DestinationPath $ZipPath -Force

$zipHash = Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256
Set-Content -LiteralPath $HashPath -Value "$($zipHash.Hash)  $(Split-Path -Leaf $ZipPath)" -Encoding ascii
Remove-WorkspaceItem -Root $Root -RelativePath "dist\$PackageBaseName" -Recurse

Write-Step "Package ready"
Get-ChildItem -LiteralPath $OnedirPath -File |
    Where-Object { $_.Name -in @("optionsentry-gui.exe", "config.toml", "config.example.toml") } |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize
Get-ChildItem -LiteralPath $DistPath -File |
    Where-Object { $_.Name -in @("$PackageBaseName.zip", "$PackageBaseName.zip.sha256.txt") } |
    Select-Object Name, Length, LastWriteTime |
    Format-Table -AutoSize
