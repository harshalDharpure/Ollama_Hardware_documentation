# Hardware Spec Converter - One-click setup (Run as Administrator)
# Right-click this file -> Run with PowerShell (Admin)

$ErrorActionPreference = "Stop"
Write-Host "=== Hardware Spec Converter Setup ===" -ForegroundColor Cyan

# 1. Python dependencies
Write-Host "`n[1/4] Installing Python packages..." -ForegroundColor Yellow
Set-Location $PSScriptRoot
pip install -r requirements.txt

# 2. Ollama
Write-Host "`n[2/4] Installing Ollama..." -ForegroundColor Yellow
$ollamaInstaller = "$env:USERPROFILE\Downloads\OllamaSetup.exe"
if (-not (Test-Path $ollamaInstaller)) {
    Write-Host "Downloading Ollama..."
    Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $ollamaInstaller
}
Start-Process -FilePath $ollamaInstaller -Wait
Write-Host "Ollama installed. Waiting for service to start..."
Start-Sleep -Seconds 10

# 3. Pull models
Write-Host "`n[3/4] Pulling Ollama models (this may take several minutes)..." -ForegroundColor Yellow
$env:Path = [System.Environment]::GetEnvironmentVariable("Path", "Machine") + ";" + [System.Environment]::GetEnvironmentVariable("Path", "User")
ollama pull qwen2.5:7b
ollama pull llava:13b

# 4. Optional OCR
Write-Host "`n[4/4] Installing Tesseract OCR (optional)..." -ForegroundColor Yellow
choco install tesseract -y 2>$null

Write-Host "`n=== Setup Complete ===" -ForegroundColor Green
Write-Host "Run the app with:"
Write-Host "  cd $PSScriptRoot"
Write-Host "  python -m streamlit run app.py"
Write-Host "`nOpen http://localhost:8501 in your browser"
