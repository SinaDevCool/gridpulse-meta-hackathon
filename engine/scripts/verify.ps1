param(
    [ValidateSet("fast", "release")]
    [string]$Mode = "fast"
)

$ErrorActionPreference = "Stop"
$Python = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
$Reports = Join-Path $PSScriptRoot "..\reports\tests"
New-Item -ItemType Directory -Force -Path $Reports | Out-Null

& $Python -m pytest -q -m "not slow" --junitxml="$Reports\fast.xml"
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

if ($Mode -eq "release") {
    $SlowFiles = @(
        "tests/test_capacity_real_public.py",
        "tests/test_capacity_study_pipeline_integration.py",
        "tests/test_network_study.py",
        "tests/test_research_pipeline.py"
    )
    foreach ($TestFile in $SlowFiles) {
        $Name = [System.IO.Path]::GetFileNameWithoutExtension($TestFile)
        & $Python -m pytest -q --run-slow $TestFile --junitxml="$Reports\$Name.xml"
        if ($LASTEXITCODE -ne 0) {
            exit $LASTEXITCODE
        }
    }
}
