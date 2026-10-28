// Hosted as a child window of the game, opened by the native AddOns page's existing button.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Runtime.InteropServices;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Windows.Forms;

namespace ASR.Setup {
    public sealed class AddonManager : Form {
        static readonly Color Ink = GameUi.Backdrop, Surface = GameUi.Well,
            TextColor = GameUi.Text, Muted = GameUi.Muted, Gold = GameUi.Gold;
        readonly GameFonts fonts;
        readonly AddonStore store;
        readonly IntPtr parent;
        readonly DataGridView list = new DataGridView();
        readonly Label message = new Label(), detail = new Label();
        readonly Button install, remove, refresh, import, back;
        readonly GameUi.Activity progress = new GameUi.Activity();
        readonly Timer follow = new Timer { Interval = 150 };
        Addon[] catalog = new Addon[0];
        bool busy, closingLocked;
        Size parentSize = Size.Empty;
        sealed class Row { public string name; public Addon available; public InstalledAddon installed; }

        public static bool IsFolderArgument(string path, string gameFolder) {
            try { return Path.GetFullPath(path).TrimEnd('\\').Equals(Path.Combine(gameFolder, "benilla-config", "AddOns"), StringComparison.OrdinalIgnoreCase); }
            catch (ArgumentException) { return false; } catch (NotSupportedException) { return false; }
        }
        public static int Run(string folder) {
            IntPtr window = ParentGameWindow(folder);
            if (window == IntPtr.Zero) throw new InvalidOperationException("Open Manage AddOns from the game's Options > AddOns tab.");
            using (var singleton = new System.Threading.Mutex(false, @"Local\ASR.AddonWindow." + window.ToInt64())) {
                bool entered;
                try { entered = singleton.WaitOne(0); } catch (System.Threading.AbandonedMutexException) { entered = true; }
                if (!entered) return 0;
                try {
                    try { SetThreadDpiAwarenessContext(GetWindowDpiAwarenessContext(window)); } catch (EntryPointNotFoundException) { }
                    using (var form = new AddonManager(new AddonStore(folder), window)) Application.Run(form);
                } finally { singleton.ReleaseMutex(); }
            }
            return 0;
        }

        public AddonManager(AddonStore store, IntPtr parent) {
            this.store = store; this.parent = parent; fonts = new GameFonts(store.Folder);
            Text = "ASR AddOns"; BackColor = Ink; ForeColor = TextColor;
            Font = fonts.Body(14); AutoScaleMode = AutoScaleMode.None;
            FormBorderStyle = FormBorderStyle.None; ShowInTaskbar = false; KeyPreview = true;
            ClientSize = new Size(1000, 660);
            var frame = new GameUi.Frame { Padding = new Padding(24) }; Controls.Add(frame);
            AccessibleName = "ASR addon manager";
            var layout = new TableLayoutPanel { Dock = DockStyle.Fill, ColumnCount = 1, RowCount = 5, BackColor = GameUi.Panel };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 92));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 48));
            layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 104));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 40));
            frame.Controls.Add(layout);
            var header = new Panel { Dock = DockStyle.Fill };
            var heading = new Label { Text = "AddOns", ForeColor = Gold, Font = fonts.Title(34), TextAlign = ContentAlignment.MiddleCenter,
                Dock = DockStyle.Top, Height = 48 }; header.Controls.Add(heading);
            var subtitle = new Label { Text = "Choose addons from ASR's GitHub catalog, or install a WoW 1.12 ZIP.", ForeColor = Muted,
                Dock = DockStyle.Bottom, Height = 32, TextAlign = ContentAlignment.MiddleCenter };
            header.Controls.Add(subtitle); layout.Controls.Add(header, 0, 0);
            back = Button("Back to game", delegate { Close(); });
            var toolbar = new FlowLayoutPanel { Dock = DockStyle.Fill, WrapContents = false, Padding = new Padding(0, 0, 0, 8) };
            refresh = Button("Refresh catalog", async delegate { await Reload(true); });
            import = Button("Install ZIP...", async delegate {
                using (var picker = new OpenFileDialog { Title = "Install an addon", Filter = "Addon ZIP files (*.zip)|*.zip", CheckFileExists = true }) {
                    if (picker.ShowDialog(this) != DialogResult.OK) return;
                    string zip = picker.FileName;
                    await Perform("Installing addon...", delegate { string name = store.Import(zip, false); return name + " installed. Start a new run to load it."; });
                }
            });
            toolbar.Controls.Add(refresh); toolbar.Controls.Add(import); layout.Controls.Add(toolbar, 0, 1);
            list.Dock = DockStyle.Fill; list.BackgroundColor = Surface; list.BorderStyle = BorderStyle.None;
            list.AllowUserToAddRows = false; list.AllowUserToDeleteRows = false; list.AllowUserToResizeRows = false;
            list.RowHeadersVisible = false; list.ReadOnly = true; list.MultiSelect = false; list.SelectionMode = DataGridViewSelectionMode.FullRowSelect;
            list.AutoSizeColumnsMode = DataGridViewAutoSizeColumnsMode.Fill; list.RowTemplate.Height = 42;
            list.EnableHeadersVisualStyles = false; list.ColumnHeadersBorderStyle = DataGridViewHeaderBorderStyle.None;
            list.AdvancedColumnHeadersBorderStyle.All = DataGridViewAdvancedCellBorderStyle.None; list.ColumnHeadersHeight = 38; list.ColumnHeadersHeightSizeMode = DataGridViewColumnHeadersHeightSizeMode.DisableResizing;
            list.ColumnHeadersDefaultCellStyle = new DataGridViewCellStyle { BackColor = Surface, ForeColor = Gold, Padding = new Padding(10, 0, 0, 0), Font = Font };
            list.DefaultCellStyle = new DataGridViewCellStyle { BackColor = Surface, ForeColor = TextColor, SelectionBackColor = Color.FromArgb(50, 31, 12), SelectionForeColor = Gold, Padding = new Padding(10, 0, 0, 0) };
            list.GridColor = Color.FromArgb(51, 40, 18); list.CellBorderStyle = DataGridViewCellBorderStyle.SingleHorizontal;
            list.CellPainting += PaintAddonCell;
            list.Columns.Add("addon", "Addon"); list.Columns[0].FillWeight = 65;
            list.Columns.Add("source", "Source"); list.Columns[1].FillWeight = 20;
            list.Columns.Add("state", "Status"); list.Columns[2].FillWeight = 20;
            list.SelectionChanged += delegate { Selection(); }; list.AccessibleName = "Available and installed addons";
            list.ScrollBars = ScrollBars.None;
            var listHost = new Panel { Dock = DockStyle.Fill, BackColor = Surface };
            var scroll = new GameUi.ListScroll(list) { Dock = DockStyle.Right, Width = 12 };
            listHost.Controls.Add(list); listHost.Controls.Add(scroll); layout.Controls.Add(listHost, 0, 2);
            var selected = new Panel { Dock = DockStyle.Fill, Padding = new Padding(0, 16, 0, 0) };
            detail.ForeColor = Muted; detail.Dock = DockStyle.Fill; detail.AutoEllipsis = true; selected.Controls.Add(detail);
            install = Button("Install", async delegate {
                Row row = Selected(); if (row == null || row.available == null) return;
                await Perform("Downloading " + row.name + "...", delegate { store.Install(row.available); return row.name + " installed. Start a new run to load it."; });
            });
            remove = Button("Remove", async delegate {
                Row row = Selected(); if (row == null || row.installed == null) return;
                if (MessageBox.Show(this, "Remove " + row.name + "?\n\nIts addon files will be removed. The change takes effect on your next run.",
                    "Remove addon", MessageBoxButtons.YesNo, MessageBoxIcon.Question, MessageBoxDefaultButton.Button2) != DialogResult.Yes) return;
                await Perform("Removing " + row.name + "...", delegate { store.Remove(row.name); return row.name + " removed. It will stay removed when ASR restarts."; });
            });
            var actions = new FlowLayoutPanel { Dock = DockStyle.Bottom, Height = 36, FlowDirection = FlowDirection.RightToLeft, WrapContents = false };
            back.Margin = new Padding(10, 0, 0, 0); remove.Margin = new Padding(10, 0, 0, 0); install.Margin = new Padding(10, 0, 0, 0);
            actions.Controls.Add(back); actions.Controls.Add(remove); actions.Controls.Add(install); selected.Controls.Add(actions); layout.Controls.Add(selected, 0, 3);
            var footer = new Panel { Dock = DockStyle.Fill };
            message.Dock = DockStyle.Fill; message.AutoEllipsis = true; message.ForeColor = Muted; message.Text = "Changes apply when you start your next run."; message.AccessibleName = "Addon operation status";
            progress.Dock = DockStyle.Bottom; progress.Height = 3; progress.Visible = false;
            footer.Controls.Add(message); footer.Controls.Add(progress); layout.Controls.Add(footer, 0, 4);
            Font regular = Font, compactBody = fonts.Body(12), largeTitle = heading.Font, compactTitle = fonts.Title(28);
            Action arrange = delegate {
                bool compact = ClientSize.Height < 540;
                int inset = compact ? 10 : 24;
                frame.Size = new Size(Math.Max(1, Math.Min(1160, ClientSize.Width-inset*2)), Math.Max(1, Math.Min(780, ClientSize.Height-inset*2)));
                frame.Location = new Point((ClientSize.Width-frame.Width)/2, (ClientSize.Height-frame.Height)/2);
                frame.Padding = new Padding(compact ? 12 : 24);
                Font = compact ? compactBody : regular;
                foreach (Button control in new[] { back, remove, install, import, refresh }) { control.Font = Font; control.Height = compact ? 30 : 34; }
                heading.Font = compact ? compactTitle : largeTitle; heading.Height = compact ? 38 : 48;
                list.DefaultCellStyle.Font = list.ColumnHeadersDefaultCellStyle.Font = Font;
                list.ColumnHeadersHeight = compact ? 28 : 38; list.RowTemplate.Height = compact ? 32 : 42;
                foreach (DataGridViewRow row in list.Rows) row.Height = list.RowTemplate.Height;
                toolbar.Padding = new Padding(0, 0, 0, compact ? 0 : 8);
                selected.Padding = new Padding(0, compact ? 8 : 16, 0, 0); actions.Height = compact ? 32 : 36;
                layout.RowStyles[0].Height = compact ? 68 : 86;
                layout.RowStyles[1].Height = compact ? 36 : 48;
                layout.RowStyles[3].Height = compact ? 74 : 100;
                layout.RowStyles[4].Height = compact ? 24 : 36;
                subtitle.Height = compact ? 24 : 32;
            };
            ClientSizeChanged += delegate { arrange(); }; arrange();
            Shown += async delegate { Attach(); FollowParent(); await Reload(true); };
            follow.Tick += delegate { FollowParent(); }; if (parent != IntPtr.Zero) follow.Start();
            FormClosing += delegate(object sender, FormClosingEventArgs e) { if (closingLocked && parent != IntPtr.Zero && IsWindow(parent)) e.Cancel = true; };
            FormClosed += delegate { follow.Dispose(); if (parent != IntPtr.Zero && IsWindow(parent)) { SetForegroundWindow(parent); SetFocus(parent); } };
            KeyDown += delegate(object sender, KeyEventArgs e) { if (e.KeyCode == Keys.Escape && !closingLocked) { e.Handled = true; Close(); } };
        }
        Button Button(string text, EventHandler click) {
            var button = new GameUi.Button { Text = text, Font = Font, AccessibleName = text.Replace("...", "") };
            button.Click += click; return button;
        }
        void PaintAddonCell(object sender, DataGridViewCellPaintingEventArgs e) {
            if (e.RowIndex < 0) return;
            e.Paint(e.ClipBounds, DataGridViewPaintParts.All & ~DataGridViewPaintParts.Focus);
            if ((e.State & DataGridViewElementStates.Selected) != 0) {
                using (var pen = new Pen(GameUi.Border)) {
                    Rectangle r = e.CellBounds; e.Graphics.DrawLine(pen, r.Left, r.Top, r.Right, r.Top);
                    e.Graphics.DrawLine(pen, r.Left, r.Bottom-1, r.Right, r.Bottom-1);
                    if (e.ColumnIndex == 0) e.Graphics.DrawLine(pen, r.Left, r.Top, r.Left, r.Bottom-1);
                    if (e.ColumnIndex == list.Columns.Count-1) e.Graphics.DrawLine(pen, r.Right-1, r.Top, r.Right-1, r.Bottom-1);
                }
            }
            e.Handled = true;
        }
        protected override void Dispose(bool disposing) {
            base.Dispose(disposing);
            if (disposing && fonts != null) fonts.Dispose();
        }
        Row Selected() { return list.SelectedRows.Count == 0 ? null : list.SelectedRows[0].Tag as Row; }
        void Selection() {
            if (install == null || remove == null) return;
            Row row = Selected();
            install.Enabled = !busy && row != null && row.available != null && row.installed == null;
            remove.Enabled = !busy && row != null && row.installed != null;
            detail.Text = row == null ? "Select an addon to install or remove it." :
                row.installed != null ? "Use the game's checkboxes to enable or disable. Remove deletes the addon files." :
                (String.IsNullOrWhiteSpace(row.available.description) ? "Available from ASR's addon catalog." : row.available.description) + "\nChanges apply to your next run.";
        }
        void Busy(bool value, string text, bool changes = false) {
            busy = value; closingLocked = value && changes; refresh.Enabled = import.Enabled = !value; back.Enabled = !closingLocked; progress.Visible = value;
            message.ForeColor = Muted; message.Text = text; Selection();
        }
        void Bind(InstalledAddon[] installed) {
            string selection = Selected() == null ? null : Selected().name;
            var rows = new Dictionary<string, Row>(StringComparer.OrdinalIgnoreCase);
            foreach (Addon a in catalog) rows[a.name] = new Row { name = a.name, available = a };
            foreach (InstalledAddon a in installed) {
                Row row; if (!rows.TryGetValue(a.name, out row)) { row = new Row { name = a.name }; rows.Add(a.name, row); }
                row.installed = a;
            }
            list.Rows.Clear();
            foreach (Row row in rows.Values.OrderBy(r => r.installed == null).ThenBy(r => r.name)) {
                string title = row.installed != null ? row.installed.title : row.available.title;
                if (String.IsNullOrWhiteSpace(title)) title = row.name;
                title = Regex.Replace(title, @"\|c[0-9a-fA-F]{8}|\|r", "");
                int index = list.Rows.Add(title, row.available != null ? "ASR catalog" : "Local ZIP", row.installed != null ? "Installed" : "Available");
                list.Rows[index].Tag = row;
                if (row.name == selection) list.CurrentCell = list.Rows[index].Cells[0];
            }
            Selection();
        }
        async Task Reload(bool online) {
            Busy(true, "Loading addons...");
            try {
                InstalledAddon[] installed = await Task.Run(() => store.Installed()); if (IsDisposed) return; Bind(installed);
                if (online) { Addon[] fetched = await Task.Run(() => store.Catalog()); if (IsDisposed) return; catalog = fetched; }
                Bind(installed); Busy(false, list.Rows.Count == 0 ? "No addons yet. Install a ZIP, or refresh the catalog to browse available addons." : "Changes apply when you start your next run.");
            } catch (Exception error) { if (!IsDisposed) { Busy(false, "Catalog unavailable. Install a ZIP or remove addons below. Refresh to retry."); message.AccessibleDescription = error.Message; } }
        }
        async Task Perform(string status, Func<string> work) {
            Busy(true, status, true);
            try { string result = await Task.Run(work); Bind(await Task.Run(() => store.Installed()));
                try { SignalNativeRefresh(); } catch (Exception) { result += " Reopen ASR to refresh its addon list."; }
                Busy(false, result); }
            catch (Exception error) { Busy(false, error.Message); message.ForeColor = Color.FromArgb(255, 177, 164); }
        }
        void SignalNativeRefresh() {
            if (parent == IntPtr.Zero || !IsWindow(parent)) return;
            uint pid; GetWindowThreadProcessId(parent, out pid);
            if (pid == 0) throw new InvalidOperationException("The game window is unavailable.");
            File.WriteAllText(Path.Combine(store.Folder, ".asr-addons-refresh-" + pid.ToString("x8")), "1");
        }
        protected override void OnHandleCreated(EventArgs e) {
            base.OnHandleCreated(e);
            if (parent == IntPtr.Zero) return;
            Attach();
        }
        void Attach() {
            if (parent == IntPtr.Zero) return;
            long style = GetWindowLong(Handle, -16).ToInt64();
            SetWindowLong(Handle, -16, new IntPtr((style & ~0x80000000L) | 0x40000000L));
            SetParent(Handle, parent);
            if (GetParent(Handle) != parent) throw new InvalidOperationException("The addon manager could not attach to the game window.");
        }
        void FollowParent() {
            if (parent == IntPtr.Zero) return;
            if (!IsWindow(parent)) { busy = closingLocked = false; Close(); return; }
            Rect rect;
            if (GetClientRect(parent, out rect) && parentSize != new Size(rect.right, rect.bottom)) {
                parentSize = new Size(rect.right, rect.bottom); MoveWindow(Handle, 0, 0, rect.right, rect.bottom, true);
            }
        }

        static IntPtr ParentGameWindow(string folder) {
            uint parentId = 0; IntPtr snapshot = CreateToolhelp32Snapshot(2, 0);
            if (snapshot != new IntPtr(-1)) {
                try {
                    var entry = new ProcessEntry { size = (uint)Marshal.SizeOf(typeof(ProcessEntry)) };
                    if (Process32First(snapshot, ref entry)) do {
                        if (entry.pid == (uint)Process.GetCurrentProcess().Id) { parentId = entry.parent; break; }
                    } while (Process32Next(snapshot, ref entry));
                } finally { CloseHandle(snapshot); }
            }
            if (parentId == 0) return IntPtr.Zero;
            try {
                using (var process = Process.GetProcessById((int)parentId)) {
                    string executable = process.MainModule.FileName;
                    if (!Path.GetDirectoryName(executable).Equals(Path.GetFullPath(folder).TrimEnd('\\'), StringComparison.OrdinalIgnoreCase) ||
                        !(Path.GetFileName(executable).Equals(Game.ExeName, StringComparison.OrdinalIgnoreCase) || Path.GetFileName(executable).Equals(Game.LegacyExe, StringComparison.OrdinalIgnoreCase))) return IntPtr.Zero;
                    return process.MainWindowHandle;
                }
            } catch (Exception) { return IntPtr.Zero; }
        }
        [StructLayout(LayoutKind.Sequential)] struct Rect { public int left, top, right, bottom; }
        [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] struct ProcessEntry {
            public uint size, usage, pid; public IntPtr heap; public uint module, threads, parent; public int priority; public uint flags;
            [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 260)] public string exe;
        }
        [DllImport("kernel32.dll")] static extern IntPtr CreateToolhelp32Snapshot(uint flags, uint pid);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "Process32FirstW")] static extern bool Process32First(IntPtr snapshot, ref ProcessEntry entry);
        [DllImport("kernel32.dll", CharSet = CharSet.Unicode, EntryPoint = "Process32NextW")] static extern bool Process32Next(IntPtr snapshot, ref ProcessEntry entry);
        [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
        [DllImport("user32.dll", SetLastError = true)] static extern IntPtr SetParent(IntPtr child, IntPtr parent);
        [DllImport("user32.dll")] static extern IntPtr GetParent(IntPtr window);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongPtrW")] static extern IntPtr GetWindowLong64(IntPtr window, int index);
        [DllImport("user32.dll", EntryPoint = "GetWindowLongW")] static extern int GetWindowLong32(IntPtr window, int index);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongPtrW")] static extern IntPtr SetWindowLong64(IntPtr window, int index, IntPtr value);
        [DllImport("user32.dll", EntryPoint = "SetWindowLongW")] static extern int SetWindowLong32(IntPtr window, int index, int value);
        static IntPtr GetWindowLong(IntPtr w, int i) { return IntPtr.Size == 8 ? GetWindowLong64(w, i) : new IntPtr(GetWindowLong32(w, i)); }
        static void SetWindowLong(IntPtr w, int i, IntPtr v) { if (IntPtr.Size == 8) SetWindowLong64(w, i, v); else SetWindowLong32(w, i, v.ToInt32()); }
        [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr window, out uint process);
        [DllImport("user32.dll")] static extern bool IsWindow(IntPtr window);
        [DllImport("user32.dll")] static extern bool GetClientRect(IntPtr window, out Rect rect);
        [DllImport("user32.dll")] static extern bool MoveWindow(IntPtr window, int x, int y, int width, int height, bool repaint);
        [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr SetFocus(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr GetWindowDpiAwarenessContext(IntPtr window);
        [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
    }
}
