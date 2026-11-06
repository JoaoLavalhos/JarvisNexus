Option Explicit
Dim shell, files, base, python, command
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
base = files.GetParentFolderName(WScript.ScriptFullName)
python = base & "\.venv\Scripts\pythonw.exe"
If Not files.FileExists(python) Then
    MsgBox "Execute INSTALAR.ps1 antes de abrir o JARVIS.", 48, "JARVIS NEXUS V18"
    WScript.Quit 1
End If
shell.CurrentDirectory = base
shell.Environment("PROCESS")("MARK_GROQ_STT") = "1"
shell.Environment("PROCESS")("PYTHONUTF8") = "1"
command = Chr(34) & python & Chr(34) & " " & Chr(34) & base & "\main.py" & Chr(34)
shell.Run command, 0, False
