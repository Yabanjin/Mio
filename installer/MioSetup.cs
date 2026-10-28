using System;
using System.IO;
using System.Drawing;
using System.Linq;
using System.Text;
using System.Threading.Tasks;
using System.Diagnostics;
using System.Windows.Forms;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Security.Cryptography;
using Microsoft.Win32;

// Native per-user installer. Payload contains Mio internals, never external servers.
class MioSetup : Form {
    readonly string source = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "payload");
    TextBox destination = new TextBox();
    TextBox details = new TextBox();
    Label status = new Label();
    ProgressBar progress = new ProgressBar();
    Button install = new Button();
    Button browse = new Button();
    Button launch = new Button();
    CheckBox desktop = new CheckBox();
    bool busy;
    string installed;
    public MioSetup() {
        Text = "Mio Setup"; Size = new Size(980, 680); MinimumSize = Size;
        StartPosition = FormStartPosition.CenterScreen; BackColor = Color.FromArgb(17,24,39);
        ForeColor = Color.FromArgb(230,235,249); Font = new Font("Segoe UI",10);
        string iconPath=Path.Combine(source,"images","mio.ico");
        if(File.Exists(iconPath)) Icon=new Icon(iconPath);
        var layout = new TableLayoutPanel { Dock=DockStyle.Fill, ColumnCount=2, RowCount=1, Padding=new Padding(16) };
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,42));
        layout.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,58)); Controls.Add(layout);
        var left = new Panel { Dock=DockStyle.Fill, Margin=new Padding(0,0,22,0), BackColor=Color.FromArgb(25,34,51) };
        var art = new PictureBox { Dock=DockStyle.Fill, SizeMode=PictureBoxSizeMode.Zoom };
        string image = Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"mio.png");
        if(File.Exists(image)) art.Image=Image.FromFile(image);
        left.Controls.Add(art);
        var brand = new Label { Text="MIO", Font=new Font("Segoe UI",30,FontStyle.Bold), Dock=DockStyle.Top, Height=76, TextAlign=ContentAlignment.MiddleCenter };
        left.Controls.Add(brand); layout.Controls.Add(left,0,0);
        var right = new TableLayoutPanel { Dock=DockStyle.Fill, RowCount=10, ColumnCount=1 };
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,68));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,85));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,28));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,38));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,35));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,47));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,25));
        right.RowStyles.Add(new RowStyle(SizeType.Percent,100));
        right.RowStyles.Add(new RowStyle(SizeType.Absolute,48));
        layout.Controls.Add(right,1,0);
        right.Controls.Add(new Label {Text="Welcome to the Mio chat app", Font=new Font("Segoe UI",20,FontStyle.Bold), Dock=DockStyle.Fill},0,0);
        right.Controls.Add(new Label {Text="Install Mio, its internal modules and speech models.\r\nYour existing external service settings are included for this local trial. Internet is needed for Python dependencies.", Dock=DockStyle.Fill},0,1);
        right.Controls.Add(new Label {Text="Installation folder",Dock=DockStyle.Fill},0,2);
        var pathrow = new TableLayoutPanel {Dock=DockStyle.Fill,ColumnCount=2};
        pathrow.ColumnStyles.Add(new ColumnStyle(SizeType.Percent,100)); pathrow.ColumnStyles.Add(new ColumnStyle(SizeType.Absolute,85));
        destination.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"Mio"); destination.Dock=DockStyle.Fill;
        browse.Text="Browse…"; browse.Dock=DockStyle.Fill;
        browse.ForeColor=Color.White;browse.BackColor=Color.FromArgb(54,78,118);browse.FlatStyle=FlatStyle.Flat;
        browse.Click+=(s,e)=> {using(var dialog=new FolderBrowserDialog()){dialog.Description="Select an empty folder for Mio"; dialog.SelectedPath=destination.Text; if(dialog.ShowDialog()==DialogResult.OK) destination.Text=dialog.SelectedPath;}};
        pathrow.Controls.Add(destination,0,0);pathrow.Controls.Add(browse,1,0);right.Controls.Add(pathrow,0,3);
        var shortcutRow=new Panel {Dock=DockStyle.Fill};
        desktop.Text="";desktop.Checked=true;desktop.Dock=DockStyle.Left;desktop.Width=22;
        var shortcutLabel=new Label {Text="Create a desktop shortcut",ForeColor=Color.White,Dock=DockStyle.Fill,TextAlign=ContentAlignment.MiddleLeft};
        shortcutLabel.Click+=(s,e)=>{if(desktop.Enabled)desktop.Checked=!desktop.Checked;};
        shortcutRow.Controls.Add(shortcutLabel);shortcutRow.Controls.Add(desktop);right.Controls.Add(shortcutRow,0,4);
        status.Text="Ready to install. Your other Mio installation will not be changed.";status.Dock=DockStyle.Fill;right.Controls.Add(status,0,5);
        progress.Dock=DockStyle.Fill;right.Controls.Add(progress,0,6);
        details.Multiline=true;details.ReadOnly=true;details.ScrollBars=ScrollBars.Vertical;details.Dock=DockStyle.Fill;
        details.BackColor=Color.FromArgb(25,34,51);details.ForeColor=ForeColor;details.BorderStyle=BorderStyle.FixedSingle;details.Font=new Font("Consolas",8);
        right.Controls.Add(details,0,7);
        var buttons=new FlowLayoutPanel {Dock=DockStyle.Fill,FlowDirection=FlowDirection.RightToLeft};
        install.Text="Install Mio";install.Width=125;install.Height=34;install.BackColor=Color.FromArgb(54,78,118);install.FlatStyle=FlatStyle.Flat;
        install.ForeColor=Color.White;
        launch.Text="Close and start Mio";launch.Width=190;launch.Height=34;launch.Enabled=false;launch.Visible=false;launch.FlatStyle=FlatStyle.Flat;
        launch.ForeColor=Color.White;launch.BackColor=Color.FromArgb(54,78,118);
        buttons.Controls.Add(install);buttons.Controls.Add(launch);right.Controls.Add(buttons,0,8);
        install.Click+=async (s,e)=>await Install();
        launch.Click+=(s,e)=>{Process.Start(new ProcessStartInfo("wscript.exe",Quote(Path.Combine(installed,"Launch Mio.vbs"))) {UseShellExecute=false,CreateNoWindow=true});Close();};
        FormClosing+=(s,e)=>{if(busy){e.Cancel=true;MessageBox.Show(this,"Please wait for installation to finish. Dependency installation is still running.","Mio Setup");}};
    }
    static string Quote(string value){return "\""+value+"\"";}
    void Log(string message) {
        if(IsDisposed || message==null) return;
        if(InvokeRequired){BeginInvoke(new Action<string>(Log),message);return;}
        if(details.TextLength>60000) details.Text=details.Text.Substring(details.TextLength-30000);
        details.AppendText(message+Environment.NewLine);
    }
    void SetProgress(int value) {if(InvokeRequired){BeginInvoke(new Action<int>(SetProgress),value);return;} progress.Value=value;}
    async Task Install() {
        string target;
        try {
            target=Path.GetFullPath(destination.Text.Trim());
            if(!Directory.Exists(source)) throw new Exception("The payload folder is missing. Keep it next to Mio Setup.exe.");
            if(target.Length>120) throw new Exception("Choose a shorter installation path (120 characters maximum).");
            if(target.StartsWith(AppDomain.CurrentDomain.BaseDirectory,StringComparison.OrdinalIgnoreCase)) throw new Exception("Choose a folder outside this installer package.");
            if(Directory.Exists(target) && Directory.EnumerateFileSystemEntries(target).Any()) throw new Exception("Choose an empty folder. Existing installations are never overwritten.");
            if(target==Path.GetPathRoot(target)) throw new Exception("Choose a dedicated Mio folder, not a drive root.");
        }catch(Exception error){MessageBox.Show(this,error.Message,"Mio Setup",MessageBoxButtons.OK,MessageBoxIcon.Warning);return;}
        busy=true;install.Enabled=false;browse.Enabled=false;destination.Enabled=false;desktop.Enabled=false;
        bool shortcut=desktop.Checked;
        try {
            status.Text="Copying Mio and its internal models…";
            await Task.Run(()=>{
                var files=Directory.GetFiles(source,"*",SearchOption.AllDirectories);
                long total=files.Sum(f=>new FileInfo(f).Length),copied=0;
                Directory.CreateDirectory(target);
                foreach(var file in files){
                    var info=new FileInfo(file);
                    if((info.Attributes & FileAttributes.ReparsePoint)!=0) throw new Exception("Unexpected linked file in package: "+file);
                    string relative=file.Substring(source.Length).TrimStart(Path.DirectorySeparatorChar);
                    string output=Path.Combine(target,relative);Directory.CreateDirectory(Path.GetDirectoryName(output));File.Copy(file,output,false);
                    copied+=info.Length;SetProgress(total>0?(int)(copied*35/total):35);
                }
                File.WriteAllText(Path.Combine(target,"INSTALL-INCOMPLETE.txt"),"If setup is interrupted, run Install Mio.cmd here to retry dependencies. The main setup never overwrites an existing folder.");
                RegisterInstallation(target,new List<string>());
            });
            status.Text="Installing the shared environment and checking internal modules…";progress.Style=ProgressBarStyle.Marquee;
            int result=await Task.Run(()=>{
                var start=new ProcessStartInfo("powershell.exe","-NoProfile -ExecutionPolicy Bypass -File "+Quote(Path.Combine(target,"scripts","Install-Mio.ps1"))+" -InternalOnly") {
                    WorkingDirectory=target,UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true
                };
                using(var child=new Process {StartInfo=start}){
                    child.OutputDataReceived+=(s,e)=>Log(e.Data);child.ErrorDataReceived+=(s,e)=>Log(e.Data);
                    child.Start();child.BeginOutputReadLine();child.BeginErrorReadLine();child.WaitForExit();return child.ExitCode;
                }
            });
            if(result!=0) throw new Exception("Dependency checks did not finish successfully. See data\\logs\\installation.log in the selected folder. Run Install Mio.cmd there to retry.");
            status.Text="Creating shortcuts…";
            await Task.Run(()=>CreateShortcuts(target,shortcut));
            File.Delete(Path.Combine(target,"INSTALL-INCOMPLETE.txt"));
            installed=target;launch.Enabled=true;launch.Visible=true;install.Visible=false;progress.Style=ProgressBarStyle.Blocks;progress.Value=100;
            status.Text="Installed. Close the other Mio session, then open Mio and press Start.";
            Log("Installation complete: "+target);install.Text="Installed";
        }catch(Exception error){progress.Style=ProgressBarStyle.Blocks;status.Text="Installation needs attention.";Log(error.ToString());MessageBox.Show(this,error.Message,"Mio Setup",MessageBoxButtons.OK,MessageBoxIcon.Error);}
        finally{busy=false;browse.Enabled=true;destination.Enabled=true;desktop.Enabled=true;}
    }
    static void RegisterInstallation(string target,List<string> shortcuts) {
        string key;
        using(var sha=SHA256.Create()) key="Mio-"+BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(target.ToLowerInvariant()))).Replace("-","").Substring(0,16).ToLowerInvariant();
        var metadata=new { Product="Mio.LocalInstaller.v1", InstallRoot=target, Shortcuts=shortcuts, RegistryKey=key };
        File.WriteAllText(Path.Combine(target,".mio-install.json"),new JavaScriptSerializer().Serialize(metadata));
        using(var entry=Registry.CurrentUser.CreateSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\"+key)) {
            entry.SetValue("DisplayName","Mio"); entry.SetValue("DisplayVersion","0.1-local");
            entry.SetValue("Publisher","Mio Project");entry.SetValue("InstallLocation",target);
            entry.SetValue("DisplayIcon",Path.Combine(target,"images","mio.ico"));
            entry.SetValue("UninstallString","powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "+Quote(Path.Combine(target,"Uninstall-Mio.ps1")));
            entry.SetValue("NoModify",1,RegistryValueKind.DWord);entry.SetValue("NoRepair",1,RegistryValueKind.DWord);
        }
    }
    static void CreateShortcuts(string target,bool desktop) {
        Type shellType=Type.GetTypeFromProgID("WScript.Shell");dynamic shell=Activator.CreateInstance(shellType);
        string programs=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"Mio");Directory.CreateDirectory(programs);
        var paths=desktop?new[]{Path.Combine(programs,"Mio.lnk"),Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"Mio.lnk")}:new[]{Path.Combine(programs,"Mio.lnk")};
        var owned=new List<string>();
        foreach(string path in paths){
            // Preserve an existing shortcut from another Mio installation.
            string chosen=File.Exists(path)?Path.Combine(Path.GetDirectoryName(path),"Mio (installed "+DateTime.Now.ToString("yyyyMMdd-HHmmss")+").lnk"):path;
            dynamic link=shell.CreateShortcut(chosen);link.TargetPath=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"wscript.exe");link.Arguments=Quote(Path.Combine(target,"Launch Mio.vbs"));link.WorkingDirectory=target;link.Description="Mio — configure and start";link.IconLocation=Path.Combine(target,"images","mio.ico")+",0";link.Save();owned.Add(chosen);
        }
        string remove=Path.Combine(programs,"Uninstall Mio.lnk");
        if(File.Exists(remove)) {
            string separate=Path.Combine(programs,"Mio ("+new DirectoryInfo(target).Name+" "+Guid.NewGuid().ToString("N").Substring(0,8)+")");
            Directory.CreateDirectory(separate);remove=Path.Combine(separate,"Uninstall Mio.lnk");
        }
        dynamic uninstall=shell.CreateShortcut(remove);uninstall.TargetPath=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),@"WindowsPowerShell\v1.0\powershell.exe");uninstall.Arguments="-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "+Quote(Path.Combine(target,"Uninstall-Mio.ps1"));uninstall.WorkingDirectory=Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);uninstall.Save();owned.Add(remove);
        uninstall.IconLocation=Path.Combine(target,"images","mio.ico")+",0";uninstall.Save();
        RegisterInstallation(target,owned);
    }
    [STAThread] static void Main(string[] args) {
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        using(var form=new MioSetup()){
            if(args.Contains("--smoke-test") || args.Contains("--preview")){
                form.Show();Application.DoEvents();
                if(args.Contains("--preview")) using(var bitmap=new Bitmap(form.Width,form.Height)) {
                    form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,form.Size));
                    bitmap.Save(Path.Combine(AppDomain.CurrentDomain.BaseDirectory,"installer-preview.png"),System.Drawing.Imaging.ImageFormat.Png);
                }
                return;
            }
            Application.Run(form);
        }
    }
}
