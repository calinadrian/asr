using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Net;
using System.Net.Security;
using System.Net.Sockets;
using System.Reflection;
using System.Security.Cryptography;
using System.Security.Cryptography.X509Certificates;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

namespace WorldOfSurvive {
    // The game uses its existing plain WebSocket override on loopback. Only this
    // helper connects to the public service, with the launcher's pinned TLS trust.
    public sealed class NativeTunnel : IDisposable {
        readonly TcpListener listener;
        readonly Uri endpoint;
        readonly string address;
        readonly string token;
        readonly List<TcpClient> clients = new List<TcpClient>();
        volatile bool stopped;
        public Action<string> ErrorLog;
        public string GameUrl { get; private set; }
        public NativeTunnel(Uri endpoint, string address) {
            if (endpoint.Scheme != "https") throw new IOException("The desktop server requires HTTPS.");
            this.endpoint = endpoint; this.address = address;
            byte[] random = new byte[24]; using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(random);
            token = BitConverter.ToString(random).Replace("-", "").ToLowerInvariant();
            listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(8);
            GameUrl = "ws://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/" + token;
            Task.Run((Func<Task>)Accept);
        }
        async Task Accept() {
            while (!stopped) {
                TcpClient client;
                try { client = await listener.AcceptTcpClientAsync(); }
                catch (ObjectDisposedException) { return; }
                catch (SocketException) { if (stopped) return; continue; }
                lock (clients) { if (stopped || clients.Count >= 8) { client.Close(); continue; } clients.Add(client); }
                Task forwarding = Task.Run(() => Forward(client));
            }
        }
        async Task Forward(TcpClient client) {
            TcpClient remote = new TcpClient();
            try {
                client.NoDelay = true; client.ReceiveTimeout = 10000;
                NetworkStream local = client.GetStream();
                byte[] header;
                using (MemoryStream bytes = new MemoryStream()) {
                    int next;
                    do {
                        next = local.ReadByte(); if (next < 0 || bytes.Length >= 8192) throw new IOException("Invalid native handshake.");
                        bytes.WriteByte((byte)next);
                        header = bytes.ToArray();
                    } while (header.Length < 4 || header[header.Length-4] != 13 || header[header.Length-3] != 10 || header[header.Length-2] != 13 || header[header.Length-1] != 10);
                }
                string request = Encoding.ASCII.GetString(header);
                string[] lines = request.Split(new[] { "\r\n" }, StringSplitOptions.None);
                if (lines[0] != "GET /" + token + " HTTP/1.1" || lines.Any(l => l.StartsWith("Origin:", StringComparison.OrdinalIgnoreCase)))
                    throw new IOException("Invalid native handshake.");
                Task connecting = remote.ConnectAsync(address, endpoint.Port);
                if (await Task.WhenAny(connecting, Task.Delay(10000)) != connecting) throw new IOException("Desktop server did not respond.");
                await connecting; remote.NoDelay = true;
                using (SslStream secure = new SslStream(remote.GetStream(), false, (sender, certificate, chain, errors) =>
                    certificate != null && Update.Hash(certificate.GetRawCertData()) == Update.Hash(Update.Resource("server.cer")) &&
                    DateTime.UtcNow >= DateTime.Parse(certificate.GetEffectiveDateString()).ToUniversalTime() &&
                    DateTime.UtcNow <= DateTime.Parse(certificate.GetExpirationDateString()).ToUniversalTime() &&
                    (errors & SslPolicyErrors.RemoteCertificateNameMismatch) == 0)) {
                    secure.ReadTimeout = 10000; secure.WriteTimeout = 10000;
                    await secure.AuthenticateAsClientAsync(endpoint.Host, null, System.Security.Authentication.SslProtocols.Tls12, false);
                    lines[0] = "GET /coop/lobby/ HTTP/1.1";
                    for (int i = 1; i < lines.Length; i++) if (lines[i].StartsWith("Host:", StringComparison.OrdinalIgnoreCase)) lines[i] = "Host: " + endpoint.Authority;
                    header = Encoding.ASCII.GetBytes(String.Join("\r\n", lines));
                    await secure.WriteAsync(header, 0, header.Length); await secure.FlushAsync();
                    client.ReceiveTimeout = 0;
                    Task upstream = local.CopyToAsync(secure), downstream = secure.CopyToAsync(local);
                    await Task.WhenAny(upstream, downstream);
                }
            } catch (Exception error) {
                if (error is OutOfMemoryException) throw;
                if (ErrorLog != null && !stopped) ErrorLog(error.GetType().Name + ": " + error.Message);
                // The game displays its native connection error; never fall back
                // to the original public directory when our service is unavailable.
            } finally {
                remote.Close(); client.Close(); lock (clients) clients.Remove(client);
            }
        }
        public void Dispose() {
            stopped = true; listener.Stop();
            lock (clients) foreach (TcpClient client in clients) client.Close();
        }
        public static int Run(string root, string executable) {
            Uri endpoint = new Uri("https://hassian.duckdns.org:47770");
            string address = endpoint.Host;
            string config = Path.Combine(root, "client", "settings.json");
            if (File.Exists(config)) {
                var settings = Update.Json.Deserialize<Dictionary<string, string>>(File.ReadAllText(config));
                endpoint = new Uri(settings["directory"]); address = endpoint.Host;
                if (File.Exists(Path.Combine(root, "use-local-server"))) address = settings["host_lan"];
            }
            using (var tunnel = new NativeTunnel(endpoint, address)) {
                tunnel.ErrorLog = message => { try { File.AppendAllText(Path.Combine(root, "native-network.log"), DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine); } catch (IOException) { } };
                var start = new ProcessStartInfo(executable) { WorkingDirectory = Path.GetDirectoryName(executable), UseShellExecute = false };
                start.EnvironmentVariables["WOW_ROGUE_COOP_URL"] = tunnel.GameUrl;
                using (Process game = Process.Start(start)) { game.WaitForExit(); return game.ExitCode; }
            }
        }
    }
    public sealed class ReleaseFile { public string path; public long size; public string sha256; }
    public sealed class Envelope { public string manifest; public string signature; }
    public sealed class Release {
        public string version; public long sequence; public string archive; public long size;
        public string sha256; public ReleaseFile[] files;
    }
    public static class Update {
        public static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        public static string BaseUrl = "https://github.com/calinadrian/asr/releases/";
        // GitHub serves release assets through redirects to its CDN; only our own test server is certificate-pinned.
        public static bool Pinned = false;
        static string EnvelopeUrl() { return BaseUrl + (Pinned ? "" : "latest/download/") + "latest-envelope.json"; }
        public static string ArchiveUrl(Release release) {
            return Pinned ? BaseUrl + release.archive : BaseUrl + "download/v" + release.version + "/" + release.sha256 + ".zip";
        }
        public static readonly string ExeName = "WorldOfSurvive.exe";
        public static byte[] Resource(string name) {
            using (Stream stream = Assembly.GetExecutingAssembly().GetManifestResourceStream(name)) {
                if (stream == null) throw new InvalidDataException("Missing launcher resource: " + name);
                using (MemoryStream output = new MemoryStream()) { stream.CopyTo(output); return output.ToArray(); }
            }
        }
        public static void Seed(string root) {
            foreach (string path in new[] { "server-cert.pem", "client/bootstrap.py", "client/settings.json" }) {
                string target = Path.Combine(root, path);
                CheckLinks(Path.GetDirectoryName(target));
                if (!File.Exists(target)) {
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    File.WriteAllBytes(target, Resource(path));
                }
            }
        }
        public static string Hash(byte[] value) {
            using (SHA256 hash = SHA256.Create()) { return BitConverter.ToString(hash.ComputeHash(value)).Replace("-", "").ToLowerInvariant(); }
        }
        public static string FileHash(string path) {
            using (SHA256 hash = SHA256.Create()) using (Stream input = File.OpenRead(path)) {
                return BitConverter.ToString(hash.ComputeHash(input)).Replace("-", "").ToLowerInvariant();
            }
        }
        public static bool SafePath(string path) {
            if (String.IsNullOrEmpty(path) || path.Contains("\\") || path.Contains(":") || path.Length > 200) return false;
            if (path.Split('/').Any(p => p == "" || p == "." || p == ".." || p.EndsWith(".") || p.EndsWith(" "))) return false;
            foreach (string part in path.Split('/')) {
                if (part.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0) return false;
                string stem = part.Split('.')[0].ToUpperInvariant();
                if (new[] { "CON", "PRN", "AUX", "NUL", "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9", "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9" }.Contains(stem)) return false;
            }
            return path == ExeName || path == "server-cert.pem" || path.StartsWith("client/", StringComparison.Ordinal);
        }
        public static Release Verify(byte[] manifest, byte[] signature) {
            if (manifest.Length > 65536 || signature.Length != 256) throw new InvalidDataException("Invalid release metadata.");
            using (RSACryptoServiceProvider rsa = new RSACryptoServiceProvider()) {
                rsa.PersistKeyInCsp = false;
                rsa.FromXmlString(Encoding.UTF8.GetString(Resource("release-key.xml")));
                if (!rsa.VerifyData(manifest, CryptoConfig.MapNameToOID("SHA256"), signature))
                    throw new InvalidDataException("Update signature did not match. No files were changed.");
            }
            Release release = Json.Deserialize<Release>(Encoding.UTF8.GetString(manifest));
            Version version;
            if (release == null || !Version.TryParse(release.version, out version) || release.sequence < 1 ||
                release.size < 1 || release.size > 128 * 1024 * 1024 || release.files == null ||
                release.files.Length < 2 || release.files.Length > 256 || !Digest(release.sha256) ||
                release.archive != "releases/" + release.sha256 + ".zip") throw new InvalidDataException("Invalid signed release.");
            HashSet<string> paths = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            long total = 0;
            foreach (ReleaseFile file in release.files) {
                if (file == null || !SafePath(file.path) || !paths.Add(file.path) || file.size < 0 || file.size > 128 * 1024 * 1024 || !Digest(file.sha256))
                    throw new InvalidDataException("Unsafe update file.");
                total += file.size;
            }
            if (total > 256 * 1024 * 1024 || !paths.Contains(ExeName) || !paths.Contains("client/bootstrap.py"))
                throw new InvalidDataException("Incomplete or oversized release.");
            return release;
        }
        static bool Digest(string s) { return s != null && s.Length == 64 && s.All(c => "0123456789abcdef".Contains(c)); }
        public static byte[] Download(string url, long limit, Action<long,long> progress, bool pin) {
            Uri uri = new Uri(url);
            if (uri.Scheme != "https") throw new InvalidDataException("HTTPS is required.");
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(uri);
            request.UserAgent = "WorldOfSurvive/" + BuildInfo.Version;
            request.Timeout = 20000; request.ReadWriteTimeout = 30000;
            request.AllowAutoRedirect = !pin;
            if (pin) {
                request.ServerCertificateValidationCallback = (sender, certificate, chain, errors) =>
                    certificate != null && Hash(certificate.GetRawCertData()) == Hash(Resource("server.cer")) &&
                    DateTime.UtcNow >= DateTime.Parse(certificate.GetEffectiveDateString()).ToUniversalTime() &&
                    DateTime.UtcNow <= DateTime.Parse(certificate.GetExpirationDateString()).ToUniversalTime() &&
                    (errors & SslPolicyErrors.RemoteCertificateNameMismatch) == 0;
            }
            using (HttpWebResponse response = (HttpWebResponse)request.GetResponse()) {
                if (response.StatusCode != HttpStatusCode.OK || response.ContentLength > limit)
                    throw new InvalidDataException("Unexpected download response.");
                using (Stream input = response.GetResponseStream()) using (MemoryStream output = new MemoryStream()) {
                    byte[] buffer = new byte[65536]; int count;
                    while ((count = input.Read(buffer, 0, buffer.Length)) > 0) {
                        if (output.Length + count > limit) throw new InvalidDataException("Download exceeds its size limit.");
                        output.Write(buffer, 0, count);
                        if (progress != null) progress(output.Length, response.ContentLength);
                    }
                    return output.ToArray();
                }
            }
        }
        public static void CheckLinks(string root) {
            DirectoryInfo directory = new DirectoryInfo(Path.GetFullPath(root));
            while (directory != null) {
                if (directory.Exists && (directory.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Choose an installation folder without directory links.");
                directory = directory.Parent;
            }
        }
        public static Release Stage(string root, Action<string> status, Action<long,long> progress) {
            CheckLinks(root);
            Envelope envelope = Json.Deserialize<Envelope>(Encoding.UTF8.GetString(Download(EnvelopeUrl(), 100000, null, Pinned)));
            if (envelope == null) throw new InvalidDataException("Missing release envelope.");
            byte[] bytes = Convert.FromBase64String(envelope.manifest);
            byte[] signature = Convert.FromBase64String(envelope.signature);
            Release release = Verify(bytes, signature);
            if (release.sequence < BuildInfo.Sequence) throw new InvalidDataException("The server offered an older release.");
            string receipt = Path.Combine(root, "installed-release.json");
            if (File.Exists(receipt)) {
                Release installed = Verify(File.ReadAllBytes(receipt), File.ReadAllBytes(receipt + ".sig"));
                if (release.sequence < installed.sequence) throw new InvalidDataException("A rollback was refused.");
                if (release.sequence == installed.sequence) {
                    if (Hash(bytes) != Hash(File.ReadAllBytes(receipt))) throw new InvalidDataException("A release sequence was reused.");
                    if (installed.files.All(f => File.Exists(Path.Combine(root, f.path)) && FileHash(Path.Combine(root, f.path)) == f.sha256)) return null;
                }
            }
            status("Downloading version " + release.version + "...");
            byte[] archive = Download(ArchiveUrl(release), release.size, progress, Pinned);
            if (archive.LongLength != release.size || Hash(archive) != release.sha256) throw new InvalidDataException("Update checksum did not match.");
            string stage = Path.Combine(root, ".update", Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stage);
            try {
                Dictionary<string,ReleaseFile> expected = release.files.ToDictionary(f => f.path, StringComparer.OrdinalIgnoreCase);
                using (ZipArchive zip = new ZipArchive(new MemoryStream(archive), ZipArchiveMode.Read)) {
                    HashSet<string> found = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
                    foreach (ZipArchiveEntry entry in zip.Entries) {
                        ReleaseFile file;
                        if (!SafePath(entry.FullName) || !expected.TryGetValue(entry.FullName, out file) || !found.Add(entry.FullName) ||
                            entry.Length != file.size || ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                            throw new InvalidDataException("Unexpected archive entry.");
                        string target = Path.Combine(stage, file.path);
                        Directory.CreateDirectory(Path.GetDirectoryName(target));
                        entry.ExtractToFile(target);
                        if (FileHash(target) != file.sha256) throw new InvalidDataException("An extracted file failed verification.");
                    }
                    if (found.Count != expected.Count) throw new InvalidDataException("The update is incomplete.");
                }
                File.WriteAllBytes(Path.Combine(stage, "release.json"), bytes);
                File.WriteAllBytes(Path.Combine(stage, "release.sig"), signature);
                File.WriteAllText(Path.Combine(root, "pending-update.txt"), stage);
                return release;
            } catch { Directory.Delete(stage, true); throw; }
        }
        public static void Apply(string root, string stage) {
            root = Path.GetFullPath(root); stage = Path.GetFullPath(stage);
            CheckLinks(root); CheckLinks(stage);
            if (!stage.StartsWith(Path.Combine(root, ".update") + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("Invalid staging folder.");
            byte[] bytes = File.ReadAllBytes(Path.Combine(stage, "release.json"));
            byte[] sig = File.ReadAllBytes(Path.Combine(stage, "release.sig"));
            Release release = Verify(bytes, sig);
            if (release.sequence < BuildInfo.Sequence) throw new InvalidDataException("A rollback was refused.");
            string receipt = Path.Combine(root, "installed-release.json");
            if (File.Exists(receipt)) {
                Release previous = Verify(File.ReadAllBytes(receipt), File.ReadAllBytes(receipt + ".sig"));
                if (previous.sequence > release.sequence) throw new InvalidDataException("A rollback was refused.");
            }
            foreach (ReleaseFile file in release.files) {
                string target = Path.Combine(root, file.path);
                CheckLinks(Path.GetDirectoryName(target)); CheckLinks(Path.GetDirectoryName(Path.Combine(stage, file.path)));
                if (Directory.Exists(target)) throw new IOException("An update target is a directory: " + file.path);
                if ((File.Exists(target) && (File.GetAttributes(target) & FileAttributes.ReparsePoint) != 0) ||
                    FileHash(Path.Combine(stage, file.path)) != file.sha256) throw new InvalidDataException("Update files changed after verification.");
                if (File.Exists(target)) using (FileStream probe = new FileStream(target, FileMode.Open, FileAccess.ReadWrite, FileShare.Read)) { }
            }
            string backup = Path.Combine(stage, "backup");
            List<string> changed = new List<string>();
            byte[] oldReceipt = File.Exists(receipt) ? File.ReadAllBytes(receipt) : null;
            byte[] oldSignature = File.Exists(receipt + ".sig") ? File.ReadAllBytes(receipt + ".sig") : null;
            try {
                foreach (ReleaseFile file in release.files) {
                    string target = Path.Combine(root, file.path), copy = Path.Combine(backup, file.path);
                    Directory.CreateDirectory(Path.GetDirectoryName(target));
                    if (File.Exists(target)) { Directory.CreateDirectory(Path.GetDirectoryName(copy)); File.Copy(target, copy); }
                    changed.Add(file.path);
                    File.Copy(Path.Combine(stage, file.path), target, true);
                }
                File.WriteAllBytes(receipt, bytes); File.WriteAllBytes(receipt + ".sig", sig);
                File.Delete(Path.Combine(root, "pending-update.txt"));
            } catch (Exception failure) {
                List<string> restoreErrors = new List<string>();
                foreach (string path in changed.AsEnumerable().Reverse()) {
                    string target = Path.Combine(root, path), copy = Path.Combine(backup, path);
                    try { if (File.Exists(copy)) File.Copy(copy, target, true); else if (File.Exists(target)) File.Delete(target); }
                    catch { restoreErrors.Add(path); }
                }
                try {
                    if (oldReceipt == null) File.Delete(receipt); else File.WriteAllBytes(receipt, oldReceipt);
                    if (oldSignature == null) File.Delete(receipt + ".sig"); else File.WriteAllBytes(receipt + ".sig", oldSignature);
                } catch { restoreErrors.Add("release receipt"); }
                if (restoreErrors.Count > 0) throw new IOException("Update failed; recovery copies are in " + backup + ". Restore: " + String.Join(", ", restoreErrors), failure);
                throw;
            }
        }
    }

    public sealed class Launcher : Form {
        readonly string root; readonly bool autoCheck;
        Label state, version; TextBox log; ProgressBar progress;
        Button play, check, choose; CheckBox coop; bool busy; Process game;
        public Launcher(string directory, bool automatic) {
            root = directory; autoCheck = automatic;
            Text = "ASR"; ClientSize = new Size(760, 560); MinimumSize = new Size(730, 550);
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 10); BackColor = Color.FromArgb(24, 29, 35); ForeColor = Color.FromArgb(244, 240, 229);
            TableLayoutPanel layout = new TableLayoutPanel { Dock = DockStyle.Fill, Padding = new Padding(30), ColumnCount = 1, RowCount = 9 };
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 62)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 36));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 42));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 24)); layout.RowStyles.Add(new RowStyle(SizeType.Percent, 100));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 34));
            layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 16)); layout.RowStyles.Add(new RowStyle(SizeType.Absolute, 52));
            Label title = new Label { Text = "ASR", Font = new Font("Segoe UI", 25, FontStyle.Bold), Dock = DockStyle.Fill };
            Label endpoint = new Label { Text = "Windows desktop game", Dock = DockStyle.Fill, ForeColor = Color.FromArgb(196, 205, 213) };
            version = new Label { Text = "Launcher " + BuildInfo.Version, Dock = DockStyle.Fill };
            state = new Label { Text = "Ready to check for updates.", Dock = DockStyle.Fill, AutoEllipsis = true, AccessibleName = "Current task" };
            progress = new ProgressBar { Dock = DockStyle.Fill, Minimum = 0, Maximum = 100, AccessibleName = "Download progress" };
            log = new TextBox { Multiline = true, ReadOnly = true, ScrollBars = ScrollBars.Vertical, Dock = DockStyle.Fill,
                BackColor = Color.FromArgb(32, 39, 47), ForeColor = ForeColor, BorderStyle = BorderStyle.FixedSingle, AccessibleName = "Activity log" };
            FlowLayoutPanel actions = new FlowLayoutPanel { Dock = DockStyle.Fill, FlowDirection = FlowDirection.RightToLeft };
            play = new Button { Text = NativeGame() != null ? "Play Windows game" : "Install game", Width = 180, Height = 42, BackColor = Color.FromArgb(232, 182, 76), ForeColor = Color.FromArgb(24,29,35), FlatStyle = FlatStyle.Flat, AccessibleName = "Install or play Windows game" };
            check = new Button { Text = "Check for updates", Width = 175, Height = 42, FlatStyle = FlatStyle.Flat, ForeColor = ForeColor };
            choose = new Button { Text = "Choose game...", Width = 145, Height = 42, FlatStyle = FlatStyle.Flat, ForeColor = ForeColor };
            coop = new CheckBox { Text = "Use separate co-op mod (opens its browser lobby)", Dock = DockStyle.Fill, AutoSize = true };
            actions.Controls.Add(play); actions.Controls.Add(check); actions.Controls.Add(choose);
            layout.Controls.Add(title); layout.Controls.Add(endpoint); layout.Controls.Add(version); layout.Controls.Add(state);
            layout.Controls.Add(progress); layout.Controls.Add(log); layout.Controls.Add(coop); layout.Controls.Add(new Panel()); layout.Controls.Add(actions); Controls.Add(layout);
            AcceptButton = play;
            play.Click += async (s,e) => await RunGame(); check.Click += async (s,e) => await Check();
            choose.Click += (s,e) => ChooseGame();
            Shown += async (s,e) => { Note(NativeGame() != null ? "Desktop game: " + NativeGame() : "Choose an existing Windows game, or install one."); if (autoCheck) await Check(); };
            FormClosing += (s,e) => { if (busy) { e.Cancel = true; Status("Wait for the current operation to finish."); } };
        }
        bool Installed() { return File.Exists(Path.Combine(root, "game", "Start-Coop.cmd")); }
        string NativeGame() {
            string preference = Path.Combine(root, "desktop-game.txt");
            if (File.Exists(preference)) {
                string selected = File.ReadAllText(preference).Trim();
                if (File.Exists(selected) && Path.GetFileName(selected).Equals("AzerothSurvivors.exe", StringComparison.OrdinalIgnoreCase)) return selected;
            }
            foreach (string relative in new[] { "game/native/AzerothSurvivors.exe", "game/AzerothSurvivors.exe" }) {
                string path = Path.Combine(root, relative); if (File.Exists(path)) return path;
            }
            return null;
        }
        void ChooseGame() {
            using (OpenFileDialog picker = new OpenFileDialog { Title = "Choose your Windows game", Filter = "Azeroth Survivors|AzerothSurvivors.exe", CheckFileExists = true }) {
                if (picker.ShowDialog(this) != DialogResult.OK) return;
                File.WriteAllText(Path.Combine(root, "desktop-game.txt"), picker.FileName);
                play.Text = "Play Windows game"; Status("Selected desktop game: " + picker.FileName);
            }
        }
        void Note(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Note), message); return; } log.AppendText(message + Environment.NewLine); }
        void Status(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Status), message); return; } state.Text = message; Note(message); }
        void Progress(long done, long total) {
            if (InvokeRequired) { BeginInvoke(new Action<long,long>(Progress), done, total); return; }
            progress.Style = total > 0 ? ProgressBarStyle.Continuous : ProgressBarStyle.Marquee;
            if (total > 0) progress.Value = (int)Math.Min(100, done * 100 / total);
        }
        void Busy(bool value) { busy = value; play.Enabled = check.Enabled = choose.Enabled = coop.Enabled = !value; if (!value) { progress.Style = ProgressBarStyle.Continuous; progress.Value = 0; } }
        async Task Check() {
            if (busy) return;
            if (game != null && !game.HasExited) { Status("Close your game or co-op session before updating."); return; }
            Busy(true); Status("Checking for ASR updates...");
            try {
                Release release = await Task.Run(() => WorldOfSurvive.Update.Stage(root, Status, Progress));
                if (release == null) { Status("You're up to date."); return; }
                string stage = File.ReadAllText(Path.Combine(root, "pending-update.txt"));
                string helper = Path.Combine(stage, "update-helper.exe");
                File.Copy(Assembly.GetExecutingAssembly().Location, helper, true);
                Process.Start(new ProcessStartInfo(helper, "--apply-update " + Process.GetCurrentProcess().Id + " " + Quote(root) + " " + Quote(stage)) { UseShellExecute = false });
                busy = false; Close();
            } catch (Exception error) { Status("Update unavailable: " + error.Message); Note("You can retry. Installed files have not been replaced."); }
            finally { if (!IsDisposed) Busy(false); }
        }
        static string Quote(string value) { return "\"" + value + "\""; }
        async Task RunGame() {
            if (busy) return;
            if (game != null && !game.HasExited) { Status("Your game or co-op session is already running."); return; }
            Busy(true);
            try {
                if (!coop.Checked && NativeGame() != null) { StartNative(); return; }
                if (!Installed()) {
                    Status("Downloading the co-op installer...");
                    await Task.Run(() => {
                        byte[] installer = WorldOfSurvive.Update.Download(BuildInfo.InstallerUrl, 2 * 1024 * 1024, Progress, false);
                        if (WorldOfSurvive.Update.Hash(installer) != BuildInfo.InstallerSha) throw new InvalidDataException("Installer checksum did not match.");
                        string path = Path.Combine(root, "coop-installer.exe"); File.WriteAllBytes(path, installer);
                        Status("Installing the game. The first download can take several minutes...");
                        ProcessStartInfo info = new ProcessStartInfo(path, "--dir " + Quote(Path.Combine(root, "game")) + " --no-shortcuts --no-open --no-pause") {
                            UseShellExecute = false, CreateNoWindow = true, RedirectStandardOutput = true, RedirectStandardError = true };
                        using (Process process = new Process { StartInfo = info }) {
                            process.OutputDataReceived += (s,e) => { if (e.Data != null) Note(e.Data); };
                            process.ErrorDataReceived += (s,e) => { if (e.Data != null) Note(e.Data); };
                            process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine(); process.WaitForExit();
                            if (process.ExitCode != 0 || !Installed()) throw new IOException("Game installation failed. Retry to resume the download.");
                        }
                    });
                }
                if (!coop.Checked) { StartNative(); return; }
                string bootstrap = Path.Combine(root, "client", "bootstrap.py");
                if (!File.Exists(bootstrap)) throw new IOException("Client files are missing. Use Check for updates first.");
                ProcessStartInfo start = new ProcessStartInfo(Path.Combine(root, "game", ".coop-runtime", "python.exe"), Quote(bootstrap)) {
                    WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
                game = Process.Start(start); Status("Room browser opened. Create a room or join another player."); play.Text = "Play";
            } catch (Exception error) { Status(error.Message); }
            finally { Busy(false); }
        }
        void StartNative() {
            string executable = NativeGame();
            if (executable == null) throw new IOException("Choose AzerothSurvivors.exe using Choose game.");
            foreach (Process running in Process.GetProcessesByName("AzerothSurvivors")) {
                try {
                    if (String.Equals(running.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) {
                        game = running; Status("Your Windows game is already running. Switch to its window to play."); return;
                    }
                } catch (System.ComponentModel.Win32Exception) { }
                catch (InvalidOperationException) { }
            }
            ProcessStartInfo start = new ProcessStartInfo(Assembly.GetExecutingAssembly().Location,
                "--native-session " + Quote(root) + " " + Quote(executable)) { WorkingDirectory = root, UseShellExecute = false, CreateNoWindow = true };
            game = Process.Start(start); Status("Windows game opened. Its co-op menu now connects to the ASR server."); play.Text = "Play Windows game";
        }
        public void SavePreview(string path) { using (Bitmap image = new Bitmap(Width, Height)) { DrawToBitmap(image, new Rectangle(0,0,Width,Height)); image.Save(path); } }
    }

    static class Program {
        [STAThread] static int Main(string[] args) {
            ServicePointManager.SecurityProtocol = SecurityProtocolType.Tls12;
            Application.EnableVisualStyles(); Application.SetCompatibleTextRenderingDefault(false);
            try {
                if (args.Length == 3 && args[0] == "--native-session") return NativeTunnel.Run(args[1], args[2]);
                if (args.Length == 4 && args[0] == "--apply-update") {
                    try { Process parent = Process.GetProcessById(Int32.Parse(args[1])); if (!parent.WaitForExit(60000)) throw new IOException("Launcher is still running."); }
                    catch (ArgumentException) { }
                    Update.Apply(args[2], args[3]);
                    Process.Start(new ProcessStartInfo(Path.Combine(args[2], Update.ExeName), "--root \"" + args[2] + "\" --no-auto-check") { UseShellExecute = false });
                    return 0;
                }
                if (args.Length == 2 && args[0] == "--verify-release") {
                    Update.Verify(File.ReadAllBytes(args[1]), File.ReadAllBytes(args[1] + ".sig")); return 0;
                }
                if (args.Length == 2 && args[0] == "--test-update") {
                    Update.BaseUrl = "https://127.0.0.1:47770/launcher/"; Update.Pinned = true;
                    Directory.CreateDirectory(args[1]);
                    Release staged = Update.Stage(args[1], message => {}, null);
                    if (staged != null) Update.Apply(args[1], File.ReadAllText(Path.Combine(args[1], "pending-update.txt")));
                    return 0;
                }
                if (args.Length == 2 && args[0] == "--render-preview") {
                    using (Launcher form = new Launcher(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location), false)) {
                        form.Show(); Application.DoEvents(); form.SavePreview(args[1]); form.Close(); return 0;
                    }
                }
                string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "WorldOfSurvive");
                for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--root") root = Path.GetFullPath(args[i + 1]);
                Update.CheckLinks(root); Directory.CreateDirectory(root);
                for (int i = 0; i + 1 < args.Length; i++) if (args[i] == "--desktop-game") {
                    string selected = Path.GetFullPath(args[i + 1]);
                    if (!File.Exists(selected) || !Path.GetFileName(selected).Equals("AzerothSurvivors.exe", StringComparison.OrdinalIgnoreCase))
                        throw new IOException("Choose an existing AzerothSurvivors.exe.");
                    File.WriteAllText(Path.Combine(root, "desktop-game.txt"), selected);
                }
                if (args.Contains("--local-server")) File.WriteAllText(Path.Combine(root, "use-local-server"), "1");
                Update.Seed(root);
                string target = Path.Combine(root, Update.ExeName);
                if (!String.Equals(Path.GetFullPath(Assembly.GetExecutingAssembly().Location), target, StringComparison.OrdinalIgnoreCase)) {
                    if (!File.Exists(target)) File.Copy(Assembly.GetExecutingAssembly().Location, target);
                    Process.Start(new ProcessStartInfo(target, "--root \"" + root + "\"" + (args.Contains("--no-auto-check") ? " --no-auto-check" : "")) { UseShellExecute = false }); return 0;
                }
                using (Mutex mutex = new Mutex(false, "Local\\WorldOfSurvive-" + Update.Hash(Encoding.UTF8.GetBytes(root)).Substring(0,16))) {
                    if (!mutex.WaitOne(0)) return 0;
                    try { Application.Run(new Launcher(root, !args.Contains("--no-auto-check"))); }
                    finally { mutex.ReleaseMutex(); }
                }
                return 0;
            } catch (Exception error) {
                if (args.Length > 0 && (args[0] == "--verify-release" || args[0] == "--test-update")) {
                    Console.Error.WriteLine(error.Message); return 1;
                }
                MessageBox.Show(error.Message, "ASR", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
        }
    }
}
