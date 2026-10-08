# BA WorkTrack - Day 1 installer (Windows, PowerShell)
# Run in a normal PowerShell window:  powershell -ExecutionPolicy Bypass -File .\day1-install.ps1
# winget may show UAC prompts - accept them. Safe to re-run; installed tools are skipped.

$ErrorActionPreference = "Continue"

function Refresh-Path {
    $env:Path = [Environment]::GetEnvironmentVariable("Path", "Machine") + ";" +
                [Environment]::GetEnvironmentVariable("Path", "User")
}

Write-Host "`n=== 1. Installing tools with winget ===" -ForegroundColor Cyan
$apps = @(
    @{ Id = "Python.Python.3.12";                         Name = "Python 3.12" },
    @{ Id = "Microsoft.VisualStudioCode";                 Name = "VS Code" },
    @{ Id = "Git.Git";                                    Name = "Git" },
    @{ Id = "GitHub.cli";                                 Name = "GitHub CLI" },
    @{ Id = "Bruno.Bruno";                                Name = "Bruno" },
    @{ Id = "DBBrowserForSQLite.DBBrowserForSQLite";      Name = "DB Browser for SQLite" },
    @{ Id = "Ollama.Ollama";                              Name = "Ollama" }
)
foreach ($a in $apps) {
    Write-Host "-> $($a.Name)" -ForegroundColor Yellow
    winget install --id $a.Id -e --accept-source-agreements --accept-package-agreements --silent
}
Refresh-Path

Write-Host "`n=== 2. VS Code extensions ===" -ForegroundColor Cyan
$ext = "ms-python.python", "ms-python.vscode-pylance", "charliermarsh.ruff",
       "eamodio.gitlens", "qwtel.sqlite-viewer"
foreach ($e in $ext) { code --install-extension $e --force }

Write-Host "`n=== 3. Git defaults ===" -ForegroundColor Cyan
$name  = Read-Host "Your name for Git commits (e.g. Ankur Gupta)"
$email = Read-Host "Email for Git commits (use your GitHub email or the noreply address)"
git config --global user.name  "$name"
git config --global user.email "$email"
git config --global init.defaultBranch main

Write-Host "`n=== 4. Ollama model (about 5 GB, runs in background) ===" -ForegroundColor Cyan
$ramGB = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
$model = if ($ramGB -ge 16) { "llama3.1:8b" } else { "llama3.2:3b" }
Write-Host "Detected $ramGB GB RAM -> pulling $model"
Start-Process -FilePath "ollama" -ArgumentList "pull $model" -NoNewWindow:$false

Write-Host "`n=== 5. Version check ===" -ForegroundColor Cyan
py -3.12 --version
git --version
gh --version | Select-Object -First 1
code --version | Select-Object -First 1

Write-Host "`nDone. Next: run  gh auth login  (GitHub.com -> HTTPS -> web browser)." -ForegroundColor Green
Write-Host "Open a NEW terminal so PATH changes apply everywhere." -ForegroundColor Green