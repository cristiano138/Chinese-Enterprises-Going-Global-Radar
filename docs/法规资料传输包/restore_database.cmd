@echo off
setlocal
cd /d "%~dp0"
if exist "regulations.sqlite3" (
  echo STOP: regulations.sqlite3 already exists. Move it before restoring.
  pause
  exit /b 1
)
if not exist "regulations.sqlite3.part001" (
  echo MISSING: regulations.sqlite3.part001. Extract ALL ZIP files into this folder.
  pause
  exit /b 1
)
if not exist "regulations.sqlite3.part002" (
  echo MISSING: regulations.sqlite3.part002. Extract ALL ZIP files into this folder.
  pause
  exit /b 1
)
if not exist "regulations.sqlite3.part003" (
  echo MISSING: regulations.sqlite3.part003. Extract ALL ZIP files into this folder.
  pause
  exit /b 1
)
if not exist "regulations.sqlite3.part004" (
  echo MISSING: regulations.sqlite3.part004. Extract ALL ZIP files into this folder.
  pause
  exit /b 1
)
if not exist "regulations.sqlite3.part005" (
  echo MISSING: regulations.sqlite3.part005. Extract ALL ZIP files into this folder.
  pause
  exit /b 1
)
echo Checking all parts. Please wait...
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; function FileHash($p){$s=[System.IO.File]::OpenRead($p);$h=[System.Security.Cryptography.SHA256]::Create();try{[System.BitConverter]::ToString($h.ComputeHash($s)).Replace('-','')}finally{$s.Dispose();$h.Dispose()}}; $m=Get-Content -Raw -LiteralPath 'manifest.json' | ConvertFrom-Json; foreach($p in $m.parts){if((Get-Item -LiteralPath $p.file).Length -ne $p.bytes){throw ('Wrong size: '+$p.file)}; if((FileHash $p.file) -ne $p.sha256){throw ('Checksum mismatch: '+$p.file)}}"
if errorlevel 1 goto failed
echo Restoring database...
copy /b "regulations.sqlite3.part001"+"regulations.sqlite3.part002"+"regulations.sqlite3.part003"+"regulations.sqlite3.part004"+"regulations.sqlite3.part005" "regulations.sqlite3" >nul
if errorlevel 1 goto failed
powershell.exe -NoProfile -Command "$ErrorActionPreference='Stop'; function FileHash($p){$s=[System.IO.File]::OpenRead($p);$h=[System.Security.Cryptography.SHA256]::Create();try{[System.BitConverter]::ToString($h.ComputeHash($s)).Replace('-','')}finally{$s.Dispose();$h.Dispose()}}; if((FileHash 'regulations.sqlite3') -ne 'bfb145a5c8ccf6a65809ddc237bdf0e463efc4e03e1b6e52dee64c0f9150012b'){Write-Error 'Final checksum mismatch'; exit 1}"
if errorlevel 1 goto failed
echo SUCCESS: regulations.sqlite3 restored and SHA256 verified.
pause
exit /b 0
:failed
echo FAILED. Do not use a partial output. Keep your original ZIP files.
pause
exit /b 1
