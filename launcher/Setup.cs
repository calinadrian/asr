// ASR-Setup.exe: installs the game from our GitHub into a folder the player chooses, tells it where to
// update from and where to play co-op, adds shortcuts and a Settings > Apps entry with an uninstaller. The shortcuts start
// Play ASR.exe (this program again, with --play), which starts the game and keeps its co-op connection alive across internet
// drops (Relay.cs) until the game exits. The game itself prompts when the game release on GitHub has a newer version; what it
// downloads is this program again, which finishes the update as ASR.exe (Game.Finish) so existing installations get Play ASR too.
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
    public sealed class Addon { public string name; public string url; public long size; public string sha256; }
    public sealed class Addons { public Addon[] addons; }

    public static class Game {
        // ASR_RELEASE_URL points the installer at a test copy of the release; the update helper uses the game's own update URL.
        public static string Release = Environment.GetEnvironmentVariable("ASR_RELEASE_URL") ?? "https://github.com/calinadrian/asr/releases/download/game/";
        public const string ExeName = "ASR.exe";
        // Installed by the first ASR-Setup, and kept by players who update in-game; replaced on reinstall.
        public const string LegacyExe = "AzerothSurvivors.exe";
        public const string PlayName = "Play ASR.exe";
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
            files.Add(new KeyValuePair<string, GameFile>(Path.Combine(folder, ExeName), Executable()));
            foreach (var file in files) Check(file.Value);
            status("Checking files already on this PC...");
            var missing = files.Where(f => !Current(f.Key, f.Value)).ToList();
            long total = missing.Sum(f => f.Value.parts.Sum(p => p.size)), done = 0;
            foreach (var file in missing) {
                string unpacked = file.Key + ".new";
                status("Downloading " + Path.GetFileName(file.Key) + "...");
                Fetch(file.Value, unpacked, added => { done += added; progress(done, total); });
                status("Unpacking " + Path.GetFileName(file.Key) + "...");
                if (File.Exists(file.Key)) File.Delete(file.Key);
                File.Move(unpacked, file.Key);
            }
            string legacy = Path.Combine(folder, LegacyExe);
            if (File.Exists(legacy)) File.Delete(legacy);
        }

        // game.json names the game itself; latest.json names the update helper the game's own updater installs
        // (Finish below). A release from before the helper existed has only latest.json, and it is the game.
        static GameFile Executable() {
            try { return Manifest<GameFile>("game.json"); }
            catch (WebException error) {
                var response = error.Response as HttpWebResponse;
                if (response == null || response.StatusCode != HttpStatusCode.NotFound) throw;
                return Manifest<GameFile>("latest.json");
            }
        }

        static void Check(GameFile file) {
            if (file.parts == null || file.size < 1 || file.size > 4L << 30 || file.sha256 == null ||
                file.parts.Any(p => p == null || p.url == null || p.size < 1 || p.size > 64 << 20 || !Regex.IsMatch(p.url, @"^[A-Za-z0-9._-]{1,120}$")))
                throw new InvalidDataException("Invalid game manifest.");
        }

        // Downloads and unpacks one file to target, verified; added reports each downloaded part's size.
        static void Fetch(GameFile file, string target, Action<long> added) {
            string packed = target + ".download";
            using (FileStream output = File.Create(packed))
                foreach (Part part in file.parts) {
                    byte[] data = Download(Release + part.url, part.size);
                    if (data.LongLength != part.size) throw new InvalidDataException("A download was incomplete. Try again.");
                    output.Write(data, 0, data.Length); added(data.Length);
                }
            using (FileStream input = File.OpenRead(packed)) using (var gzip = new GZipStream(input, CompressionMode.Decompress))
            using (FileStream output = File.Create(target)) gzip.CopyTo(output);
            File.Delete(packed);
            if (!Current(target, file)) { File.Delete(target); throw new InvalidDataException(Path.GetFileName(target) + " failed verification. Try again."); }
        }

        // The game's own updater downloads latest.json's file and restarts it as the game, so that file is this
        // program, which then runs here as ASR.exe. It brings in the game named in game.json, adds Play ASR to an
        // ASR-Setup installation (the game's updater can't add files or change shortcuts), swaps the game in and
        // starts it. Until the swap ASR.exe stays this helper, so opening ASR again retries after a failure.
        public static void Finish(string self, Action<string> status, Action<long, long> progress) {
            string folder = Path.GetDirectoryName(self);
            string feed = Environment.GetEnvironmentVariable("WOW_ROGUE_UPDATE_URL");
            if (feed != null && feed.StartsWith("https://") && feed.EndsWith("/latest.json")) Release = feed.Substring(0, feed.Length - "latest.json".Length);
            status("Checking for the new version...");
            GameFile game = Manifest<GameFile>("game.json");
            Check(game);
            string fresh = Path.Combine(folder, "ASR-game.new");
            long done = 0, total = game.parts.Sum(p => p.size);
            status("Downloading ASR " + game.version + "...");
            Fetch(game, fresh, added => { done += added; progress(done, total); });
            status("Finishing the update...");
            bool installed = File.Exists(Path.Combine(folder, Registration.Marker));
            if (installed) {
                byte[] helper = File.ReadAllBytes(self);
                // Bytes only, as in Register; a copy that is running now (Play ASR during an update) is replaced next time.
                foreach (string name in new[] { PlayName, Registration.Uninstaller }) {
                    string path = Path.Combine(folder, name);
                    try { if (!File.Exists(path) || !File.ReadAllBytes(path).SequenceEqual(helper)) File.WriteAllBytes(path, helper); }
                    catch (IOException) { } catch (UnauthorizedAccessException) { }
                }
                foreach (string shortcut in Registration.Shortcuts(folder))
                    if (File.Exists(shortcut)) Shortcut(shortcut, self);
            }
            // Windows lets a running program be renamed, not replaced; Play ASR deletes the .old copy later.
            string old = self + ".old";
            if (File.Exists(old)) File.Delete(old);
            File.Move(self, old);
            File.Move(fresh, self);
            // Under Play ASR the game's URL is its loopback relay, and Play ASR is waiting for the game to restart.
            bool relayed = (Environment.GetEnvironmentVariable("WOW_ROGUE_COOP_URL") ?? "").StartsWith("ws://127.0.0.1:");
            string play = Path.Combine(folder, PlayName);
            if (installed && !relayed && File.Exists(play))
                Process.Start(new ProcessStartInfo(play, "--play") { WorkingDirectory = folder, UseShellExecute = false });
            else
                Process.Start(new ProcessStartInfo(self) { WorkingDirectory = folder, UseShellExecute = false });
        }

        public static void Configure() {
            // User variables: no administrator rights; Windows tells Explorer, so shortcuts start the game with them.
            foreach (var setting in Settings) Environment.SetEnvironmentVariable(setting.Key, setting.Value, EnvironmentVariableTarget.User);
        }

        public static List<string> Shortcuts(string exe, bool desktop) {
            var made = new List<string>();
            var folders = new List<string> { Environment.GetFolderPath(Environment.SpecialFolder.Programs) };
            if (desktop) folders.Add(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory));
            foreach (string folder in folders) {
                string path = Path.Combine(folder, "ASR.lnk");
                Shortcut(path, exe);
                made.Add(path);
            }
            return made;
        }

        // An ASR shortcut that starts Play ASR, with the game's icon.
        static void Shortcut(string path, string exe) {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { path });
            Type linkType = link.GetType();
            linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { Path.Combine(Path.GetDirectoryName(exe), PlayName) });
            linkType.InvokeMember("Arguments", BindingFlags.SetProperty, null, link, new object[] { "--play" });
            linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { Path.GetDirectoryName(exe) });
            linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { exe + ",0" });
            linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "ASR" });
            linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
        }

        public static void Start(string exe) {
            Process.Start(new ProcessStartInfo(Path.Combine(Path.GetDirectoryName(exe), PlayName), "--play") { WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false });
        }

        // Play ASR.exe: runs the game with its co-op connection through the relay, and stays until the game is gone.
        public static int Play(string exe) {
            string logPath = Path.Combine(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), "coop-relay.log");
            object logLock = new object();
            Action<string> log = message => {
                lock (logLock) try {
                    if (File.Exists(logPath) && new FileInfo(logPath).Length > 1 << 20) File.Delete(logPath);
                    File.AppendAllText(logPath, DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine);
                } catch (IOException) { } catch (UnauthorizedAccessException) { }
            };
            // The update helper Finish swapped out last time.
            try { File.Delete(exe + ".old"); } catch (IOException) { } catch (UnauthorizedAccessException) { }
            var relay = new Relay(new Uri(Environment.GetEnvironmentVariable("ASR_RELAY_URL") ?? Relay.ServerUrl), log);
            var start = new ProcessStartInfo(exe) { WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false };
            // Started right after installing, before Windows hands the new user settings to programs.
            foreach (var setting in Settings)
                if (Environment.GetEnvironmentVariable(setting.Key) == null) start.EnvironmentVariables[setting.Key] = setting.Value;
            start.EnvironmentVariables["WOW_ROGUE_COOP_URL"] = relay.GameUrl;
            Process game = Process.Start(start);
            // The game reads its addons as each run starts, so a sync that finishes after the menu is up still counts.
            Task.Run(() => {
                try { SyncAddons(Path.GetDirectoryName(exe), log); }
                catch (Exception error) { if (error is OutOfMemoryException) throw; log("addons: " + error.GetType().Name + ": " + error.Message); }
            });
            while (game != null) {
                game.WaitForExit(); game.Dispose();
                game = Restarted(exe);
            }
            return 0;
        }

        // ASR's own addons (addons.json on the release) into the game's AddOns folder, where its AddOns page lists them
        // for the player to turn on. Each carries a marker with its zip's hash: an unchanged one is left alone, a changed
        // one replaced whole, and one the release no longer lists removed. Folders without a marker are the player's.
        public const string AddonMarker = ".asr-addon";
        public static void SyncAddons(string folder, Action<string> log) {
            string root = Path.Combine(folder, "benilla-config", "AddOns");
            Directory.CreateDirectory(root);
            Addon[] listed = Manifest<Addons>("addons.json").addons ?? new Addon[0];
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (Addon addon in listed) {
                if (addon == null || addon.name == null || !Regex.IsMatch(addon.name, @"^[A-Za-z0-9_]{1,40}$") || addon.url == null ||
                    !Regex.IsMatch(addon.url, @"^[A-Za-z0-9._-]{1,120}$") || addon.size < 1 || addon.size > 16 << 20 || addon.sha256 == null)
                    throw new InvalidDataException("Invalid addons manifest.");
                names.Add(addon.name);
                string target = Path.Combine(root, addon.name), marker = Path.Combine(target, AddonMarker);
                if (File.Exists(marker) && File.ReadAllText(marker).Trim() == addon.sha256) continue;
                // A same-named folder without our marker is the player's own copy: never overwrite it.
                if (Directory.Exists(target) && !File.Exists(marker)) { log("addons: kept the player's own " + addon.name); continue; }
                byte[] zip = Download(Release + addon.url, addon.size);
                string hash;
                using (SHA256 sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(zip)).Replace("-", "").ToLowerInvariant();
                if (zip.LongLength != addon.size || hash != addon.sha256) throw new InvalidDataException(addon.name + " failed verification.");
                string fresh = target + ".new";
                if (Directory.Exists(fresh)) Directory.Delete(fresh, true);
                Directory.CreateDirectory(fresh);
                string inside = Path.GetFullPath(fresh) + Path.DirectorySeparatorChar;
                using (var archive = new ZipArchive(new MemoryStream(zip), ZipArchiveMode.Read))
                    foreach (ZipArchiveEntry entry in archive.Entries) {
                        if (entry.FullName.EndsWith("/")) continue;
                        if (!entry.FullName.StartsWith(addon.name + "/")) throw new InvalidDataException(addon.name + " has files outside its folder.");
                        string path = Path.GetFullPath(Path.Combine(fresh, entry.FullName.Substring(addon.name.Length + 1)));
                        if (!path.StartsWith(inside, StringComparison.OrdinalIgnoreCase)) throw new InvalidDataException(addon.name + " has an unsafe path.");
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using (Stream input = entry.Open()) using (FileStream output = File.Create(path)) input.CopyTo(output);
                    }
                File.WriteAllText(Path.Combine(fresh, AddonMarker), addon.sha256);
                if (Directory.Exists(target)) Directory.Delete(target, true);
                Directory.Move(fresh, target);
                log("addons: installed " + addon.name);
            }
            foreach (string installed in Directory.GetDirectories(root))
                if (File.Exists(Path.Combine(installed, AddonMarker)) && !names.Contains(Path.GetFileName(installed))) {
                    Directory.Delete(installed, true);
                    log("addons: removed " + Path.GetFileName(installed));
                }
        }

        // After installing an update the game restarts itself, with this same environment and so the same relay.
        static Process Restarted(string exe) {
            DateTime deadline = DateTime.UtcNow.AddSeconds(20);
            while (DateTime.UtcNow < deadline) {
                foreach (Process candidate in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(exe))) {
                    try { if (String.Equals(candidate.MainModule.FileName, exe, StringComparison.OrdinalIgnoreCase)) return candidate; }
                    catch (System.ComponentModel.Win32Exception) { }
                    catch (InvalidOperationException) { }
                    candidate.Dispose();
                }
                System.Threading.Thread.Sleep(500);
            }
            return null;
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
            // Bytes only: File.Copy would carry over the download's "from the internet" mark, and Windows would warn on every start.
            try { File.WriteAllBytes(Path.Combine(folder, Game.PlayName), File.ReadAllBytes(Assembly.GetExecutingAssembly().Location)); }
            catch (IOException) { throw new IOException("Close ASR first, then run ASR-Setup again."); }
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

        // The ASR shortcuts Setup recorded for the installation in folder.
        public static List<string> Shortcuts(string folder) {
            var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(File.ReadAllText(Path.Combine(folder, Marker)));
            object listed;
            var shortcuts = new List<string>();
            if (record.TryGetValue("shortcuts", out listed) && listed is System.Collections.ArrayList)
                foreach (object shortcut in (System.Collections.ArrayList)listed)
                    if (shortcut is string && ((string)shortcut).EndsWith("ASR.lnk", StringComparison.OrdinalIgnoreCase)) shortcuts.Add((string)shortcut);
            return shortcuts;
        }

        // Removes what Setup added. Characters live in the user's AppData, outside the folder, and are kept.
        public static void Remove(string folder) {
            if (!File.Exists(Path.Combine(folder, Marker))) throw new InvalidOperationException("No ASR installation was found in " + folder + ".");
            foreach (string shortcut in Shortcuts(folder)) File.Delete(shortcut);
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

    // The window the update helper shows while it brings in the new version.
    public sealed class Updating : Form {
        readonly Label state = new Label { Location = new Point(24, 24), Size = new Size(392, 24), AutoEllipsis = true };
        readonly ProgressBar bar = new ProgressBar { Location = new Point(24, 58), Size = new Size(392, 20), Style = ProgressBarStyle.Marquee, AccessibleName = "Update progress" };
        bool failed;

        Updating(string self) {
            Text = "Updating ASR"; Icon = Icon.ExtractAssociatedIcon(self);
            ClientSize = new Size(440, 100); FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false; MinimizeBox = true;
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi; Font = new Font("Segoe UI", 10);
            BackColor = Color.FromArgb(24, 29, 35); ForeColor = Color.FromArgb(244, 240, 229);
            Controls.AddRange(new Control[] { state, bar });
            Shown += async (s, e) => {
                try { await Task.Run(() => Game.Finish(self, Status, Progress)); }
                catch (Exception error) {
                    failed = true;
                    MessageBox.Show(this, "ASR couldn't finish updating: " + error.Message + "\n\nOpen ASR again to try again.", "ASR", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                Close();
            };
        }
        void Status(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Status), message); return; } state.Text = message; }
        void Progress(long done, long total) {
            if (InvokeRequired) { BeginInvoke(new Action<long, long>(Progress), done, total); return; }
            bar.Style = ProgressBarStyle.Continuous; bar.Value = (int)Math.Min(100, done * 100 / Math.Max(1, total));
        }
        public static int Run(string self) {
            using (var form = new Updating(self)) { Application.Run(form); return form.failed ? 1 : 0; }
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
                // Named as the game: the game's updater installed this program from latest.json and restarted it.
                string self = Assembly.GetExecutingAssembly().Location, name = Path.GetFileName(self);
                if (name.Equals(Game.ExeName, StringComparison.OrdinalIgnoreCase) || name.Equals(Game.LegacyExe, StringComparison.OrdinalIgnoreCase))
                    return Updating.Run(self);
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
                    if (Process.GetProcessesByName("ASR").Concat(Process.GetProcessesByName("Play ASR")).Any(p => { try { return p.MainModule.FileName.StartsWith(folder, StringComparison.OrdinalIgnoreCase); } catch (Exception) { return false; } }) ||
                        Process.GetProcessesByName("AzerothSurvivors").Any()) {
                        MessageBox.Show("Close ASR first, then uninstall again.", "Uninstall ASR", MessageBoxButtons.OK, MessageBoxIcon.Warning); return 1;
                    }
                    Registration.Remove(folder);
                    if (!args.Contains("--yes")) MessageBox.Show("ASR was removed.", "Uninstall ASR", MessageBoxButtons.OK, MessageBoxIcon.Information);
                    // Delete this temporary copy once it has exited.
                    Process.Start(new ProcessStartInfo("cmd.exe", "/c ping -n 3 127.0.0.1 >nul & del \"" + Assembly.GetExecutingAssembly().Location + "\"") { CreateNoWindow = true, UseShellExecute = false });
                    return 0;
                }
                if (args.Contains("--play")) {
                    string here = Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location);
                    string game = Option(args, "--game") ?? Path.Combine(here, Game.ExeName);
                    if (!File.Exists(game) && File.Exists(Path.Combine(here, Game.LegacyExe))) game = Path.Combine(here, Game.LegacyExe);
                    return Game.Play(game);
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
