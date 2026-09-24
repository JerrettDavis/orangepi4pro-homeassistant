# PowerShell 7 wrapper. Native Linux/WSL is required for appliance/image operations.
$ErrorActionPreference = 'Stop'
$cli = Join-Path $PSScriptRoot 'opiha'
if (Get-Command python -ErrorAction SilentlyContinue) {
    & python $cli @args
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
    & py -3 $cli @args
} else {
    throw 'Python 3.10+ was not found. Use WSL or install Python with tzdata.'
}
exit $LASTEXITCODE
