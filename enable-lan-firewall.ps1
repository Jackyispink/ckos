param([switch]$Remove)
$ErrorActionPreference = 'Stop'
$ruleName = 'CKOS-LAN-8000'
if ($Remove) {
    Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue | Remove-NetFirewallRule
    Write-Host 'CKOS LAN firewall rule removed.'
    return
}
if (Get-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue) {
    throw 'CKOS rule already exists. Inspect it, or remove it with -Remove before recreating.'
}
New-NetFirewallRule -Name $ruleName -DisplayName 'CKOS trusted LAN TCP 8000' -Direction Inbound -Action Allow -Protocol TCP -LocalPort 8000 -RemoteAddress LocalSubnet -Profile Private -Program 'D:\yidui\miniconda\envs\ckos\python.exe' | Out-Null
Write-Host 'Allowed CKOS TCP 8000 from the local subnet on Private networks only.'
