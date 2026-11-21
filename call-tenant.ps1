# Places the rent reminder call to one tenant through the running backend.
# Usage:  .\call-tenant.ps1 "Keshava Karthik"          (add -DryRun to only look the tenant up)
param([Parameter(Mandatory)][string]$Name, [switch]$DryRun, [string]$Api = "http://localhost:8000")

# PowerShell 5.1 returns a JSON array as one object; ForEach-Object { $_ } unrolls it
$t = Invoke-RestMethod "$Api/tenants/all" | ForEach-Object { $_ } | Where-Object { $_.name -eq $Name }
if (-not $t) { Write-Error "No active tenant named '$Name'"; exit 1 }
"{0}: room {1}, phone {2}, rent this month: {3} ({4} of {5} paid)" -f $t.name, $t.room, $t.phone, $t.rent_status, $t.paid, $t.due
if ($t.rent_status -eq "paid") { "Rent is already paid, nothing to call about."; exit 0 }
if ($DryRun) { "Dry run: no call placed."; exit 0 }

$r = Invoke-RestMethod -Method Post "$Api/tools/send_reminders" -ContentType "application/json" -Body (@{ tenant_ids = @($t.id) } | ConvertTo-Json)
$r.calls | Format-Table name, room, status, call_id
"Result appears on the dashboard (Activity log > Calls) about a minute after the call ends."
