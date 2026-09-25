// expose-connector runs one foreground shell for an explicitly enrolled session.
package main

import (
	"bytes"
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"runtime"
	"strconv"
	"strings"
	"syscall"
	"time"
)

type terminal interface {
	io.ReadWriteCloser
	Resize(int, int) error
}
type relay struct {
	origin, token string
	client        *http.Client
}

func (r *relay) request(ctx context.Context, method, path string, body []byte, result any) error {
	req, err := http.NewRequestWithContext(ctx, method, r.origin+path, bytes.NewReader(body))
	if err != nil {
		return err
	}
	req.Header.Set("Authorization", "Bearer "+r.token)
	req.Header.Set("Content-Type", "application/octet-stream")
	response, err := r.client.Do(req)
	if err != nil {
		return fmt.Errorf("relay connection failed")
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusGone {
		return io.EOF
	}
	if response.StatusCode != http.StatusOK {
		return fmt.Errorf("relay returned HTTP %d", response.StatusCode)
	}
	if result != nil {
		return json.NewDecoder(io.LimitReader(response.Body, 262144)).Decode(result)
	}
	_, err = io.Copy(io.Discard, response.Body)
	return err
}
func run(ctx context.Context) error {
	origin, ticket := os.Getenv("EXPOSE_URL"), os.Getenv("EXPOSE_TICKET")
	os.Unsetenv("EXPOSE_URL")
	os.Unsetenv("EXPOSE_TICKET")
	parsed, err := url.Parse(origin)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") || ticket == "" {
		return errors.New("launch this connector with a fresh connection command from expose")
	}
	r := &relay{origin: strings.TrimRight(origin, "/"), token: ticket, client: &http.Client{Timeout: 20 * time.Second, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	host, _ := os.Hostname()
	metadata, _ := json.Marshal(map[string]string{"host": host, "os": runtime.GOOS, "arch": runtime.GOARCH})
	var registered struct {
		ID    string `json:"id"`
		Token string `json:"token"`
	}
	if err = r.request(ctx, "POST", "/console/register", metadata, &registered); err != nil {
		return err
	}
	if registered.ID == "" || registered.Token == "" {
		return errors.New("invalid registration response")
	}
	r.token = registered.Token
	prefix := "/console/agent/" + url.PathEscape(registered.ID)
	defer func() {
		endCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
		defer cancel()
		_ = r.request(endCtx, "POST", prefix+"/exit", nil, nil)
	}()
	tty, err := startTerminal()
	if err != nil {
		return err
	}
	defer tty.Close()
	fmt.Fprintf(os.Stderr, "Connected to %s as %s (%s/%s). Ctrl+C here disconnects.\n", r.origin, host, runtime.GOOS, runtime.GOARCH)
	failures := make(chan error, 2)
	go func() {
		buffer := make([]byte, 16384)
		for {
			n, readErr := tty.Read(buffer)
			if n > 0 {
				if err := r.request(ctx, "POST", prefix+"/output", buffer[:n], nil); err != nil {
					failures <- err
					return
				}
			}
			if readErr != nil {
				failures <- readErr
				return
			}
		}
	}()
	go func() {
		cursor := 0
		for {
			var reply struct {
				Closed bool `json:"closed"`
				Events []struct {
					Seq  int    `json:"seq"`
					Data string `json:"data"`
					Cols int    `json:"cols"`
					Rows int    `json:"rows"`
				} `json:"events"`
			}
			if err := r.request(ctx, "GET", prefix+"/input?after="+strconv.Itoa(cursor), nil, &reply); err != nil {
				failures <- err
				return
			}
			if reply.Closed {
				failures <- io.EOF
				return
			}
			for _, event := range reply.Events {
				if event.Seq <= cursor {
					continue
				}
				if event.Data != "" {
					data, err := base64.StdEncoding.DecodeString(event.Data)
					if err != nil {
						failures <- err
						return
					}
					if _, err = tty.Write(data); err != nil {
						failures <- err
						return
					}
				}
				if event.Cols >= 2 && event.Cols <= 500 && event.Rows >= 2 && event.Rows <= 200 {
					if err := tty.Resize(event.Cols, event.Rows); err != nil {
						failures <- err
						return
					}
				}
				cursor = event.Seq
			}
		}
	}()
	select {
	case <-ctx.Done():
		return nil
	case err := <-failures:
		if errors.Is(err, io.EOF) {
			return nil
		}
		return err
	}
}
func main() {
	ctx, cancel := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer cancel()
	if err := run(ctx); err != nil {
		fmt.Fprintln(os.Stderr, "Session ended:", err)
		os.Exit(1)
	}
}
