#ifndef AppVersion
  #error AppVersion must be provided with /DAppVersion=X.Y.Z
#endif

#define AppName "LabelImg Enhanced"
#define AppExeName "LabelImgEnhanced.exe"

[Setup]
AppId={{A691AE5A-6E7A-4D6B-B799-3A113DE95520}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=LabelImg Enhanced contributors
AppPublisherURL=https://github.com/zaney955/labelimg-enhanced
AppSupportURL=https://github.com/zaney955/labelimg-enhanced/issues
AppUpdatesURL=https://github.com/zaney955/labelimg-enhanced/releases
DefaultDirName={localappdata}\Programs\LabelImg Enhanced
DefaultGroupName=LabelImg Enhanced
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=LabelImg-Enhanced-{#AppVersion}-windows-x64-setup
SetupIconFile=..\..\resources\icons\app.ico
UninstallDisplayIcon={app}\{#AppExeName}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
Uninstallable=yes
LicenseFile=..\..\COPYING.GPL-3.0
VersionInfoVersion={#AppVersion}.0
VersionInfoDescription=LabelImg Enhanced unsigned installer

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\..\dist\LabelImgEnhanced\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "managed-install.json"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\COPYING.GPL-3.0"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\LabelImg Enhanced"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall LabelImg Enhanced"; Filename: "{uninstallexe}"
Name: "{autodesktop}\LabelImg Enhanced"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
