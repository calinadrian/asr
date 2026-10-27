// Play ASR: keeps the game's co-op connection alive while the internet drops. The game connects to this
// process on loopback, a connection that never breaks; this process connects to the server's /coop/relay/
// and, when that link drops, reconnects and resumes the same lobby session (protocol in server/native_relay.py).
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Net.WebSockets;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace ASR.Setup {
    public sealed class Relay {
        public const string ServerUrl = "wss://game.hassian.duckdns.org:47770/coop/relay/";
        // A little under the server's 120 seconds, so we give up before it does.
        public static readonly TimeSpan Grace = TimeSpan.FromSeconds(110);
        readonly Uri server;
        readonly TcpListener listener;
        readonly string token;
        readonly Action<string> log;
        public string GameUrl { get; private set; }

        public Relay(Uri server, Action<string> log) {
            this.server = server; this.log = log;
            byte[] random = new byte[24]; using (var rng = RandomNumberGenerator.Create()) rng.GetBytes(random);
            token = BitConverter.ToString(random).Replace("-", "").ToLowerInvariant();
            listener = new TcpListener(IPAddress.Loopback, 0); listener.Start(8);
            GameUrl = "ws://127.0.0.1:" + ((IPEndPoint)listener.LocalEndpoint).Port + "/" + token;
            Task.Run((Func<Task>)Accept);
        }

        async Task Accept() {
            while (true) {
                TcpClient client;
                try { client = await listener.AcceptTcpClientAsync(); }
                catch (ObjectDisposedException) { return; }
                catch (SocketException) { continue; }
                Task tunnel = Task.Run(() => new Tunnel(this, client).Run());
            }
        }

        sealed class Tunnel {
            readonly Relay relay; readonly TcpClient client; NetworkStream local;
            readonly object localWrite = new object(), state = new object();
            readonly SemaphoreSlim sending = new SemaphoreSlim(1, 1);
            // Messages from the game, numbered from 0; pending holds firstPending..sent-1 until the server acknowledges them.
            readonly List<byte[]> pending = new List<byte[]>();
            long firstPending, sent, linkSent, received;
            byte[] session = new byte[16];
            ClientWebSocket link;
            volatile bool closing;

            public Tunnel(Relay relay, TcpClient client) { this.relay = relay; this.client = client; }

            public async Task Run() {
                try {
                    client.NoDelay = true; local = client.GetStream(); local.ReadTimeout = 10000;
                    string key = Handshake();
                    // Only a reachable server lets the game in; otherwise it shows its own "cannot be reached".
                    if (!await Connect()) { Reply("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n"); return; }
                    string accept = Convert.ToBase64String(SHA1.Create().ComputeHash(Encoding.ASCII.GetBytes(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")));
                    Reply("HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Accept: " + accept + "\r\n\r\n");
                    local.ReadTimeout = Timeout.Infinite;
                    Task upstream = Task.Run((Func<Task>)Upstream), heartbeat = Task.Run((Func<Task>)Heartbeat);
                    FromGame();
                } catch (Exception error) {
                    if (error is OutOfMemoryException) throw;
                    if (!closing) relay.log("game connection: " + error.GetType().Name + ": " + error.Message);
                } finally {
                    closing = true;
                    ClientWebSocket current = link;
                    if (current != null) {
                        // Tell the server the game left, so the party sees it at once rather than after the grace period.
                        if (sending.Wait(3000))
                            try { Send(current, new byte[] { (byte)'E' }).Wait(3000); } catch (Exception) { } finally { sending.Release(); }
                        current.Abort();
                    }
                    client.Close();
                }
            }

            string Handshake() {
                var bytes = new MemoryStream();
                while (bytes.Length < 4 || !Encoding.ASCII.GetString(bytes.ToArray()).EndsWith("\r\n\r\n")) {
                    int next = local.ReadByte();
                    if (next < 0 || bytes.Length >= 8192) throw new IOException("Invalid game handshake.");
                    bytes.WriteByte((byte)next);
                }
                string[] lines = Encoding.ASCII.GetString(bytes.ToArray()).Split(new[] { "\r\n" }, StringSplitOptions.None);
                if (lines[0] != "GET /" + relay.token + " HTTP/1.1" || lines.Any(l => l.StartsWith("Origin:", StringComparison.OrdinalIgnoreCase)))
                    throw new IOException("Invalid game handshake.");
                string key = lines.Where(l => l.StartsWith("Sec-WebSocket-Key:", StringComparison.OrdinalIgnoreCase)).Select(l => l.Substring(18).Trim()).FirstOrDefault();
                if (key == null) throw new IOException("Invalid game handshake.");
                return key;
            }

            void Reply(string text) { byte[] data = Encoding.ASCII.GetBytes(text); local.Write(data, 0, data.Length); local.Flush(); }

            // Reads the game's frames until it closes the connection.
            void FromGame() {
                var message = new MemoryStream();
                while (true) {
                    byte[] head = Read(2);
                    bool final = (head[0] & 128) != 0; int opcode = head[0] & 15;
                    long size = head[1] & 127;
                    if ((head[1] & 128) == 0) throw new IOException("Unmasked game frame.");
                    if (size == 126) { byte[] b = Read(2); size = (b[0] << 8) | b[1]; }
                    else if (size == 127) { byte[] b = Read(8); size = 0; foreach (byte v in b) size = (size << 8) | v; }
                    if (size > 2 << 20 || message.Length + size > 2 << 20) throw new IOException("Game message too large.");
                    byte[] mask = Read(4), payload = Read((int)size);
                    for (int i = 0; i < payload.Length; i++) payload[i] ^= mask[i % 4];
                    if (opcode == 8) return;
                    if (opcode == 9) { ToGame(payload, 10); continue; }
                    if (opcode == 10) continue;
                    message.Write(payload, 0, payload.Length);
                    if (!final) continue;
                    byte[] whole = message.ToArray(); message.SetLength(0);
                    // The lobby's ping (9) is answered here (28), so the game never waits on a dropped link.
                    if (whole.Length == 1 && whole[0] == 9) { ToGame(new byte[] { 28 }, 2); continue; }
                    lock (state) { pending.Add(whole); sent++; }
                    Flush();
                }
            }

            byte[] Read(int count) {
                byte[] data = new byte[count]; int done = 0;
                while (done < count) {
                    int n = local.Read(data, done, count - done);
                    if (n <= 0) throw new EndOfStreamException();
                    done += n;
                }
                return data;
            }

            void ToGame(byte[] payload, int opcode) {
                var frame = new MemoryStream();
                frame.WriteByte((byte)(128 | opcode));
                if (payload.Length < 126) frame.WriteByte((byte)payload.Length);
                else if (payload.Length < 65536) { frame.WriteByte(126); frame.WriteByte((byte)(payload.Length >> 8)); frame.WriteByte((byte)payload.Length); }
                else { frame.WriteByte(127); for (int shift = 56; shift >= 0; shift -= 8) frame.WriteByte((byte)((long)payload.Length >> shift)); }
                frame.Write(payload, 0, payload.Length);
                lock (localWrite) { local.Write(frame.GetBuffer(), 0, (int)frame.Length); }
            }

            static async Task Send(ClientWebSocket socket, byte[] data) {
                await socket.SendAsync(new ArraySegment<byte>(data), WebSocketMessageType.Binary, true, CancellationToken.None);
            }

            static byte[] Prefixed(char kind, byte[] data) {
                byte[] result = new byte[data.Length + 1]; result[0] = (byte)kind; Buffer.BlockCopy(data, 0, result, 1, data.Length); return result;
            }

            // Sends every message the current link has not carried yet, in order.
            void Flush() {
                sending.Wait();
                try {
                    while (true) {
                        ClientWebSocket current; byte[] next;
                        lock (state) {
                            current = link;
                            if (current == null || linkSent >= sent) return;
                            next = pending[(int)(linkSent - firstPending)];
                        }
                        try { Send(current, Prefixed('D', next)).Wait(); }
                        catch (Exception) { Drop(current); return; }
                        lock (state) { if (link == current) linkSent++; }
                    }
                } finally { sending.Release(); }
            }

            void Drop(ClientWebSocket socket) {
                lock (state) { if (link == socket) link = null; }
                try { socket.Abort(); } catch (Exception) { }
            }

            static async Task<byte[]> Receive(ClientWebSocket socket, TimeSpan timeout) {
                var message = new MemoryStream(); byte[] buffer = new byte[65536];
                using (var cancel = new CancellationTokenSource(timeout)) {
                    while (true) {
                        WebSocketReceiveResult result = await socket.ReceiveAsync(new ArraySegment<byte>(buffer), cancel.Token);
                        if (result.MessageType == WebSocketMessageType.Close) return null;
                        message.Write(buffer, 0, result.Count);
                        if (message.Length > 2 << 20) throw new IOException("Server message too large.");
                        if (result.EndOfMessage) return message.ToArray();
                    }
                }
            }

            // Opens a link and resumes the session on it; false when the server can't be reached.
            async Task<bool> Connect() {
                var socket = new ClientWebSocket();
                try {
                    using (var cancel = new CancellationTokenSource(TimeSpan.FromSeconds(10)))
                        await socket.ConnectAsync(relay.server, cancel.Token);
                    byte[] hello = new byte[25]; hello[0] = (byte)'H';
                    lock (state) { Buffer.BlockCopy(session, 0, hello, 1, 16); BitConverter.GetBytes(received).CopyTo(hello, 17); }
                    await Send(socket, hello);
                    byte[] welcome = await Receive(socket, TimeSpan.FromSeconds(10));
                    if (welcome != null && welcome.Length == 1 && welcome[0] == 'X') throw new SessionEnded();
                    if (welcome == null || welcome.Length != 25 || welcome[0] != 'W') throw new IOException("Unexpected relay reply.");
                    sending.Wait();
                    try {
                        lock (state) {
                            Buffer.BlockCopy(welcome, 1, session, 0, 16);
                            Acknowledge(BitConverter.ToInt64(welcome, 17));
                            linkSent = firstPending;
                            link = socket;
                        }
                    } finally { sending.Release(); }
                    Flush();
                    return true;
                } catch (SessionEnded) { socket.Abort(); throw; }
                catch (Exception error) {
                    if (error is OutOfMemoryException) throw;
                    relay.log("server link: " + error.GetType().Name + ": " + error.Message);
                    socket.Abort(); return false;
                }
            }

            void Acknowledge(long count) {
                if (count > sent) throw new IOException("Server acknowledged messages it never got.");
                if (count <= firstPending) return;
                pending.RemoveRange(0, (int)(count - firstPending)); firstPending = count;
            }

            // Delivers the server's messages to the game, and reconnects whenever the link drops.
            async Task Upstream() {
                DateTime dropped = DateTime.MaxValue;
                try {
                    while (!closing) {
                        ClientWebSocket current = link;
                        if (current == null) {
                            if (DateTime.UtcNow - dropped > Grace) { relay.log("gave up reconnecting"); break; }
                            if (!await Connect()) { await Task.Delay(1000); continue; }
                            relay.log("resumed the co-op session");
                            continue;
                        }
                        byte[] message;
                        try { message = await Receive(current, TimeSpan.FromSeconds(15)); }
                        catch (Exception) { message = null; }
                        if (message == null || message.Length == 0) {
                            if (closing) break;
                            relay.log("server link dropped; reconnecting");
                            Drop(current); dropped = DateTime.UtcNow; continue;
                        }
                        if (message[0] == 'D') {
                            byte[] payload = new byte[message.Length - 1]; Buffer.BlockCopy(message, 1, payload, 0, payload.Length);
                            ToGame(payload, 2);
                            lock (state) received++;
                        } else if (message[0] == 'A' && message.Length == 9) {
                            lock (state) Acknowledge(BitConverter.ToInt64(message, 1));
                        } else if (message[0] == 'E') {
                            break;  // the server ended the session; the game sees its connection close
                        }
                    }
                } catch (SessionEnded) {
                    relay.log("the server had already ended the session");
                } catch (Exception error) {
                    if (error is OutOfMemoryException) throw;
                    if (!closing) relay.log("relay: " + error.GetType().Name + ": " + error.Message);
                }
                closing = true;
                client.Close();
            }

            // Tells the server what arrived, and proves the link is alive.
            async Task Heartbeat() {
                while (!closing) {
                    await Task.Delay(5000);
                    ClientWebSocket current = link;
                    if (current == null) continue;
                    byte[] ack = new byte[9]; ack[0] = (byte)'A';
                    lock (state) BitConverter.GetBytes(received).CopyTo(ack, 1);
                    await sending.WaitAsync();
                    try { await Send(current, ack); }
                    catch (Exception) { Drop(current); }
                    finally { sending.Release(); }
                }
            }
        }

        sealed class SessionEnded : Exception { }
    }
}
