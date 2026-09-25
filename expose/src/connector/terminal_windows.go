package main

import (
	"github.com/UserExistsError/conpty"
	"os/exec"
)

func startTerminal() (terminal, error) {
	shell, err := exec.LookPath("pwsh.exe")
	if err != nil {
		shell, err = exec.LookPath("powershell.exe")
	}
	if err != nil {
		return nil, err
	}
	return conpty.Start(`"`+shell+`" -NoLogo -NoProfile`, conpty.ConPtyDimensions(80, 24))
}
