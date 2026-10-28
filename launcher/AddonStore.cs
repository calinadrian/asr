// Addon files belong in benilla-config/AddOns; preferences and staging stay outside the game's index.
using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Web.Script.Serialization;

namespace ASR.Setup {
    public sealed class AddonChoices { public string[] removed = new string[0]; }
    public sealed class InstalledAddon { public string name; public string title; public bool managed; }

    public sealed class AddonStore {
        public const long MaxZip = 16L << 20, MaxExpanded = 64L << 20;
        public readonly string Folder, Root;
        readonly string config, choices;
        readonly Func<string, long, byte[]> download;
        static readonly JavaScriptSerializer Json = new JavaScriptSerializer();
        static readonly Regex Name = new Regex(@"^[A-Za-z0-9_-]{1,40}$");
        static readonly HashSet<string> Extensions = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            ".toc", ".lua", ".xml", ".txt", ".md", ".blp", ".tga", ".png", ".jpg", ".jpeg",
            ".ttf", ".otf", ".wav", ".mp3", ".ogg", ".csv", ".json"
        };
        static readonly HashSet<string> Documents = new HashSet<string>(StringComparer.OrdinalIgnoreCase) {
            "LICENSE", "COPYING", "README", "CHANGELOG", "AUTHORS"
        };

        public AddonStore(string folder, Func<string, long, byte[]> fetch = null) {
            Folder = Path.GetFullPath(folder);
            if (Folder.Length > Path.GetPathRoot(Folder).Length) Folder = Folder.TrimEnd(Path.DirectorySeparatorChar);
            config = Path.Combine(Folder, "benilla-config");
            Root = Path.Combine(config, "AddOns"); choices = Path.Combine(config, "asr-addons.json");
            download = fetch ?? Game.Download;
        }

        sealed class Lease : IDisposable {
            readonly Mutex mutex;
            public Lease(string folder) {
                byte[] hash;
                using (var sha = SHA256.Create()) hash = sha.ComputeHash(Encoding.UTF8.GetBytes(folder.ToUpperInvariant()));
                mutex = new Mutex(false, @"Local\ASR.Addons." + BitConverter.ToString(hash).Replace("-", ""));
                bool entered;
                try { entered = mutex.WaitOne(30000); } catch (AbandonedMutexException) { entered = true; }
                if (!entered) { mutex.Dispose(); throw new IOException("Another addon operation is still running. Try again shortly."); }
            }
            public void Dispose() { mutex.ReleaseMutex(); mutex.Dispose(); }
        }

        void Prepare() { RegularPath(Root); Directory.CreateDirectory(Root); RegularPath(choices); }
        static void RegularPath(string path) {
            for (string p = Path.GetFullPath(path); !String.IsNullOrEmpty(p); p = Path.GetDirectoryName(p))
                if ((Directory.Exists(p) || File.Exists(p)) && (File.GetAttributes(p) & FileAttributes.ReparsePoint) != 0)
                    throw new IOException("Addon paths cannot use symbolic links or junctions.");
        }
        static void RegularTree(string path) {
            RegularPath(path);
            foreach (string entry in Directory.EnumerateFileSystemEntries(path)) {
                RegularPath(entry);
                if (Directory.Exists(entry)) RegularTree(entry);
            }
        }
        string Target(string name) {
            if (name == null || !Name.IsMatch(name)) throw new InvalidDataException("Invalid addon folder name.");
            string path = Path.Combine(Root, name); RegularPath(path); return path;
        }
        HashSet<string> Removed() {
            if (!File.Exists(choices)) return new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            if (new FileInfo(choices).Length > 65536) throw new InvalidDataException("The addon preferences file is too large.");
            var state = Json.Deserialize<AddonChoices>(File.ReadAllText(choices));
            if (state == null || state.removed == null || state.removed.Any(n => n == null || !Name.IsMatch(n)))
                throw new InvalidDataException("The addon preferences file is invalid.");
            return new HashSet<string>(state.removed, StringComparer.OrdinalIgnoreCase);
        }
        void Save(HashSet<string> removed) {
            string fresh = Path.Combine(config, ".asr-addons-" + Guid.NewGuid().ToString("N") + ".tmp");
            try {
                File.WriteAllText(fresh, Json.Serialize(new AddonChoices { removed = removed.OrderBy(n => n).ToArray() }));
                if (File.Exists(choices)) File.Replace(fresh, choices, null); else File.Move(fresh, choices);
            } finally { if (File.Exists(fresh)) File.Delete(fresh); }
        }

        public Addon[] Catalog() {
            // Release assets are replaced in place. GitHub's CDN can keep the old
            // redirect cached even after a successful upload; each refresh needs
            // a new URL, including install-time catalog verification.
            string url = Game.Release + "addons.json?refresh=" + Guid.NewGuid().ToString("N");
            var manifest = Json.Deserialize<Addons>(Encoding.UTF8.GetString(download(url, 1 << 20)));
            if (manifest == null || manifest.addons == null || manifest.addons.Length > 200)
                throw new InvalidDataException("The addon catalog is invalid.");
            var names = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            foreach (Addon addon in manifest.addons) {
                if (addon == null || addon.name == null || !Name.IsMatch(addon.name) || !names.Add(addon.name) ||
                    addon.url == null || !Regex.IsMatch(addon.url, @"^[A-Za-z0-9_-][A-Za-z0-9._-]{0,119}\.zip$") ||
                    addon.size < 1 || addon.size > MaxZip || addon.sha256 == null || !Regex.IsMatch(addon.sha256, @"^[0-9a-f]{64}$"))
                    throw new InvalidDataException("The addon catalog contains an invalid entry.");
            }
            return manifest.addons;
        }

        public InstalledAddon[] Installed() {
            using (new Lease(Folder)) {
                Prepare(); var result = new List<InstalledAddon>();
                foreach (string path in Directory.EnumerateDirectories(Root)) {
                    string name = Path.GetFileName(path);
                    if (!Name.IsMatch(name)) continue;
                    RegularPath(path);
                    string toc = Path.Combine(path, name + ".toc");
                    if (!File.Exists(toc)) continue;
                    RegularPath(toc);
                    string title = name;
                    if (new FileInfo(toc).Length <= 65536)
                        foreach (string line in File.ReadLines(toc))
                            if (line.StartsWith("## Title:", StringComparison.OrdinalIgnoreCase)) { title = line.Substring(9).Trim(); break; }
                    result.Add(new InstalledAddon { name = name, title = title, managed = File.Exists(Path.Combine(path, Game.AddonMarker)) });
                }
                return result.OrderBy(a => a.title).ToArray();
            }
        }

        static string Hash(byte[] data) {
            using (var sha = SHA256.Create()) return BitConverter.ToString(sha.ComputeHash(data)).Replace("-", "").ToLowerInvariant();
        }
        public void Install(Addon addon) {
            using (new Lease(Folder)) {
                Prepare();
                // Re-read the trusted catalog entry instead of accepting a caller-supplied URL or checksum.
                Addon current = Catalog().SingleOrDefault(a => a.name.Equals(addon.name, StringComparison.OrdinalIgnoreCase));
                if (current == null) throw new IOException("This addon is no longer in the catalog. Refresh the list.");
                InstallCatalog(current);
            }
        }
        void InstallCatalog(Addon addon) {
            string target = Target(addon.name);
            if (Directory.Exists(target) && !File.Exists(Path.Combine(target, Game.AddonMarker)))
                throw new IOException("A local copy of this addon is installed. Remove it first to use the catalog version.");
            byte[] data = download(Game.Release + addon.url, addon.size);
            if (data.LongLength != addon.size || Hash(data) != addon.sha256) throw new InvalidDataException("The addon download failed verification.");
            InstallZip(data, addon.name, true, addon.sha256);
        }

        public string Import(string zipPath, bool replace) {
            using (new Lease(Folder)) {
                Prepare();
                if (new FileInfo(zipPath).Length > MaxZip) throw new InvalidDataException("Addon ZIP files must be smaller than 16 MB.");
                return InstallZip(File.ReadAllBytes(zipPath), null, replace, null);
            }
        }

        string InstallZip(byte[] zip, string expected, bool replace, string catalogHash) {
            string stage = Path.Combine(config, ".asr-addon-stage-" + Guid.NewGuid().ToString("N"));
            Directory.CreateDirectory(stage);
            string backup = null, target = null;
            try {
                string name = expected;
                using (var archive = new ZipArchive(new MemoryStream(zip), ZipArchiveMode.Read)) {
                    if (archive.Entries.Count < 1 || archive.Entries.Count > 4096) throw new InvalidDataException("The addon ZIP contains too many files.");
                    string archiveRoot = null;
                    if (expected == null) {
                        var toc = archive.Entries.Where(e => e.FullName.Replace('\\', '/').Split('/').Length == 2 &&
                            Path.GetExtension(e.FullName).Equals(".toc", StringComparison.OrdinalIgnoreCase)).ToArray();
                        if (toc.Length == 1) {
                            archiveRoot = toc[0].FullName.Replace('\\', '/').Split('/')[0];
                            name = Path.GetFileNameWithoutExtension(toc[0].FullName.Replace('\\', '/'));
                        }
                    }
                    var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase); long expanded = 0;
                    foreach (var entry in archive.Entries) {
                        string relative = entry.FullName.Replace('\\', '/');
                        bool directory = relative.EndsWith("/", StringComparison.Ordinal);
                        string[] parts = relative.TrimEnd('/').Split('/');
                        if (parts.Length < 1 || parts.Any(p => p.Length == 0 || p == "." || p == ".." || p.EndsWith(".") || p.EndsWith(" ") ||
                            p.IndexOfAny(new[] { ':', '\0', '<', '>', '|', '?', '*' }) >= 0 || p.Any(c => c < 32) ||
                            Regex.IsMatch(p, @"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\.|$)", RegexOptions.IgnoreCase)) ||
                            ((entry.ExternalAttributes >> 16) & 0xF000) == 0xA000)
                            throw new InvalidDataException("The addon ZIP contains an unsafe path.");
                        if (name == null) name = parts[0];
                        if (archiveRoot == null) archiveRoot = name;
                        if (!Name.IsMatch(name) || parts[0] != archiveRoot) throw new InvalidDataException("The ZIP must contain one addon folder with its matching .toc file.");
                        if (!seen.Add(relative.TrimEnd('/'))) throw new InvalidDataException("The addon ZIP contains duplicate paths.");
                        if (directory) continue;
                        if (parts.Length < 2 || !(Extensions.Contains(Path.GetExtension(relative)) || Documents.Contains(parts[parts.Length-1])))
                            throw new InvalidDataException("The addon ZIP contains an unsupported file type. Executables and command scripts are not allowed.");
                        if (entry.Length < 0 || entry.Length > MaxExpanded || expanded + entry.Length > MaxExpanded)
                            throw new InvalidDataException("The addon ZIP expands beyond the 64 MB limit.");
                        parts[0] = name;
                        string path = Path.GetFullPath(Path.Combine(stage, String.Join(Path.DirectorySeparatorChar.ToString(), parts)));
                        if (!path.StartsWith(stage + Path.DirectorySeparatorChar, StringComparison.OrdinalIgnoreCase) || path.Length > 240)
                            throw new InvalidDataException("An addon path is unsafe or too long.");
                        Directory.CreateDirectory(Path.GetDirectoryName(path));
                        using (Stream input = entry.Open()) using (var output = File.Create(path)) {
                            byte[] buffer = new byte[65536]; int count; long written = 0;
                            while ((count = input.Read(buffer, 0, buffer.Length)) > 0) {
                                written += count; expanded += count;
                                if (expanded > MaxExpanded || written > entry.Length) throw new InvalidDataException("The addon ZIP exceeds its declared size.");
                                output.Write(buffer, 0, count);
                            }
                            if (written != entry.Length) throw new InvalidDataException("An addon file is incomplete.");
                        }
                    }
                }
                string fresh = Path.Combine(stage, name ?? "");
                if (name == null || !File.Exists(Path.Combine(fresh, name + ".toc")))
                    throw new InvalidDataException("The ZIP must contain AddonName/AddonName.toc for a WoW 1.12 addon.");
                target = Target(name);
                if (Directory.Exists(target) && !replace) throw new IOException("This addon is already installed. Remove it first to replace it.");
                if (Directory.Exists(target)) {
                    RegularTree(target); backup = Path.Combine(config, ".asr-addon-backup-" + Guid.NewGuid().ToString("N"));
                    Directory.Move(target, backup);
                }
                try {
                    if (catalogHash != null) File.WriteAllText(Path.Combine(fresh, Game.AddonMarker), catalogHash);
                    Directory.Move(fresh, target);
                    var removed = Removed(); removed.Remove(name); Save(removed);
                } catch {
                    if (Directory.Exists(target)) Directory.Delete(target, true);
                    if (backup != null) { Directory.Move(backup, target); backup = null; }
                    throw;
                }
                if (backup != null) { Directory.Delete(backup, true); backup = null; }
                return name;
            } finally { if (Directory.Exists(stage)) Directory.Delete(stage, true); }
        }

        public void Remove(string name) {
            using (new Lease(Folder)) {
                Prepare(); string path = Target(name);
                if (!Directory.Exists(path)) return;
                RegularTree(path);
                var removed = Removed(); removed.Add(name); Save(removed);
                // Rename out of the game's index first, so a failed cleanup cannot leave a partial addon loaded.
                string trash = Path.Combine(config, ".asr-addon-removed-" + Guid.NewGuid().ToString("N"));
                Directory.Move(path, trash); Directory.Delete(trash, true);
            }
        }

        public void Sync(Action<string> log) {
            using (new Lease(Folder)) {
                Prepare(); var removed = Removed();
                foreach (Addon addon in Catalog()) {
                    string path = Target(addon.name), marker = Path.Combine(path, Game.AddonMarker);
                    // New catalog entries and player removals always require an explicit Install action.
                    if (removed.Contains(addon.name) || !Directory.Exists(path) || !File.Exists(marker)) continue;
                    RegularPath(marker);
                    if (File.ReadAllText(marker).Trim() == addon.sha256) continue;
                    InstallCatalog(addon); log("addons: updated " + addon.name);
                }
            }
        }
    }
}
