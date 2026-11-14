@echo off
rem deepl-quick portable launcher - pure ASCII shell, codepage-proof.
rem TCL/TK_LIBRARY must point into the bundled tcl data dir.
set "HERE=%~dp0"
set "TCL_LIBRARY=%HERE%runtime\tcl\tcl8.6"
set "TK_LIBRARY=%HERE%runtime\tcl\tk8.6"
start "" "%HERE%runtime\pythonw.exe" "%HERE%deepl_quick.pyw"
