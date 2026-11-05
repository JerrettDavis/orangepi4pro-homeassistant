<#
Expose this workstation's Paseo daemon to the Home Assistant add-on without opening any
inbound port here. A logon scheduled task keeps a reverse SSH tunnel to the Orange Pi
(127.0.0.1:$TunnelPort there -> this daemon), and the add-on registers the workstation
as a host through its forwarding-restricted key. Idempotent.
  .\scripts\paseo-ha-workstation-link.ps1 -HaHost jd@homeassistant
#>
param(
    [string]$HaHost = "jd@homeassistant",
    [string]$Label = "jdh-pro-05",
    [string]$Workspace = "G:\git",
    [int]$DaemonPort = 6767,
    [int]$TunnelPort = 16767,
    [string]$TaskName = "paseo-ha-reverse-tunnel"
)
$ErrorActionPreference = "Stop"
$ssh = (Get-Command ssh.exe).Source
$sshArgs = "-N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3 -R 127.0.0.1:${TunnelPort}:127.0.0.1:${DaemonPort} $HaHost"

$loop = "while (`$true) { & '$ssh' $sshArgs; Start-Sleep -Seconds 15 }"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -Command `"$loop`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name='ssh.exe'" | Where-Object { $_.CommandLine -match "-R 127.0.0.1:${TunnelPort}:" } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-ScheduledTask -TaskName $TaskName

# Allow the add-on's restricted key to reach the tunnel port, then register host and workspace.
$remote = @"
set -e
sed -i 's#permitopen="127.0.0.1:$DaemonPort"#permitopen="127.0.0.1:$DaemonPort",permitopen="127.0.0.1:$TunnelPort"#' ~/.ssh/authorized_keys
sed -i 's#\(permitopen="127.0.0.1:$DaemonPort",permitopen="127.0.0.1:$TunnelPort"\),permitopen="127.0.0.1:$TunnelPort"#\1#' ~/.ssh/authorized_keys
C=`$(sudo docker ps --format '{{.Names}}' | grep -E '^app_.*_paseo`$' | head -1)
G=`$(sudo docker exec `$C sh -c "ip route | awk '/default/ {print \`$3; exit}'")
CONN="ssh://`$(id -un)@`$G?daemonPort=$TunnelPort"
for i in 1 2 3 4 5 6; do nc -z 127.0.0.1 $TunnelPort && break; sleep 2; done
nc -z 127.0.0.1 $TunnelPort || { echo 'tunnel not up' >&2; exit 1; }
sudo docker exec `$C paseo host ls --home /data/home/.paseo --json | grep -q '"label": "$Label"' || \
  sudo docker exec `$C paseo host add "`$CONN" --label $Label --meta platform=windows --meta labels=windows,x64,bare-metal --home /data/home/.paseo
sudo docker exec `$C paseo --host "`$CONN" project create '$Workspace' --json >/dev/null
sleep 5
sudo docker exec `$C paseo host ls --home /data/home/.paseo
"@
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote.Replace("`r", "")))
ssh $HaHost "echo $b64 | base64 -d | bash"
