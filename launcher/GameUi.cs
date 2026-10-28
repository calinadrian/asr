// Match the native game's Options controls; fonts are read from the player's existing game data.
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Text;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text;
using System.Windows.Forms;

namespace ASR.Setup {
    internal static class GameUi {
        public static readonly Color Backdrop = Color.FromArgb(7, 6, 3), Panel = Color.FromArgb(17, 13, 7),
            Well = Color.FromArgb(10, 8, 4), Gold = Color.FromArgb(255, 211, 86), Text = Color.FromArgb(238, 215, 156),
            Muted = Color.FromArgb(195, 175, 123), Border = Color.FromArgb(129, 101, 35);
        public sealed class Frame : System.Windows.Forms.Panel {
            public Frame() { DoubleBuffered = true; BackColor = Panel; }
            protected override void OnPaint(PaintEventArgs e) {
                base.OnPaint(e); e.Graphics.SmoothingMode = SmoothingMode.AntiAlias;
                using (var path = Outline(new Rectangle(0, 0, Width-1, Height-1), 6))
                using (var pen = new Pen(Border)) e.Graphics.DrawPath(pen, path);
            }
        }
        static GraphicsPath Outline(Rectangle r, int radius) {
            var p = new GraphicsPath(); int d = radius*2;
            p.AddArc(r.Left, r.Top, d, d, 180, 90); p.AddArc(r.Right-d, r.Top, d, d, 270, 90);
            p.AddArc(r.Right-d, r.Bottom-d, d, d, 0, 90); p.AddArc(r.Left, r.Bottom-d, d, d, 90, 90); p.CloseFigure(); return p;
        }
        public sealed class Button : System.Windows.Forms.Button {
            bool hover, down;
            public Button() {
                SetStyle(ControlStyles.UserPaint | ControlStyles.AllPaintingInWmPaint | ControlStyles.OptimizedDoubleBuffer | ControlStyles.ResizeRedraw, true);
                FlatStyle = FlatStyle.Flat; FlatAppearance.BorderSize = 0; Cursor = Cursors.Hand;
                Size = new Size(132, 34); Margin = new Padding(0, 0, 10, 0); ForeColor = Gold;
            }
            protected override void OnMouseEnter(EventArgs e) { hover = true; Invalidate(); base.OnMouseEnter(e); }
            protected override void OnMouseLeave(EventArgs e) { hover = down = false; Invalidate(); base.OnMouseLeave(e); }
            protected override void OnMouseDown(MouseEventArgs e) { down = true; Invalidate(); base.OnMouseDown(e); }
            protected override void OnMouseUp(MouseEventArgs e) { down = false; Invalidate(); base.OnMouseUp(e); }
            protected override void OnEnabledChanged(EventArgs e) { Invalidate(); base.OnEnabledChanged(e); }
            protected override void OnGotFocus(EventArgs e) { Invalidate(); base.OnGotFocus(e); }
            protected override void OnLostFocus(EventArgs e) { Invalidate(); base.OnLostFocus(e); }
            protected override void OnPaint(PaintEventArgs e) {
                var bounds = new Rectangle(0, 0, Width-1, Height-1);
                using (var fill = new LinearGradientBrush(bounds, !Enabled ? Color.FromArgb(27,23,15) : hover ? Color.FromArgb(81,25,13) : Color.FromArgb(53,15,10),
                    down ? Color.FromArgb(48,13,8) : Color.FromArgb(17,7,4), LinearGradientMode.Vertical)) e.Graphics.FillRectangle(fill, bounds);
                using (var pen = new Pen(Enabled && (hover || Focused) ? Gold : Border)) e.Graphics.DrawRectangle(pen, bounds);
                var text = ClientRectangle; if (down) text.Offset(0, 1);
                TextRenderer.DrawText(e.Graphics, Text, Font, text, Enabled ? Gold : Color.FromArgb(164,145,96),
                    TextFormatFlags.HorizontalCenter | TextFormatFlags.VerticalCenter | TextFormatFlags.EndEllipsis);
                if (Focused && ShowFocusCues) ControlPaint.DrawFocusRectangle(e.Graphics, Rectangle.Inflate(bounds, -4, -4), Gold, Panel);
            }
        }
        public sealed class ListScroll : Control {
            readonly DataGridView grid;
            public ListScroll(DataGridView grid) {
                this.grid = grid; DoubleBuffered = true; BackColor = Well;
                grid.RowsAdded += delegate { UpdateRange(); }; grid.RowsRemoved += delegate { UpdateRange(); };
                grid.Resize += delegate { UpdateRange(); }; grid.RowHeightChanged += delegate { UpdateRange(); };
                grid.ColumnHeadersHeightChanged += delegate { UpdateRange(); }; grid.Scroll += delegate { Invalidate(); };
            }
            int Page { get { return Math.Max(1, (grid.ClientSize.Height-grid.ColumnHeadersHeight)/Math.Max(1, grid.RowTemplate.Height)); } }
            int Maximum { get { return Math.Max(0, grid.Rows.Count-Page); } }
            void UpdateRange() { Visible = Maximum > 0; Invalidate(); }
            Rectangle Thumb {
                get {
                    int size = Math.Min(Height, Math.Max(22, Height*Page/Math.Max(1,grid.Rows.Count)));
                    int first = Math.Max(0, grid.FirstDisplayedScrollingRowIndex);
                    int y = Maximum == 0 ? 0 : (Height-size)*Math.Min(first,Maximum)/Maximum;
                    return new Rectangle(3,y,Math.Max(1,Width-6),size);
                }
            }
            void MoveThumb(int y) {
                if (Maximum == 0) return;
                Rectangle thumb = Thumb;
                int index = Math.Max(0,Math.Min(Maximum,(y-thumb.Height/2)*Maximum/Math.Max(1,Height-thumb.Height)));
                grid.FirstDisplayedScrollingRowIndex = index; Invalidate();
            }
            protected override void OnMouseDown(MouseEventArgs e) { base.OnMouseDown(e); if (e.Button == MouseButtons.Left) { Capture = true; MoveThumb(e.Y); } }
            protected override void OnMouseMove(MouseEventArgs e) { base.OnMouseMove(e); if (Capture) MoveThumb(e.Y); }
            protected override void OnMouseUp(MouseEventArgs e) { Capture = false; base.OnMouseUp(e); }
            protected override void OnPaint(PaintEventArgs e) {
                e.Graphics.Clear(Well); using (var track = new Pen(Color.FromArgb(57,44,18))) e.Graphics.DrawLine(track,Width/2,0,Width/2,Height);
                using (var fill = new SolidBrush(Border)) e.Graphics.FillRectangle(fill,Thumb);
            }
        }
        public sealed class Activity : Control {
            readonly Timer timer = new Timer { Interval = 40 }; int step;
            public Activity() { DoubleBuffered = true; Height = 3; timer.Tick += delegate { step = (step+3)%200; Invalidate(); }; }
            protected override void OnVisibleChanged(EventArgs e) { base.OnVisibleChanged(e); timer.Enabled = Visible; }
            protected override void OnPaint(PaintEventArgs e) {
                e.Graphics.Clear(Well); int width = Math.Max(30, Width/5), x = (Width+width)*step/200-width;
                using (var brush = new SolidBrush(Gold)) e.Graphics.FillRectangle(brush, x, 0, width, Height);
            }
            protected override void Dispose(bool disposing) { if (disposing) timer.Dispose(); base.Dispose(disposing); }
        }
    }

    // Read only the two named fonts, with bounded MPQ tables/files and zlib sectors.
    // No game font bytes are bundled, downloaded, installed system-wide or checked into source control.
    internal sealed class GameFonts : IDisposable {
        readonly PrivateFontCollection collection = new PrivateFontCollection();
        readonly List<IntPtr> memory = new List<IntPtr>(), registrations = new List<IntPtr>();
        readonly List<Font> fonts = new List<Font>();
        FontFamily body, title; bool disposed;
        public GameFonts(string folder) {
            body = Load(folder, "Fonts\\FRIZQT__.TTF") ?? FontFamily.GenericSerif;
            title = Load(folder, "Fonts\\MORPHEUS.TTF") ?? body;
        }
        public Font Body(float pixels) { var f = new Font(body, pixels, FontStyle.Regular, GraphicsUnit.Pixel); fonts.Add(f); return f; }
        public Font Title(float pixels) { var f = new Font(title, pixels, FontStyle.Regular, GraphicsUnit.Pixel); fonts.Add(f); return f; }
        FontFamily Load(string folder, string name) {
            string data = Path.Combine(folder, "Data"); if (!Directory.Exists(data)) return null;
            foreach (string file in Directory.GetFiles(data, "*.MPQ").OrderByDescending(f => Path.GetFileNameWithoutExtension(f).Equals("patch", StringComparison.OrdinalIgnoreCase) ? "" : Path.GetFileName(f), StringComparer.OrdinalIgnoreCase)) {
                try {
                    byte[] bytes = ReadFont(file, name); if (bytes == null) continue;
                    IntPtr block = Marshal.AllocHGlobal(bytes.Length); memory.Add(block); Marshal.Copy(bytes, 0, block, bytes.Length);
                    int count = 0; IntPtr registration = AddFontMemResourceEx(block, (uint)bytes.Length, IntPtr.Zero, ref count);
                    if (registration != IntPtr.Zero) registrations.Add(registration);
                    int previous = collection.Families.Length; collection.AddMemoryFont(block, bytes.Length);
                    if (collection.Families.Length > previous) return collection.Families.Last();
                } catch (IOException) { } catch (ArgumentException) { } catch (NotSupportedException) { }
            }
            return null;
        }
        static readonly uint[] Crypt = MakeTable();
        static uint[] MakeTable() {
            var result = new uint[0x500]; uint seed = 0x100001;
            for (int low=0; low<256; low++) for (int high=0; high<5; high++) {
                seed = (seed*125+3)%0x2aaaab; uint first = (seed & 65535)<<16;
                seed = (seed*125+3)%0x2aaaab; result[low+high*256] = first | (seed & 65535);
            }
            return result;
        }
        static uint Hash(string text, int type) {
            uint a = 0x7fed7fed, b = 0xeeeeeeee;
            unchecked { foreach (byte ch in Encoding.ASCII.GetBytes(text.Replace('/', '\\').ToUpperInvariant())) {
                a = Crypt[type+ch] ^ (a+b); b = ch+a+b+(b<<5)+3;
            } } return a;
        }
        static uint[] Table(BinaryReader reader, uint position, uint count, uint key) {
            if (count > 131072 || (long)position+count*16 > reader.BaseStream.Length) throw new InvalidDataException("Invalid font archive table.");
            reader.BaseStream.Position = position; var words = new uint[checked((int)count*4)]; uint seed = 0xeeeeeeee;
            unchecked { for (int i=0; i<words.Length; i++) {
                seed += Crypt[0x400+(key & 255)]; uint plain = reader.ReadUInt32() ^ (key+seed); words[i] = plain;
                key = ((~key<<21)+0x11111111) | (key>>11); seed = plain+seed+(seed<<5)+3;
            } } return words;
        }
        static byte[] ReadFont(string path, string name) {
            using (var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.ReadWrite | FileShare.Delete))
            using (var reader = new BinaryReader(stream)) {
                if (stream.Length < 32 || reader.ReadUInt32() != 0x1a51504d) return null;
                reader.ReadUInt32(); reader.ReadUInt32(); if (reader.ReadUInt16() != 0) return null;
                int shift = reader.ReadUInt16(); if (shift > 12) return null;
                uint hp = reader.ReadUInt32(), bp = reader.ReadUInt32(), slots = reader.ReadUInt32(), count = reader.ReadUInt32();
                if (slots == 0 || (slots & (slots-1)) != 0) return null;
                uint[] hashes = Table(reader, hp, slots, Hash("(hash table)", 0x300)); uint slot = Hash(name,0) & (slots-1), index = uint.MaxValue;
                uint a = Hash(name,0x100), b = Hash(name,0x200);
                for (uint i=0; i<slots; i++, slot=(slot+1)&(slots-1)) {
                    uint at=slot*4; if (hashes[at+3] == uint.MaxValue) return null;
                    if (hashes[at] == a && hashes[at+1] == b && hashes[at+3] < count) { index=hashes[at+3]; break; }
                }
                if (index == uint.MaxValue) return null;
                uint[] blocks = Table(reader, bp, count, Hash("(block table)",0x300)); uint pos=blocks[index*4], packed=blocks[index*4+1], size=blocks[index*4+2], flags=blocks[index*4+3];
                if (size > 4*1024*1024 || packed > 8*1024*1024 || (flags & 0x10100)!=0 || (long)pos+packed > stream.Length) return null;
                stream.Position=pos; byte[] raw=reader.ReadBytes((int)packed);
                if ((flags & 0x200)==0) return raw.Length == size ? raw : null;
                if ((flags & 0x1000000)!=0) return Inflate(raw,0,raw.Length,(int)size);
                int sector=512<<shift, sectors=((int)size+sector-1)/sector;
                if (raw.Length < (sectors+1)*4) throw new InvalidDataException("Invalid font archive sectors.");
                using (var output = new MemoryStream((int)size)) {
                    for (int i=0; i<sectors; i++) {
                        uint begin=BitConverter.ToUInt32(raw,i*4), end=BitConverter.ToUInt32(raw,(i+1)*4);
                        if (begin > end || end > raw.Length) throw new InvalidDataException("Invalid font archive sector.");
                        byte[] chunk=Inflate(raw,(int)begin,(int)(end-begin),Math.Min(sector,(int)size-i*sector)); output.Write(chunk,0,chunk.Length);
                    } return output.ToArray();
                }
            }
        }
        static byte[] Inflate(byte[] raw, int start, int count, int expected) {
            if (count == expected) { var direct=new byte[count]; Buffer.BlockCopy(raw,start,direct,0,count); return direct; }
            if (count < 7 || raw[start] != 2) throw new InvalidDataException("Unsupported font compression.");
            using (var input=new MemoryStream(raw,start+3,count-7)) using (var zip=new DeflateStream(input,CompressionMode.Decompress)) {
                var result=new byte[expected]; int at=0, n;
                while (at < expected && (n=zip.Read(result,at,expected-at))>0) at+=n;
                if (at != expected || zip.ReadByte()!=-1) throw new InvalidDataException("Invalid decompressed font length.");
                return result;
            }
        }
        public void Dispose() {
            if (disposed) return; disposed = true;
            foreach (Font f in fonts) f.Dispose(); collection.Dispose();
            foreach (IntPtr registration in registrations) RemoveFontMemResourceEx(registration);
            foreach (IntPtr block in memory) Marshal.FreeHGlobal(block);
        }
        [DllImport("gdi32.dll")] static extern IntPtr AddFontMemResourceEx(IntPtr data, uint length, IntPtr reserved, ref int count);
        [DllImport("gdi32.dll")] static extern bool RemoveFontMemResourceEx(IntPtr handle);
    }
}
