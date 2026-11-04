# QuillSail installer for Windows.
#
#   irm __QUILLSAIL_SITE_URL__/install.ps1 | iex
#
# Installs the QuillSail desktop app for your Windows account and a `quillsail`
# command for your terminal. The download is checked against the size and SHA-256
# checksum listed in QuillSail's signed release feed before anything is
# installed. No administrator rights are needed, and publications are never touched.
#
# Settings, as environment variables set before running the command:
#
#   $env:QUILLSAIL_CHANNEL = 'stable'          # Default: beta, while QuillSail is in beta.
#   $env:QUILLSAIL_INSTALL_DIR = 'D:\Apps'     # Default: %LOCALAPPDATA%\Programs
#   $env:QUILLSAIL_BIN_DIR = 'D:\Tools'        # Default: %USERPROFILE%\.local\bin
#   $env:QUILLSAIL_NO_MODIFY_PATH = '1'        # Don't add the command's folder to PATH.
#   $env:QUILLSAIL_UNINSTALL = '1'             # Remove the app and command. Publications are kept.
#
# Works in Windows PowerShell 5.1 and PowerShell 7.

# Everything runs from Install-QuillSail, at the very end, so a partly downloaded script does nothing.

function Install-QuillSail {
    # Set inside the function: `irm | iex` runs in your session, and these shouldn't outlast the install.
    $ErrorActionPreference = 'Stop'
    $ProgressPreference = 'SilentlyContinue'
    Set-StrictMode -Version 2

    $Site = '__QUILLSAIL_SITE_URL__'
    $MarkerLine = 'rem Installed by the QuillSail installer.'
    $Target = 'windows-x86_64'

    function Say([string] $Message) { Write-Host $Message }
    function Step([string] $Message) { Write-Host "> $Message" }
    function Note([string] $Message) { Write-Host "Note: $Message" -ForegroundColor Yellow }
    function Stop-Install([string] $Message) { throw "QuillSail was not installed. $Message" }
    function Setting([string] $Name, [string] $Default) {
        $value = [Environment]::GetEnvironmentVariable($Name)
        if ([string]::IsNullOrWhiteSpace($value)) { return $Default }
        return $value.Trim()
    }

    $channel = Setting 'QUILLSAIL_CHANNEL' 'beta'
    $installDir = Setting 'QUILLSAIL_INSTALL_DIR' (Join-Path $env:LOCALAPPDATA 'Programs')
    $binDir = Setting 'QUILLSAIL_BIN_DIR' (Join-Path $HOME '.local\bin')
    $modifyPath = (Setting 'QUILLSAIL_NO_MODIFY_PATH' '0') -ne '1'
    $uninstall = (Setting 'QUILLSAIL_UNINSTALL' '0') -eq '1'

    if ($channel -notin @('beta', 'stable')) { Stop-Install "Choose the beta or stable channel, not '$channel'." }
    if (-not ($Site.StartsWith('https://') -or $Site -match '^http://(127\.0\.0\.1|localhost)(:\d+)?$')) {
        Stop-Install 'The installer must come from an https:// address.'
    }

    $installDir = [IO.Path]::GetFullPath($installDir)
    $binDir = [IO.Path]::GetFullPath($binDir)
    $app = Join-Path $installDir 'QuillSail'
    $exe = Join-Path $app 'QuillSail.exe'
    $marker = Join-Path $app 'quillsail-install.json'
    $command = Join-Path $binDir 'quillsail.cmd'
    $shortcut = Join-Path ([Environment]::GetFolderPath('Programs')) 'QuillSail.lnk'
    $dataDir = Join-Path $env:LOCALAPPDATA 'QuillSail'

    function Get-InstalledVersion {
        if (-not (Test-Path -LiteralPath $marker -PathType Leaf)) { return $null }
        try { return (Get-Content -LiteralPath $marker -Raw | ConvertFrom-Json).version } catch { return $null }
    }

    function Test-OurCommand {
        if (-not (Test-Path -LiteralPath $command -PathType Leaf)) { return $false }
        return (Get-Content -LiteralPath $command -Raw).Contains($MarkerLine)
    }

    function Assert-NotRunning {
        $running = Get-Process -Name 'QuillSail' -ErrorAction SilentlyContinue |
            Where-Object { $_.Path -and $_.Path -ieq $exe }
        if ($running) { Stop-Install 'QuillSail is running. Run quillsail instance stop --all and quillsail quit, then run the installer again.' }
    }

    # --- uninstall -----------------------------------------------------------------------------

    if ($uninstall) {
        $removed = $false
        if (Get-InstalledVersion) {
            Assert-NotRunning
            Remove-Item -LiteralPath $app -Recurse -Force
            Say "Removed $app"
            $removed = $true
        } elseif (Test-Path -LiteralPath $app) {
            Note "$app isn't a QuillSail installation, so it was left alone."
        }
        if (Test-OurCommand) {
            Remove-Item -LiteralPath $command -Force
            Say "Removed $command"
            $removed = $true
        }
        if (Test-Path -LiteralPath $shortcut) {
            $link = (New-Object -ComObject WScript.Shell).CreateShortcut($shortcut)
            if ($link.TargetPath -ieq $exe) {
                Remove-Item -LiteralPath $shortcut -Force
                Say 'Removed the Start menu shortcut'
            }
        }
        if (-not $removed) { Say "QuillSail wasn't installed by this installer, so nothing was removed." }
        Say ''
        Say "Your publications are still in $dataDir. Delete that folder if you no longer need them."
        return
    }

    # --- checks --------------------------------------------------------------------------------

    if (-not [Environment]::Is64BitOperatingSystem) { Stop-Install 'QuillSail needs 64-bit Windows.' }
    $processor = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $processor = $env:PROCESSOR_ARCHITEW6432 }
    if ($processor -eq 'ARM64') { Note "This PC has an ARM processor. QuillSail's x64 app runs through Windows' built-in emulation." }

    # Windows PowerShell 5.1 may not offer TLS 1.2 by default.
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

    try {
        $release = Invoke-RestMethod -UseBasicParsing -Uri "$Site/api/v1/releases/latest/$($Target)?channel=$channel"
    } catch {
        Stop-Install "Release details couldn't be downloaded from $Site. Check your connection and try again in a few minutes."
    }
    $version = [string] $release.version
    $archive = [string] $release.archive
    $sha256 = ([string] $release.sha256).ToLowerInvariant()
    $size = [int64] $release.size
    $url = [string] $release.url
    if ($version -notmatch '^\d+\.\d+\.\d+$' -or $sha256 -notmatch '^[0-9a-f]{64}$' -or $size -le 0 -or
        $archive -ne "QuillSail-$version-$Target.zip") {
        Stop-Install "The release details from $Site weren't in the expected format."
    }
    if (-not ($url.StartsWith('https://') -or (-not $Site.StartsWith('https://') -and $url -match '^http://(127\.0\.0\.1|localhost):\d+/'))) {
        Stop-Install 'The download address must use https://.'
    }

    $current = Get-InstalledVersion
    if ((Test-Path -LiteralPath $app) -and -not $current) {
        Stop-Install "$app already exists and isn't a QuillSail installation. Move it, or set QUILLSAIL_INSTALL_DIR to another folder."
    }

    # --- download, check and install -----------------------------------------------------------

    if ($current -eq $version) {
        Say "QuillSail $version is already installed at $app."
    } else {
        Assert-NotRunning
        New-Item -ItemType Directory -Force -Path $installDir | Out-Null
        $work = Join-Path ([IO.Path]::GetTempPath()) ('quillsail-install-' + [Guid]::NewGuid().ToString('N'))
        $staged = Join-Path $installDir ('.quillsail-install-' + $PID)
        New-Item -ItemType Directory -Force -Path $work | Out-Null
        try {
            $zip = Join-Path $work $archive
            Step "Downloading QuillSail $version for 64-bit Windows..."
            try {
                Invoke-WebRequest -UseBasicParsing -Uri $url -OutFile $zip
            } catch {
                Stop-Install "The download didn't finish. Check your connection and try again."
            }
            Step 'Checking the download...'
            $actualSize = (Get-Item -LiteralPath $zip).Length
            if ($actualSize -ne $size) { Stop-Install "The download is $actualSize bytes, but the signed release lists $size. Nothing was changed." }
            $actual = (Get-FileHash -LiteralPath $zip -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($actual -ne $sha256) { Stop-Install "The download's SHA-256 checksum doesn't match the signed release. Nothing was changed." }

            # Every file must sit inside the app's own folder.
            Add-Type -AssemblyName System.IO.Compression.FileSystem
            $reader = [IO.Compression.ZipFile]::OpenRead($zip)
            try {
                foreach ($entry in $reader.Entries) {
                    $name = $entry.FullName.Replace('\', '/')
                    if (-not $name.StartsWith('QuillSail/') -or $name -match '(^|/)\.\.(/|$)' -or $name -match ':') {
                        Stop-Install "The download contains an unexpected path ($name). Nothing was changed."
                    }
                }
            } finally {
                $reader.Dispose()
            }

            Step "Installing to $app..."
            if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Recurse -Force }
            # Unpack beside the destination, so the final step is a rename on one disk. This is much
            # faster than Expand-Archive, and also refuses entries that would land outside $staged.
            [IO.Compression.ZipFile]::ExtractToDirectory($zip, $staged)
            $new = Join-Path $staged 'QuillSail'
            $newMarker = Join-Path $new 'quillsail-install.json'
            $details = $null
            try { $details = Get-Content -LiteralPath $newMarker -Raw | ConvertFrom-Json } catch { }
            if (-not $details -or $details.version -ne $version -or $details.target -ne $Target) {
                Stop-Install "The unpacked app doesn't match QuillSail $version for this computer. Nothing was changed."
            }
            $previous = $null
            if (Test-Path -LiteralPath $app) {
                $previous = Join-Path $staged 'previous'
                Move-Item -LiteralPath $app -Destination $previous
            }
            try {
                Move-Item -LiteralPath $new -Destination $app
            } catch {
                if ($previous) { Move-Item -LiteralPath $previous -Destination $app }
                Stop-Install 'The new app could not be moved into place. The previous version was kept.'
            }
        } finally {
            if (Test-Path -LiteralPath $staged) { Remove-Item -LiteralPath $staged -Recurse -Force -ErrorAction SilentlyContinue }
            if (Test-Path -LiteralPath $work) { Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue }
        }
    }

    # --- shortcut, command and PATH ------------------------------------------------------------

    try {
        $shell = New-Object -ComObject WScript.Shell
        $link = $shell.CreateShortcut($shortcut)
        $link.TargetPath = $exe
        $link.WorkingDirectory = $app
        $link.Description = 'Blogs and newsletters where readers write'
        $link.Save()
    } catch {
        Note 'The Start menu shortcut could not be created.'
    }

    $commandStatus = 'written'
    $other = @('quillsail.exe', 'quillsail.bat') | ForEach-Object { Join-Path $binDir $_ } |
        Where-Object { Test-Path -LiteralPath $_ }
    if (((Test-Path -LiteralPath $command) -and -not (Test-OurCommand)) -or $other) {
        $commandStatus = 'kept'
    } else {
        New-Item -ItemType Directory -Force -Path $binDir | Out-Null
        # cmd.exe expands %LOCALAPPDATA% itself, which also copes with non-ASCII user folders.
        $default = Join-Path $env:LOCALAPPDATA 'Programs\QuillSail\QuillSail.exe'
        $target = $exe
        if ($exe -ieq $default) { $target = '%LOCALAPPDATA%\Programs\QuillSail\QuillSail.exe' }
        $lines = @(
            '@echo off',
            "$MarkerLine Runs the quillsail command from the app.",
            "rem Remove it with: `$env:QUILLSAIL_UNINSTALL = '1'; irm $Site/install.ps1 | iex",
            "`"$target`" cli %*"
        )
        $oem = [Text.Encoding]::GetEncoding([Globalization.CultureInfo]::CurrentCulture.TextInfo.OEMCodePage)
        [IO.File]::WriteAllText($command, ($lines -join "`r`n") + "`r`n", $oem)
    }

    $pathChanged = $false
    if ($commandStatus -eq 'written' -and $modifyPath) {
        # Read the raw registry value so entries such as %USERPROFILE%\bin stay unexpanded.
        $key = Get-Item -LiteralPath 'HKCU:\Environment'
        $raw = ''
        if ($key.GetValueNames() -contains 'Path') { $raw = [string] $key.GetValue('Path', '', 'DoNotExpandEnvironmentNames') }
        $entries = @($raw.Split(';') | Where-Object { $_ })
        $present = $entries | Where-Object { [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -ieq $binDir.TrimEnd('\') }
        if (-not $present) {
            Set-ItemProperty -LiteralPath 'HKCU:\Environment' -Name 'Path' -Value (($entries + $binDir) -join ';') -Type ExpandString
            # Setting any user variable tells Windows (and new terminals) that the environment changed.
            [Environment]::SetEnvironmentVariable('QUILLSAIL_INSTALLER', '1', 'User')
            [Environment]::SetEnvironmentVariable('QUILLSAIL_INSTALLER', $null, 'User')
            $env:Path = "$env:Path;$binDir"
            $pathChanged = $true
        }
    }

    # --- results -------------------------------------------------------------------------------

    $installed = Get-InstalledVersion
    Say ''
    Say "QuillSail $installed is installed."
    Say "  App      $app"
    if ($commandStatus -eq 'written') {
        Say "  Command  $command"
    } else {
        Note "A quillsail command already exists in $binDir and wasn't made by this installer, so it was left alone."
    }
    Say ''
    if ($pathChanged) { Say "Added $binDir to your PATH. Open a new terminal, then start your publication: quillsail instance" }
    elseif ($commandStatus -eq 'written') { Say 'Start your publication: quillsail instance' }
    if ($commandStatus -eq 'written') {
        Say 'Open the desktop window: quillsail desktop'
        Say 'See every command: quillsail'
    }
    Say 'You can also open QuillSail from the Start menu.'
    Say "Your publications are kept in $dataDir."
}

Install-QuillSail
