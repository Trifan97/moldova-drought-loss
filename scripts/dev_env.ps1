# Prepare this PowerShell window for work on the project. Dot-source it from the
# repository root:
#
#     . .\scripts\dev_env.ps1
#
# It sets environment variables for this window only, so other projects and new windows
# keep whatever Python they had, and nothing is added to your PowerShell profile.
#
# The environment lives outside the repository because a conda prefix must not contain
# spaces, and this folder's name does. Override the defaults on another machine:
#
#     $env:DROUGHT_LOSS_ENV = "D:\envs\drought-loss"
#     $env:MAMBA_ROOT_PREFIX = "D:\micromamba"

if (-not $env:MAMBA_ROOT_PREFIX) { $env:MAMBA_ROOT_PREFIX = "F:\micromamba" }
if (-not $env:DROUGHT_LOSS_ENV) { $env:DROUGHT_LOSS_ENV = "F:\envs\drought-loss" }

$micromamba = Join-Path $env:MAMBA_ROOT_PREFIX "micromamba.exe"
if (-not (Test-Path $micromamba)) {
    throw "No micromamba at $micromamba. Follow the 'Quick start' section of README.md first."
}
if (-not (Test-Path (Join-Path $env:DROUGHT_LOSS_ENV "python.exe"))) {
    throw "No environment at $env:DROUGHT_LOSS_ENV. Follow the 'Quick start' section of README.md first."
}

# Activation, not just the right python.exe: GDAL's DLLs are found through PATH.
(& $micromamba shell hook --shell powershell) | Out-String | Invoke-Expression
micromamba activate $env:DROUGHT_LOSS_ENV
