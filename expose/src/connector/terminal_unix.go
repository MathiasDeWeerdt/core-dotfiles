//go:build linux || darwin

package main

import (
	"errors"
	"io"

	"github.com/creack/pty"
	"os"
	"os/exec"
	"syscall"
)

type unixTerminal struct {
	*os.File
	cmd *exec.Cmd
}

func startTerminal() (terminal, error) {
	shell := os.Getenv("SHELL")
	if shell == "" {
		shell = "/bin/bash"
	}
	cmd := exec.Command(shell, "-i")
	cmd.Env = append(os.Environ(), "TERM=xterm-256color", "COLORTERM=truecolor")
	file, err := pty.StartWithSize(cmd, &pty.Winsize{Rows: 24, Cols: 80})
	if err != nil {
		return nil, err
	}
	go func() { _ = cmd.Wait() }()
	return &unixTerminal{file, cmd}, nil
}
func (t *unixTerminal) Read(buffer []byte) (int, error) {
	n, err := t.File.Read(buffer)
	// Linux PTYs report EIO when the final slave descriptor closes.
	if errors.Is(err, syscall.EIO) {
		err = io.EOF
	}
	return n, err
}
func (t *unixTerminal) Resize(cols, rows int) error {
	return pty.Setsize(t.File, &pty.Winsize{Rows: uint16(rows), Cols: uint16(cols)})
}
func (t *unixTerminal) Close() error {
	_ = syscall.Kill(-t.cmd.Process.Pid, syscall.SIGHUP)
	return t.File.Close()
}
