# OrbitalMind --- API Smoke Test v2 (PowerShell)
# =============================================
# Uses [Console]::WriteLine for fully capturable output.
# All PASS/FAIL lines go to stdout --- pipeable, redirectable, CI-friendly.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\api_smoke_test.ps1
#   powershell -ExecutionPolicy Bypass -File scripts\api_smoke_test.ps1 -BaseUrl http://localhost:8001

param(
    [string]$BaseUrl = "http://localhost:8000",
    [int]$TimeoutSec = 30
)

$ErrorActionPreference = "SilentlyContinue"
$script:pass = 0
$script:fail = 0

# ------ Output helpers (Console::WriteLine is always capturable) ------------------------------------------------------
function pOK   { param($m) [Console]::WriteLine("  [PASS]  $m"); $script:pass++ }
function pFail { param($m) [Console]::WriteLine("  [FAIL]  $m"); $script:fail++ }
function pInfo { param($m) [Console]::WriteLine("         $m") }
function pHead { param($m) [Console]::WriteLine(""); [Console]::WriteLine($m) }
function pBar  { [Console]::WriteLine(("=" * 62)) }

# ------ HTTP helper ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
function Invoke-Api {
    param([string]$Method="GET", [string]$Path, [string]$JsonBody=$null, [int]$Sec=0)
    if ($Sec -eq 0) { $Sec = $TimeoutSec }
    $uri = "$BaseUrl$Path"
    try {
        if ($Method -eq "POST") {
            $body = if ($JsonBody) { $JsonBody } else { '{}' }
            $resp = Invoke-WebRequest -Uri $uri -Method POST `
                      -ContentType "application/json" -Body $body `
                      -TimeoutSec $Sec -UseBasicParsing -ErrorAction Stop
        } else {
            $resp = Invoke-WebRequest -Uri $uri -Method GET `
                      -TimeoutSec $Sec -UseBasicParsing -ErrorAction Stop
        }
        return @{ Status=[int]$resp.StatusCode; Body=($resp.Content | ConvertFrom-Json); OK=$true }
    } catch {
        $code = 0
        $errBody = $null
        if ($_.Exception.Response) {
            $code = [int]$_.Exception.Response.StatusCode
            try {
                $s = $_.Exception.Response.GetResponseStream()
                $errBody = (New-Object System.IO.StreamReader($s)).ReadToEnd() | ConvertFrom-Json -ErrorAction SilentlyContinue
            } catch {}
        }
        return @{ Status=$code; Body=$errBody; OK=$false; Error=$_.Exception.Message }
    }
}

function chk { param($label, $cond, $detail="")
    if ($cond) { pOK "$label  $detail" } else { pFail "$label  $detail" }
}

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
pBar
[Console]::WriteLine("  OrbitalMind API Smoke Test - $BaseUrl")
pBar

# ------ GET /health ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
pHead "GET /health"
$r = Invoke-Api -Path "/health"
chk "200 OK"                ($r.Status -eq 200)
chk "status=ok"             ($r.Body.status -eq "ok")
chk "demo_mode=true"        ($r.Body.demo_mode -eq $true)
chk "version=2.0.0"         ($r.Body.version -eq "2.0.0")
chk "5 supported_disasters" ($r.Body.supported_disasters.Count -eq 5)
pInfo "disasters: $($r.Body.supported_disasters -join ' | ')"

# ------ GET /api/modules ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
pHead "GET /api/modules"
$r = Invoke-Api -Path "/api/modules"
chk "200 OK"               ($r.Status -eq 200)
chk "5 modules"            ($r.Body.Count -eq 5)
$fl = $r.Body | Where-Object { $_.disaster_type -eq "flood" }
chk "flood status=live"    ($fl.status -eq "live")
chk "flood color=#1e40af"  ($fl.color -eq "#1e40af")
$wf = $r.Body | Where-Object { $_.disaster_type -eq "wildfire" }
chk "wildfire status=demo" ($wf.status -eq "demo")
chk "wildfire color ok"    ($wf.color -eq "#dc2626")
foreach ($m in $r.Body) { pInfo "$($m.disaster_type.PadRight(12)) status=$($m.status)  color=$($m.color)" }

# ------ GET /api/events ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
pHead "GET /api/events"
$r = Invoke-Api -Path "/api/events"
chk "200 OK"       ($r.Status -eq 200)
chk ">=5 events"   ($r.Body.Count -ge 5)
foreach ($ev in $r.Body) { pInfo "$($ev.event_id.PadRight(22)) $($ev.disaster_type)" }

# ------ GET /api/events?disaster_type=wildfire ------------------------------------------------------------------------------------------------------------
pHead "GET /api/events?disaster_type=wildfire"
$r = Invoke-Api -Path "/api/events?disaster_type=wildfire"
chk "200 OK"            ($r.Status -eq 200)
chk "all wildfire"      (($r.Body | Where-Object { $_.disaster_type -ne "wildfire" }).Count -eq 0)
pInfo "count=$($r.Body.Count)  event=$($r.Body[0].event_id)"

# ------ GET /api/events?disaster_type=tornado (422) ---------------------------------------------------------------------------------------------
pHead "GET /api/events?disaster_type=tornado"
$r = Invoke-Api -Path "/api/events?disaster_type=tornado"
chk "422 Unprocessable" ($r.Status -eq 422)

# ------ GET /api/events/kerala-2018/zones  [FLOOD] ------------------------------------------------------------------------------------------------
pHead "GET /api/events/kerala-2018/zones  [FLOOD]"
$r = Invoke-Api -Path "/api/events/kerala-2018/zones"
chk "200 OK"                     ($r.Status -eq 200)
chk "disaster_type=flood"        ($r.Body.disaster_type -eq "flood")
chk "GeoJSON FeatureCollection"  ($r.Body.affected_zones_geojson.type -eq "FeatureCollection")
chk ">=1 feature"                ($r.Body.affected_zones_geojson.features.Count -ge 1)
chk ">=1 priority zone"          ($r.Body.priority_zones.Count -ge 1)
$topScore = [float]$r.Body.priority_zones[0].score
chk "top score above 0.6"        ($topScore -gt 0.6)
$p0 = $r.Body.priority_zones[0]; $p1 = $r.Body.priority_zones[1]
chk "sorted desc"                ([float]$p0.score -ge [float]$p1.score)
chk "module_info=FloodModule"    ($r.Body.module_info.module -eq "FloodModule")
pInfo "top zone: $($r.Body.priority_zones[0].zone)  score=$topScore"

# ------ GET /api/events/uttarakhand_2024/zones  [WILDFIRE] ------------------------------------------------------------------------
pHead "GET /api/events/uttarakhand_2024/zones  [WILDFIRE]"
$r = Invoke-Api -Path "/api/events/uttarakhand_2024/zones"
chk "200 OK"                   ($r.Status -eq 200)
chk "disaster_type=wildfire"   ($r.Body.disaster_type -eq "wildfire")
chk "WildfireModule"           ($r.Body.module_info.module -eq "WildfireModule")
chk ">=1 priority zone"        ($r.Body.priority_zones.Count -ge 1)
pInfo "top zone: $($r.Body.priority_zones[0].zone)  score=$($r.Body.priority_zones[0].score)"

# ------ GET /api/platform/summary ---------------------------------------------------------------------------------------------------------------------------------------------------
pHead "GET /api/platform/summary"
$r = Invoke-Api -Path "/api/platform/summary"
chk "200 OK"                   ($r.Status -eq 200)
chk "total_modules=5"          ($r.Body.total_modules -eq 5)
chk "live_modules=1"           ($r.Body.live_modules -eq 1)
chk "5 disasters_covered"      ($r.Body.disasters_covered.Count -eq 5)
$pd = $r.Body.per_disaster
chk "all 5 per_disaster keys"  ($pd.flood -and $pd.wildfire -and $pd.landslide -and $pd.cyclone -and $pd.earthquake)
chk "pop_affected above 1M"    ($r.Body.totals.total_pop_affected -gt 1000000)
pInfo "source=$($r.Body.source)  latency=$($r.Body.latency_ms)ms"

# ------ POST /api/analyze [flood] ---------------------------------------------------------------------------------------------------------------------------------------------------
pHead "POST /api/analyze  [flood]"
$r = Invoke-Api -Method POST -Path "/api/analyze" -JsonBody '{"event_id":"kerala_2018","disaster_type":"flood","demo_mode":true}'
chk "202 Accepted"        ($r.Status -eq 202)
chk "has task_id"         ($null -ne $r.Body.task_id -and $r.Body.task_id -ne "")
chk "status=running"      ($r.Body.status -eq "running")
chk "disaster_type=flood" ($r.Body.disaster_type -eq "flood")
pInfo "task_id=$($r.Body.task_id)"

# ------ POST /api/analyze [wildfire] ------------------------------------------------------------------------------------------------------------------------------------------
pHead "POST /api/analyze  [wildfire]"
$r = Invoke-Api -Method POST -Path "/api/analyze" -JsonBody '{"event_id":"uttarakhand_2024","disaster_type":"wildfire","demo_mode":true}'
chk "202 Accepted"           ($r.Status -eq 202)
chk "has task_id"            ($null -ne $r.Body.task_id -and $r.Body.task_id -ne "")
chk "disaster_type=wildfire" ($r.Body.disaster_type -eq "wildfire")
pInfo "task_id=$($r.Body.task_id)"

# ------ POST /api/analyze [invalid] ---------------------------------------------------------------------------------------------------------------------------------------------
pHead "POST /api/analyze  [invalid type]"
$r = Invoke-Api -Method POST -Path "/api/analyze" -JsonBody '{"event_id":"test","disaster_type":"tornado"}'
chk "422 rejected" ($r.Status -in @(400,422))

# ------ GET /api/narration/kerala-2018/ernakulam ------------------------------------------------------------------------------------------------------
pHead "GET /api/narration/kerala-2018/ernakulam"
$r = Invoke-Api -Path "/api/narration/kerala-2018/ernakulam" -Sec 30
chk "200 OK"              ($r.Status -eq 200)
chk "narration >= 60 ch"  ($r.Body.narration.Length -ge 60)
chk "has source"          ($r.Body.source -ne "")
pInfo "source=$($r.Body.source)  latency=$($r.Body.latency_ms)ms"
pInfo "text: $($r.Body.narration.Substring(0,[Math]::Min(70,$r.Body.narration.Length)))..."

# ------ POST /api/report ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
pHead "POST /api/report/kerala-2018?narrate=false&top_n=3"
$r = Invoke-Api -Method POST -Path "/api/report/kerala-2018?narrate=false&top_n=3" -JsonBody '{}' -Sec 30
chk "200 OK"                     ($r.Status -eq 200)
chk "has report_id"              ($r.Body.report_id -like "OM-*")
chk "3 priority zones"           ($r.Body.priority_zones.Count -eq 3)
chk "platform_context=Wildfire"  ($r.Body.platform_context -like "*Wildfire*")
pInfo "report_id=$($r.Body.report_id)"

# ------ GET /api/llm/status ---------------------------------------------------------------------------------------------------------------------------------------------------------------------
pHead "GET /api/llm/status"
$r = Invoke-Api -Path "/api/llm/status"
chk "200 OK"            ($r.Status -eq 200)
chk "has 'available'"   ($null -ne $r.Body.available)
pInfo "available=$($r.Body.available)  model=$($r.Body.model)"

# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
[Console]::WriteLine("")
pBar
$total = $script:pass + $script:fail
if ($script:fail -eq 0) {
    [Console]::WriteLine("  RESULT: ALL $total TESTS PASSED")
} else {
    [Console]::WriteLine("  RESULT: $($script:pass) PASSED  $($script:fail) FAILED  (total $total)")
}
pBar
[Console]::WriteLine("")
if ($script:fail -gt 0) { exit 1 } else { exit 0 }

