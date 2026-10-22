# Prompts for the Supabase Postgres connection string (input hidden) and
# writes it to .env as SUPABASE_DB_URL, replacing any existing line.
$envFile = Join-Path (Split-Path $PSScriptRoot -Parent) ".env"
$secure = Read-Host "Paste your Supabase connection string (postgresql://...) and press Enter" -AsSecureString
$url = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)).Trim()
if (-not $url.StartsWith("postgres")) { Write-Host "That doesn't look like a postgresql:// connection string. Nothing saved." -ForegroundColor Red; exit 1 }
$lines = @(Get-Content $envFile | Where-Object { $_ -notmatch '^SUPABASE_DB_URL=' })
$lines += "SUPABASE_DB_URL=$url"
[IO.File]::WriteAllLines($envFile, $lines, (New-Object Text.UTF8Encoding $false))
Write-Host "Saved SUPABASE_DB_URL to $envFile" -ForegroundColor Green
