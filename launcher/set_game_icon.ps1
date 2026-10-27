# Replaces the game executable's icon (group 1) with launcher/asr.ico, in place.
param([Parameter(Mandatory)][string]$Exe, [string]$Ico = (Join-Path $PSScriptRoot 'asr.ico'))
$ErrorActionPreference = 'Stop'
Add-Type @'
using System; using System.Runtime.InteropServices; using System.Collections.Generic;
public static class IconResource {
    delegate bool EnumLangs(IntPtr m, IntPtr type, IntPtr name, ushort lang, IntPtr p);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr LoadLibraryEx(string f, IntPtr h, uint flags);
    [DllImport("kernel32")] static extern bool EnumResourceLanguages(IntPtr m, IntPtr type, IntPtr name, EnumLangs cb, IntPtr p);
    [DllImport("kernel32")] static extern bool FreeLibrary(IntPtr m);
    [DllImport("kernel32", SetLastError=true, CharSet=CharSet.Unicode)] static extern IntPtr BeginUpdateResource(string f, bool deleteExisting);
    [DllImport("kernel32", SetLastError=true)] static extern bool UpdateResource(IntPtr h, IntPtr type, IntPtr name, ushort lang, byte[] data, uint size);
    [DllImport("kernel32", SetLastError=true)] static extern bool EndUpdateResource(IntPtr h, bool discard);
    public static List<ushort> Languages(string file, int type, int name) {
        var list = new List<ushort>(); IntPtr m = LoadLibraryEx(file, IntPtr.Zero, 2);
        EnumResourceLanguages(m, (IntPtr)type, (IntPtr)name, (a, b, c, lang, d) => { list.Add(lang); return true; }, IntPtr.Zero);
        FreeLibrary(m); return list;
    }
    public static void Replace(string file, byte[] ico, ushort lang, int oldIcons) {
        int count = BitConverter.ToUInt16(ico, 4);
        var group = new List<byte>(); group.AddRange(new byte[] { 0, 0, 1, 0 }); group.AddRange(BitConverter.GetBytes((ushort)count));
        IntPtr h = BeginUpdateResource(file, false);
        if (h == IntPtr.Zero) throw new System.ComponentModel.Win32Exception();
        for (int i = 0; i < count; i++) {
            int e = 6 + 16 * i; int size = BitConverter.ToInt32(ico, e + 8), offset = BitConverter.ToInt32(ico, e + 12);
            byte[] image = new byte[size]; Array.Copy(ico, offset, image, 0, size);
            if (!UpdateResource(h, (IntPtr)3, (IntPtr)(i + 1), lang, image, (uint)size)) throw new System.ComponentModel.Win32Exception();
            for (int k = 0; k < 8; k++) group.Add(ico[e + k]);           // width, height, colors, reserved, planes, bit count
            group.AddRange(BitConverter.GetBytes(size)); group.AddRange(BitConverter.GetBytes((ushort)(i + 1)));
        }
        for (int i = count + 1; i <= oldIcons; i++) UpdateResource(h, (IntPtr)3, (IntPtr)i, lang, null, 0);  // drop leftovers
        byte[] g = group.ToArray();
        if (!UpdateResource(h, (IntPtr)14, (IntPtr)1, lang, g, (uint)g.Length)) throw new System.ComponentModel.Win32Exception();
        if (!EndUpdateResource(h, false)) throw new System.ComponentModel.Win32Exception();
    }
}
'@
$Exe = (Resolve-Path $Exe).Path
$langs = [IconResource]::Languages($Exe, 14, 1)
if ($langs.Count -ne 1) { throw "Expected one icon group 1, found languages: $($langs -join ',')" }
$oldIcons = 1; while ([IconResource]::Languages($Exe, 3, $oldIcons + 1).Count -gt 0) { $oldIcons++ }
[IconResource]::Replace($Exe, [System.IO.File]::ReadAllBytes($Ico), $langs[0], $oldIcons)
Write-Host "Replaced the icon of $Exe (language $($langs[0]))"
