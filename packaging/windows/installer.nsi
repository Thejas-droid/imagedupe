Unicode true
!include "MUI2.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"
Var TestMode
!ifndef APP_VERSION
  !define APP_VERSION "1.1.1"
!endif
!ifndef APP_DIR
  !define APP_DIR "..\..\dist\ImageDupe"
!endif
!ifndef OUTPUT_FILE
  !define OUTPUT_FILE "..\..\release\ImageDupe-Setup.exe"
!endif
Name "ImageDupe"
OutFile "${OUTPUT_FILE}"
InstallDir "$PROFILE\Applications\ImageDupe"
InstallDirRegKey HKCU "Software\ImageDupe" "InstallDir"
RequestExecutionLevel user
SetCompressor /SOLID zlib
BrandingText "ImageDupe — offline image search"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "ImageDupe"
VIAddVersionKey /LANG=1033 "FileDescription" "ImageDupe Installer"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "ImageDupe contributors"
!define MUI_ICON "..\..\src\imagedupe\assets\imagedupe.ico"
!define MUI_UNICON "..\..\src\imagedupe\assets\imagedupe.ico"
!define MUI_ABORTWARNING
!define MUI_FINISHPAGE_RUN "$INSTDIR\ImageDupe.exe"
!define MUI_FINISHPAGE_RUN_TEXT "Open ImageDupe"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\..\LICENSE"
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"

Function .onInit
  SetShellVarContext current
  ; Older releases used AppData, whose inherited AppContainer ACLs can prevent
  ; Chromium's sandboxed helper from loading its DLLs. Keep custom locations.
  ${If} $INSTDIR == "$LOCALAPPDATA\Programs\ImageDupe"
    StrCpy $INSTDIR "$PROFILE\Applications\ImageDupe"
  ${EndIf}
  StrCpy $TestMode "0"
  ${GetParameters} $R0
  ClearErrors
  ${GetOptions} $R0 "/TEST" $R1
  ${IfNot} ${Errors}
    StrCpy $TestMode "1"
  ${EndIf}
  MessageBox MB_OKCANCEL "Close ImageDupe before installing or updating. Your saved collections and photos will be kept." /SD IDOK IDOK continue
  Abort
  continue:
FunctionEnd

Section "ImageDupe" SEC_APP
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${APP_DIR}\*.*"
  File /oname=ImageDupe.ico "..\..\src\imagedupe\assets\imagedupe.ico"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  Delete "$INSTDIR\.test-install"
  ${If} $TestMode == "1"
    FileOpen $R0 "$INSTDIR\.test-install" w
    FileClose $R0
    Goto installed
  ${EndIf}
  CreateDirectory "$SMPROGRAMS\ImageDupe"
  CreateShortcut "$SMPROGRAMS\ImageDupe\ImageDupe.lnk" "$INSTDIR\ImageDupe.exe" "" "$INSTDIR\ImageDupe.ico" 0
  CreateShortcut "$SMPROGRAMS\ImageDupe\Uninstall.lnk" "$INSTDIR\Uninstall.exe"
  CreateShortcut "$DESKTOP\ImageDupe.lnk" "$INSTDIR\ImageDupe.exe" "" "$INSTDIR\ImageDupe.ico" 0
  WriteRegStr HKCU "Software\ImageDupe" "InstallDir" "$INSTDIR"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "DisplayName" "ImageDupe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "Publisher" "ImageDupe"
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "UninstallString" '$\"$INSTDIR\Uninstall.exe$\"'
  WriteRegStr HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "QuietUninstallString" '$\"$INSTDIR\Uninstall.exe$\" /S'
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "NoModify" 1
  WriteRegDWORD HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe" "NoRepair" 1
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
  installed:
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  IfFileExists "$INSTDIR\.test-install" files_only
  Delete "$DESKTOP\ImageDupe.lnk"
  Delete "$SMPROGRAMS\ImageDupe\ImageDupe.lnk"
  Delete "$SMPROGRAMS\ImageDupe\Uninstall.lnk"
  RMDir "$SMPROGRAMS\ImageDupe"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\ImageDupe"
  DeleteRegKey HKCU "Software\ImageDupe"
  files_only:
  Delete "$INSTDIR\.test-install"
  ; Remove only known installed files; never recursively remove a user-selected folder.
  Delete "$INSTDIR\ImageDupe.exe"
  Delete "$INSTDIR\ImageDupe.ico"
  RMDir /r "$INSTDIR\_internal"
  Delete "$INSTDIR\Uninstall.exe"
  RMDir "$INSTDIR"
  ; Collection data in LOCALAPPDATA\ImageDupe\data and source photos are preserved.
SectionEnd
