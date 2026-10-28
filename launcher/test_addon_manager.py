"""Addon archive, persistent-choice and native-button integration contracts."""
import hashlib
import os
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import addon_manager_patch

ROOT = Path(__file__).resolve().parents[1]
CSC = Path(os.environ.get('WINDIR', r'C:\Windows')) / 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'

HARNESS = r'''
using System; using System.IO; using System.IO.Compression; using System.Linq;
using System.Security.Cryptography; using System.Text; using System.Web.Script.Serialization;
using ASR.Setup;
public static class AddonStoreChecks {
 static void Check(bool ok,string text) { if(!ok)throw new Exception(text); Console.WriteLine("PASS "+text); }
 static byte[] Zip(params string[] paths) {
  using(var stream=new MemoryStream()) {
   using(var zip=new ZipArchive(stream,ZipArchiveMode.Create,true))
    foreach(string path in paths) using(var file=new StreamWriter(zip.CreateEntry(path).Open())) file.Write(path.EndsWith(".toc")?"## Interface: 11200\n## Title: Fixture\nmain.lua":"-- fixture");
   return stream.ToArray();
  }
 }
 static string Hash(byte[] b) { using(var sha=SHA256.Create())return BitConverter.ToString(sha.ComputeHash(b)).Replace("-","").ToLowerInvariant(); }
 static void Reject(Action action,string text) { bool failed=false;try{action();}catch(InvalidDataException){failed=true;}catch(IOException){failed=true;}Check(failed,text); }
 public static int Main(string[] args) {
  string root=args[0];Directory.CreateDirectory(root);
  byte[] payload=Zip("Fixture/Fixture.toc","Fixture/main.lua");
  var addon=new Addon{name="Fixture",url="Fixture.zip",size=payload.Length,sha256=Hash(payload),title="Fixture"};
  var listed=new[]{addon};
  var catalogUrls=new System.Collections.Generic.List<string>();
  Func<string,long,byte[]> fetch=(url,limit)=> {
   if(new Uri(url).AbsolutePath.EndsWith("/addons.json")) {
    catalogUrls.Add(url);
    return Encoding.UTF8.GetBytes(new JavaScriptSerializer().Serialize(new Addons{addons=listed}));
   }
   return payload;
  };
  var store=new AddonStore(root,fetch);
  store.Catalog();store.Catalog();
  Check(catalogUrls[0]!=catalogUrls[1] && new Uri(catalogUrls[0]).Query.StartsWith("?refresh="),"catalog refresh bypasses stale release CDN redirects");
  store.Sync(s=>{});Check(store.Installed().Length==0,"startup does not install unchosen catalog entries");
  store.Install(addon);Check(store.Installed().Length==1,"verified catalog install appears in installed list");
  store.Remove("Fixture");store.Sync(s=>{});Check(store.Installed().Length==0,"removed addon stays removed during startup sync");
  store=new AddonStore(root,fetch);store.Sync(s=>{});Check(store.Installed().Length==0,"removal persists in a new store instance");
  store.Install(addon);Check(store.Installed().Length==1,"explicit reinstall clears removal choice");
  byte[] original=File.ReadAllBytes(Path.Combine(store.Root,"Fixture","main.lua"));
  payload=Zip("Fixture/Fixture.toc","Fixture/new.lua");addon.size=payload.Length;addon.sha256=Hash(payload);
  store.Sync(s=>{});Check(File.Exists(Path.Combine(store.Root,"Fixture","new.lua")),"startup updates an existing managed addon");
  addon.sha256=new string('0',64);Reject(()=>store.Install(addon),"checksum mismatch is rejected");
  Check(File.Exists(Path.Combine(store.Root,"Fixture","new.lua")),"failed update preserves existing addon");addon.sha256=Hash(payload);
  listed=new Addon[0];store.Sync(s=>{});Check(store.Installed().Length==1,"catalog removal does not delete player files");listed=new[]{addon};
  string local=Path.Combine(root,"local.zip");File.WriteAllBytes(local,Zip("Local/Local.toc","Local/main.lua"));
  store.Import(local,false);Check(store.Installed().Any(a=>a.name=="Local"&&!a.managed),"local ZIP install works without catalog ownership");
  Reject(()=>store.Import(local,false),"local install never silently overwrites existing files");
  File.WriteAllBytes(local,Zip("GitHub-main/GitHub.toc","GitHub-main/main.lua","GitHub-main/LICENSE"));
  store.Import(local,false);Check(store.Installed().Any(a=>a.name=="GitHub"),"GitHub branch ZIP wrappers normalize to their TOC name");
  foreach(string path in new[]{"../escape.lua","Fixture/../escape.lua","Fixture/file:ads.lua","Fixture/CON.lua","Fixture/trailing./file.lua","Fixture/runner.exe","Fixture/script.ps1","Fixture/FILE.lua"}) {
   File.WriteAllBytes(local,Zip("Fixture/Fixture.toc","Fixture/file.lua",path));Reject(()=>store.Import(local,true),"unsafe archive rejected: "+path);
  }
  Check(!File.Exists(Path.Combine(root,"escape.lua")),"archive traversal never writes outside staging");
  using(var stream=new MemoryStream()) {
   using(var zip=new ZipArchive(stream,ZipArchiveMode.Create,true)) {
    var link=zip.CreateEntry("Linked/Linked.toc");link.ExternalAttributes=unchecked((int)0xA1FF0000);
    using(var output=new StreamWriter(link.Open()))output.Write("../../outside");
   }
   File.WriteAllBytes(local,stream.ToArray());
  }
  Reject(()=>store.Import(local,false),"ZIP symbolic links are rejected");
  File.WriteAllBytes(local,Zip(Enumerable.Range(0,4097).Select(i=>"Many/"+i+".lua").ToArray()));
  Reject(()=>store.Import(local,false),"archive entry-count limit is enforced");
  using(var stream=new MemoryStream()) {
   using(var zip=new ZipArchive(stream,ZipArchiveMode.Create,true)) {
    using(var output=zip.CreateEntry("Large/Large.toc").Open()) {byte[] buffer=new byte[65536];for(int i=0;i<1025;i++)output.Write(buffer,0,buffer.Length);}
   }
   File.WriteAllBytes(local,stream.ToArray());
  }
  Reject(()=>store.Import(local,false),"expanded archive limit is enforced before installation");
  Check(!Directory.EnumerateDirectories(Path.Combine(root,"benilla-config"),".asr-addon-stage-*").Any(),"failed imports clean staging directories");
  Check(AddonManager.IsFolderArgument(Path.Combine(root,"benilla-config","AddOns"),root),"native folder argument is recognized");
  Check(!AddonManager.IsFolderArgument(Path.Combine(root,"Other"),root),"unrelated folders cannot open the manager");
  return 0;
 }
}
'''


@unittest.skipUnless(CSC.exists(), 'Windows .NET compiler required')
class AddonStoreTests(unittest.TestCase):
    def test_archive_and_persistent_choice_contracts(self):
        scratch = ROOT/'downloads'; scratch.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='asr-addon-check-', dir=scratch) as tmp:
            folder = Path(tmp)
            harness = folder/'Checks.cs'; harness.write_text(HARNESS)
            exe = folder/'checks.exe'
            command = [str(CSC), '/nologo', '/target:exe', '/optimize+', '/main:AddonStoreChecks', '/out:'+str(exe),
                       '/reference:System.Windows.Forms.dll', '/reference:System.Drawing.dll', '/reference:System.Web.Extensions.dll', '/reference:System.IO.Compression.dll']
            command += [str(ROOT/'launcher'/n) for n in ('Setup.cs','Relay.cs','AddonStore.cs','AddonManager.cs','GameUi.cs')]+[str(harness)]
            subprocess.run(command, check=True, capture_output=True, text=True)
            result = subprocess.run([str(exe), str(folder/'game')], check=True, capture_output=True, text=True, timeout=60)
            self.assertGreaterEqual(result.stdout.count('PASS '), 20, result.stdout)


class AddonPatchTests(unittest.TestCase):
    def fixture(self):
        data = bytearray(0xa00); data[:2] = b'MZ'; struct.pack_into('<I',data,60,0x80);data[0x80:0x84]=b'PE\0\0'
        struct.pack_into('<HH',data,0x84,0x8664,2);struct.pack_into('<H',data,0x94,240)
        opt=0x98;struct.pack_into('<H',data,opt,0x20b);struct.pack_into('<II',data,opt+32,4096,512)
        for i,(name,va,raw,size) in enumerate(((b'.text',0x1000,0x400,0x200),(b'.rdata',0x2000,0x600,0x400))):
            struct.pack_into('<8sIIIIIIHHI',data,opt+240+40*i,name,size,va,size,raw,0,0,0,0,0x40000040)
        body=bytearray(b'\x90'*0x80);hook=0x1010
        before=b'\x48\x8d\x15'+struct.pack('<i',0x2000-(hook+7));body[0x10:0x17]=before
        data[0x400:0x480]=body;data[0x600:0x608]=b'explorer'
        texts=(b'"options.open_addons_folder": "Open AddOns Folder",\n'*14)
        data[0x620:0x620+len(texts)]=texts
        profile=(0x1000,0x1080,hook,before.hex(),hashlib.sha256(body).hexdigest())
        return bytes(data),profile

    def test_reapply_and_unknown_handler_rejection(self):
        source,profile=self.fixture()
        with patch.object(addon_manager_patch,'PROFILES',(profile,)):
            result=addon_manager_patch.apply(source)
            self.assertEqual(addon_manager_patch.apply(result),result)
            self.assertEqual(result.count(b'"Manage AddOns"'),14)
            self.assertIn(b'ASRAddOn\0',result)
            changed=bytearray(source);changed[0x440]^=1
            with self.assertRaisesRegex(ValueError,'Unsupported native AddOns handler'):
                addon_manager_patch.apply(changed)


if __name__ == '__main__': unittest.main()
