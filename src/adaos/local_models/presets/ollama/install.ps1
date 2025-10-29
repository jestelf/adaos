param()
$ErrorActionPreference = 'Continue'

Write-Host "[Ollama] Checking installation..."
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  Write-Host "[Ollama] Ollama is not installed. Preparing offline installer for manual setup."
  try {
    $tempDir = [System.IO.Path]::GetTempPath()
    if (-not (Test-Path $tempDir)) {
      $tempDir = "$env:USERPROFILE\AppData\Local\Temp"
      New-Item -ItemType Directory -Force -Path $tempDir | Out-Null
    }

    $installerPath = Join-Path $tempDir "OllamaSetup.exe"
    if (Test-Path $installerPath -PathType Leaf) {
      try {
        Remove-Item -Path $installerPath -Force -ErrorAction Stop
      } catch {
        Write-Host "[Ollama] Existing installer is locked. Creating a new copy alongside." -ForegroundColor Yellow
        $installerPath = Join-Path $tempDir ("OllamaSetup_{0}.exe" -f [Guid]::NewGuid().ToString("N"))
      }
    }

    try {
      [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    } catch {}
    $installerUrl = "https://ollama.com/download/OllamaSetup.exe"
    Write-Host "[Ollama] Downloading installer from $installerUrl ..."
    Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing -TimeoutSec 300

    if ((Get-Item $installerPath).Length -lt 5MB) {
      throw "Downloaded file is unexpectedly small; please re-download manually."
    }

    Write-Host "[Ollama] Installer saved to $installerPath"
    Write-Host "[Ollama] Please launch it manually (Run as administrator) to finish Ollama setup."
  } catch {
    Write-Host "[Ollama] Failed to prepare installer: $_" -ForegroundColor Yellow
    exit 1
  }
  exit 1
}

Write-Host "[Ollama] Starting ollama serve in background (if not running)..."
try { Start-Process -FilePath ollama -ArgumentList 'serve' -WindowStyle Minimized } catch {}
Start-Sleep -Seconds 2

$models = @(
  'llama3.2:3b-instruct','llama3.1:8b-instruct','qwen2.5:7b-instruct','qwen2.5:3b-instruct',
  'mistral:7b-instruct','phi3:mini','gemma2:2b-instruct','neural-chat:7b-v3.3','openhermes:2.5-mistral'
)
foreach ($m in $models) {
  Write-Host "ollama pull $m"
  ollama pull $m
}
Write-Host "Done. Base URL: http://127.0.0.1:11434/v1"
