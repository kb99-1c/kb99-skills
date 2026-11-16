<#
.SYNOPSIS
    Обращение к REST API Redmine (redmine.kb99.pro): справочные запросы и создание задач.

.DESCRIPTION
    Ключ берется из переменной REDMINE_API_KEY: сначала из окружения процесса,
    затем из окружения пользователя Windows (после setx процесс, запущенный раньше,
    ключа не видит). Ключ не выводится.

    Создание задач разрешено только в проекте v8_dev_vetis.

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Redmine.ps1 -Get trackers

.EXAMPLE
    powershell -NoProfile -ExecutionPolicy Bypass -File Redmine.ps1 -NewIssue C:\tmp\issue-1.json -WhatIf
#>
[CmdletBinding(SupportsShouldProcess = $true, DefaultParameterSetName = 'Get')]
param(
    # Путь API без .json, со строкой запроса или без, например: trackers,
    # projects/v8_dev_vetis/memberships, issues/123?include=children, issues?parent_id=123
    [Parameter(Mandatory = $true, ParameterSetName = 'Get')]
    [string]$Get,

    # JSON-файл в формате Redmine: {"issue": {"project_id": "v8_dev_vetis", "subject": "...", ...}}
    [Parameter(Mandatory = $true, ParameterSetName = 'NewIssue')]
    [string]$NewIssue
)

$ErrorActionPreference = 'Stop'
$BaseUrl = 'https://redmine.kb99.pro'
$AllowedProjects = @('v8_dev_vetis', '285')

[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$ApiKey = $env:REDMINE_API_KEY
if (-not $ApiKey) {
    $ApiKey = [Environment]::GetEnvironmentVariable('REDMINE_API_KEY', 'User')
}
if (-not $ApiKey) {
    throw 'REDMINE_API_KEY не задан ни в окружении процесса, ни в окружении пользователя.'
}
$Headers = @{ 'X-Redmine-API-Key' = $ApiKey }

function Invoke-Redmine {
    param([string]$Method, [string]$Url, [byte[]]$Body)
    try {
        $Params = @{ Method = $Method; Uri = $Url; Headers = $Headers; UseBasicParsing = $true }
        if ($Body) {
            $Params.Body = $Body
            $Params.ContentType = 'application/json; charset=utf-8'
        }
        $Response = Invoke-WebRequest @Params
        $Reader = New-Object System.IO.StreamReader($Response.RawContentStream, [Text.Encoding]::UTF8)
        return $Reader.ReadToEnd()
    }
    catch [System.Net.WebException] {
        $Status = [int]$_.Exception.Response.StatusCode
        $ErrorText = ''
        if ($_.Exception.Response) {
            $Reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream(), [Text.Encoding]::UTF8)
            $ErrorText = $Reader.ReadToEnd()
        }
        throw "Redmine вернул HTTP $Status на $Method $Url. $ErrorText"
    }
}

if ($PSCmdlet.ParameterSetName -eq 'Get') {
    # .json вставляется перед строкой запроса: issues/1?include=children -> issues/1.json?include=children
    $Parts = $Get.Split([char[]]'?', 2)
    $Path = $Parts[0].Trim('/') -replace '\.json$', ''
    $Query = ''
    if ($Parts.Count -eq 2 -and $Parts[1]) { $Query = '?' + $Parts[1] }
    Invoke-Redmine -Method GET -Url "$BaseUrl/$Path.json$Query"
    return
}

# Файл читается через ReadAllText (снимает BOM) и отправляется байтами UTF-8 без BOM:
# строковое тело в PowerShell 5.1 портит кириллицу.
$Text = [IO.File]::ReadAllText((Resolve-Path $NewIssue), [Text.Encoding]::UTF8)
$Issue = ($Text | ConvertFrom-Json).issue
if (-not $Issue) { throw 'В файле нет корневого объекта "issue".' }
if ($AllowedProjects -notcontains [string]$Issue.project_id) {
    throw "project_id '$($Issue.project_id)' не разрешен. Допустимо: $($AllowedProjects -join ', ')."
}
if (-not $Issue.subject) { throw 'Не заполнено поле subject.' }

$Summary = "project=$($Issue.project_id) tracker_id=$($Issue.tracker_id) subject='$($Issue.subject)'"
if (-not $PSCmdlet.ShouldProcess($Summary, 'Создать задачу в Redmine')) {
    return
}

$Body = (New-Object System.Text.UTF8Encoding($false)).GetBytes($Text)
$Created = (Invoke-Redmine -Method POST -Url "$BaseUrl/issues.json" -Body $Body | ConvertFrom-Json).issue
"#$($Created.id) $($Created.subject)"
"$BaseUrl/issues/$($Created.id)"
