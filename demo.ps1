param(
    [switch]$Live,
    [ValidateSet('composed','individual')][string]$Mode = 'composed',
    [string]$Question = 'Who can cover pickup R24?',
    [switch]$Defense
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Push-Location $PSScriptRoot
$inferenceProcess = $null
try {
    $python = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    $uv = Get-Command uv -ErrorAction SilentlyContinue
    if (!(Test-Path -LiteralPath $python)) {
        if ($uv) {
            & uv venv --python 3.11 .venv
        } else {
            $pythonCommand = Get-Command python -CommandType Application -TotalCount 1 -ErrorAction SilentlyContinue
            $launcher = Get-Command py -CommandType Application -TotalCount 1 -ErrorAction SilentlyContinue
            if ($pythonCommand) {
                & $pythonCommand -c 'import sys; sys.exit(sys.version_info < (3, 11))'
            }
            if ($pythonCommand -and $LASTEXITCODE -eq 0) {
                & $pythonCommand -m venv .venv
            } elseif ($launcher) {
                & $launcher -3.11 -m venv .venv
            } else {
                throw 'Install Python 3.11+ or uv, then retry.'
            }
        }
        if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11+ or uv, then retry.' }
    }
    $pipOptions = @()
    if ($Defense) { $pipOptions += '--quiet' }
    if ($uv) { & uv pip install --python $python -r requirements.txt @pipOptions }
    else { & $python -m pip install -r requirements.txt @pipOptions }
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the project dependencies.' }
    if (!$Live -and !$Defense) {
        & $python demo.py
    } else {
        $endpoint = $env:DISPATCH_MODEL_URL
        $model = $env:DISPATCH_MODEL
        if (!$endpoint) {
            $cache = Join-Path $env:LOCALAPPDATA 'vibeathon-tools'
            $server = Join-Path $cache 'llama/llama-server.exe'
            $weights = Join-Path $cache 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
            $model = 'Qwen3-4B-Instruct-2507'
            $inferenceOptions = @('-c', '8192')
            if ($Defense) {
                $demoServer = Join-Path $PSScriptRoot '.work/llama-runtime/llama-server.exe'
                $demoWeights = Join-Path $PSScriptRoot '.work/Qwen3.5-0.8B-Q4_K_M.gguf'
                if ((Test-Path -LiteralPath $demoServer -PathType Leaf) -and
                    (Test-Path -LiteralPath $demoWeights -PathType Leaf)) {
                    $server = $demoServer
                    $weights = $demoWeights
                    $model = 'Qwen3.5-0.8B-Q4_K_M'
                    $inferenceOptions = @('-c', '4096', '-b', '256', '-ub', '128', '-ngl', '0', '--reasoning', 'off')
                }
            }
            if (!(Test-Path -LiteralPath $server) -or !(Test-Path -LiteralPath $weights)) {
                throw 'For live inference set DISPATCH_MODEL_URL and DISPATCH_MODEL as described in README.md.'
            }
            $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
            $listener.Start()
            try { $port = $listener.LocalEndpoint.Port } finally { $listener.Stop() }
            $endpoint = "http://127.0.0.1:$port/v1"
            $inferenceArguments = @(
                '-m', ('"{0}"' -f $weights), '--alias', $model, '--host', '127.0.0.1', '--port', $port,
                '-np', '1', '-t', '6', '--jinja'
            ) + $inferenceOptions
            $inferenceProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $server -ArgumentList $inferenceArguments
            $ready = $false
            for ($i = 0; $i -lt 90 -and !$ready; $i++) {
                if ($inferenceProcess.HasExited) { throw 'The local inference server stopped during startup.' }
                try { $ready = (Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2).status -eq 'ok' }
                catch { Start-Sleep -Seconds 1 }
            }
            if (!$ready) { throw 'The local model did not become ready within the startup window.' }
        }
        if (!$model) { throw 'Set DISPATCH_MODEL to the name served by DISPATCH_MODEL_URL.' }
        if ($Defense) {
            & $python -u defense.py --base-url $endpoint --model $model
        } else {
            & $python agent.py $Question --mode $Mode --base-url $endpoint --model $model
        }
    }
    if ($LASTEXITCODE -ne 0) { throw "Demo exited with code $LASTEXITCODE." }
} finally {
    if ($inferenceProcess -and !$inferenceProcess.HasExited) { $inferenceProcess.Kill(); $inferenceProcess.WaitForExit() }
    Pop-Location
}
