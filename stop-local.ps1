$ErrorActionPreference = 'SilentlyContinue'
foreach ($port in 5000, 5173) {
    $listeners = Get-NetTCPConnection -LocalPort $port -State Listen
    foreach ($listener in $listeners) {
        Stop-Process -Id $listener.OwningProcess -Force
    }
}
Write-Output 'AttendEase services stopped.'
