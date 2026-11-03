; Instalador por usuario (sin administrador). Compilar desde la raíz: iscc /DAppVersion=0.1.0 installer\actas.iss
; Antes: python tools/fetch_bins.py --uv   (deja bin\ffmpeg, bin\llama-*, bin\uv, bin\python)
#ifndef AppVersion
#define AppVersion "0.1.0"
#endif

[Setup]
AppId={{8C1D4C2E-5B7A-4E55-9D0B-A71C7C0E6A11}
AppName=Actas
AppVersion={#AppVersion}
AppPublisher=wDona
DefaultDirName={localappdata}\Programs\Actas
DefaultGroupName=Actas
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename=Actas-setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=Actas

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Crear un acceso directo en el escritorio"; Flags: unchecked

[Files]
Source: "instalar.cmd"; DestDir: "{app}"
Source: "..\app.py"; DestDir: "{app}"
Source: "..\pipeline.py"; DestDir: "{app}"
Source: "..\nube.py"; DestDir: "{app}"
Source: "..\destinos.py"; DestDir: "{app}"
Source: "..\destinos_tipos.py"; DestDir: "{app}"
Source: "..\importar_registro.py"; DestDir: "{app}"
Source: "..\plantillas.py"; DestDir: "{app}"
Source: "..\rag.py"; DestDir: "{app}"
Source: "..\models.py"; DestDir: "{app}"
Source: "..\transcripts.py"; DestDir: "{app}"
Source: "..\documentos.py"; DestDir: "{app}"
Source: "..\buscar.py"; DestDir: "{app}"
Source: "..\vision.py"; DestDir: "{app}"
Source: "..\exportar.py"; DestDir: "{app}"
Source: "..\privacidad.py"; DestDir: "{app}"
Source: "..\dudas.py"; DestDir: "{app}"
Source: "..\correo.py"; DestDir: "{app}"
Source: "..\correo_entrada.py"; DestDir: "{app}"
Source: "..\msgraph.py"; DestDir: "{app}"
Source: "..\carpetas.py"; DestDir: "{app}"
Source: "..\registro.py"; DestDir: "{app}"
Source: "..\export_registro.py"; DestDir: "{app}"
Source: "..\derivar.py"; DestDir: "{app}"
Source: "..\informe.py"; DestDir: "{app}"
Source: "..\poblar.py"; DestDir: "{app}"
Source: "..\preguntar_reg.py"; DestDir: "{app}"
Source: "..\pptx_min.py"; DestDir: "{app}"
Source: "..\grabar.py"; DestDir: "{app}"
Source: "..\procs.py"; DestDir: "{app}"
Source: "..\pyproject.toml"; DestDir: "{app}"
Source: "..\uv.lock"; DestDir: "{app}"
Source: "..\.python-version"; DestDir: "{app}"
Source: "..\README.md"; DestDir: "{app}"
Source: "..\static\*"; DestDir: "{app}\static"; Flags: recursesubdirs
Source: "..\bin\ffmpeg\*"; DestDir: "{app}\bin\ffmpeg"
Source: "..\bin\llama-b11690-vulkan\*"; DestDir: "{app}\bin\llama-b11690-vulkan"; Flags: recursesubdirs
Source: "..\bin\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs
Source: "..\bin\uv\uv.exe"; DestDir: "{app}\tools"

[Icons]
Name: "{autoprograms}\Actas"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-X utf8 app.py"; WorkingDir: "{app}"
Name: "{autodesktop}\Actas"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-X utf8 app.py"; WorkingDir: "{app}"; Tasks: desktopicon
; «Enviar a → Actas»: Windows añade las rutas seleccionadas al final de los parámetros
Name: "{sendto}\Actas"; Filename: "{app}\.venv\Scripts\pythonw.exe"; Parameters: "-X utf8 app.py --encolar"; WorkingDir: "{app}"

[Registry]
; menú contextual «Procesar con Actas» (ficheros y carpetas), solo para el usuario; se borra al desinstalar
Root: HKCU; Subkey: "Software\Classes\*\shell\ProcesarConActas"; ValueType: string; ValueName: ""; ValueData: "Procesar con Actas"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\*\shell\ProcesarConActas"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\.venv\Scripts\pythonw.exe"
Root: HKCU; Subkey: "Software\Classes\*\shell\ProcesarConActas\command"; ValueType: string; ValueName: ""; ValueData: """{app}\.venv\Scripts\pythonw.exe"" -X utf8 ""{app}\app.py"" --encolar ""%1"""
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ProcesarConActas"; ValueType: string; ValueName: ""; ValueData: "Procesar con Actas"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ProcesarConActas"; ValueType: string; ValueName: "Icon"; ValueData: "{app}\.venv\Scripts\pythonw.exe"
Root: HKCU; Subkey: "Software\Classes\Directory\shell\ProcesarConActas\command"; ValueType: string; ValueName: ""; ValueData: """{app}\.venv\Scripts\pythonw.exe"" -X utf8 ""{app}\app.py"" --encolar ""%1"""

[UninstallDelete]
; entorno y Python (regenerables); work\ y models\ solo si el usuario lo pide (ver abajo)
Type: filesandordirs; Name: "{app}\.venv"
Type: filesandordirs; Name: "{app}\python"
Type: filesandordirs; Name: "{app}\.uv-cache"
Type: filesandordirs; Name: "{app}\__pycache__"
Type: filesandordirs; Name: "{app}\bin"
Type: filesandordirs; Name: "{app}\static"
Type: filesandordirs; Name: "{app}\tools"
Type: files; Name: "{app}\.actas.lock"
Type: files; Name: "{app}\instalacion.log"
Type: files; Name: "{app}\instalacion.done"

[Code]
procedure CurStepChanged(CurStep: TSetupStep);
var
  Pg: TOutputMarqueeProgressWizardPage;
  Done, Res: string;
  Code, I: Integer;
  S: AnsiString;
begin
  if CurStep <> ssPostInstall then Exit;
  Done := ExpandConstant('{app}\instalacion.done');
  DeleteFile(Done);
  Pg := CreateOutputMarqueeProgressPage('Instalando componentes', 'Descargando Python y las librerías (necesita internet; puede tardar varios minutos)…');
  Pg.Show;
  try
    Exec(ExpandConstant('{app}\instalar.cmd'), '', ExpandConstant('{app}'), SW_HIDE, ewNoWait, Code);
    I := 0;
    while (not FileExists(Done)) and (I < 36000) do begin
      Pg.Animate;
      Sleep(100);
      I := I + 1;
    end;
    Sleep(300);
  finally
    Pg.Hide;
  end;
  Res := '1';
  if LoadStringFromFile(Done, S) then Res := Trim(String(S));
  if Res <> '0' then begin
    Log('uv sync falló, código ' + Res);
    MsgBox('No se pudieron descargar los componentes. Comprueba que hay conexión a internet y vuelve a ejecutar el instalador.' + #13#10 +
      'Detalles: ' + ExpandConstant('{app}\instalacion.log'), mbError, MB_OK);
    Abort;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent() then
    // por defecto (No) se conservan reuniones y modelos (varios GB); en silencioso (UninstallSilent) no se pregunta y se conservan
    if MsgBox('¿Borrar también las reuniones procesadas y los modelos descargados (varios GB)?', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
      DelTree(ExpandConstant('{app}'), True, True, True);
end;
