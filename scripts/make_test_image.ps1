# Generates a deterministic test image for VLM feasibility checks.
# Content is fixed so correctness of model answers is verifiable:
#   - dark blue background
#   - white text "HELLO 42" top-left
#   - red filled circle bottom-right
#   - green filled rectangle bottom-left
param(
    [string]$OutPath = "$PSScriptRoot\..\data\cache\test_frame_42.png",
    [switch]$VariantB
)
Add-Type -AssemblyName System.Drawing

$dir = Split-Path -Parent $OutPath
if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir | Out-Null }

$bmp = New-Object System.Drawing.Bitmap(640, 480)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias

if ($VariantB) {
    # Variant B: different text, colors, and layout for multi-image ordering tests.
    $g.Clear([System.Drawing.Color]::FromArgb(30, 30, 30))
    $font = New-Object System.Drawing.Font("Arial", 48, [System.Drawing.FontStyle]::Bold)
    $g.DrawString("SECOND 77", $font, [System.Drawing.Brushes]::Yellow, 40, 90)
    $g.FillEllipse([System.Drawing.Brushes]::Orange, 60, 320, 120, 120)     # orange circle left
    $g.FillRectangle([System.Drawing.Brushes]::Purple, 440, 330, 140, 90)   # purple rectangle right
} else {
    $g.Clear([System.Drawing.Color]::DarkBlue)
    $font = New-Object System.Drawing.Font("Arial", 48, [System.Drawing.FontStyle]::Bold)
    $g.DrawString("HELLO 42", $font, [System.Drawing.Brushes]::White, 40, 90)
    $g.FillEllipse([System.Drawing.Brushes]::Red, 440, 320, 120, 120)      # red circle
    $g.FillRectangle([System.Drawing.Brushes]::LimeGreen, 60, 330, 140, 90) # green rectangle
}

$g.Dispose()
$bmp.Save($OutPath, [System.Drawing.Imaging.ImageFormat]::Png)
$bmp.Dispose()
Write-Output "Wrote $OutPath"
