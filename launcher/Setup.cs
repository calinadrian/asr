// ASR-Setup.exe: installs the game from our GitHub, tells it where to update from and where to play
// co-op, adds ASR shortcuts and starts it. Nothing of ours keeps running afterwards: the game itself
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

namespace ASR.Setup {
    public sealed class Part { public string url; public long size; }
    public sealed class GameFile { public string name; public string version; public long size; public string sha256; public Part[] parts; }
    public sealed class GameFiles { public GameFile[] patches; }

    public static class Game {
        public const string Release = "https://github.com/calinadrian/asr/releases/download/game/";
        public const string ExeName = "AzerothSurvivors.exe";
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
        }

        public static void Configure() {
            // User variables: no administrator rights; Windows tells Explorer, so shortcuts start the game with them.
            foreach (var setting in Settings) Environment.SetEnvironmentVariable(setting.Key, setting.Value, EnvironmentVariableTarget.User);
        }

        public static void Shortcuts(string exe) {
            Type shellType = Type.GetTypeFromProgID("WScript.Shell");
            object shell = Activator.CreateInstance(shellType);
            foreach (string folder in new[] { Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory), Environment.GetFolderPath(Environment.SpecialFolder.Programs) }) {
                object link = shellType.InvokeMember("CreateShortcut", BindingFlags.InvokeMethod, null, shell, new object[] { Path.Combine(folder, "ASR.lnk") });
                Type linkType = link.GetType();
                linkType.InvokeMember("TargetPath", BindingFlags.SetProperty, null, link, new object[] { exe });
                linkType.InvokeMember("WorkingDirectory", BindingFlags.SetProperty, null, link, new object[] { Path.GetDirectoryName(exe) });
                linkType.InvokeMember("IconLocation", BindingFlags.SetProperty, null, link, new object[] { exe + ",0" });
                linkType.InvokeMember("Description", BindingFlags.SetProperty, null, link, new object[] { "ASR" });
                linkType.InvokeMember("Save", BindingFlags.InvokeMethod, null, link, null);
            }
        }

        public static void Start(string exe) {
            var start = new ProcessStartInfo(exe) { WorkingDirectory = Path.GetDirectoryName(exe), UseShellExecute = false };
            foreach (var setting in Settings) start.EnvironmentVariables[setting.Key] = setting.Value;
            Process.Start(start);
        }
    }

    public sealed class Window : Form {
        readonly Label state; readonly ProgressBar bar;
        public Window() {
            Text = "ASR Setup"; Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);
            ClientSize = new Size(520, 150); FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 10); BackColor = Color.FromArgb(24, 29, 35); ForeColor = Color.FromArgb(244, 240, 229);
            Controls.Add(new Label { Text = "Installing ASR", Font = new Font("Segoe UI", 15, FontStyle.Bold), Location = new Point(24, 18), AutoSize = true });
            state = new Label { Text = "Preparing...", Location = new Point(26, 60), Size = new Size(470, 24), AutoEllipsis = true, ForeColor = Color.FromArgb(196, 205, 213) };
            bar = new ProgressBar { Location = new Point(26, 96), Size = new Size(468, 22), Style = ProgressBarStyle.Marquee, AccessibleName = "Download progress" };
            Controls.Add(state); Controls.Add(bar);
        }
        public void Status(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Status), message); return; } state.Text = message; }
        public void Progress(long done, long total) {
            if (InvokeRequired) { BeginInvoke(new Action<long, long>(Progress), done, total); return; }
            bar.Style = ProgressBarStyle.Continuous; bar.Value = (int)Math.Min(100, done * 100 / Math.Max(1, total));
            state.Text = String.Format("Downloading the game: {0:0.0} of {1:0.0} GB", done / 1e9, total / 1e9);
        }
        public void SavePreview(string path) { using (Bitmap image = new Bitmap(Width, Height)) { DrawToBitmap(image, new Rectangle(0, 0, Width, Height)); image.Save(path); } }
    }

    static class Program {
        [STAThread] static int Main(string[] args) {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            if (args.Length == 2 && args[0] == "--render-preview") {
                using (Window form = new Window()) { form.Show(); form.Progress(420000000, 1400000000); Application.DoEvents(); form.SavePreview(args[1]); }
                return 0;
            }
            string folder = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "ASR", "game");
            for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--dir") folder = Path.GetFullPath(args[i + 1]);
            bool test = args.Contains("--test");  // install only: no settings, shortcuts or game start
            Exception failure = null;
            using (Window window = new Window()) {
                window.Shown += async (s, e) => {
                    try {
                        await Task.Run(() => {
                            Game.Install(folder, window.Status, window.Progress);
                            if (test) return;
                            window.Status("Adding shortcuts..."); Game.Configure(); Game.Shortcuts(Path.Combine(folder, Game.ExeName));
                        });
                    } catch (Exception error) { failure = error; }
                    window.Close();
                };
                Application.Run(window);
            }
            if (failure != null) {
                if (test) Console.Error.WriteLine(failure);
                else MessageBox.Show(failure.Message, "ASR Setup", MessageBoxButtons.OK, MessageBoxIcon.Error);
                return 1;
            }
            if (!test) Game.Start(Path.Combine(folder, Game.ExeName));
            return 0;
        }
    }
}
