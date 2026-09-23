#define AppName "Certificate Automation"
#define AppVersion "2.1.0"
#define AppPublisher "Certificate Automation"
#define AppExeName "CertificateAutomation.exe"
#ifndef BuildRoot
#define BuildRoot "..\dist\CertificateAutomation"
#endif

[Setup]
AppId={{9E62B5A8-D6F0-4A6E-A914-367EEFB49CE9}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={localappdata}\Programs\CertificateAutomation
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist\installer
OutputBaseFilename=CertificateAutomation-Setup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#AppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "{#BuildRoot}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\examples\sample_students.xlsx"; DestDir: "{app}\examples"; Flags: ignoreversion
Source: "..\examples\sample_recipients.csv"; DestDir: "{app}\examples"; Flags: ignoreversion
Source: "..\examples\sample_certificate_template.docx"; DestDir: "{app}\examples"; Flags: ignoreversion
Source: "..\docs\user-guide.md"; DestDir: "{app}\docs"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
