# Draws launcher/asr.ico (16-256 px): a gold shield with a sword on the launcher's dark slate.
param([string]$Out = (Join-Path $PSScriptRoot 'asr.ico'), [string]$Preview)
Add-Type -AssemblyName System.Drawing

function Draw([int]$size) {
    $bmp = New-Object System.Drawing.Bitmap $size, $size
    $g = [System.Drawing.Graphics]::FromImage($bmp)
    $g.SmoothingMode = 'AntiAlias'; $g.PixelOffsetMode = 'HighQuality'
    $s = $size / 256.0
    function P([double]$x, [double]$y) { New-Object System.Drawing.PointF ([float]($x * $s)), ([float]($y * $s)) }
    # Rounded slate tile.
    $tile = New-Object System.Drawing.Drawing2D.GraphicsPath
    $r = 56 * $s; $w = 248 * $s; $o = 4 * $s
    $tile.AddArc($o, $o, $r, $r, 180, 90); $tile.AddArc($o + $w - $r, $o, $r, $r, 270, 90)
    $tile.AddArc($o + $w - $r, $o + $w - $r, $r, $r, 0, 90); $tile.AddArc($o, $o + $w - $r, $r, $r, 90, 90); $tile.CloseFigure()
    $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush (P 0 0), (P 0 256), ([System.Drawing.Color]::FromArgb(40, 48, 58)), ([System.Drawing.Color]::FromArgb(18, 22, 27))
    $g.FillPath($bg, $tile)
    # Shield.
    $shield = New-Object System.Drawing.Drawing2D.GraphicsPath
    $shield.AddBezier((P 128 30), (P 160 44), (P 196 46), (P 214 44))
    $shield.AddBezier((P 214 44), (P 218 140), (P 186 196), (P 128 232))
    $shield.AddBezier((P 128 232), (P 70 196), (P 38 140), (P 42 44))
    $shield.AddBezier((P 42 44), (P 60 46), (P 96 44), (P 128 30))
    $gold = New-Object System.Drawing.Drawing2D.LinearGradientBrush (P 0 30), (P 0 232), ([System.Drawing.Color]::FromArgb(250, 214, 120)), ([System.Drawing.Color]::FromArgb(196, 132, 40))
    $g.FillPath($gold, $shield)
    $inner = $shield.Clone(); $m = New-Object System.Drawing.Drawing2D.Matrix
    $m.Translate(128 * $s, 132 * $s); $m.Scale(0.78, 0.78); $m.Translate(-128 * $s, -132 * $s); $inner.Transform($m)
    $g.FillPath((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(122, 28, 30))), $inner)
    # Sword: blade, guard, grip, pommel.
    $steel = New-Object System.Drawing.Drawing2D.LinearGradientBrush (P 116 0), (P 140 0), ([System.Drawing.Color]::FromArgb(250, 250, 245)), ([System.Drawing.Color]::FromArgb(168, 176, 186))
    $g.FillPolygon($steel, [System.Drawing.PointF[]]@((P 128 54), (P 140 76), (P 140 166), (P 116 166), (P 116 76)))
    $g.FillRectangle($gold, 88 * $s, 162 * $s, 80 * $s, 14 * $s)
    $g.FillRectangle((New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(64, 38, 22))), 120 * $s, 176 * $s, 16 * $s, 30 * $s)
    $g.FillEllipse($gold, 117 * $s, 202 * $s, 22 * $s, 22 * $s)
    $g.Dispose()
    return $bmp
}

$sizes = 256, 128, 64, 48, 32, 24, 16
$images = foreach ($size in $sizes) {
    $bmp = Draw $size
    if ($Preview -and $size -eq 256) { $bmp.Save($Preview, [System.Drawing.Imaging.ImageFormat]::Png) }
    $ms = New-Object System.IO.MemoryStream; $bmp.Save($ms, [System.Drawing.Imaging.ImageFormat]::Png); $bmp.Dispose()
    , $ms.ToArray()
}
# ICO container with PNG-compressed entries.
$file = New-Object System.IO.MemoryStream; $w = New-Object System.IO.BinaryWriter $file
$w.Write([uint16]0); $w.Write([uint16]1); $w.Write([uint16]$sizes.Count)
$offset = 6 + 16 * $sizes.Count
for ($i = 0; $i -lt $sizes.Count; $i++) {
    $d = if ($sizes[$i] -ge 256) { 0 } else { $sizes[$i] }
    $w.Write([byte]$d); $w.Write([byte]$d); $w.Write([byte]0); $w.Write([byte]0)
    $w.Write([uint16]1); $w.Write([uint16]32); $w.Write([uint32]$images[$i].Length); $w.Write([uint32]$offset)
    $offset += $images[$i].Length
}
foreach ($img in $images) { $w.Write($img) }
[System.IO.File]::WriteAllBytes($Out, $file.ToArray())
Write-Host "Wrote $Out"
