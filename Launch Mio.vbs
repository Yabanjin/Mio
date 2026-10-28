Option Explicit
Dim shell, files, root
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
shell.Run "wscript.exe " & Chr(34) & root & "\interface\Launch Mio.vbs" & Chr(34), 0, False
