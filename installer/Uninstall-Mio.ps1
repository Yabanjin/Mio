param([switch]$Preview)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
[Windows.Forms.Application]::EnableVisualStyles()
$InstallRoot=$PSScriptRoot
$form=New-Object Windows.Forms.Form
$form.Text='Mio Uninstall'
$form.Size=New-Object Drawing.Size(980,680)
$form.MinimumSize=$form.Size
$form.StartPosition='CenterScreen'
$form.BackColor=[Drawing.Color]::FromArgb(17,24,39)
$form.ForeColor=[Drawing.Color]::White
$form.Font=New-Object Drawing.Font('Segoe UI',10)
$layout=New-Object Windows.Forms.TableLayoutPanel
$layout.Dock='Fill';$layout.Padding=New-Object Windows.Forms.Padding(16)
$layout.ColumnCount=2;$layout.RowCount=1
$layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent',42))) | Out-Null
$layout.ColumnStyles.Add((New-Object Windows.Forms.ColumnStyle('Percent',58))) | Out-Null
$form.Controls.Add($layout)
$left=New-Object Windows.Forms.Panel
$left.Dock='Fill';$left.BackColor=[Drawing.Color]::FromArgb(25,34,51)
$left.Margin=New-Object Windows.Forms.Padding(0,0,22,0)
$picture=New-Object Windows.Forms.PictureBox
$picture.Dock='Fill';$picture.SizeMode='Zoom'
$imagePath=Join-Path $InstallRoot 'images\mio.png'
if(Test-Path -LiteralPath $imagePath){
    $original=[Drawing.Image]::FromFile($imagePath)
    $picture.Image=New-Object Drawing.Bitmap($original)
    $original.Dispose()
}
$iconPath=Join-Path $InstallRoot 'images\mio.ico'
if(Test-Path -LiteralPath $iconPath){
    $originalIcon=New-Object Drawing.Icon($iconPath)
    $form.Icon=$originalIcon.Clone();$originalIcon.Dispose()
}
$left.Controls.Add($picture)
$brand=New-Object Windows.Forms.Label
$brand.Text='MIO';$brand.Font=New-Object Drawing.Font('Segoe UI',30,[Drawing.FontStyle]::Bold)
$brand.Dock='Top';$brand.Height=76;$brand.TextAlign='MiddleCenter'
$left.Controls.Add($brand);$layout.Controls.Add($left,0,0)
$right=New-Object Windows.Forms.TableLayoutPanel
$right.Dock='Fill';$right.ColumnCount=1;$right.RowCount=7
foreach($height in @(58,90,32,70,55)){$right.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute',$height))) | Out-Null}
$right.RowStyles.Add((New-Object Windows.Forms.RowStyle('Percent',100))) | Out-Null
$right.RowStyles.Add((New-Object Windows.Forms.RowStyle('Absolute',48))) | Out-Null
$layout.Controls.Add($right,1,0)
$title=New-Object Windows.Forms.Label
$title.Text='Uninstall Mio';$title.Font=New-Object Drawing.Font('Segoe UI',22,[Drawing.FontStyle]::Bold);$title.Dock='Fill'
$right.Controls.Add($title,0,0)
$description=New-Object Windows.Forms.Label
$description.Text="Remove Mio and all its local settings, memories, voice samples, models and logs.`r`nExternal applications are kept."
$description.Dock='Fill';$right.Controls.Add($description,0,1)
$folderTitle=New-Object Windows.Forms.Label
$folderTitle.Text='Installation folder';$folderTitle.Dock='Fill';$right.Controls.Add($folderTitle,0,2)
$folder=New-Object Windows.Forms.TextBox
$folder.Text=$InstallRoot;$folder.ReadOnly=$true;$folder.Multiline=$true;$folder.Dock='Fill'
$folder.BackColor=[Drawing.Color]::FromArgb(25,34,51);$folder.ForeColor=[Drawing.Color]::White
$right.Controls.Add($folder,0,3)
$status=New-Object Windows.Forms.Label
$status.Text='Choose Uninstall to review the confirmation.';$status.Dock='Fill';$right.Controls.Add($status,0,4)
$progress=New-Object Windows.Forms.ProgressBar
$progress.Dock='Top';$progress.Height=22;$right.Controls.Add($progress,0,5)
$buttons=New-Object Windows.Forms.FlowLayoutPanel
$buttons.Dock='Fill';$buttons.FlowDirection='RightToLeft'
$remove=New-Object Windows.Forms.Button
$remove.Text='Uninstall Mio';$remove.Width=145;$remove.Height=34;$remove.FlatStyle='Flat'
$remove.ForeColor=[Drawing.Color]::White;$remove.BackColor=[Drawing.Color]::FromArgb(54,78,118)
$cancel=New-Object Windows.Forms.Button
$cancel.Text='Cancel';$cancel.Width=110;$cancel.Height=34;$cancel.FlatStyle='Flat'
$cancel.ForeColor=[Drawing.Color]::White;$cancel.BackColor=[Drawing.Color]::FromArgb(54,78,118)
$buttons.Controls.Add($remove);$buttons.Controls.Add($cancel);$right.Controls.Add($buttons,0,6)
$script:removalProcess=$null
$timer=New-Object Windows.Forms.Timer
$timer.Interval=500
$cancel.Add_Click({$form.Close()})
$form.Add_FormClosing({param($sender,$eventArgs) if($script:removalProcess -and -not $script:removalProcess.HasExited){$eventArgs.Cancel=$true}})
$remove.Add_Click({
    $answer=[Windows.Forms.MessageBox]::Show($form,"Permanently delete Mio and ALL local data from:`n$InstallRoot`n`nThis cannot be undone.",'Confirm uninstall','YesNo','Warning','Button2')
    if($answer -ne 'Yes'){return}
    try{
        $worker=Join-Path $InstallRoot 'scripts\Remove-Mio.ps1'
        if(-not(Test-Path -LiteralPath $worker)){throw 'Removal module is missing. No files were removed.'}
        $script:errorLog=Join-Path $env:TEMP ('Mio-uninstall-'+[guid]::NewGuid().ToString('N')+'.log')
        $script:removalProcess=Start-Process -FilePath 'powershell.exe' -ArgumentList ('-NoProfile -ExecutionPolicy Bypass -File "'+$worker+'"') -WorkingDirectory $env:TEMP -WindowStyle Hidden -RedirectStandardError $script:errorLog -PassThru
        $remove.Enabled=$false;$cancel.Enabled=$false;$status.Text='Removing Mio and its local data…';$progress.Style='Marquee';$timer.Start()
    }catch{[Windows.Forms.MessageBox]::Show($form,$_.Exception.Message,'Mio uninstall','OK','Error') | Out-Null}
})
$timer.Add_Tick({
    if(-not $script:removalProcess.HasExited){return}
    $timer.Stop();$progress.Style='Blocks';$cancel.Enabled=$true;$cancel.Text='Close'
    $filesRemoved=-not(Test-Path -LiteralPath $InstallRoot)
    if($script:removalProcess.ExitCode -eq 0 -or $filesRemoved){
        $progress.Value=100
        $remove.Enabled=$false
        $remove.BackColor=[Drawing.Color]::FromArgb(52,57,68)
        $remove.FlatAppearance.BorderColor=[Drawing.Color]::FromArgb(85,90,104)
        if($script:removalProcess.ExitCode -eq 0){$status.Text='Mio and its local data have been removed.'}
        else{$status.Text='Mio files have been removed. Some shortcuts or the Windows entry may still need cleanup.'}
    }
    else{
        $status.Text='Removal needs attention. Close Mio and try again.'
        $detail=Get-Content -LiteralPath $script:errorLog -Raw -ErrorAction SilentlyContinue
        [Windows.Forms.MessageBox]::Show($form,$detail,'Mio uninstall','OK','Error') | Out-Null
        $remove.Enabled=$true
    }
})
if($Preview){$form.Show();[Windows.Forms.Application]::DoEvents();$form.Close()}
else{[Windows.Forms.Application]::Run($form)}
$timer.Dispose();$form.Dispose()
