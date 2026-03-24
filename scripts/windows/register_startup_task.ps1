param(
    [string]$TaskName = "JiraTelegramBot",
    [string]$RepoRoot = "",
    [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

if ([string]::IsNullOrWhiteSpace($RepoRoot)) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
}

$runBat = Join-Path $RepoRoot "run_bot.bat"
if (-not (Test-Path $runBat)) {
    throw "Không tìm thấy file run_bot.bat tại: $runBat"
}

# Truyền PYTHON_EXE vào môi trường process của task để run_bot.bat ưu tiên dùng đúng interpreter.
$taskCommand = "set ""PYTHON_EXE=$PythonExe"" && `"$runBat`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c $taskCommand" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType S4U -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Khởi động Jira Telegram Bot khi bật máy." `
    -Force

Write-Host "Đã đăng ký task '$TaskName'."
Write-Host "RepoRoot : $RepoRoot"
Write-Host "PythonExe: $PythonExe"
Write-Host "Để chạy thử ngay: Start-ScheduledTask -TaskName `"$TaskName`""
