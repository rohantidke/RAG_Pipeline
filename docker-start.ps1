# PowerShell script to manage the full-stack RAG application via Docker Compose

param (
    [switch]$Build,
    [switch]$Down,
    [switch]$Stop,
    [switch]$Start,
    [switch]$Pause,
    [switch]$Unpause,
    [switch]$Logs,
    [switch]$Status
)

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# 1. Stop and remove containers + networks
if ($Down) {
    Write-Host "Stopping and removing RAG pipeline containers..." -ForegroundColor Yellow
    docker compose down
    exit 0
}

# 2. Stop temporarily without removing containers
if ($Stop) {
    Write-Host "Temporarily stopping containers (state preserved)..." -ForegroundColor Yellow
    docker compose stop
    docker compose ps
    exit 0
}

# 3. Resume stopped containers
if ($Start) {
    Write-Host "Resuming stopped containers..." -ForegroundColor Green
    docker compose start
    docker compose ps
    exit 0
}

# 4. Pause / Freeze processes in memory
if ($Pause) {
    Write-Host "Pausing container execution in memory..." -ForegroundColor Yellow
    docker compose pause
    docker compose ps
    exit 0
}

# 5. Unpause / Thaw processes
if ($Unpause) {
    Write-Host "Unpausing containers..." -ForegroundColor Green
    docker compose unpause
    docker compose ps
    exit 0
}

# 6. Check status
if ($Status) {
    docker compose ps
    exit 0
}

# 7. View live logs
if ($Logs) {
    docker compose logs -f
    exit 0
}

# Verify Docker engine is running
try {
    docker info | Out-Null
} catch {
    Write-Error "Docker daemon is not running. Please start Docker Desktop and retry."
    exit 1
}

Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Starting Full-Stack RAG Pipeline with Docker   " -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan

if ($Build) {
    Write-Host "`nBuilding images and starting services..." -ForegroundColor Green
    docker compose --env-file .env.docker up -d --build
} else {
    Write-Host "`nStarting services..." -ForegroundColor Green
    docker compose --env-file .env.docker up -d
}

Write-Host "`nWaiting for services to become healthy..." -ForegroundColor Yellow
Start-Sleep -Seconds 5

docker compose ps

Write-Host "`nServices:" -ForegroundColor Cyan
Write-Host "  - Frontend UI:        http://localhost:3000" -ForegroundColor White
Write-Host "  - Gateway Actuator:   http://localhost:8080/actuator/health" -ForegroundColor White
Write-Host "  - FastAPI Health:     http://localhost:8000/health" -ForegroundColor White
Write-Host "  - PostgreSQL:         localhost:5432" -ForegroundColor White

Write-Host "`nUseful commands:" -ForegroundColor Cyan
Write-Host "  .\docker-start.ps1 -Stop     # Temporarily stop (does NOT remove containers)" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Start    # Resume stopped containers" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Pause    # Freeze containers in memory" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Unpause  # Unfreeze containers" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Logs     # View live logs" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Status   # Check container status" -ForegroundColor Gray
Write-Host "  .\docker-start.ps1 -Down     # Stop and remove containers" -ForegroundColor Gray
