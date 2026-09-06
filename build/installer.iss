; Установщик Zapret Control+ (Inno Setup 6)
; Сборка: build\build.ps1 — он подставит версию и запустит ISCC.

#define AppName "Zapret Control+"
#define AppExeName "ZapretControlPlus.exe"
#define AppPublisher "Ivan Milyaev (ketamine)"
#define AppUrl "https://github.com/77WhyNot/ZapretControlPlus"
#ifndef AppVersion
  #define AppVersion "1.0.0"
#endif

[Setup]
AppId={{2B7A9E14-63D5-4C81-A0F2-9D4E6C1B8A55}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}/issues
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoDescription={#AppName} — обход блокировок и Smart DNS

DefaultDirName={autopf}\Zapret Control Plus
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
AllowNoIcons=yes

; Нужны права администратора: WinDivert грузит драйвер ядра, а служба
; zapret создаётся в системе.
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

OutputDir=..\dist
OutputBaseFilename=ZapretControlPlus-Setup-{#AppVersion}
Compression=lzma2/ultra64
SolidCompression=yes
LZMANumBlockThreads=4

WizardStyle=modern
WizardSizePercent=110
SetupIconFile=..\app\resources\icon.ico
WizardImageFile=art\wizard-banner.bmp
WizardSmallImageFile=art\wizard-small.bmp
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}

CloseApplications=yes
RestartApplications=no
SetupMutex=ZapretControlPlusSetupMutex

[Languages]
Name: "russian"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Создать ярлык на рабочем столе"; \
    GroupDescription: "Ярлыки:"
Name: "autostart"; Description: "Запускать программу вместе с Windows"; \
    GroupDescription: "Дополнительно:"; Flags: unchecked

[Files]
Source: "..\dist\ZapretControlPlus\*"; DestDir: "{app}"; \
    Excludes: "core"; \
    Flags: ignoreversion recursesubdirs createallsubdirs

; Ядро zapret. onlyifdoesntexist бережёт списки пользователя и то ядро,
; которое программа уже обновила сама из GitHub.
Source: "..\payload\zapret\*"; DestDir: "{app}\core"; \
    Flags: onlyifdoesntexist recursesubdirs createallsubdirs uninsneveruninstall

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Удалить {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{sys}\schtasks.exe"; \
    Parameters: "/create /f /tn ""ZapretControlPlus Autostart"" /tr ""\""{app}\{#AppExeName}\"" --tray"" /sc onlogon /rl highest"; \
    Flags: runhidden; Tasks: autostart
; shellexec обязателен: postinstall-запуск идёт от обычного пользователя, а у
; программы манифест requireAdministrator — CreateProcess падает с ошибкой 740.
Filename: "{app}\{#AppExeName}"; Description: "Запустить {#AppName}"; \
    Flags: nowait postinstall skipifsilent shellexec

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im {#AppExeName}"; \
    Flags: runhidden; RunOnceId: "killapp"
Filename: "{sys}\sc.exe"; Parameters: "stop zapret"; \
    Flags: runhidden; RunOnceId: "stopsvc"
Filename: "{sys}\sc.exe"; Parameters: "delete zapret"; \
    Flags: runhidden; RunOnceId: "delsvc"
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im winws.exe"; \
    Flags: runhidden; RunOnceId: "killwinws"
Filename: "{sys}\sc.exe"; Parameters: "stop WinDivert"; \
    Flags: runhidden; RunOnceId: "stopwd"
Filename: "{sys}\sc.exe"; Parameters: "delete WinDivert"; \
    Flags: runhidden; RunOnceId: "delwd"
Filename: "{sys}\schtasks.exe"; Parameters: "/delete /f /tn ""ZapretControlPlus Autostart"""; \
    Flags: runhidden; RunOnceId: "deltask"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\core"
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"

[Code]

{ --- Обнаружение уже установленной версии ------------------------------- }

const
  UninstallKey = 'Software\Microsoft\Windows\CurrentVersion\Uninstall\{2B7A9E14-63D5-4C81-A0F2-9D4E6C1B8A55}_is1';

var
  ActionPage: TInputOptionWizardPage;
  PrevVersion: String;
  PrevUninstaller: String;
  LeavingAfterUninstall: Boolean;

function PreviousInstallFound(): Boolean;
begin
  Result := RegQueryStringValue(HKLM, UninstallKey, 'UninstallString',
                                PrevUninstaller);
  if Result then
  begin
    if not RegQueryStringValue(HKLM, UninstallKey, 'DisplayVersion',
                               PrevVersion) then
      PrevVersion := 'неизвестной версии';
  end;
end;

function RunPreviousUninstaller(Quiet: Boolean): Boolean;
var
  Command, Params: String;
  ResultCode: Integer;
begin
  Command := RemoveQuotes(PrevUninstaller);
  if Quiet then
    Params := '/VERYSILENT /NORESTART /SUPPRESSMSGBOXES'
  else
    Params := '/NORESTART';
  Result := Exec(Command, Params, '', SW_SHOW, ewWaitUntilTerminated, ResultCode);
  { Деинсталлятор Inno отвязывается от своего процесса, поэтому ждём отдельно. }
  Sleep(2500);
end;

procedure InitializeWizard();
begin
  LeavingAfterUninstall := False;
  if PreviousInstallFound() then
  begin
    ActionPage := CreateInputOptionPage(wpWelcome,
      'Zapret Control+ уже установлена',
      'На компьютере найдена версия ' + PrevVersion + '.',
      'Выберите, что сделать:', True, False);
    ActionPage.Add('Обновить — настройки, списки и подписка сохранятся');
    ActionPage.Add('Переустановить начисто — снести старую версию и поставить заново');
    ActionPage.Add('Удалить программу с компьютера');
    ActionPage.SelectedValueIndex := 0;
  end;
end;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  { При обновлении папку выбирать незачем — она уже известна. }
  Result := (ActionPage <> nil) and (PageID = wpSelectDir);
end;

function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (ActionPage = nil) or (CurPageID <> ActionPage.ID) then
    Exit;

  case ActionPage.SelectedValueIndex of
    1:
      begin
        if not RunPreviousUninstaller(True) then
        begin
          MsgBox('Не удалось запустить удаление старой версии.' #13#10
                 'Удалите её вручную через «Программы и компоненты».',
                 mbError, MB_OK);
          Result := False;
        end;
      end;
    2:
      begin
        RunPreviousUninstaller(False);
        LeavingAfterUninstall := True;
        Result := False;
        WizardForm.Close;
      end;
  end;
end;

procedure CancelButtonClick(CurPageID: Integer; var Cancel, Confirm: Boolean);
begin
  { После удаления подтверждать выход не нужно — пользователь этого и хотел. }
  if LeavingAfterUninstall then
    Confirm := False;
end;


function IsAppRunning(): Boolean;
var
  ResultCode: Integer;
begin
  Result := Exec('cmd.exe',
    '/c tasklist /fi "IMAGENAME eq {#AppExeName}" | find /i "{#AppExeName}"',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode) and (ResultCode = 0);
end;

function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
  Internal: String;
  Legacy: String;
begin
  NeedsRestart := False;
  if IsAppRunning() then
  begin
    Exec('taskkill.exe', '/f /im {#AppExeName}', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
    Sleep(1200);
  end;

  { Наследство версий 2.x: свой движок VPN. Процессы при этом не трогаем —
    одноимённый sing-box.exe принадлежит чужому клиенту (Happ и подобным),
    и снимать его мы не вправе. }
  Legacy := ExpandConstant('{app}\singbox');
  if DirExists(Legacy) then
    DelTree(Legacy, True, True, True);

  { Библиотеки Qt между версиями меняются — старую папку чистим целиком. }
  Internal := ExpandConstant('{app}\_internal');
  if DirExists(Internal) then
    DelTree(Internal, True, True, True);

  Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ResultCode: Integer;
begin
  if (CurStep = ssPostInstall) and WizardSilent() then
    ShellExec('open', ExpandConstant('{app}\{#AppExeName}'), '',
              ExpandConstant('{app}'), SW_SHOW, ewNoWait, ResultCode);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  DataDir: String;
begin
  if CurUninstallStep = usPostUninstall then
  begin
    DataDir := ExpandConstant('{localappdata}\ZapretControlPlus');
    if DirExists(DataDir) then
    begin
      if MsgBox('Удалить настройки программы и журнал?' + #13#10 +
                'Списки доменов и резервные копии тоже будут удалены.',
                mbConfirmation, MB_YESNO) = IDYES then
        DelTree(DataDir, True, True, True);
    end;
  end;
end;
