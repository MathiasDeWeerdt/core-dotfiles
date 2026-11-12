# expose winenum — read-only low-privilege Windows enumeration.
# Authorized assessments only. This script changes nothing.
$ErrorActionPreference = 'SilentlyContinue'
$ProgressPreference = 'SilentlyContinue'
$findings = New-Object System.Collections.Generic.List[string]
$report = Join-Path $env:TEMP ("expose-winenum-{0}-{1}.txt" -f $env:COMPUTERNAME, (Get-Date -Format 'yyyyMMdd-HHmmss'))
$transcript = $false
try { Start-Transcript -Path $report -Force | Out-Null; $transcript = $true } catch {}

function Section([string]$title) {
    Write-Host "`n===== $title =====" -ForegroundColor Cyan
}
function Note([string]$text) {
    Write-Host "  $text" -ForegroundColor DarkGray
}
function Candidate([string]$text) {
    $findings.Add($text) | Out-Null
    Write-Host "  [!] $text" -ForegroundColor Yellow
}
function Exists([string]$path) {
    return (Test-Path -LiteralPath $path -ErrorAction SilentlyContinue)
}
function WritableByUser([string]$path) {
    if (-not (Exists $path)) { return }
    $acl = Get-Acl -LiteralPath $path -ErrorAction SilentlyContinue
    if (-not $acl) { return }
    foreach ($rule in $acl.Access) {
        if ($rule.AccessControlType -ne 'Allow') { continue }
        if ($rule.FileSystemRights -notmatch 'Write|Modify|FullControl') { continue }
        if ($rule.IdentityReference -match 'Users|Everyone|Authenticated Users' -or
            $rule.IdentityReference.Value -eq ([Security.Principal.WindowsIdentity]::GetCurrent().Name)) {
            Write-Host "  $path -> $($rule.IdentityReference) : $($rule.FileSystemRights)"
        }
    }
}

Section 'Identity and token'
whoami /all
Note "Computer: $env:COMPUTERNAME"
Note "User: $env:USERDOMAIN\$env:USERNAME"
Note "Identity: $([Security.Principal.WindowsIdentity]::GetCurrent().Name)"
Note "PowerShell: $($PSVersionTable.PSVersion)"
Note "Language mode: $($ExecutionContext.SessionState.LanguageMode)"

Section 'Dangerous token privileges'
$danger = 'SeImpersonatePrivilege','SeAssignPrimaryTokenPrivilege','SeBackupPrivilege',
          'SeRestorePrivilege','SeDebugPrivilege','SeTakeOwnershipPrivilege',
          'SeLoadDriverPrivilege','SeCreateTokenPrivilege','SeTcbPrivilege',
          'SeManageVolumePrivilege'
$privs = whoami /priv
$privs | Select-String $danger
foreach ($name in $danger) {
    if ($privs -match $name) { Candidate "Token privilege present: $name" }
}

Section 'Host and patch level'
Get-CimInstance Win32_OperatingSystem |
    Select-Object Caption,Version,BuildNumber,OSArchitecture,LastBootUpTime,InstallDate
Get-CimInstance Win32_ComputerSystem |
    Select-Object Name,Domain,PartOfDomain,Manufacturer,Model,TotalPhysicalMemory
Get-CimInstance Win32_BIOS | Select-Object SerialNumber,SMBIOSBIOSVersion,ReleaseDate
Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors
Get-HotFix | Sort-Object InstalledOn -Descending | Select-Object -First 20 HotFixID,Description,InstalledOn
Get-MpComputerStatus | Select-Object AMEnabled,RealTimeProtectionEnabled,AntivirusEnabled,AntispywareEnabled,BehaviorMonitorEnabled

Section 'Network'
ipconfig /all
route print
arp -a
Get-NetTCPConnection -State Listen | Sort-Object LocalPort |
    Select-Object LocalAddress,LocalPort,OwningProcess,
        @{n='Process';e={(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName}}
Get-NetUDPEndpoint | Sort-Object LocalPort | Select-Object LocalAddress,LocalPort,OwningProcess
Get-DnsClientServerAddress
net use
Get-SmbMapping
netsh winhttp show proxy
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Internet Settings' |
    Select-Object ProxyEnable,ProxyServer,AutoConfigURL

Section 'Users, groups, domain'
net user
net localgroup
net localgroup administrators
Get-LocalUser | Select-Object Name,Enabled,LastLogon,Description
Get-LocalGroupMember -Group Administrators
net config workstation
nltest /dsgetdc:$env:USERDNSDOMAIN
nltest /domain_trusts
net group /domain
net group "Domain Admins" /domain
net group "Enterprise Admins" /domain
gpresult /r
if (Get-Module -ListAvailable ActiveDirectory) {
    Import-Module ActiveDirectory
    Get-ADDomain | Select-Object DNSRoot,NetBIOSName,DomainMode
    (Get-ADUser $env:USERNAME -Properties MemberOf).MemberOf
    Get-ADGroupMember 'Domain Admins' | Select-Object SamAccountName,Name,objectClass
    Get-ADGroupMember 'Enterprise Admins' | Select-Object SamAccountName,Name,objectClass
}

Section 'Sessions and logons'
quser
query session
Get-CimInstance Win32_LogonSession | Select-Object LogonId,LogonType,StartTime
Get-CimInstance Win32_LoggedOnUser | Select-Object Antecedent,Dependent

Section 'Services'
$services = Get-CimInstance Win32_Service |
    Select-Object Name,DisplayName,State,StartMode,StartName,PathName
$services | Format-Table -AutoSize
Write-Host "`n-- Unquoted service paths"
$unquoted = $services | Where-Object { $_.PathName -match '^[^"].*\.exe\s' }
$unquoted | Select-Object Name,PathName | Format-Table -AutoSize
foreach ($service in $unquoted) {
    Candidate "Unquoted service path: $($service.Name) -> $($service.PathName)"
}
Write-Host "`n-- Service files or directories writable by this user"
foreach ($service in $services) {
    if (-not $service.PathName) { continue }
    $exe = $null
    if ($service.PathName -match '^"([^"]+)"') { $exe = $matches[1] }
    elseif ($service.PathName -match '^(\S+\.exe)') { $exe = $matches[1] }
    if (-not $exe) { continue }
    if (Exists $exe) { WritableByUser $exe }
    $dir = Split-Path -Parent $exe
    if ($dir -and (Exists $dir)) { WritableByUser $dir }
}
Write-Host "`n-- Raw service ACLs for non-Windows services"
foreach ($service in $services | Where-Object { $_.PathName -and $_.PathName -notmatch 'C:\\Windows\\' }) {
    Write-Host "`n$($service.Name)"
    sc.exe sdshow $service.Name
}

Section 'Scheduled tasks'
Get-ScheduledTask | Select-Object TaskPath,TaskName,State,Author | Sort-Object TaskPath,TaskName
foreach ($task in Get-ScheduledTask) {
    foreach ($action in $task.Actions) {
        if ($action.Execute) {
            "$($task.TaskPath)$($task.TaskName): $($action.Execute) $($action.Arguments)"
        }
    }
}
schtasks /query /fo LIST /v |
    Select-String 'TaskName|Run As User|Task To Run|Schedule Type|Status'

Section 'Autoruns and startup'
Get-CimInstance Win32_StartupCommand | Select-Object Name,Command,Location,User
Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run'
Get-ItemProperty 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Run'
Get-ItemProperty 'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Run'
Get-ChildItem "$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup" -Force
Get-ChildItem 'C:\ProgramData\Microsoft\Windows\Start Menu\Programs\StartUp' -Force

Section 'Installed software'
$uninstall = 'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*',
             'HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
             'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*'
Get-ItemProperty $uninstall | Where-Object DisplayName |
    Select-Object DisplayName,DisplayVersion,Publisher,InstallDate | Sort-Object DisplayName

Section 'Shares and sessions'
net share
Get-SmbShare | Select-Object Name,Path,Description
Get-SmbSession | Select-Object ClientComputerName,ClientUserName,NumOpens

Section 'Credential and secret locations (presence only)'
cmdkey /list
klist
foreach ($path in @("$env:APPDATA\Microsoft\Credentials",
                    "$env:LOCALAPPDATA\Microsoft\Credentials",
                    "$env:USERPROFILE\.ssh",
                    "$env:APPDATA\Microsoft\Windows\PowerShell\PSReadLine")) {
    if (Exists $path) {
        Write-Host "`n$path"
        Get-ChildItem -LiteralPath $path -Force | Select-Object Name,Length,LastWriteTime
        Candidate "User-readable credential material: $path"
    }
}
foreach ($path in @('C:\unattend.xml','C:\Windows\Panther\Unattend.xml',
                    'C:\Windows\Panther\Unattend\Unattend.xml',
                    'C:\Windows\System32\Sysprep\sysprep.inf',
                    'C:\Windows\System32\Sysprep\sysprep.xml')) {
    if (Exists $path) { Candidate "Unattend/sysprep file present: $path" }
}

Section 'Escalation indicators'
Write-Host "`n-- AlwaysInstallElevated"
foreach ($key in 'HKLM:\SOFTWARE\Policies\Microsoft\Windows\Installer',
                 'HKCU:\SOFTWARE\Policies\Microsoft\Windows\Installer') {
    if (Exists $key) {
        $value = Get-ItemProperty -LiteralPath $key -Name AlwaysInstallElevated
        if ($value.AlwaysInstallElevated -eq 1) {
            Write-Host "  $key = 1"
            Candidate "AlwaysInstallElevated is enabled in $key"
        }
    }
}
Write-Host "`n-- Winlogon autologon"
$winlogon = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
[pscustomobject]@{
    AutoAdminLogon = $winlogon.AutoAdminLogon
    DefaultUserName = $winlogon.DefaultUserName
    DefaultDomainName = $winlogon.DefaultDomainName
    DefaultPasswordPresent = [bool]$winlogon.DefaultPassword
}
if ($winlogon.DefaultPassword) { Candidate 'Plaintext DefaultPassword is present in Winlogon' }

Write-Host "`n-- Writable PATH directories"
foreach ($dir in ($env:Path -split ';')) {
    if ($dir -and (Exists $dir)) { WritableByUser $dir }
}
Write-Host "`n-- UAC configuration"
Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System' |
    Select-Object EnableLUA,ConsentPromptBehaviorAdmin,PromptOnSecureDesktop
Write-Host "`n-- AppLocker policy present"
Get-AppLockerPolicy -Effective -ErrorAction SilentlyContinue | Select-Object -First 1

Section 'Candidate escalation paths'
if ($findings.Count -eq 0) {
    Write-Host '  No obvious low-privilege path was identified by this script.'
} else {
    $findings | Sort-Object -Unique | ForEach-Object { Write-Host "  [!] $_" -ForegroundColor Yellow }
}
Write-Host "`n  Validate each candidate manually. This script does not exploit anything."

if ($transcript) { try { Stop-Transcript | Out-Null } catch {} }
Write-Host "`n[+] Report: $report"
if ($ExposeOrigin -and $ExposeTicket) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -s -F "files=@$report" "$ExposeOrigin/upload?ticket=$ExposeTicket" | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "[+] Report uploaded to $ExposeOrigin" }
        else { Write-Host "[!] Upload failed; retrieve the report manually." }
    } else {
        Write-Host '[!] curl.exe not found; retrieve the report manually.'
    }
}
