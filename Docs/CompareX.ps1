<#
Tool Name : CompareX
Author      : Shivaraj Hosur Sangu
email: shivaraj.hosur@ensono.com
Description :
    Compares baseline vs generated output files
    - AFTER CSV comparison
    - Root-level mixed file comparison
    - Generates HTML and Word reports
#>

# ==============================================================
# CompareX.ps1  (UPDATED: Beyond Compare used for PASS/FAIL)
# Runs BOTH comparisons:
# 1) AFTER-only CSV comparison
# 2) Root-level mixed files comparison (digit-start reconstruction)
# Adds interactive prompt to generate report ONLY on failures.
# below commad for generate report for all even failed files
#PS C:\Clients\SSAB.OX\baseline> & "C:\Clients\SSAB.OX\baseline\CompareX.ps1" SG02\P02070-HPPL486P -PromptOnFail $false -GenerateReportOn All
# ==============================================================

param(
  # NEW: pass like SG02\0231-Gcrs3214 (quotes optional)
  [Parameter(Position=0, Mandatory=$true)]
  [string]$ProgramRelPath,

  # Prompt per failed file (default: true)
  [bool]$PromptOnFail = $true,

  # Optional case-insensitive (used in RootMixed & report temp files)
  [bool]$IgnoreCase = $false,

  # Beyond Compare console executable (console version that waits & returns exit code)
  [string]$BeyondCompareExe = "C:\Program Files\Beyond Compare 5\BComp.com",

  # Report mode for PASS: 'Pass' | 'Fail' | 'All'
  # (FAIL is now interactive; this controls PASS behavior only)
  [ValidateSet('Pass','Fail','All')]
  [string]$GenerateReportOn = 'Pass'
)

# ----------------- Paths & patterns (DYNAMIC; unchanged behavior) -----------------
# Baseline root = folder where this script lives (e.g., D:\Users\shosur2\baseline)
$BaselineRoot  = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProgramRelPath = $ProgramRelPath.Trim()

# ProgramCode is the part after "SGxx\"
$ProgramCode   = ($ProgramRelPath -split '\\', 2)[1]

# --- Derived report name & title (bind to ProgramCode) ---
$ReportDocName = "$ProgramCode-REPORT.docx"
$ReportTitle   = "$ProgramCode Output Compare Report"

# ----------------- AFTER-only CSV -----------------
$After_LeftRoot   = Join-Path $BaselineRoot (Join-Path $ProgramRelPath 'FILES\AFTER')
$After_RightRoot  = Join-Path $BaselineRoot 'files\AFTER'   # constant for all programs
$After_ReportRoot = Join-Path $BaselineRoot (Join-Path $ProgramRelPath 'REPORT')
$After_Patterns   = @('*.csv')

# ----------------- Root-level mixed -----------------
$Root_LeftRoot    = Join-Path $BaselineRoot (Join-Path $ProgramRelPath 'FILES')
$Root_RightRoot   = Join-Path $BaselineRoot 'files'         # constant for all programs
$Root_ReportRoot  = Join-Path $BaselineRoot (Join-Path $ProgramRelPath 'REPORT')
$Root_Patterns    = @('*.csv','*.txt','*.seq')

# Optional: fail fast if folders are wrong
if (-not (Test-Path $Root_LeftRoot))  { throw "Left root not found: $Root_LeftRoot" }
if (-not (Test-Path $After_LeftRoot)) { throw "After left root not found: $After_LeftRoot" }

# ----------------- Helpers -----------------
function Assert-BC {
  if (-not (Test-Path -LiteralPath $BeyondCompareExe)) {
    throw "Beyond Compare console app not found: $BeyondCompareExe"
  }
}

function New-TempFileFromLines {
  param([Parameter(Mandatory=$true)][string[]]$Lines, [string]$Tag="qc")
  $p = Join-Path $env:TEMP ("bc_{0}_{1}.txt" -f $Tag, [guid]::NewGuid().Guid)
  Set-Content -LiteralPath $p -Value $Lines -Encoding UTF8
  return $p
}

function Invoke-BC-QuickCompareBinary {
  param(
    [Parameter(Mandatory=$true)][string]$LeftFile,
    [Parameter(Mandatory=$true)][string]$RightFile
  )
  Assert-BC
  # /quickcompare=binary => exit codes include:
  # 1 = Binary same, 11 = Binary differences (we use 1 for PASS, others for FAIL).  (Scooter docs)
  $psi = Start-Process -FilePath $BeyondCompareExe `
          -ArgumentList @("/quickcompare=binary", "`"$LeftFile`"", "`"$RightFile`"") `
          -WindowStyle Hidden -Wait -PassThru
  return $psi.ExitCode
}
function Test-BC-BinarySame {
  param([int]$ExitCode)
  return ($ExitCode -eq 1)  # 1 = Binary same
}

function Write-BC-HtmlReport {
  param(
    [Parameter(Mandatory=$true)][string]$LeftFile,
    [Parameter(Mandatory=$true)][string]$RightFile,
    [Parameter(Mandatory=$true)][string]$OutHtml
  )
  if (-not (Test-Path $BeyondCompareExe)) {
    Write-Host "⚠️ Beyond Compare not found at: $BeyondCompareExe — skipping report" -ForegroundColor Yellow
    return
  }
  $bcScript = @"
log normal append:""$env:TEMP\bc_text_report.log""
criteria rules-based ignore-unimportant
text-report layout:side-by-side options:ignore-unimportant,display-all output-to:""%3"" output-options:html-color ""%1"" ""%2""
"@
  $tmpScript = Join-Path $env:TEMP ("bc_text_report_" + [guid]::NewGuid().Guid + ".txt")
  Set-Content -LiteralPath $tmpScript -Value $bcScript -Encoding UTF8
  try {
    Start-Process -FilePath $BeyondCompareExe `
      -ArgumentList @("@`"$tmpScript`"", "`"$LeftFile`"", "`"$RightFile`"", "`"$OutHtml`"", "/closescript", "/silent") `
      -WindowStyle Hidden -Wait | Out-Null
    Write-Host " ↳ Report written: $OutHtml" -ForegroundColor DarkGray
  } finally {
    Remove-Item -LiteralPath $tmpScript -ErrorAction SilentlyContinue
  }
}

function Write-BC-Report-FromNormalized-AfterCsv {
  param(
    [Parameter(Mandatory=$true)][string[]]$LeftNormalizedSorted,
    [Parameter(Mandatory=$true)][string[]]$RightNormalizedSorted,
    [Parameter(Mandatory=$true)][string]$OutHtml
  )
  if (-not (Test-Path $BeyondCompareExe)) {
    Write-Host "⚠️ Beyond Compare not found at: $BeyondCompareExe — skipping report" -ForegroundColor Yellow
    return
  }
  $tmpLeft  = New-TempFileFromLines -Lines $LeftNormalizedSorted  -Tag "after_report_l"
  $tmpRight = New-TempFileFromLines -Lines $RightNormalizedSorted -Tag "after_report_r"
  try {
    Write-BC-HtmlReport -LeftFile $tmpLeft -RightFile $tmpRight -OutHtml $OutHtml
  } finally {
    Remove-Item -LiteralPath $tmpLeft,$tmpRight -ErrorAction SilentlyContinue
  }
}

function Write-BC-Report-FromNormalized-RootMixed {
  param(
    [Parameter(Mandatory=$true)][string[]]$LeftNormalizedSorted,
    [Parameter(Mandatory=$true)][string[]]$RightNormalizedSorted,
    [Parameter(Mandatory=$true)][string]$OutHtml
  )
  if (-not (Test-Path $BeyondCompareExe)) {
    Write-Host "⚠️ Beyond Compare not found at: $BeyondCompareExe — skipping report" -ForegroundColor Yellow
    return
  }
  $tmpLeft  = New-TempFileFromLines -Lines $LeftNormalizedSorted  -Tag "root_report_l"
  $tmpRight = New-TempFileFromLines -Lines $RightNormalizedSorted -Tag "root_report_r"
  try {
    Write-BC-HtmlReport -LeftFile $tmpLeft -RightFile $tmpRight -OutHtml $OutHtml
  } finally {
    Remove-Item -LiteralPath $tmpLeft,$tmpRight -ErrorAction SilentlyContinue
  }
}

# === AFTER CSV: normalized temp files for Beyond Compare HTML (unchanged) ===
function Build-NormalizedTempFiles-AfterCsv {
  param(
    [Parameter(Mandatory=$true)][string[]]$LeftRecords,
    [Parameter(Mandatory=$true)][string[]]$RightRecords
  )
  $normalizeLine = {
    param($line)
    $s = $line -replace '"', ''   
    $s = $s -replace '\s+', ''    # remove ALL whitespace
    # IGNORE datetime tokens (YYYY-MM-DD[ T]?HH:MM:SS[.fraction])
    $s = [regex]::Replace($s, '\b\d{4}-\d{2}-\d{2}(?:[ T]?)\d{2}:\d{2}:\d{2}(?:\.\d+)?\b', '')
    # Numeric normalization		
	$s = [regex]::Replace($s, '(?<=\d)\.(\d*?[1-9])0+(?=\D|$)', '.$1')  
	$s = [regex]::Replace($s, '(?<=\d)\.0+(?=\D|$)', '')                
	$s = [regex]::Replace($s, '(?<=\d)\.(?=\D|$)', '')                  

    return $s
  }
  # Keep original order for HTML visuals
  $leftOut  = $LeftRecords  | ForEach-Object { & $normalizeLine $_ } | Where-Object { $_ -ne '' }
  $rightOut = $RightRecords | ForEach-Object { & $normalizeLine $_ } | Where-Object { $_ -ne '' }
  $tmpLeft  = Join-Path $env:TEMP ("bc_norm_after_left_"  + [guid]::NewGuid().Guid + ".txt")
  $tmpRight = Join-Path $env:TEMP ("bc_norm_after_right_" + [guid]::NewGuid().Guid + ".txt")
  Set-Content -LiteralPath $tmpLeft  -Value $leftOut  -Encoding UTF8
  Set-Content -LiteralPath $tmpRight -Value $rightOut -Encoding UTF8
  return @{ Left=$tmpLeft; Right=$tmpRight }
}

# === ROOT MIXED: normalized temp files for Beyond Compare HTML (unchanged) ===
function Build-NormalizedTempFiles-RootMixed {
  param(
    [Parameter(Mandatory=$true)][string[]]$LeftRecords,
    [Parameter(Mandatory=$true)][string[]]$RightRecords,
    [Parameter(Mandatory=$true)][bool]$IgnoreCase
  )
  $normalizeLine = {
    param($line, $IgnoreCase)
    $s = $line
    # 1) NULL/control -> space
    $s = $s -replace "`0", " "
    $s = [regex]::Replace($s, '[\x00-\x08\x0B\x0C\x0E-\x1F]', ' ')
    # 2) Drop separator-only lines
    if ($s -match '^[\s=_-]+$') { return $null }
    # 3) Dates left intact by default
    # 4) Normalize isolated hyphen
    $s = [regex]::Replace($s, '(?<=\s)-(?=\s)', ' ')
    # 5) Strip leading '1'
    $s = [regex]::Replace($s, '^\s*1\s*-\s*', ' ')
    $s = [regex]::Replace($s, '^\s*1\s+', ' ')
    # 6) Remove ALL whitespace
    $s = $s -replace '\s+', ''
    # 7) Case-insensitive option
    if ($IgnoreCase) { $s = $s.ToLowerInvariant() }
    if ($s -and $s -ne '') { return $s } else { return $null }
  }
  # Keep original order for HTML visuals
  $leftOut  = $LeftRecords  | ForEach-Object { & $normalizeLine $_ $IgnoreCase } | Where-Object { $_ -ne $null }
  $rightOut = $RightRecords | ForEach-Object { & $normalizeLine $_ $IgnoreCase } | Where-Object { $_ -ne $null }
  $tmpLeft  = Join-Path $env:TEMP ("bc_norm_root_left_"  + [guid]::NewGuid().Guid + ".txt")
  $tmpRight = Join-Path $env:TEMP ("bc_norm_root_right_" + [guid]::NewGuid().Guid + ".txt")
  Set-Content -LiteralPath $tmpLeft  -Value $leftOut  -Encoding UTF8
  Set-Content -LiteralPath $tmpRight -Value $rightOut -Encoding UTF8
  return @{ Left=$tmpLeft; Right=$tmpRight }
}

# [AllowEmptyCollection()] for empty arrays during delta snippets
function Write-FailDeltaSnippet {
  param(
    [Parameter(Mandatory=$true)][string]$OutDir,
    [Parameter(Mandatory=$true)][string]$FileName,
    [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$LeftOnly,
    [Parameter(Mandatory=$true)][AllowEmptyCollection()][string[]]$RightOnly,
    [int]$Top = 25
  )
  try {
    $fn      = [System.IO.Path]::GetFileNameWithoutExtension($FileName)
    $outPath = Join-Path $OutDir ("{0}-delta.txt" -f $fn)
    $lines = @()
    $lines += "File: $FileName"
    $lines += "---- Left-only (top $Top) ----"
    $lines += ($LeftOnly  | Select-Object -First $Top)
    $lines += ""
    $lines += "---- Right-only (top $Top) ----"
    $lines += ($RightOnly | Select-Object -First $Top)
    Set-Content -Path $outPath -Value $lines -Encoding UTF8
    Write-Host " ↳ Delta snippet: $outPath" -ForegroundColor DarkGray
  } catch {
    Write-Host "⚠️ Failed to write delta snippet for ${FileName}: $($_.Exception.Message)" -ForegroundColor Yellow
  }
}

function Build-TempFiles-ForReport {
  param(
    [Parameter(Mandatory=$true)][string[]]$LeftRecords,
    [Parameter(Mandatory=$true)][string[]]$RightRecords,
    [Parameter(Mandatory=$true)][bool]$IgnoreCase
  )
  $normalizeForReport = {
    param($line, $IgnoreCase)
    $s = ($line -replace '\s+', ' ').Trim()
    if ($IgnoreCase) { $s = $s.ToLowerInvariant() }
    return $s
  }
  $leftOut  = $LeftRecords  | ForEach-Object { & $normalizeForReport $_ $IgnoreCase } | Sort-Object
  $rightOut = $RightRecords | ForEach-Object { & $normalizeForReport $_ $IgnoreCase } | Sort-Object
  $tmpLeft  = Join-Path $env:TEMP ("bc_report_left_"  + [guid]::NewGuid().Guid + ".txt")
  $tmpRight = Join-Path $env:TEMP ("bc_report_right_" + [guid]::NewGuid().Guid + ".txt")
  Set-Content -LiteralPath $tmpLeft  -Value $leftOut  -Encoding UTF8
  Set-Content -LiteralPath $tmpRight -Value $rightOut -Encoding UTF8
  return @{ Left=$tmpLeft; Right=$tmpRight }
}

function Ask-YesNo {
  param(
    [Parameter(Mandatory=$true)][string]$Message,
    [ValidateSet('Y','N')][string]$Default = 'N'
  )
  while ($true) {
    $resp = Read-Host "$Message [Y/N] (default: $Default)"
    if ([string]::IsNullOrWhiteSpace($resp)) { return ($Default -eq 'Y') }
    switch -Regex ($resp.Trim()) {
      '^(y|yes)$' { return $true }
      '^(n|no)$'  { return $false }
      default { Write-Host "Please answer Y or N." -ForegroundColor Yellow }
    }
  }
}

# ----------------- AFTER-only CSV functions (unchanged) -----------------
function Get-CsvRecords {
  param([Parameter(Mandatory=$true)][string]$FilePath)
  $records = New-Object System.Collections.Generic.List[string]
  $sb = New-Object System.Text.StringBuilder
  $quoteTot = 0
  foreach ($line in Get-Content -LiteralPath $FilePath) {
    [void]$sb.AppendLine($line)
    $quoteTot += ([regex]::Matches($line, '"').Count) # "" counts as two quotes -> parity stays correct
    if (($quoteTot % 2) -eq 0) {
      $rec = ($sb.ToString() -replace "`r?`n", " ").Trim() # keep word boundaries
      $records.Add($rec)
      $sb.Clear() | Out-Null
      $quoteTot = 0
    }
  }
  if ($sb.Length -gt 0) {
    $records.Add(($sb.ToString() -replace "`r?`n", " ").Trim())
  }
  return $records.ToArray()
}
function Normalize-Lines-AfterCsv {
  param([Parameter(Mandatory=$true)][string[]]$Lines,
  [switch]$PreserveWhitespaceForReport,   #added PreserveWhitespaceForReport switch for preserving whitespace
  [switch]$PreserveDateTimeForReport)      #Preserve datetime in report
  
  $normalized = foreach ($line in $Lines) {
    $s = $line -replace '"', ''    
    # $s = $s -replace '\s+', ''     # remove ALL whitespace
	
	#Default: remove ALL whitespace; below Report-only: preserve whitespace like original
	if (-not $PreserveWhitespaceForReport) {
			# remove all whitespace for comparison (original behavior)
			$s = $s -replace '\s+', ''
	} else {
			# preserve whitespace for HTML report
	}


    # Matches: YYYY-MM-DD[ optional ' ' or 'T' ]HH:MM:SS[.fraction]
	if (-not $PreserveDateTimeForReport) {
			$s = [regex]::Replace($s, '\b\d{4}-\d{2}-\d{2}(?:[ T]?)\d{2}:\d{2}:\d{2}(?:\.\d+)?\b', '')
	} else {
			# preserve DateTime Stamp for HTML report
	}

    # Trim trailing zeros after decimal, then drop trailing '.'    
	$s = [regex]::Replace($s, '(?<=\d)\.(\d*?[1-9])0+(?=\D|$)', '.$1') 
	$s = [regex]::Replace($s, '(?<=\d)\.0+(?=\D|$)', '')                
	$s = [regex]::Replace($s, '(?<=\d)\.(?=\D|$)', '')                  
    $s
  }
  $normalized | Where-Object { $_ -ne '' } | Sort-Object
}

# Robust record reconstruction (unchanged)
function Reconstruct-Records {
  param([Parameter(Mandatory=$true)][string]$FilePath)
  $records = New-Object System.Collections.Generic.List[string]
  $sb = New-Object System.Text.StringBuilder
  $quoteTot = 0
  foreach ($line in Get-Content -LiteralPath $FilePath) {
    [void]$sb.AppendLine($line)
    $quoteTot += ([regex]::Matches($line, '"').Count)
    if (($quoteTot % 2) -eq 0) {
      $rec = ($sb.ToString() -replace "`r?`n", " ").Trim()
      if ($rec -ne '') { $records.Add($rec) }
      $sb.Clear() | Out-Null
      $quoteTot = 0
    }
  }
  if ($sb.Length -gt 0) {
    $rec = ($sb.ToString() -replace "`r?`n", " ").Trim()
    if ($rec -ne '') { $records.Add($rec) }
  }
  return $records.ToArray()
}

function Normalize-Lines-RootMixed {
  param(
    [Parameter(Mandatory=$true)][string[]]$Lines,
    [bool]$IgnoreCase,
	[switch]$PreserveWhitespaceForReport   # <— NEW OPTIONAL SWITCH for White space preserved as ooriginal data
    )
  $normalized =
    $Lines |
    ForEach-Object {
      $s = $_
      $s = $s -replace "`0", " "
      $s = [regex]::Replace($s, '[\x00-\x08\x0B\x0C\x0E-\x1F]', ' ')
      # 2) Drop pure separator lines (only -, _, =, spaces)
      if ($s -match '^[\s=_-]+$') { return $null }
      # 3) Keep dates by default
      # 4) Normalize isolated hyphen tokens
      $s = [regex]::Replace($s, '(?<=\s)-(?=\s)', ' ')
      # 5) Strip leading standalone '1' (header controller) ONLY
      $s = [regex]::Replace($s, '^\s*1\s*-\s*', ' ')
      $s = [regex]::Replace($s, '^\s*1\s+', ' ')
      # 6) Remove ALL whitespace   ------> Its old one 
      #$s = $s -replace '\s+', ''	  
	  
	 # 6) Default: remove ALL whitespace; below Report-only: preserve whitespace like original
	  if (-not $PreserveWhitespaceForReport) {
		$s = $s -replace '\s+', ''
	  } else {
		 # Preserve whitespace as-is for the report rendering
	  }


      # 7) Case-insensitive option
      if ($IgnoreCase) { $s = $s.ToLowerInvariant() }
      $s
    } |
    Where-Object { $_ -and $_ -ne '' } |
    Sort-Object
  return $normalized
}

# --- Collect PASS/FAIL file names ---
$global:AcceptedDiffs = New-Object System.Collections.Generic.List[string]
$global:NoDiffs       = New-Object System.Collections.Generic.List[string]
function Add-PassFile { param([string]$FileName) $global:NoDiffs.Add($FileName) }
function Add-FailFile { param([string]$FileName) $global:AcceptedDiffs.Add($FileName) }

# this for ignoring special characters like GCRS1935 -> keep hooks above if needed:
# (Already added) Map special/extended spacing/control characters to spaces
# $s = $s -replace '[\u00A0\u1680\u2000-\\u200A\\u202F\\u205F\\u3000]', ' '
# $s = $s -replace '[\u200B\\u200C\\u200D\\u2060\\u200E\\u200F]', ' '
# $s = [regex]::Replace($s, '[\\x80-\\x9F]', ' ')
# $s = [regex]::Replace($s, '\\p{Cc}', ' ')
# $s = [regex]::Replace($s, '\\p{Z}', ' ')
# $s = [regex]::Replace($s, '[^\\p{L}\\p{Nd}]', ' ')  # Aggressive: collapse non-letters/digits

# ----------------- AFTER-only CSV comparison (NOW via Beyond Compare) -----------------
function Run-AfterCsvComparison {
  Write-Host "LEFT (baseline AFTER): $After_LeftRoot"
  Write-Host "RIGHT (generated AFTER): $After_RightRoot"
  Write-Host "Comparing CSV files ONLY with CSV-record reconstruction (order & whitespace ignored)..." -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path $After_ReportRoot | Out-Null

  $AllOk = $true
  $passCount = 0
  $failCount = 0

  foreach ($pat in $After_Patterns) {
    Get-ChildItem -Path $After_LeftRoot -Filter $pat -File | ForEach-Object {
      $leftFile  = $_.FullName
      $name      = $_.Name
      $rightFile = Join-Path $After_RightRoot $name

      if (-not (Test-Path $rightFile)) {
        Write-Host "MISSING on RIGHT: $name" -ForegroundColor Yellow
        Add-FailFile $name
        $AllOk = $false; $failCount++
        return
      }

      # Reconstruct & normalize (order-independent)
      $leftRecords  = Get-CsvRecords -FilePath $leftFile
      $rightRecords = Get-CsvRecords -FilePath $rightFile
      $L = Normalize-Lines-AfterCsv -Lines $leftRecords
      $R = Normalize-Lines-AfterCsv -Lines $rightRecords

      # === PASS/FAIL decision via Beyond Compare on the normalized arrays ===
      $tmpL = New-TempFileFromLines -Lines $L -Tag "after_qc_l"
      $tmpR = New-TempFileFromLines -Lines $R -Tag "after_qc_r"
      try {
        $code = Invoke-BC-QuickCompareBinary -LeftFile $tmpL -RightFile $tmpR
        if (Test-BC-BinarySame $code) {
          Write-Host "PASS (data identical after normalize): $name" -ForegroundColor Green
          Add-PassFile $name; $passCount++

          if ($GenerateReportOn -in @('Pass','All')) {
            $outHtml = Join-Path $After_ReportRoot ("$([System.IO.Path]::GetFileNameWithoutExtension($name)).html")
			# commented below its old one becuase need to preserve White spacs in report
            #Write-BC-Report-FromNormalized-AfterCsv -LeftNormalizedSorted $L -RightNormalizedSorted $R -OutHtml $outHtml
			
			# Build report arrays with whitespace preserved
			$L_report = Normalize-Lines-AfterCsv -Lines $leftRecords -PreserveWhitespaceForReport  -PreserveDateTimeForReport
			$R_report = Normalize-Lines-AfterCsv -Lines $rightRecords -PreserveWhitespaceForReport  -PreserveDateTimeForReport		
			Write-BC-Report-FromNormalized-AfterCsv -LeftNormalizedSorted  $L_report -RightNormalizedSorted $R_report -OutHtml $outHtml


          }
        } else {
          Write-Host "FAIL (data differs after normalize): $name" -ForegroundColor Red
          Add-FailFile $name; $AllOk = $false; $failCount++

          # For triage display/snippet only (BC already decided FAIL)
          #$diff = Compare-Object -ReferenceObject $L -DifferenceObject $R -IncludeEqual:$false
					  # Build report-friendly versions (preserve whitespace + datetime)
			$L_report = Normalize-Lines-AfterCsv `
						   -Lines $leftRecords `
						   -PreserveWhitespaceForReport `
						   -PreserveDateTimeForReport

			$R_report = Normalize-Lines-AfterCsv `
						   -Lines $rightRecords `
						   -PreserveWhitespaceForReport `
						   -PreserveDateTimeForReport

			# Delta computed on whitespace-preserved content
		  $diff = Compare-Object -ReferenceObject $L_report -DifferenceObject $R_report -IncludeEqual:$false
					  
          $leftOnly  = @($diff | Where-Object { $_.SideIndicator -eq '<=' } | Select-Object -ExpandProperty InputObject)
          $rightOnly = @($diff | Where-Object { $_.SideIndicator -eq '=>' } | Select-Object -ExpandProperty InputObject)
          Write-FailDeltaSnippet -OutDir $After_ReportRoot -FileName $name -LeftOnly $leftOnly -RightOnly $rightOnly -Top 25

          if ($leftOnly)  { Write-Host " Lines only in LEFT (normalized):"  -ForegroundColor DarkRed;    $leftOnly  | Select-Object -First 10 | ForEach-Object { Write-Host " $_" } }
          if ($rightOnly) { Write-Host " Lines only in RIGHT (normalized):" -ForegroundColor DarkYellow; $rightOnly | Select-Object -First 10 | ForEach-Object { Write-Host " $_" } }
		   
		  $doReport = $true
          if ($PromptOnFail) {
            $doReport = Ask-YesNo -Message "Generate Beyond Compare report for FAILED file '$name'?" -Default 'Y'
		  }
		  if ($doReport) {
              $outHtml = Join-Path $After_ReportRoot ("$([System.IO.Path]::GetFileNameWithoutExtension($name)).html")
			  # commented below its old one becuase need to preserve White spacs in report
              #Write-BC-Report-FromNormalized-AfterCsv -LeftNormalizedSorted $L -RightNormalizedSorted $R -OutHtml $outHtml		  
			  $L_report = Normalize-Lines-AfterCsv -Lines $leftRecords -PreserveWhitespaceForReport  -PreserveDateTimeForReport
			  $R_report = Normalize-Lines-AfterCsv -Lines $rightRecords -PreserveWhitespaceForReport  -PreserveDateTimeForReport
			  
			  Write-BC-Report-FromNormalized-AfterCsv -LeftNormalizedSorted  $L_report -RightNormalizedSorted $R_report -OutHtml $outHtml

            } else {
              Write-Host " ↳ Skipped report for FAILED file '$name'." -ForegroundColor DarkGray
            }
          
        }
      } finally {
        Remove-Item -LiteralPath $tmpL,$tmpR -ErrorAction SilentlyContinue
      }
    }
  }

  # Check for extra files on RIGHT
  foreach ($pat in $After_Patterns) {
    Get-ChildItem -Path $After_RightRoot -Filter $pat -File | ForEach-Object {
      $name = $_.Name
      if (-not (Test-Path (Join-Path $After_LeftRoot $name))) {
        Write-Host "EXTRA on RIGHT (no baseline): $name" -ForegroundColor DarkYellow
        Add-FailFile $name
        $AllOk = $false; $failCount++
      }
    }
  }

  Write-Host ""
  if ($AllOk) {
    Write-Host "✅ PASS (AFTER CSV): All AFTER CSVs match (ignoring order, whitespace, and embedded line breaks)." -ForegroundColor Green
  } else {
    Write-Host "❌ FAIL (AFTER CSV): Differences or missing/extra files detected." -ForegroundColor Red
  }
  Write-Host "Summary (AFTER CSV): $passCount pass, $failCount fail"
  return @{ AllOk=$AllOk; Pass=$passCount; Fail=$failCount }
}

# ----------------- Root-level mixed comparison (NOW via Beyond Compare) -----------------
function Run-RootMixedComparison {
  Write-Host "LEFT (baseline): $Root_LeftRoot"
  Write-Host "RIGHT (generated): $Root_RightRoot"
  Write-Host "Comparing root-level files only with record reconstruction (order & whitespace ignored)..." -ForegroundColor Cyan
  New-Item -ItemType Directory -Force -Path $Root_ReportRoot | Out-Null

  $AllOk = $true
  $passCount = 0
  $failCount = 0

  foreach ($pat in $Root_Patterns) {
    Get-ChildItem -Path $Root_LeftRoot -Filter $pat -File | ForEach-Object {
      $leftFile  = $_.FullName
      $name      = $_.Name
      $rightFile = Join-Path $Root_RightRoot $name

      if (-not (Test-Path $rightFile)) {
        Write-Host "MISSING on RIGHT: $name" -ForegroundColor Yellow
        Add-FailFile $name
        $AllOk = $false; $failCount++
        return
      }

      # Reconstruct & normalize (RootMixed behavior)
      $leftRecords  = Reconstruct-Records -FilePath $leftFile
      $rightRecords = Reconstruct-Records -FilePath $rightFile
      $L = Normalize-Lines-RootMixed -Lines $leftRecords  -IgnoreCase:$IgnoreCase
      $R = Normalize-Lines-RootMixed -Lines $rightRecords -IgnoreCase:$IgnoreCase

      # === PASS/FAIL decision via Beyond Compare on normalized arrays ===
      $tmpL = New-TempFileFromLines -Lines $L -Tag "root_qc_l"
      $tmpR = New-TempFileFromLines -Lines $R -Tag "root_qc_r"
      try {
        $code = Invoke-BC-QuickCompareBinary -LeftFile $tmpL -RightFile $tmpR
        if (Test-BC-BinarySame $code) {
          Write-Host "PASS (data identical after normalize): $name" -ForegroundColor Green
          Add-PassFile $name; $passCount++

          if ($GenerateReportOn -in @('Pass','All')) {
            $outHtml = Join-Path $Root_ReportRoot ("$([System.IO.Path]::GetFileNameWithoutExtension($name)).html")
			# commented below its old one becuase need to preserve White spacs in report
            #Write-BC-Report-FromNormalized-RootMixed -LeftNormalizedSorted $L -RightNormalizedSorted $R -OutHtml $outHtml  
		   
		  # Build report inputs that preserve whitespace (report only; comparison stays unchanged)
			$L_report = Normalize-Lines-RootMixed -Lines $leftRecords  -IgnoreCase:$IgnoreCase -PreserveWhitespaceForReport
			$R_report = Normalize-Lines-RootMixed -Lines $rightRecords -IgnoreCase:$IgnoreCase -PreserveWhitespaceForReport
			Write-BC-Report-FromNormalized-RootMixed -LeftNormalizedSorted $L_report -RightNormalizedSorted $R_report -OutHtml $outHtml

          }
        } else {
          Write-Host "FAIL (data differs after normalize): $name" -ForegroundColor Red
          Add-FailFile $name; $AllOk = $false; $failCount++

          # For triage display/snippet only (BC already decided FAIL)
          #$diff = Compare-Object -ReferenceObject $L -DifferenceObject $R -IncludeEqual:$false
		  # Build report-friendly versions (preserve whitespace)
		 $L_report = Normalize-Lines-RootMixed `
					   -Lines $leftRecords `
					   -IgnoreCase:$IgnoreCase `
					   -PreserveWhitespaceForReport

		 $R_report = Normalize-Lines-RootMixed `
					   -Lines $rightRecords `
					   -IgnoreCase:$IgnoreCase `
					   -PreserveWhitespaceForReport

		 $diff = Compare-Object -ReferenceObject $L_report -DifferenceObject $R_report -IncludeEqual:$false

          $leftOnly  = @($diff | Where-Object { $_.SideIndicator -eq '<=' } | Select-Object -ExpandProperty InputObject)
          $rightOnly = @($diff | Where-Object { $_.SideIndicator -eq '=>' } | Select-Object -ExpandProperty InputObject)
          Write-FailDeltaSnippet -OutDir $Root_ReportRoot -FileName $name -LeftOnly $leftOnly -RightOnly $rightOnly -Top 25

          if ($leftOnly)  { Write-Host " Lines only in LEFT (normalized):"  -ForegroundColor DarkRed;    $leftOnly  | Select-Object -First 10 | ForEach-Object { Write-Host " $_" } }
          if ($rightOnly) { Write-Host " Lines only in RIGHT (normalized):" -ForegroundColor DarkYellow; $rightOnly | Select-Object -First 10 | ForEach-Object { Write-Host " $_" } }
		  $doReport = $true
          if ($PromptOnFail) {
            $doReport = Ask-YesNo -Message "Generate Beyond Compare report for FAILED file '$name'?" -Default 'Y'
		  }
            if ($doReport) {
              $outHtml = Join-Path $Root_ReportRoot ("$([System.IO.Path]::GetFileNameWithoutExtension($name)).html")
			  # commented below its old one becuase need to preserve White spacs in report for like PASSSS
              #Write-BC-Report-FromNormalized-RootMixed -LeftNormalizedSorted $L -RightNormalizedSorted $R -OutHtml $outHtml
			  	  
			  #Build report inputs that preserve whitespace (report only; comparison stays unchanged)
			  $L_report = Normalize-Lines-RootMixed -Lines $leftRecords  -IgnoreCase:$IgnoreCase -PreserveWhitespaceForReport
			  $R_report = Normalize-Lines-RootMixed -Lines $rightRecords -IgnoreCase:$IgnoreCase -PreserveWhitespaceForReport
			  Write-BC-Report-FromNormalized-RootMixed -LeftNormalizedSorted $L_report -RightNormalizedSorted $R_report -OutHtml $outHtml

            } else {
              Write-Host " ↳ Skipped report for FAILED file '$name'." -ForegroundColor DarkGray
            }
          
        }
      } finally {
        Remove-Item -LiteralPath $tmpL,$tmpR -ErrorAction SilentlyContinue
      }
    }
  }

  # Check for extra files on RIGHT
  foreach ($pat in $Root_Patterns) {
    Get-ChildItem -Path $Root_RightRoot -Filter $pat -File | ForEach-Object {
      $name = $_.Name
      if (-not (Test-Path (Join-Path $Root_LeftRoot $name))) {
        Write-Host "EXTRA on RIGHT (no baseline): $name" -ForegroundColor DarkYellow
        Add-FailFile $name
        $AllOk = $false; $failCount++
      }
    }
  }

  Write-Host ""
  if ($AllOk) {
    Write-Host "✅ PASS (Root Mixed): All root-level files match (ignoring order, whitespace, and line breaks)." -ForegroundColor Green
  } else {
    Write-Host "❌ FAIL (Root Mixed): Differences or missing/extra files detected." -ForegroundColor Red
  }
  Write-Host "Summary (Root Mixed): $passCount pass, $failCount fail"
  return @{ AllOk=$AllOk; Pass=$passCount; Fail=$failCount }
}

function Write-WordSummary {
  param(
    [string]$OutDir,
    [string]$DocName = $ReportDocName,
    [string]$Title   = $ReportTitle
  )
  $outPath = [string](Join-Path $OutDir $DocName)
  try { $word = New-Object -ComObject Word.Application } catch {
    Write-Host "⚠️ Word not available; writing text fallback." -ForegroundColor Yellow
    $txtPath = [System.IO.Path]::ChangeExtension($outPath,'txt')
    $content = @()
    $content += $Title
    $content += ""
    $content += "Accepted Differences"
    $content += $global:AcceptedDiffs
    $content += ""
    $content += "No Differences"
    $content += $global:NoDiffs
    Set-Content -Path $txtPath -Value $content -Encoding UTF8
    Write-Host "↳ Fallback report: $txtPath"
    return
  }
  $word.Visible = $false
  $doc = $word.Documents.Add()
  $sel = $word.Selection

  # Title
  $sel.Style = $word.ActiveDocument.Styles.Item("Title")
  $sel.TypeText($Title)
  $sel.TypeParagraph()

  # Accepted Differences
  $sel.Style = $word.ActiveDocument.Styles.Item("Heading 1")
  $sel.TypeText("Accepted Differences")
  $sel.TypeParagraph()
  foreach ($f in $global:AcceptedDiffs) { $sel.TypeText($f); $sel.TypeParagraph() }

  # No Differences
  $sel.Style = $word.ActiveDocument.Styles.Item("Heading 1")
  $sel.TypeText("No Differences")
  $sel.TypeParagraph()
  foreach ($f in $global:NoDiffs) { $sel.TypeText($f); $sel.TypeParagraph() }

  $wdFormatXMLDocument = 12 # Word .docx
  try {
    $doc.SaveAs($outPath, $wdFormatXMLDocument)
    
} catch {
	$doc.Close()
    $word.Quit()
    Write-Host "⚠️ Word auto-save failed. Please save manually if Word popup appeared." -ForegroundColor Yellow
    Write-Host "   Expected path: $outPath" -ForegroundColor Yellow
}
  [System.Runtime.InteropServices.Marshal]::ReleaseComObject($word) | Out-Null
  Write-Host "↳ Word report written: $outPath" -ForegroundColor DarkBlue
}

# ----------------- Run BOTH comparisons and summarize the results for both 1. -----------------
$resultAfter = Run-AfterCsvComparison
$resultRoot  = Run-RootMixedComparison

Write-Host ""
Write-Host "================== OVERALL SUMMARY =================="
Write-Host ("AFTER CSV : {0} pass, {1} fail" -f $resultAfter.Pass, $resultAfter.Fail)
Write-Host ("Root Mixed : {0} pass, {1} fail" -f $resultRoot.Pass,  $resultRoot.Fail)
$overallOk = ($resultAfter.AllOk -and $resultRoot.AllOk)

# --- CALL THE WORD WRITER RIGHT BEFORE EXIT ---
$ReportOutDir = $Root_ReportRoot
Write-WordSummary -OutDir $ReportOutDir

if ($overallOk) {
  Write-Host "✅ OVERALL: PASS (both sections)" -ForegroundColor Green
  exit 0
} else {
  Write-Host "❌ OVERALL: FAIL (one or both sections found issues)" -ForegroundColor Red
  exit 1
}