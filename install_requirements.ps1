param(
    [string]$VenvPath = ".\venv_py312",
    [string]$CudaIndexUrl = "https://download.pytorch.org/whl/cu121",
    [switch]$SkipTorch,
    [switch]$InstallBitsAndBytes
)

$ErrorActionPreference = "Stop"

$pythonPath = Join-Path $VenvPath "Scripts\python.exe"

if (-not (Test-Path $pythonPath)) {
    Write-Host "Creating virtual environment at $VenvPath" -ForegroundColor Green
    $createdWithPy312 = $false
    if (Get-Command py -ErrorAction SilentlyContinue) {
        py -3.12 -m venv $VenvPath
        $createdWithPy312 = ($LASTEXITCODE -eq 0)
    }
    if (-not $createdWithPy312) {
        Write-Warning "Python 3.12 was not found by the py launcher. Falling back to the default python on PATH."
        python -m venv $VenvPath
    }
}

& $pythonPath --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    throw "The virtual environment at $VenvPath exists but its Python executable is not usable. Remove that folder and rerun this script."
}

Write-Host "Installing RAG pipeline dependencies..." -ForegroundColor Green

& $pythonPath -m pip install --upgrade pip

if (-not $SkipTorch) {
    Write-Host "Installing PyTorch from $CudaIndexUrl" -ForegroundColor Green
    & $pythonPath -m pip install torch torchvision torchaudio --index-url $CudaIndexUrl
}

& $pythonPath -m pip install -r requirements.txt

if ($InstallBitsAndBytes) {
    Write-Host "Installing optional bitsandbytes package..." -ForegroundColor Yellow
    & $pythonPath -m pip install bitsandbytes
}

& $pythonPath -m ipykernel install --user --name=rag_py312 --display-name="Python 3.12 (RAG GPU)"

Write-Host "`nAll packages installed successfully." -ForegroundColor Green
Write-Host "You can now use the 'Python 3.12 (RAG GPU)' kernel in Jupyter." -ForegroundColor Cyan
