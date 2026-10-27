// ASR-Setup.exe: installs the game from our GitHub into a folder the player chooses, tells it where to
// update from and where to play co-op, adds shortcuts and a Settings > Apps entry with an uninstaller. Nothing of ours keeps running afterwards: the game itself
// prompts when the game release on GitHub has a newer version.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using Microsoft.Win32;

namespace ASR.Setup {
    public sealed class Part { public string url; public long size; }
    public sealed class GameFile { public string name; public string version; public long size; public string sha256; public Part[] parts; }
    public sealed class GameFiles { public GameFile[] patches; }

    public static class Game {
        public const string Release = "https://github.com/calinadrian/asr/releases/download/game/";
        public const string ExeName = "ASR.exe";
        // Installed by the first ASR-Setup, and kept by players who update in-game; replaced on reinstall.
        public const string LegacyExe = "AzerothSurvivors.exe";
        // Read by the game at start; each is a setting the game already supports.
        public static readonly Dictionary<string, string> Settings = new Dictionary<string, string> {
            { "WOW_ROGUE_UPDATE_URL", Release + "latest.json" },
            { "WOW_ROGUE_DATA_URL", Release + "patches.json" },
            { "WOW_ROGUE_COOP_URL", "wss://game.hassian.duckdns.org:47770/coop/lobby/" },
            { "WOW_ROGUE_PRESENCE", "0" },  // otherwise the game browses its author's lobby instead of ours
        };
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();

        public static byte[] Download(string url, long limit) {
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(url);
            request.UserAgent = "ASR-Setup"; request.Timeout = 30000; request.ReadWriteTimeout = 60000;
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse())
            using (Stream input = response.GetResponseStream()) using (MemoryStream output = new MemoryStream()) {
                if (response.ResponseUri.Scheme != "https" || response.ContentLength > limit) throw new InvalidDataException("Unexpected download from " + url);
                byte[] buffer = new byte[65536]; int count;
                while ((count = input.Read(buffer, 0, buffer.Length)) > 0) {
                    if (output.Length + count > limit) throw new InvalidDataException("Download too large: " + url);
                    output.Write(buffer, 0, count);
                }
                return output.ToArray();
            }
        }
        static string Hash(string path) {
            using (SHA256 sha = SHA256.Create()) using (Stream input = File.OpenRead(path))
                return BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
        }
        static bool Current(string path, GameFile file) { return File.Exists(path) && new FileInfo(path).Length == file.size && Hash(path) == file.sha256; }
        static T Manifest<T>(string name) { return Json.Deserialize<T>(Encoding.UTF8.GetString(Download(Release + name, 1 << 20))); }

        public static void Install(string folder, Action<string> status, Action<long, long> progress) {
            Directory.CreateDirectory(Path.Combine(folder, "Data"));
            var files = new List<KeyValuePair<string, GameFile>>();
            foreach (string list in new[] { "base.json", "patches.json" })
                foreach (GameFile data in Manifest<GameFiles>(list).patches) {
                    if (data.name == null || !Regex.IsMatch(data.name, @"^[A-Za-z0-9-]{1,40}\.MPQ$")) throw new InvalidDataException("Unsafe game data name.");
                    files.Add(new KeyValuePair<string, GameFile>(Path.Combine(folder, "Data", data.name), data));
                }
            // The executable comes last: its presence means the installation is complete.
            files.Add(new KeyValuePair<string, GameFile>(Path.Combine(folder, ExeName), Manifest<GameFile>("latest.json")));
            foreach (var file in files)
                if (file.Value.parts == null || file.Value.size < 1 || file.Value.size > 4L << 30 || file.Value.sha256 == null ||
                    file.Value.parts.Any(p => p == null || p.url == null || p.size < 1 || p.size > 64 << 20 || !Regex.IsMatch(p.url, @"^[A-Za-z0-9._-]{1,120}$")))
                    throw new InvalidDataException("Invalid game manifest.");
            status("Checking files already on this PC...");
            var missing = files.Where(f => !Current(f.Key, f.Value)).ToList();
            long total = missing.Sum(f => f.Value.parts.Sum(p => p.size)), done = 0;
            foreach (var file in missing) {
                string packed = file.Key + ".download", unpacked = file.Key + ".new";
                using (FileStream output = File.Create(packed))
                    foreach (Part part in file.Value.parts) {
                        byte[] data = Download(Release + part.url, part.size);
                        if (data.LongLength != part.size) throw new InvalidDataException("A download was incomplete. Run ASR-Setup again.");
                        output.Write(data, 0, data.Length); done += data.Length; progress(done, total);
                    }
                status("Unpacking " + Path.GetFileName(file.Key) + "...");
                using (FileStream input = File.OpenRead(packed)) using (var gzip = new GZipStream(input, CompressionMode.Decompress))
                using (FileStream output = File.Create(unpacked)) gzip.CopyTo(output);
                File.Delete(packed);
                if (!Current(unpacked, file.Value)) { File.Delete(unpacked); throw new InvalidDataException(Path.GetFileName(file.Key) + " failed verification. Run ASR-Setup again."); }
                if (File.Exists(file.Key)) File.Delete(file.Key);
                File.Move(unpacked, file.Key);
            }
            string legacy = Path.Combine(folder, LegacyExe);
            if (File.Exists(legacy)) File.Delete(legacy);
        }

        public static void Configure() {
            // User variables: no administrator rights; Windows tells Explorer, so shortcuts start the game with them.
            foreach (var setting in Settings) Environment.SetEnvironmentVariable(setting.Key, setting.Value, EnvironmentVariableTarget.User);
        }

        public static List<string> Shortcuts(string exe, bool desktop) {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            var made = new List<string>();
            var folders = new List<string> { Environment.GetFolderPath(Environment.SpecialFolder.Programs) };
            if (desktop) folders.Add(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
            foreach (string folder in folders) {
                string path = Path.Combine(folder, "ASR.lnk");
                object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
                Type linkType = link.GetType();
                linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { exe });
                linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { Path.GetDirectoryName(exe) });
                linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { exe + ",0" });
                linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "ASR" });
                linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
                made.Add(path);
            }
            return made;
        }

        public static void Start(string exe) {
            var start = new ProcessStartInfo(exe) { WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false };
            foreach (var setting in Settings) start.EnvironmentVariables[setting.Key] = setting.Value;
            Process.Start(start);
        }
    }

    // Windows "Installed apps" entry, per user like the installation itself.
    public static class Registration {
        const string Key = @"Software\Microsoft\Windows\CurrentVersion\Uninstall\ASR";
        public const string Marker = "asr-install.json";
        public const string Uninstaller = "Uninstall ASR.exe";

        public static string InstalledFolder() {
            using (RegistryKey key = Registry.CurrentUser.OpenSubKey(Key)) {
                string folder = key == null ? null : key.GetValue("InstallLocation") as string;
                if (folder != null && (File.Exists(Path.Combine(folder, Game.ExeName)) || File.Exists(Path.Combine(folder, Game.LegacyExe)))) return folder;
            }
            // Installed by the first ASR-Setup, before it had a folder choice.
            string first = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ASR", "game");
            if (File.Exists(Path.Combine(first, Game.LegacyExe)) || File.Exists(Path.Combine(first, Game.ExeName))) return first;
            return null;
        }

        public static void Register(string folder, List<string> shortcuts) {
            string uninstaller = Path.Combine(folder, Uninstaller);
            File.Copy(Assembly.GetExecutingAssembly().Location, uninstaller, true);
            File.WriteAllText(Path.Combine(folder, Marker), new JavaScriptSerializer().Serialize(new Dictionary<string, object> { { "shortcuts", shortcuts } }));
            long size = new DirectoryInfo(folder).EnumerateFiles("*", SearchOption.AllDirectories).Sum(f => f.Length);
            string version = "";
            try { version = FileVersionInfo.GetVersionInfo(Path.Combine(folder, Game.ExeName)).ProductVersion ?? ""; } catch (IOException) { }
            using (RegistryKey key = Registry.CurrentUser.CreateSubKey(Key)) {
                key.SetValue("DisplayName", "ASR");
                key.SetValue("DisplayIcon", Path.Combine(folder, Game.ExeName) + ",0");
                key.SetValue("Publisher", "ASR");
                key.SetValue("InstallLocation", folder);
                key.SetValue("UninstallString", "\"" + uninstaller + "\" --uninstall");
                key.SetValue("URLInfoAbout", "https://github.com/calinadrian/asr");
                key.SetValue("EstimatedSize", (int)(size / 1024), RegistryValueKind.DWord);
                key.SetValue("NoModify", 1, RegistryValueKind.DWord);
                key.SetValue("NoRepair", 1, RegistryValueKind.DWord);
                if (version != "") key.SetValue("DisplayVersion", version);
            }
        }

        // Removes what Setup added. Characters live in the user's AppData, outside the folder, and are kept.
        public static void Remove(string folder) {
            if (!File.Exists(Path.Combine(folder, Marker))) throw new InvalidOperationException("No ASR installation was found in " + folder + ".");
            var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(folder, Marker)));
            object listed;
            if (record.TryGetValue("shortcuts", out listed) && listed is System.Collections.ArrayList)
                foreach (object shortcut in (System.Collections.ArrayList)listed)
                    if (shortcut is string && ((string)shortcut).EndsWith("ASR.lnk", StringComparison.OrdinalIgnoreCase)) File.Delete((string)shortcut);
            foreach (var setting in Game.Settings)
                if (Environment.GetEnvironmentVariable(setting.Key, EnvironmentVariableTarget.User) == setting.Value)
                    Environment.SetEnvironmentVariable(setting.Key, null, EnvironmentVariableTarget.User);
            Registry.CurrentUser.DeleteSubKeyTree(Key, false);
            Directory.Delete(folder, true);
        }
    }

    public sealed class Wizard : Form {
        static readonly Color Muted = Color.FromArgb(196, 205, 213), Gold = Color.FromArgb(232, 182, 76), Ink = Color.FromArgb(24, 29, 35);
        readonly Panel choose = new Panel(), working = new Panel(), done = new Panel();
        readonly TextBox folder; readonly CheckBox desktop, startNow; readonly Label space, state, doneText; readonly ProgressBar bar;
        readonly Button install;
        public bool Installed { get; private set; }
        // Read once installed: the text box is gone after the window closes.
        public string InstalledTo { get; private set; }
        string Folder { get { return folder.Text.Trim(); } }
        public bool StartNow { get { return startNow.Checked; } }

        public Wizard(string suggested, bool automatic) {
            Text = "ASR Setup"; Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);
            ClientSize = new Size(580, 300); FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 10); BackColor = Ink; ForeColor = Color.FromArgb(244, 240, 229);
            foreach (Panel page in new[] { choose, working, done }) { page.Dock = DockStyle.Fill; page.Padding = new Padding(28); Controls.Add(page); }

            choose.Controls.Add(Title("Install ASR"));
            choose.Controls.Add(new Label { Text = "Install to:", Location = new Point(30, 72), AutoSize = true });
            folder = new TextBox { Text = suggested, Location = new Point(30, 96), Size = new Size(410, 26), BackColor = Color.FromArgb(32, 39, 47), ForeColor = ForeColor, BorderStyle = BorderStyle.FixedSingle };
            Button browse = Plain("Browse...", new Point(450, 94), 100);
            browse.Click += (s, e) => Browse();
            space = new Label { Location = new Point(30, 128), Size = new Size(520, 22), ForeColor = Muted };
            desktop = new CheckBox { Text = "Create a desktop shortcut", Checked = true, Location = new Point(30, 160), AutoSize = true };
            install = Primary("Install", new Point(440, 236));
            install.Click += (s, e) => Start();
            Button cancel = Plain("Cancel", new Point(320, 236), 110);
            cancel.Click += (s, e) => Close();
            folder.TextChanged += (s, e) => ShowSpace();
            choose.Controls.AddRange(new Control[] { folder, browse, space, desktop, install, cancel });
            ShowSpace();

            working.Controls.Add(Title("Installing ASR"));
            state = new Label { Text = "Preparing...", Location = new Point(30, 80), Size = new Size(520, 24), AutoEllipsis = true, ForeColor = Muted };
            bar = new ProgressBar { Location = new Point(30, 116), Size = new Size(520, 22), Style = ProgressBarStyle.Marquee, AccessibleName = "Download progress" };
            working.Controls.AddRange(new Control[] { state, bar });

            done.Controls.Add(Title("ASR is installed"));
            doneText = new Label { Location = new Point(30, 76), Size = new Size(520, 70), ForeColor = Muted,
                Text = "Open ASR from the Start menu. When a new version is out, the game asks you and updates itself. Remove it in Settings > Apps." };
            startNow = new CheckBox { Text = "Start ASR now", Checked = true, Location = new Point(30, 160), AutoSize = true };
            Button finish = Primary("Finish", new Point(440, 236));
            finish.Click += (s, e) => Close();
            done.Controls.AddRange(new Control[] { doneText, startNow, finish });

            Show(choose); AcceptButton = install;
            if (automatic) { startNow.Checked = false; Shown += (s, e) => Start(); }
        }
        Label Title(string text) { return new Label { Text = text, Font = new Font("Segoe UI", 16, FontStyle.Bold), Location = new Point(26, 18), AutoSize = true }; }
        Button Primary(string text, Point at) { return new Button { Text = text, Location = at, Size = new Size(110, 38), BackColor = Gold, ForeColor = Ink, FlatStyle = FlatStyle.Flat }; }
        Button Plain(string text, Point at, int width) { return new Button { Text = text, Location = at, Size = new Size(width, 38), FlatStyle = FlatStyle.Flat, ForeColor = ForeColor }; }
        void Show(Panel page) { foreach (Panel p in new[] { choose, working, done }) p.Visible = p == page; }

        void Browse() {
            using (var picker = new FolderBrowserDialog { Description = "Choose where to install ASR. An ASR folder is created inside it.", ShowNewFolderButton = true }) {
                if (picker.ShowDialog(this) != DialogResult.OK) return;
                string chosen = picker.SelectedPath;
                folder.Text = Path.GetFileName(chosen.TrimEnd('\\')).Equals("ASR", StringComparison.OrdinalIgnoreCase) ? chosen : Path.Combine(chosen, "ASR");
            }
        }
        void ShowSpace() {
            try {
                long free = new DriveInfo(Path.GetPathRoot(Path.GetFullPath(Folder))).AvailableFreeSpace;
                space.Text = String.Format("Needs 3 GB free while installing, 1.5 GB after. Free here: {0:0} GB", free / 1e9);
                space.ForeColor = free < 3e9 ? Color.FromArgb(240, 120, 110) : Muted;
            } catch (Exception) { space.Text = "Choose a folder on a local drive."; space.ForeColor = Color.FromArgb(240, 120, 110); }
        }
        string Check() {
            string path;
            try { path = Path.GetFullPath(Folder); } catch (Exception) { return "That is not a valid folder."; }
            if (Directory.Exists(path) && Directory.EnumerateFileSystemEntries(path).Any() &&
                !File.Exists(Path.Combine(path, Game.ExeName)) && !File.Exists(Path.Combine(path, Game.LegacyExe)) && !File.Exists(Path.Combine(path, Registration.Marker)))
                return "That folder already has other files in it. Choose an empty folder or a new one.";
            try {
                Directory.CreateDirectory(path);
                string probe = Path.Combine(path, ".asr-write-test"); File.WriteAllText(probe, ""); File.Delete(probe);
            } catch (Exception) { return "ASR can't write to that folder. Choose one in your user folder, for example the suggested one."; }
            if (new DriveInfo(Path.GetPathRoot(path)).AvailableFreeSpace < 3e9) return "There isn't enough free space on that drive.";
            folder.Text = path;
            return null;
        }

        async void Start() {
            string problem = Check();
            if (problem != null) { MessageBox.Show(this, problem, "ASR Setup", MessageBoxButtons.OK, MessageBoxIcon.Warning); return; }
            Show(working); ControlBox = false;
            string target = Folder; bool wantDesktop = desktop.Checked;
            try {
                await Task.Run(() => {
                    Game.Install(target, Status, Progress);
                    Status("Adding shortcuts...");
                    Game.Configure();
                    Registration.Register(target, Game.Shortcuts(Path.Combine(target, Game.ExeName), wantDesktop));
                });
                InstalledTo = target; Installed = true; ControlBox = true; Show(done); AcceptButton = null;
                if (!startNow.Checked && Environment.GetCommandLineArgs().Contains("--yes")) Close();
            } catch (Exception error) {
                ControlBox = true;
                MessageBox.Show(this, error.Message + "\n\nRun ASR-Setup again to continue; finished files are kept.", "ASR Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                Close();
            }
        }
        public void Status(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Status), message); return; } state.Text = message; }
        public void Progress(long done, long total) {
            if (InvokeRequired) { BeginInvoke(new Action<long, long>(Progress), done, total); return; }
            bar.Style = ProgressBarStyle.Continuous; bar.Value = (int)Math.Min(100, done * 100 / Math.Max(1, total));
            state.Text = String.Format("Downloading the game: {0:0.0} of {1:0.0} GB", done / 1e9, total / 1e9);
        }
        public void Preview(string page, string path) {
            Show(page == "working" ? working : page == "done" ? done : choose);
            if (page == "working") Progress(420000000, 1400000000);
            using (Bitmap image = new Bitmap(Width, Height)) { DrawToBitmap(image, new Rectangle(0, 0, Width, Height)); image.Save(path); }
        }
    }

    static class Program {
        static string Option(string[] args, string name) {
            for (int i = 0; i + 1 < args.Length; i++) if (args[i] == name) return args[i + 1];
            return null;
        }

        [STAThread] static int Main(string[] args) {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            string defaultFolder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Programs", "ASR");
            try {
                if (args.Length == 3 && args[0] == "--render-preview") {
                    using (Wizard form = new Wizard(defaultFolder, false)) { form.Show(); Application.DoEvents(); form.Preview(args[1], args[2]); }
                    return 0;
                }
                if (args.Contains("--uninstall")) {
                    // The uninstaller lives in the folder it removes, so it runs a temporary copy of itself.
                    string folder = Option(args, "--uninstall-from") ?? Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                    if (Option(args, "--uninstall-from") == null) {
                        string copy = Path.Combine(Path.GetTempPath(), "asr-uninstall-" + Guid.NewGuid().ToString("N") + ".exe");
                        File.Copy(Assembly.GetExecutingAssembly().Location, copy);
                        Process.Start(copy, "--uninstall --uninstall-from \"" + folder + "\"" + (args.Contains("--yes") ? " --yes" : ""));
                        return 0;
                    }
                    if (!args.Contains("--yes") && MessageBox.Show("Remove ASR from this PC?\n\nYour characters are kept.", "Uninstall ASR",
                            MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) return 1;
                    if (Process.GetProcessesByName("ASR").Any(p => { try { return p.MainModule.FileName.StartsWith(folder, StringComparison.OrdinalIgnoreCase); } catch (Exception) { return false; } }) ||
                        Process.GetProcessesByName("AzerothSurvivors").Any()) {
                        MessageBox.Show("Close ASR first, then uninstall again.", "Uninstall ASR", MessageBoxButtons.OK, MessageBoxIcon.Warning); return 1;
                    }
                    Registration.Remove(folder);
                    if (!args.Contains("--yes")) MessageBox.Show("ASR was removed.", "Uninstall ASR", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    // Delete this temporary copy once it has exited.
                    Process.Start(new ProcessStartInfo("cmd.exe", "/c ping -n 3 127.0.0.1 >nul & del \"" + Assembly.GetExecutingAssembly().Location + "\"") { CreateNoWindow = true, UseShellExecute = false });
                    return 0;
                }
                if (args.Contains("--test")) {  // install the files only, into --dir, with no window, settings or shortcuts
                    Game.Install(Path.GetFullPath(Option(args, "--dir")), s => { }, (d, t) => { });
                    return 0;
                }
                using (Wizard wizard = new Wizard(Option(args, "--dir") ?? Registration.InstalledFolder() ?? defaultFolder, args.Contains("--yes"))) {
                    Application.Run(wizard);
                    if (wizard.Installed && wizard.StartNow) Game.Start(Path.Combine(wizard.InstalledTo, Game.ExeName));
                    return wizard.Installed ? 0 : 1;
                }
            } catch (Exception error) {
                MessageBox.Show(error.Message, "ASR Setup", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
        }
    }
}
