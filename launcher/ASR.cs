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

namespace ASR {
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
                // With presence on, the game browses co-op through its author's presence connection instead of this URL.
                start.EnvironmentVariables["WOW_ROGUE_PRESENCE"] = "0";
                // The game updates itself from our GitHub release, then restarts with this same environment.
                start.EnvironmentVariables["WOW_ROGUE_UPDATE_URL"] = GameUpdateUrl;
                start.EnvironmentVariables["WOW_ROGUE_UPDATE_AUTO"] = "1";
                start.EnvironmentVariables["WOW_ROGUE_DATA_URL"] = GameInstall.ReleaseUrl + "patches.json";
                Process game = Process.Start(start);
                while (true) {
                    game.WaitForExit(); int code = game.ExitCode; game.Dispose();
                    game = Restarted(executable);
                    if (game == null) return code;
                }
            }
        }
        public const string GameUpdateUrl = GameInstall.ReleaseUrl + "latest.json";
        // Keeps the tunnel open across the game's restart after it installs an update.
        static Process Restarted(string executable) {
            DateTime deadline = DateTime.UtcNow.AddSeconds(20);
            while (DateTime.UtcNow < deadline) {
                foreach (Process candidate in Process.GetProcessesByName(Path.GetFileNameWithoutExtension(executable))) {
                    try { if (String.Equals(candidate.MainModule.FileName, executable, StringComparison.OrdinalIgnoreCase)) return candidate; }
                    catch (System.ComponentModel.Win32Exception) { }
                    catch (InvalidOperationException) { }
                    candidate.Dispose();
                }
                Thread.Sleep(500);
            }
            return null;
        }
    }
    public sealed class GamePart { public string url; public long size; }
    public sealed class GameFile { public string name; public string version; public long size; public string sha256; public GamePart[] parts; }
    public sealed class GameFiles { public GameFile[] patches; }
    // Installs the game from our GitHub release in the format the game's own updaters read: gzip parts per file.
    public static class GameInstall {
        public const string ReleaseUrl = "https://github.com/calinadrian/asr/releases/download/game/";
        public const string ExeName = "AzerothSurvivors.exe";
        static T Manifest<T>(string name) {
            return Update.Json.Deserialize<T>(Encoding.UTF8.GetString(Update.Download(ReleaseUrl + name, 1024 * 1024, null, false)));
        }
        static bool Current(string path, GameFile file) {
            return File.Exists(path) && new FileInfo(path).Length == file.size && Update.FileHash(path) == file.sha256;
        }
        public static void Run(string folder, Action<string> status, Action<long,long> progress) {
            Update.CheckLinks(folder); Directory.CreateDirectory(Path.Combine(folder, "Data"));
            var files = new List<KeyValuePair<string, GameFile>>();
            foreach (string list in new[] { "base.json", "patches.json" })
                foreach (GameFile data in Manifest<GameFiles>(list).patches) {
                    if (data.name == null || !System.Text.RegularExpressions.Regex.IsMatch(data.name, @"^[A-Za-z0-9-]{1,40}\.MPQ$"))
                        throw new InvalidDataException("Unsafe game data name.");
                    files.Add(new KeyValuePair<string, GameFile>(Path.Combine(folder, "Data", data.name), data));
                }
            // The executable comes last: its presence means the installation is complete.
            files.Add(new KeyValuePair<string, GameFile>(Path.Combine(folder, ExeName), Manifest<GameFile>("latest.json")));
            foreach (var file in files)
                if (file.Value.parts == null || file.Value.size < 1 || file.Value.size > 4L << 30 || file.Value.sha256 == null ||
                    file.Value.parts.Any(p => p == null || p.url == null || p.size < 1 || p.size > 64 << 20 || !System.Text.RegularExpressions.Regex.IsMatch(p.url, @"^[A-Za-z0-9._-]{1,120}$")))
                    throw new InvalidDataException("Invalid game manifest.");
            status("Checking installed game files...");
            var missing = files.Where(f => !Current(f.Key, f.Value)).ToList();
            long total = missing.Sum(f => f.Value.parts.Sum(p => p.size)), done = 0;
            foreach (var file in missing) {
                status("Downloading " + Path.GetFileName(file.Key) + "...");
                string packed = file.Key + ".download", unpacked = file.Key + ".new";
                using (FileStream output = File.Create(packed))
                    foreach (GamePart part in file.Value.parts) {
                        byte[] data = Update.Download(ReleaseUrl + part.url, part.size, null, false);
                        if (data.LongLength != part.size) throw new InvalidDataException("A game download was incomplete.");
                        output.Write(data, 0, data.Length); done += data.Length; progress(done, total);
                    }
                using (FileStream input = File.OpenRead(packed)) using (var gzip = new GZipStream(input, CompressionMode.Decompress))
                using (FileStream output = File.Create(unpacked)) gzip.CopyTo(output);
                File.Delete(packed);
                if (!Current(unpacked, file.Value)) { File.Delete(unpacked); throw new InvalidDataException(Path.GetFileName(file.Key) + " failed verification. Try again."); }
                if (File.Exists(file.Key)) File.Delete(file.Key);
                File.Move(unpacked, file.Key);
            }
            status("The game is installed.");
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
        public static readonly string ExeName = "ASR.exe";
        // Launchers up to 0.1.6 accept only release files under this name, so it stays the archive's name for
        // the launcher and is installed as ExeName.
        public const string ArchiveExe = "WorldOfSurvive.exe";
        public static string Installed(string path) { return path == ArchiveExe ? ExeName : path; }
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
            return path == ArchiveExe || path == "server-cert.pem" || path.StartsWith("client/", StringComparison.Ordinal);
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
            if (total > 256 * 1024 * 1024 || !paths.Contains(ArchiveExe) || !paths.Contains("client/bootstrap.py"))
                throw new InvalidDataException("Incomplete or oversized release.");
            return release;
        }
        static bool Digest(string s) { return s != null && s.Length == 64 && s.All(c => "0123456789abcdef".Contains(c)); }
        public static byte[] Download(string url, long limit, Action<long,long> progress, bool pin) {
            Uri uri = new Uri(url);
            if (uri.Scheme != "https") throw new InvalidDataException("HTTPS is required.");
            HttpWebRequest request = (HttpWebRequest)WebRequest.Create(uri);
            request.UserAgent = "ASR/" + BuildInfo.Version;
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
                    if (installed.files.All(f => File.Exists(Path.Combine(root, Installed(f.path))) && FileHash(Path.Combine(root, Installed(f.path))) == f.sha256)) return null;
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
                string target = Path.Combine(root, Installed(file.path));
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
                    string target = Path.Combine(root, Installed(file.path)), copy = Path.Combine(backup, file.path);
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
                    string target = Path.Combine(root, Installed(path)), copy = Path.Combine(backup, path);
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

    // Shown only while a first run downloads the game.
    public sealed class InstallWindow : Form {
        readonly Label state; readonly ProgressBar bar;
        public InstallWindow() {
            Text = "ASR"; Icon = Icon.ExtractAssociatedIcon(Assembly.GetExecutingAssembly().Location);
            ClientSize = new Size(520, 150); FormBorderStyle = FormBorderStyle.FixedSingle; MaximizeBox = false;
            StartPosition = FormStartPosition.CenterScreen; AutoScaleMode = AutoScaleMode.Dpi;
            Font = new Font("Segoe UI", 10); BackColor = Color.FromArgb(24, 29, 35); ForeColor = Color.FromArgb(244, 240, 229);
            Label title = new Label { Text = "Installing ASR", Font = new Font("Segoe UI", 15, FontStyle.Bold), Location = new Point(24, 18), AutoSize = true };
            state = new Label { Text = "Preparing...", Location = new Point(26, 60), Size = new Size(470, 24), AutoEllipsis = true, ForeColor = Color.FromArgb(196, 205, 213) };
            bar = new ProgressBar { Location = new Point(26, 96), Size = new Size(468, 22), Style = ProgressBarStyle.Marquee, AccessibleName = "Download progress" };
            Controls.Add(title); Controls.Add(state); Controls.Add(bar);
        }
        public void Status(string message) { if (InvokeRequired) { BeginInvoke(new Action<string>(Status), message); return; } state.Text = message; }
        public void Progress(long done, long total) {
            if (InvokeRequired) { BeginInvoke(new Action<long,long>(Progress), done, total); return; }
            bar.Style = ProgressBarStyle.Continuous; bar.Value = (int)Math.Min(100, done * 100 / Math.Max(1, total));
            state.Text = String.Format("Downloading the game: {0:0.0} of {1:0.0} GB", done / 1e9, total / 1e9);
        }
        public void SavePreview(string path) { using (Bitmap image = new Bitmap(Width, Height)) { DrawToBitmap(image, new Rectangle(0,0,Width,Height)); image.Save(path); } }
    }

    // ASR.exe has no window of its own: it updates itself quietly, installs the game on the first run,
    // then runs the game with co-op on our server and game updates from our GitHub.
    public static class Starter {
        public static string NativeGame(string root) {
            string preference = Path.Combine(root, "desktop-game.txt");
            if (File.Exists(preference)) {
                string selected = File.ReadAllText(preference).Trim();
                if (File.Exists(selected) && Path.GetFileName(selected).Equals(GameInstall.ExeName, StringComparison.OrdinalIgnoreCase)) return selected;
            }
            foreach (string relative in new[] { "game/native/" + GameInstall.ExeName, "game/" + GameInstall.ExeName }) {
                string path = Path.Combine(root, relative); if (File.Exists(path)) return path;
            }
            return null;
        }
        public static int Run(string root, bool checkUpdates) {
            if (checkUpdates && SelfUpdate(root)) return 0;
            if (NativeGame(root) == null && !Install(root)) return 1;
            return NativeTunnel.Run(root, NativeGame(root));
        }
        static void Log(string root, string message) {
            try { File.AppendAllText(Path.Combine(root, "asr.log"), DateTime.UtcNow.ToString("o") + " " + message + Environment.NewLine); } catch (IOException) { }
        }
        static string Quote(string value) { return "\"" + value + "\""; }
        // A newer signed ASR.exe is applied by a helper copy, which then starts it with --no-auto-check.
        static bool SelfUpdate(string root) {
            try {
                Release release = Update.Stage(root, message => {}, null);
                if (release == null) return false;
                string stage = File.ReadAllText(Path.Combine(root, "pending-update.txt"));
                string helper = Path.Combine(stage, "update-helper.exe");
                File.Copy(Assembly.GetExecutingAssembly().Location, helper, true);
                Process.Start(new ProcessStartInfo(helper, "--apply-update " + Process.GetCurrentProcess().Id + " " + Quote(root) + " " + Quote(stage)) { UseShellExecute = false });
                Log(root, "Updating ASR to " + release.version);
                return true;
            } catch (Exception error) { Log(root, "Update check failed, starting the installed version: " + error.Message); return false; }
        }
        static bool Install(string root) {
            Exception failure = null; bool finished = false;
            using (InstallWindow window = new InstallWindow()) {
                window.Shown += async (s, e) => {
                    try { await Task.Run(() => GameInstall.Run(Path.Combine(root, "game"), window.Status, window.Progress)); finished = true; }
                    catch (Exception error) { failure = error; }
                    window.Close();
                };
                Application.Run(window);
            }
            if (failure != null)
                MessageBox.Show(failure.Message + "\n\nStart ASR again to continue; finished files are kept.", "ASR", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return finished && NativeGame(root) != null;
        }
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
                    using (InstallWindow form = new InstallWindow()) {
                        form.Show(); form.Progress(420000000, 1400000000); Application.DoEvents(); form.SavePreview(args[1]); form.Close(); return 0;
                    }
                }
                string data = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                // Installations made before the rename keep their folder, with the co-op game installed in it.
                string root = Path.Combine(data, "ASR");
                if (!Directory.Exists(root) && Directory.Exists(Path.Combine(data, "WorldOfSurvive"))) root = Path.Combine(data, "WorldOfSurvive");
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
                    // A launcher updated by 0.1.6 or older runs as WorldOfSurvive.exe; it hands over to a missing or older ASR.exe.
                    string self = Assembly.GetExecutingAssembly().Location;
                    if (!File.Exists(target) || (String.Equals(Path.GetFullPath(self), Path.Combine(root, Update.ArchiveExe), StringComparison.OrdinalIgnoreCase) &&
                        new Version(FileVersionInfo.GetVersionInfo(target).FileVersion) < new Version(FileVersionInfo.GetVersionInfo(self).FileVersion)))
                        File.Copy(self, target, true);
                    Process.Start(new ProcessStartInfo(target, "--root \"" + root + "\"" + (args.Contains("--no-auto-check") ? " --no-auto-check" : "")) { UseShellExecute = false }); return 0;
                }
                using (Mutex mutex = new Mutex(false, "Local\\ASR-" + Update.Hash(Encoding.UTF8.GetBytes(root)).Substring(0,16))) {
                    if (!mutex.WaitOne(0)) return 0;
                    try { return Starter.Run(root, !args.Contains("--no-auto-check")); }
                    finally { mutex.ReleaseMutex(); }
                }
            } catch (Exception error) {
                if (args.Length > 0 && (args[0] == "--verify-release" || args[0] == "--test-update")) {
                    Console.Error.WriteLine(error.Message); return 1;
                }
                MessageBox.Show(error.Message, "ASR", MessageBoxButtons.OK, MessageBoxIcon.Error); return 1;
            }
        }
    }
}
