#requires -Version 5.1
<#
.SYNOPSIS
    Command-line build/upload/monitor tooling for the R-Net joystick project.

.DESCRIPTION
    Thin wrapper around the arduino-cli bundled inside Arduino IDE 2.x, so no
    separate toolchain install is needed. Board and port are auto-detected from
    whatever is plugged in, or pinned via 'rnet config'.

.EXAMPLE
    .\tools\rnet.ps1 boards          # what's plugged in
    .\tools\rnet.ps1 build           # compile
    .\tools\rnet.ps1 flash           # compile + upload
    .\tools\rnet.ps1 monitor         # serial monitor at 115200
    .\tools\rnet.ps1 run             # compile + upload + monitor
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [ValidateSet('boards', 'build', 'upload', 'flash', 'monitor', 'scope',
                 'hid', 'demo', 'run', 'cores', 'config', 'doctor', 'cli',
                 'help')]
    [string]$Command = 'help',

    [string]$Sketch,
    [string]$Fqbn,
    [string]$Port,
    [int]$Baud = 0,
    [switch]$Clean,
    [switch]$Hid,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = 'Stop'

# ---------------------------------------------------------------- paths -----

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ConfigPath  = Join-Path $PSScriptRoot 'board.json'
$BuildRoot   = Join-Path $ProjectRoot 'build'
$DefaultSketch = Join-Path $ProjectRoot 'r-net_test'

# The multi-HID sketch only works under a different USB descriptor set, which
# lives in the FQBN. Getting it wrong silently builds the serial-only variant
# and you spend a while wondering why no gamepad appears in Windows.
$HidSketch = Join-Path $ProjectRoot 'r-net_hid'
$HidFqbn   = 'teensy:avr:teensy30:usb=serialhid'

$CliCandidates = @(
    $env:ARDUINO_CLI,
    'C:\Z\apps\dev\arduino-ide_2.3.4_Windows_64bit\resources\app\lib\backend\resources\arduino-cli.exe'
)

function Get-Cli {
    foreach ($c in $CliCandidates) {
        if ($c -and (Test-Path $c)) { return (Resolve-Path $c).Path }
    }
    # Fall back to anything on PATH, or an IDE installed elsewhere under C:\Z\apps.
    $onPath = Get-Command 'arduino-cli' -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }

    $found = Get-ChildItem -Path 'C:\Z\apps' -Filter 'arduino-cli.exe' -Recurse `
                -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($found) { return $found.FullName }

    throw "arduino-cli not found. Set `$env:ARDUINO_CLI to its full path."
}

$Cli = Get-Cli

# --------------------------------------------------------------- config -----

function Get-Config {
    if (Test-Path $ConfigPath) {
        return Get-Content $ConfigPath -Raw | ConvertFrom-Json
    }
    return [pscustomobject]@{ fqbn = ''; port = ''; monitorPort = ''; baud = 115200 }
}

function Get-ConfigValue([object]$cfg, [string]$name) {
    $p = $cfg.PSObject.Properties[$name]
    if ($p -and $p.Value) { return $p.Value }
    return $null
}

# ------------------------------------------------------------ detection -----

function Get-DetectedPorts {
    $json = & $Cli board list --format json
    if ($LASTEXITCODE -ne 0) { throw "arduino-cli board list failed." }

    $parsed = $json | ConvertFrom-Json
    # arduino-cli 1.x wraps results in .detected_ports; older builds return a bare array.
    $ports = $parsed
    if ($parsed.PSObject.Properties['detected_ports']) { $ports = $parsed.detected_ports }
    if (-not $ports) { return @() }

    $out = @()
    foreach ($p in $ports) {
        $board = $null
        if ($p.PSObject.Properties['matching_boards'] -and $p.matching_boards) {
            $board = $p.matching_boards[0]
        }
        $fqbnVal = ''
        $nameVal = 'Unknown'
        if ($board) {
            if ($board.PSObject.Properties['fqbn']) { $fqbnVal = $board.fqbn }
            if ($board.PSObject.Properties['name']) { $nameVal = $board.name }
        }
        $out += [pscustomobject]@{
            Address  = $p.port.address
            Protocol = $p.port.protocol
            Label    = $p.port.label
            Fqbn     = $fqbnVal
            Name     = $nameVal
        }
    }
    return $out
}

function Resolve-Fqbn {
    if ($Fqbn) { return $Fqbn }
    if ($Hid) { return $HidFqbn }
    $cfg = Get-Config
    $v = Get-ConfigValue $cfg 'fqbn'
    if ($v) { return $v }
    if ($env:RNET_FQBN) { return $env:RNET_FQBN }

    $match = Get-DetectedPorts | Where-Object { $_.Fqbn } | Select-Object -First 1
    if ($match) {
        Write-Host "auto-detected board: $($match.Name) [$($match.Fqbn)]" -ForegroundColor DarkGray
        return $match.Fqbn
    }
    throw "No board detected and no FQBN configured. Run 'rnet.ps1 boards', then 'rnet.ps1 config -Fqbn <fqbn>'."
}

# Port used for uploading. For Teensy this is a 'teensy' protocol pseudo-port,
# not the COM port, so prefer whichever port actually identified a board.
function Resolve-UploadPort {
    if ($Port) { return $Port }
    $cfg = Get-Config
    $v = Get-ConfigValue $cfg 'port'
    if ($v) { return $v }
    if ($env:RNET_PORT) { return $env:RNET_PORT }

    $detected = Get-DetectedPorts
    $match = $detected | Where-Object { $_.Fqbn } | Select-Object -First 1
    if ($match) { return $match.Address }

    $serial = $detected | Where-Object { $_.Protocol -eq 'serial' } | Select-Object -First 1
    if ($serial) { return $serial.Address }

    throw "No upload port detected. Plug the board in, or pass -Port <COMn>."
}

# Port used for the serial monitor -- always a real COM port.
function Resolve-SerialPort {
    if ($Port) { return $Port }
    $cfg = Get-Config
    $v = Get-ConfigValue $cfg 'monitorPort'
    if ($v) { return $v }
    if ($env:RNET_MONITOR_PORT) { return $env:RNET_MONITOR_PORT }

    $serial = Get-DetectedPorts | Where-Object { $_.Protocol -eq 'serial' } | Select-Object -First 1
    if ($serial) { return $serial.Address }

    throw "No serial port detected. Plug the board in, or pass -Port <COMn>."
}

function Resolve-Baud {
    if ($Baud -gt 0) { return $Baud }
    $cfg = Get-Config
    $v = Get-ConfigValue $cfg 'baud'
    if ($v) { return [int]$v }
    return 115200
}

function Resolve-Sketch {
    $s = $Sketch
    if (-not $s -and $Hid) { $s = $HidSketch }
    if (-not $s) { $s = $DefaultSketch }
    if (-not (Test-Path $s)) { throw "Sketch not found: $s" }
    return (Resolve-Path $s).Path
}

function Get-BuildPath([string]$sketchPath, [string]$fqbn) {
    $leaf = Split-Path -Leaf $sketchPath
    $slug = $fqbn -replace '[:\\/]', '_'
    return (Join-Path $BuildRoot "$leaf.$slug")
}

# ------------------------------------------------------------- commands -----

function Invoke-Boards {
    $detected = Get-DetectedPorts
    if (-not $detected) {
        Write-Host "No boards detected." -ForegroundColor Yellow
        return
    }
    $detected | Format-Table Address, Protocol, Name, Fqbn -AutoSize
}

function Invoke-Build {
    $sketchPath = Resolve-Sketch
    $fqbn       = Resolve-Fqbn
    $buildPath  = Get-BuildPath $sketchPath $fqbn

    if ($Clean -and (Test-Path $buildPath)) {
        Write-Host "cleaning $buildPath" -ForegroundColor DarkGray
        Remove-Item $buildPath -Recurse -Force
    }
    if (-not (Test-Path $buildPath)) {
        New-Item -ItemType Directory -Path $buildPath -Force | Out-Null
    }

    Write-Host "building $(Split-Path -Leaf $sketchPath) for $fqbn" -ForegroundColor Cyan
    $cliArgs = @('compile', '--fqbn', $fqbn, '--build-path', $buildPath)
    if ($Rest) { $cliArgs += $Rest }
    $cliArgs += $sketchPath

    & $Cli @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "compile failed (exit $LASTEXITCODE)" }
    Write-Host "build ok -> $buildPath" -ForegroundColor Green
}

function Invoke-Upload {
    $sketchPath = Resolve-Sketch
    $fqbn       = Resolve-Fqbn
    $uploadPort = Resolve-UploadPort
    $buildPath  = Get-BuildPath $sketchPath $fqbn

    if (-not (Test-Path $buildPath)) {
        throw "No build found at $buildPath. Run 'build' or 'flash' first."
    }

    Write-Host "uploading to $uploadPort [$fqbn]" -ForegroundColor Cyan
    $cliArgs = @('upload', '--fqbn', $fqbn, '--port', $uploadPort,
                 '--input-dir', $buildPath, $sketchPath)
    if ($Rest) { $cliArgs += $Rest }

    & $Cli @cliArgs
    if ($LASTEXITCODE -ne 0) { throw "upload failed (exit $LASTEXITCODE)" }
    Write-Host "upload ok" -ForegroundColor Green
}

function Invoke-Monitor {
    $serialPort = Resolve-SerialPort
    $baud       = Resolve-Baud
    Write-Host "monitor $serialPort @ $baud  (Ctrl+C to exit)" -ForegroundColor Cyan
    & $Cli monitor --port $serialPort --config "baudrate=$baud"
}

function Invoke-Scope {
    $script = Join-Path $PSScriptRoot 'scope.py'
    if (-not (Test-Path $script)) { throw "scope.py not found at $script" }

    $pyArgs = @($script)
    if ($Port) { $pyArgs += @('--port', $Port) }
    if ($Baud -gt 0) { $pyArgs += @('--baud', "$Baud") }
    if ($Rest) { $pyArgs += $Rest }

    & python @pyArgs
}

function Invoke-Hid {
    $script = Join-Path $PSScriptRoot 'hid.py'
    if (-not (Test-Path $script)) { throw "hid.py not found at $script" }

    $pyArgs = @($script)
    if ($Port) { $pyArgs += @('--port', $Port) }
    if ($Rest) { $pyArgs += $Rest }

    & python @pyArgs
}

function Invoke-Demo {
    $script = Join-Path $PSScriptRoot 'demos\run.py'
    if (-not (Test-Path $script)) { throw "demos\run.py not found at $script" }

    $pyArgs = @($script)
    if ($Rest) { $pyArgs += $Rest }
    if ($Port) { $pyArgs += @('--port', $Port) }

    & python @pyArgs
}

function Invoke-Config {
    $cfg = Get-Config

    $changed = $false
    if ($Fqbn) { $cfg.fqbn = $Fqbn; $changed = $true }
    if ($Port) { $cfg.port = $Port; $cfg.monitorPort = $Port; $changed = $true }
    if ($Baud -gt 0) { $cfg.baud = $Baud; $changed = $true }

    # With no arguments, pin whatever is currently detected.
    if (-not $changed) {
        $detected = Get-DetectedPorts
        $board  = $detected | Where-Object { $_.Fqbn } | Select-Object -First 1
        $serial = $detected | Where-Object { $_.Protocol -eq 'serial' } | Select-Object -First 1
        if ($board) {
            $cfg.fqbn = $board.Fqbn
            $cfg.port = $board.Address
        }
        if ($serial) { $cfg.monitorPort = $serial.Address }
        if (-not $cfg.baud) { $cfg.baud = 115200 }
    }

    # Set-Content -Encoding utf8 emits a BOM on PS 5.1, which json.loads in the
    # Python tools chokes on. Write plain UTF-8 instead.
    [System.IO.File]::WriteAllText(
        $ConfigPath, ($cfg | ConvertTo-Json), (New-Object System.Text.UTF8Encoding($false)))
    Write-Host "wrote $ConfigPath" -ForegroundColor Green
    Get-Content $ConfigPath
}

function Invoke-Doctor {
    Write-Host "arduino-cli : $Cli"
    & $Cli version
    Write-Host ""
    Write-Host "project     : $ProjectRoot"
    Write-Host "sketch      : $DefaultSketch"
    Write-Host "build root  : $BuildRoot"
    Write-Host "config      : $ConfigPath$(if (Test-Path $ConfigPath) { '' } else { '  (not created yet)' })"
    Write-Host ""
    Write-Host "--- installed cores ---"
    & $Cli core list
    Write-Host ""
    Write-Host "--- detected boards ---"
    Invoke-Boards
}

function Invoke-Help {
    @"
rnet.ps1 <command> [options]

Commands
  boards     List attached boards and ports
  build      Compile the sketch
  upload     Upload the last build
  flash      build + upload
  monitor    Open the serial monitor (raw text)
  scope      Live ASCII scope: voltages + centre-zero bargraphs
             extra flags pass through: --once, --sample N, --raw
  hid        Multi-HID mode switcher / tuner. No args = interactive.
             e.g. hid mode gamepad | hid set expo 0.45 | hid watch
  demo       Launch a 3D demo. No name = list them.
             e.g. demo labyrinth | demo carve --windowed
  run        build + upload + monitor
  cores      List installed board cores
  config     Pin board/port to tools/board.json (no args = save what's detected)
  doctor     Show toolchain, paths, cores and detected boards
  cli        Pass arguments straight through to arduino-cli
  help       This text

Options
  -Sketch <path>   Sketch folder        (default: r-net_test)
  -Fqbn <fqbn>     Board FQBN           (default: config, then auto-detect)
  -Port <port>     Upload/monitor port  (default: config, then auto-detect)
  -Baud <n>        Monitor baud rate    (default: 115200)
  -Clean           Wipe the build dir before compiling
  -Hid             Target the multi-HID sketch and its USB descriptor set
                   (r-net_hid + teensy:avr:teensy30:usb=serialhid)

Anything after the recognised options is forwarded to arduino-cli, e.g.
  .\tools\rnet.ps1 build --warnings all --verbose

Resolution order for board/port: -Fqbn/-Port > tools/board.json >
`$env:RNET_FQBN / `$env:RNET_PORT > auto-detect.
"@ | Write-Host
}

# ---------------------------------------------------------------- driver ----

switch ($Command) {
    'boards'  { Invoke-Boards }
    'build'   { Invoke-Build }
    'upload'  { Invoke-Upload }
    'flash'   { Invoke-Build; Invoke-Upload }
    'run'     { Invoke-Build; Invoke-Upload; Invoke-Monitor }
    'monitor' { Invoke-Monitor }
    'scope'   { Invoke-Scope }
    'hid'     { Invoke-Hid }
    'demo'    { Invoke-Demo }
    'cores'   { & $Cli core list }
    'config'  { Invoke-Config }
    'doctor'  { Invoke-Doctor }
    'cli'     { & $Cli @Rest }
    default   { Invoke-Help }
}
