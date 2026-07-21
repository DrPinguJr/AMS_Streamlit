param(
    [string]$InstallRoot = (Join-Path $PSScriptRoot "LibreOfficePortable"),
    [string]$DownloadUrl = "https://download.documentfoundation.org/libreoffice/portable/26.2.1/LibreOfficePortable_26.2.1_MultilingualStandard.paf.exe",
    [string]$ExpectedSha256 = "93ab521584f06c08398b1f753c7cac268865c632c5ed038d8cb9d29372c53763"
)

$ErrorActionPreference = "Stop"

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$downloadDir = Join-Path $PSScriptRoot "_downloads"
New-Item -ItemType Directory -Force -Path $downloadDir | Out-Null

$installerPath = Join-Path $downloadDir "LibreOfficePortable_26.2.1_MultilingualStandard.paf.exe"
$sofficePath = Join-Path $InstallRoot "App\libreoffice\program\soffice.exe"
$nestedSofficePath = Join-Path $InstallRoot "LibreOfficePortable\App\libreoffice\program\soffice.exe"

if ((Test-Path $sofficePath) -or (Test-Path $nestedSofficePath)) {
    Write-Host "LibreOffice Portable is already available under $InstallRoot"
    exit 0
}

Write-Host "Downloading LibreOffice Portable to $installerPath"
Invoke-WebRequest -Uri $DownloadUrl -OutFile $installerPath

$hash = (Get-FileHash -Algorithm SHA256 -Path $installerPath).Hash.ToLowerInvariant()
if ($hash -ne $ExpectedSha256) {
    throw "Downloaded installer hash mismatch. Expected $ExpectedSha256 but got $hash."
}

Write-Host "Installing LibreOffice Portable silently under:"
Write-Host $InstallRoot
Write-Host ""
Write-Host "This writes inside the project folder only; it does not need Program Files/admin installation."
$destinationArgument = $InstallRoot.TrimEnd("\") + "\"
Start-Process -FilePath $installerPath -ArgumentList @("/S", "/DESTINATION=$destinationArgument") -Wait

if ((Test-Path $sofficePath) -or (Test-Path $nestedSofficePath)) {
    Write-Host "LibreOffice Portable installed successfully. Restart Streamlit before generating PDFs."
    exit 0
}

throw "LibreOffice Portable was not found after installation. Re-run the installer and select $InstallRoot as the destination."
