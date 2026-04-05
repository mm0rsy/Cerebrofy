; Cerebrofy NSIS Installer
; Installs cerebrofy.exe to %PROGRAMFILES64%\Cerebrofy and adds it to system PATH.

!define APP_NAME "Cerebrofy"
!define APP_VERSION "1.0.0"
!define INSTALL_DIR "$PROGRAMFILES64\Cerebrofy"

Name "${APP_NAME}"
OutFile "cerebrofy-setup.exe"
InstallDir "${INSTALL_DIR}"
RequestExecutionLevel admin
SetCompressor lzma

Page directory
Page instfiles

Section "Install"
  SetOutPath "$INSTDIR"
  File "cerebrofy.exe"

  ; Add install dir to system PATH
  ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
  StrCmp $0 "" 0 +2
    StrCpy $0 "$INSTDIR"
  WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" "$0;$INSTDIR"

  ; Broadcast PATH change
  SendMessage ${HWND_BROADCAST} ${WM_WININICHANGE} 0 "STR:Environment" /TIMEOUT=5000

  ; Write uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cerebrofy" \
    "DisplayName" "${APP_NAME}"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cerebrofy" \
    "UninstallString" "$INSTDIR\uninstall.exe"
SectionEnd

Section "Uninstall"
  Delete "$INSTDIR\cerebrofy.exe"
  Delete "$INSTDIR\uninstall.exe"
  RMDir "$INSTDIR"

  ; Remove from PATH
  ReadRegStr $0 HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path"
  ; Simple removal — replace ;$INSTDIR or $INSTDIR; with empty string
  ${WordReplace} "$0" ";$INSTDIR" "" "+" $1
  ${WordReplace} "$1" "$INSTDIR;" "" "+" $2
  WriteRegExpandStr HKLM "SYSTEM\CurrentControlSet\Control\Session Manager\Environment" "Path" "$2"

  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\Cerebrofy"
SectionEnd
