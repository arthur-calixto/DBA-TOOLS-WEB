# Executar em Windows com Python 3.12 x64 e Tkinter. Não modifica registro/produção.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'O build deve ser executado no Windows.' }
$repo = Split-Path $PSScriptRoot -Parent
$work = Join-Path $env:TEMP ('dbatools-launcher-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $work | Out-Null
try {
    & py -3.12 -m venv (Join-Path $work 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao criar venv Windows.' }
    $python = Join-Path $work 'venv\Scripts\python.exe'
    & $python -c "import struct, sys, tkinter; sys.exit(0 if struct.calcsize('P') == 8 else 1)"
    if ($LASTEXITCODE -ne 0) { throw 'Python x64 com Tcl/Tk é obrigatório.' }
    & $python -m pip install -r (Join-Path $PSScriptRoot 'requirements-build.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependências de build.' }
    Push-Location $repo
    try {
        & $python -m unittest discover -s tests -p "test_launcher*.py" -v
        if ($LASTEXITCODE -ne 0) { throw 'Testes do Launcher falharam; build interrompido.' }
        & $python -m PyInstaller --noconfirm --clean --onedir --windowed `
            --name DBA-TOOLS-Launcher --paths $repo `
            --distpath (Join-Path $work 'dist') --workpath (Join-Path $work 'build') `
            --specpath $work (Join-Path $PSScriptRoot 'main.py')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller falhou.' }
        $output = Join-Path $repo 'dist'
        New-Item -ItemType Directory -Force -Path $output | Out-Null
        $archive = Join-Path $output 'DBA-TOOLS-Launcher-windows-x64.zip'
        if (Test-Path $archive) { throw 'ZIP já existe em dist. Preserve ou remova o artefato anterior antes de repetir.' }
        Compress-Archive -Path (Join-Path $work 'dist\DBA-TOOLS-Launcher') -DestinationPath $archive
        (Get-FileHash $archive -Algorithm SHA256).Hash | Set-Content ($archive + '.sha256')
        Write-Host "Build criado: $archive. Requer validação Windows e assinatura antes da distribuição ampla."
    } finally { Pop-Location }
} finally { Remove-Item -LiteralPath $work -Recurse -Force }
