package main

import (
	"context"
	"errors"
	"io"
	"strings"
	"testing"
	"time"
)

func TestRemotePlainHTTPIsRejectedBeforeConnecting(t *testing.T) {
	t.Setenv("EXPOSE_URL", "http://192.0.2.1:8080")
	t.Setenv("EXPOSE_TICKET", randomID())
	t.Setenv("EXPOSE_AUTH_PASSWORD", randomID())
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	err := run(ctx)
	if err == nil || !strings.Contains(err.Error(), "require HTTPS") {
		t.Fatal("remote plaintext endpoint was not rejected before registration")
	}
	if ctx.Err() != nil {
		t.Fatal("connector attempted networking before rejecting the insecure origin")
	}
}

func TestTransientRelayErrorsDoNotCloseShells(t *testing.T) {
	for _, code := range []int{401, 403, 410} {
		if !fatalRelay(relayStatusError{code}) {
			t.Fatalf("HTTP %d must revoke the connector", code)
		}
	}
	for _, code := range []int{408, 429, 500, 502, 503, 504} {
		if fatalRelay(relayStatusError{code}) {
			t.Fatalf("HTTP %d must permit reconnection", code)
		}
	}
	if !fatalRelay(io.EOF) || fatalRelay(errors.New("temporary transport failure")) {
		t.Fatal("PTY exit and transient transport errors were not distinguished")
	}
}
