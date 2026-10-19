<#
.SYNOPSIS
注册/卸载「出海合规雷达 · 时效性检查」Windows 计划任务。

.DESCRIPTION
默认按北京时间每天 19:00、22:00 运行 scripts/run_freshness_checks.py。
脚本会把北京时间换算成当前系统时区；若系统时区不是 China Standard Time，
会给出警告（有夏令时的地区，切换季节后触发时间可能偏移）。

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install_freshness_schedule.ps1

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install_freshness_schedule.ps1 -RunNow

.EXAMPLE
powershell -ExecutionPolicy Bypass -File scripts\install_freshness_schedule.ps1 -Uninstall
#>
[CmdletBinding()]
param(
    [string]$RepoPath = "",
    [string]$PythonExe = "",
    [string[]]$Times = @("19:00", "22:00"),
    [switch]$RunNow,
    [switch]$Uninstall
)

$ErrorActionPreference = "Stop"
$TaskName = "ComplianceRadar-Freshness"

# $PSScriptRoot 在部分 Windows PowerShell 调用方式下为空，改用命令路径兜底。
if (-not $RepoPath) {
    $scriptDir = if ($PSScriptRoot) {
        $PSScriptRoot
    } else {
        Split-Path -Parent $MyInvocation.MyCommand.Path
    }
    $RepoPath = Split-Path -Parent $scriptDir
}
$Description = "出海合规雷达：北京时间每天 19:00 / 22:00 核验官方链接与法规元数据"

if ($Uninstall) {
    $existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($existing) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "已卸载计划任务：$TaskName"
    }
    else {
        Write-Host "计划任务不存在：$TaskName"
    }
    exit 0
}

$scriptPath = Join-Path $RepoPath "scripts\run_freshness_checks.py"
if (-not (Test-Path $scriptPath)) {
    throw "找不到总入口：$scriptPath"
}

if (-not $PythonExe) {
    $venvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) {
        $PythonExe = $venvPython
    }
    else {
        $cmd = Get-Command python -ErrorAction SilentlyContinue
        if (-not $cmd) { throw "找不到 python，请用 -PythonExe 指定解释器" }
        $PythonExe = $cmd.Source
    }
}
if (-not (Test-Path $PythonExe)) {
    throw "Python 解释器不存在：$PythonExe"
}

# 北京时间 → 本机时区时间
$beijing = [TimeZoneInfo]::FindSystemTimeZoneById("China Standard Time")
$localZone = [TimeZoneInfo]::Local
$today = Get-Date
$localTimes = @()
foreach ($t in $Times) {
    if ($t -notmatch '^\d{1,2}:\d{2}$') {
        throw "时间格式应为 HH:mm，收到：$t"
    }
    $parts = $t.Split(":")
    $beijingTime = [datetime]::new(
        $today.Year, $today.Month, $today.Day,
        [int]$parts[0], [int]$parts[1], 0,
        [System.DateTimeKind]::Unspecified)
    $utc = [TimeZoneInfo]::ConvertTimeToUtc($beijingTime, $beijing)
    $localTime = [TimeZoneInfo]::ConvertTimeFromUtc($utc, $localZone)
    $localTimes += $localTime.ToString("HH:mm")
}
if ($localZone.Id -ne $beijing.Id) {
    Write-Warning ("系统时区为 {0}，已把北京时间 {1} 换算为本地 {2}；" -f
        $localZone.Id, ($Times -join " / "), ($localTimes -join " / "))
    Write-Warning "有夏令时的地区在切换季节后，本地触发时间可能偏移，请重新运行本脚本。"
}

$triggerList = @()
foreach ($lt in $localTimes) {
    $at = [datetime]::ParseExact($lt, "HH:mm",
        [System.Globalization.CultureInfo]::InvariantCulture)
    $triggerList += New-ScheduledTaskTrigger -Daily -At $at
}

$action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument ('"{0}" --proxy auto' -f $scriptPath) `
    -WorkingDirectory $RepoPath

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 300) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description $Description `
    -Action $action `
    -Trigger $triggerList `
    -Settings $settings `
    -Principal $principal `
    -Force | Out-Null

Write-Host ""
Write-Host "已注册计划任务：$TaskName"
Write-Host ("  北京时间：{0}" -f ($Times -join " / "))
Write-Host ("  本地时间：{0}" -f ($localTimes -join " / "))
Write-Host ("  Python  ：{0}" -f $PythonExe)
Write-Host ("  入口    ：{0}" -f $scriptPath)
Get-ScheduledTaskInfo -TaskName $TaskName |
    Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult |
    Format-List

if ($RunNow) {
    Write-Host "立即运行一次……"
    Start-ScheduledTask -TaskName $TaskName
    Write-Host "已触发；进度见 data\freshness_run_latest.json 与 data\freshness_run_log.jsonl"
}



