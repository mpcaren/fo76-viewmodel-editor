# Builds the portable "FO76 Viewmodel Editor" folder for Nexus: a renamed Electron runtime with this app in
# resources\app, the Python backend (with its backend\tools) in resources\backend, and a trimmed copy of
# the local Python 3.13 in resources\python (stdlib zipped, embeddable-style ._pth). No downloads.
param([string]$Out = "$PSScriptRoot\dist\FO76 Viewmodel Editor")

$ErrorActionPreference = 'Stop'
$app = $PSScriptRoot
$py = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313'
$electron = Join-Path $app 'node_modules\electron\dist'

if (Test-Path $Out) { Remove-Item $Out -Recurse -Force }
New-Item -ItemType Directory -Force $Out | Out-Null

# Electron runtime, renamed; only the English locale
Copy-Item "$electron\*" $Out -Recurse -Exclude 'locales', 'resources'
New-Item -ItemType Directory -Force "$Out\locales", "$Out\resources" | Out-Null
Copy-Item "$electron\locales\en-US.pak" "$Out\locales\"
Rename-Item "$Out\electron.exe" 'FO76 Viewmodel Editor.exe'

# the app
$res = "$Out\resources"
$dst = "$res\app"
New-Item -ItemType Directory -Force "$dst\renderer", "$dst\node_modules\three\build" | Out-Null
Copy-Item "$app\main.js", "$app\preload.js", "$app\ini.js", "$app\game.js", "$app\package.json" $dst
Copy-Item "$app\renderer\*" "$dst\renderer\"
Copy-Item "$app\node_modules\three\build\three.module.js" "$dst\node_modules\three\build\"
Copy-Item "$app\node_modules\three\LICENSE" "$dst\node_modules\three\"
Copy-Item "$app\node_modules\three\package.json" "$dst\node_modules\three\"

# backend + the Weapon Reposition tools it imports (backend\tools)
New-Item -ItemType Directory -Force "$res\backend\tools" | Out-Null
Copy-Item "$app\backend\*.py" "$res\backend\"
Copy-Item "$app\backend\tools\*.py" "$res\backend\tools\"

# Python runtime: exe + dlls, extension modules minus tk/sqlite/ssl, stdlib in python313.zip
$pd = "$res\python"
New-Item -ItemType Directory -Force $pd | Out-Null
Copy-Item "$py\python.exe", "$py\python3.dll", "$py\python313.dll", "$py\vcruntime140.dll", "$py\vcruntime140_1.dll", "$py\LICENSE.txt" $pd
Get-ChildItem "$py\DLLs" -File | Where-Object { $_.Name -notmatch '^(_tkinter|tcl|tk|_sqlite3|sqlite3|_ssl|libssl|libcrypto|py\.ico|pyc\.ico|_test|_ctypes_test|xxlimited)' } |
    Copy-Item -Destination $pd
$skip = '^(test|tests|idlelib|tkinter|turtledemo|ensurepip|site-packages|lib2to3|pydoc_data|venv|sqlite3|__pycache__)$'
$stage = Join-Path ([IO.Path]::GetTempPath()) ('vmeditor-stdlib-' + [guid]::NewGuid())
New-Item -ItemType Directory $stage | Out-Null
Get-ChildItem "$py\Lib" | Where-Object { $_.Name -notmatch $skip } | ForEach-Object { Copy-Item $_.FullName $stage -Recurse }
Get-ChildItem $stage -Recurse -Directory -Filter '__pycache__' | Remove-Item -Recurse -Force
Get-ChildItem $stage -Recurse -Directory | Where-Object { $_.Name -match '^(test|tests)$' } | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory($stage, "$pd\python313.zip", 'Optimal', $false)
Remove-Item $stage -Recurse -Force
Set-Content -Path "$pd\python313._pth" -Value "python313.zip`r`n." -Encoding ascii -NoNewline

$size = (Get-ChildItem $Out -Recurse -File | Measure-Object Length -Sum).Sum
"Built $Out ($([math]::Round($size / 1MB)) MB)"
