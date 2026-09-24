[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$SourceShare,
    [Parameter(Mandatory)][string]$Destination,
    [Parameter(Mandatory)][switch]$SourceStopped
)
$ErrorActionPreference = 'Stop'
if (-not $SourceStopped) { throw 'Stop HA Core before a raw copy. A Hyper-V VHDX is not a config directory.' }
if (-not (Test-Path (Join-Path $SourceShare 'configuration.yaml'))) { throw 'SourceShare must expose the HA /config directory.' }
if (Test-Path $Destination) { throw 'Destination already exists. Choose a new empty private directory.' }
New-Item -ItemType Directory -Path $Destination | Out-Null
& robocopy $SourceShare $Destination /E /COPY:DAT /DCOPY:DAT /XJ /R:1 /W:1 /XD deps __pycache__ /XF '*.pyc' '*.pyo' 'home-assistant.log*'
$copyExit = $LASTEXITCODE
if ($copyExit -ge 8) { throw "Robocopy failed with exit code $copyExit" }
if (-not (Test-Path (Join-Path $Destination '.storage'))) { throw 'Export is missing .storage. Verify share permissions and hidden files.' }
Write-Output "Private config exported to $Destination. Keep it out of Git; include all external database/add-on state separately."
exit 0
