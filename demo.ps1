param(
    [switch]$Live,
    [ValidateSet('composed','individual')][string]$Mode = 'composed',
    [string]$Question = 'Who can cover pickup R24?'
)
$ErrorActionPreference = 'Stop'
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
    if ($uv) { & uv pip install --python $python -r requirements.txt }
    else { & $python -m pip install -r requirements.txt }
    if ($LASTEXITCODE -ne 0) { throw 'Could not install the project dependencies.' }
    if (!$Live) {
        & $python demo.py
    } else {
        $endpoint = $env:DISPATCH_MODEL_URL
        $model = $env:DISPATCH_MODEL
        if (!$endpoint) {
            $cache = Join-Path $env:LOCALAPPDATA 'vibeathon-tools'
            $server = Join-Path $cache 'llama/llama-server.exe'
            $weights = Join-Path $cache 'Qwen3-4B-Instruct-2507-Q4_K_M.gguf'
            if (!(Test-Path -LiteralPath $server) -or !(Test-Path -LiteralPath $weights)) {
                throw 'For live inference set DISPATCH_MODEL_URL and DISPATCH_MODEL as described in README.md.'
            }
            $listener = [System.Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
            $listener.Start()
            try { $port = $listener.LocalEndpoint.Port } finally { $listener.Stop() }
            $endpoint = "http://127.0.0.1:$port/v1"
            $model = 'Qwen3-4B-Instruct-2507'
            $inferenceProcess = Start-Process -WindowStyle Hidden -PassThru -FilePath $server -ArgumentList @(
                '-m', ('"{0}"' -f $weights), '--alias', $model, '--host', '127.0.0.1', '--port', $port,
                '-c', '8192', '-np', '1', '-t', '6', '--jinja'
            )
            $ready = $false
            for ($i = 0; $i -lt 90 -and !$ready; $i++) {
                if ($inferenceProcess.HasExited) { throw 'The local inference server stopped during startup.' }
                try { $ready = (Invoke-RestMethod "http://127.0.0.1:$port/health" -TimeoutSec 2).status -eq 'ok' }
                catch { Start-Sleep -Seconds 1 }
            }
            if (!$ready) { throw 'The local model did not become ready within the startup window.' }
        }
        if (!$model) { throw 'Set DISPATCH_MODEL to the name served by DISPATCH_MODEL_URL.' }
        & $python agent.py $Question --mode $Mode --base-url $endpoint --model $model
    }
    if ($LASTEXITCODE -ne 0) { throw "Demo exited with code $LASTEXITCODE." }
} finally {
    if ($inferenceProcess -and !$inferenceProcess.HasExited) { $inferenceProcess.Kill(); $inferenceProcess.WaitForExit() }
    Pop-Location
}
