# Measures peak working set of whisper-cli during a transcription run.
param(
    [string]$Model = "downloads\whisper-models\ggml-base.en.bin",
    [string]$Audio = "data\stt\fixtures\meatthezoo_16k.wav"
)
$exe = Join-Path $PSScriptRoot "..\downloads\whisper-cpp\Release\whisper-cli.exe"
$outFile = Join-Path $env:TEMP "whisper_mem_out.txt"

$p = Start-Process -FilePath $exe `
    -ArgumentList "-m", $Model, "-f", $Audio, "-l", "en", "-np" `
    -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $outFile

$peak = 0
while (-not $p.HasExited) {
    $p.Refresh()
    if ($p.WorkingSet64 -gt $peak) { $peak = $p.WorkingSet64 }
    Start-Sleep -Milliseconds 50
}
Write-Output ("peak working set: {0:N1} MB" -f ($peak / 1MB))
