// expose-connector runs one foreground shell for an explicitly enrolled session.
package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"os"
	"os/signal"
	"runtime"
	"strconv"
	"strings"
	"sync"
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

type relayStatusError struct {
	code int
}

func (e relayStatusError) Error() string {
	return fmt.Sprintf("relay returned HTTP %d", e.code)
}

func fatalRelay(err error) bool {
	if err == nil {
		return false
	}
	if errors.Is(err, io.EOF) {
		return true
	}
	var status relayStatusError
	if errors.As(err, &status) {
		return status.code == http.StatusUnauthorized || status.code == http.StatusForbidden ||
			status.code == http.StatusGone
	}
	return false
}

func waitRetry(ctx context.Context, attempt *int) {
	shift := *attempt
	if shift > 6 {
		shift = 6
	}
	if shift < 0 {
		shift = 0
	}
	*attempt = *attempt + 1
	select {
	case <-ctx.Done():
	case <-time.After(time.Duration(1<<shift) * time.Second):
	}
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
		return relayStatusError{response.StatusCode}
	}
	if result != nil {
		return json.NewDecoder(io.LimitReader(response.Body, 4<<20)).Decode(result)
	}
	_, err = io.Copy(io.Discard, response.Body)
	return err
}

type netEvent struct {
	Seq      int    `json:"seq"`
	Type     string `json:"type"`
	Stream   string `json:"stream"`
	Callback string `json:"callback"`
	Host     string `json:"host"`
	Port     int    `json:"port"`
	Data     string `json:"data"`
}

type netRelay struct {
	relay     *relay
	prefix    string
	mu        sync.Mutex
	streams   map[string]net.Conn
	listeners map[string]net.Listener
	canceled  map[string]bool
}

func (n *netRelay) loop(ctx context.Context) {
	cursor := 0
	attempt := 0
	for ctx.Err() == nil {
		var reply struct {
			Closed bool       `json:"closed"`
			Events []netEvent `json:"events"`
		}
		err := n.relay.request(ctx, "GET", n.prefix+"/net?after="+strconv.Itoa(cursor), nil, &reply)
		if err != nil {
			if ctx.Err() != nil || fatalRelay(err) {
				return
			}
			waitRetry(ctx, &attempt)
			continue
		}
		attempt = 0
		if reply.Closed {
			return
		}
		for _, event := range reply.Events {
			if event.Seq <= cursor {
				continue
			}
			cursor = event.Seq
			switch event.Type {
			case "open":
				go n.open(ctx, event.Stream, event.Host, event.Port)
			case "data":
				n.write(event.Stream, event.Data)
			case "close":
				n.close(event.Stream)
			case "listen":
				go n.listen(ctx, event.Callback, event.Port)
			case "unlisten":
				n.unlisten(event.Callback)
			}
		}
	}
}

func (n *netRelay) open(ctx context.Context, id, host string, port int) {
	target := net.JoinHostPort(host, strconv.Itoa(port))
	conn, err := (&net.Dialer{Timeout: 5 * time.Second}).DialContext(ctx, "tcp", target)
	if err != nil {
		_ = n.relay.request(ctx, "POST", n.prefix+"/net/"+url.PathEscape(id)+"/status",
			[]byte(`{"ok":false}`), nil)
		return
	}
	n.mu.Lock()
	if n.canceled[id] {
		delete(n.canceled, id)
		n.mu.Unlock()
		_ = conn.Close()
		return
	}
	n.streams[id] = conn
	n.mu.Unlock()
	if err := n.relay.request(ctx, "POST", n.prefix+"/net/"+url.PathEscape(id)+"/status",
		[]byte(`{"ok":true}`), nil); err != nil {
		n.finish(ctx, id)
		return
	}
	go n.pump(ctx, id, conn)
}

func (n *netRelay) listen(ctx context.Context, id string, port int) {
	listener, err := net.Listen("tcp", net.JoinHostPort("0.0.0.0", strconv.Itoa(port)))
	if err != nil {
		n.callbackState(ctx, id, false, "", "cannot listen: "+err.Error())
		return
	}
	n.mu.Lock()
	if existing := n.listeners[id]; existing != nil {
		_ = existing.Close()
	}
	n.listeners[id] = listener
	n.mu.Unlock()
	n.callbackState(ctx, id, true, net.JoinHostPort(localIP(), strconv.Itoa(port)), "")
	for {
		conn, err := listener.Accept()
		if err != nil {
			return
		}
		stream := randomID()
		n.mu.Lock()
		n.streams[stream] = conn
		n.mu.Unlock()
		if err := n.inbound(ctx, stream, id, conn.RemoteAddr().String()); err != nil {
			n.finish(ctx, stream)
			continue
		}
		go n.pump(ctx, stream, conn)
	}
}

func (n *netRelay) unlisten(id string) {
	n.mu.Lock()
	listener := n.listeners[id]
	delete(n.listeners, id)
	n.mu.Unlock()
	if listener != nil {
		_ = listener.Close()
	}
}

func (n *netRelay) callbackState(ctx context.Context, id string, active bool, address, message string) {
	body, _ := json.Marshal(map[string]any{"active": active, "address": address, "error": message})
	_ = n.relay.request(ctx, "POST", n.prefix+"/callback/"+url.PathEscape(id)+"/state", body, nil)
}

func (n *netRelay) inbound(ctx context.Context, stream, callback, address string) error {
	body, _ := json.Marshal(map[string]string{"callback": callback, "address": address})
	return n.relay.request(ctx, "POST", n.prefix+"/net/"+url.PathEscape(stream)+"/inbound", body, nil)
}

func localIP() string {
	conn, err := net.Dial("udp", "8.8.8.8:80")
	if err != nil {
		return "127.0.0.1"
	}
	defer conn.Close()
	if addr, ok := conn.LocalAddr().(*net.UDPAddr); ok {
		return addr.IP.String()
	}
	return "127.0.0.1"
}

func randomID() string {
	buffer := make([]byte, 8)
	if _, err := rand.Read(buffer); err != nil {
		return strconv.FormatInt(time.Now().UnixNano(), 16)
	}
	return hex.EncodeToString(buffer)
}

func (n *netRelay) pump(ctx context.Context, id string, conn net.Conn) {
	buffer := make([]byte, 32768)
	for {
		read, err := conn.Read(buffer)
		if read > 0 {
			if postErr := n.relay.request(ctx, "POST",
				n.prefix+"/net/"+url.PathEscape(id)+"/data", buffer[:read], nil); postErr != nil {
				n.finish(ctx, id)
				return
			}
		}
		if err != nil {
			n.finish(ctx, id)
			return
		}
	}
}

func (n *netRelay) write(id, encoded string) {
	n.mu.Lock()
	conn := n.streams[id]
	n.mu.Unlock()
	if conn == nil {
		return
	}
	data, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		n.finish(context.Background(), id)
		return
	}
	_ = conn.SetWriteDeadline(time.Now().Add(10 * time.Second))
	if _, err := conn.Write(data); err != nil {
		n.finish(context.Background(), id)
	}
}

func (n *netRelay) close(id string) {
	n.mu.Lock()
	conn := n.streams[id]
	if conn == nil {
		if len(n.canceled) > 1024 {
			n.canceled = map[string]bool{}
		}
		n.canceled[id] = true
	}
	delete(n.streams, id)
	n.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
}

func (n *netRelay) finish(ctx context.Context, id string) {
	n.mu.Lock()
	conn := n.streams[id]
	delete(n.streams, id)
	delete(n.canceled, id)
	n.mu.Unlock()
	if conn != nil {
		_ = conn.Close()
	}
	endCtx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
	defer cancel()
	_ = n.relay.request(endCtx, "POST", n.prefix+"/net/"+url.PathEscape(id)+"/close",
		[]byte("{}"), nil)
}

func (n *netRelay) closeAll() {
	n.mu.Lock()
	defer n.mu.Unlock()
	for id, conn := range n.streams {
		_ = conn.Close()
		delete(n.streams, id)
	}
	for id, listener := range n.listeners {
		_ = listener.Close()
		delete(n.listeners, id)
	}
	n.canceled = map[string]bool{}
}

func run(ctx context.Context) error {
	origin, ticket := os.Getenv("EXPOSE_URL"), os.Getenv("EXPOSE_TICKET")
	os.Unsetenv("EXPOSE_URL")
	os.Unsetenv("EXPOSE_TICKET")
	parsed, err := url.Parse(origin)
	if err != nil || parsed.Host == "" || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.User != nil || parsed.RawQuery != "" || parsed.Fragment != "" || (parsed.Path != "" && parsed.Path != "/") || ticket == "" {
		return errors.New("launch this connector with a fresh connection command from expose")
	}
	r := &relay{origin: strings.TrimRight(origin, "/"), token: ticket, client: &http.Client{Timeout: 30 * time.Second, Transport: &http.Transport{MaxIdleConns: 256, MaxIdleConnsPerHost: 256, IdleConnTimeout: 90 * time.Second}, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}}
	host, _ := os.Hostname()
	metadata, _ := json.Marshal(map[string]string{"host": host, "os": runtime.GOOS,
		"arch": runtime.GOARCH, "nonce": randomID()})
	var registered struct {
		ID    string `json:"id"`
		Token string `json:"token"`
	}
	attempt := 0
	for {
		err = r.request(ctx, "POST", "/console/register", metadata, &registered)
		if err == nil {
			break
		}
		if ctx.Err() != nil {
			return err
		}
		var status relayStatusError
		if errors.As(err, &status) && status.code != http.StatusUnauthorized {
			return err
		}
		if errors.As(err, &status) && status.code == http.StatusUnauthorized && attempt >= 2 {
			return errors.New("connection link expired or already used")
		}
		if attempt > 120 {
			return err
		}
		waitRetry(ctx, &attempt)
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
	network := &netRelay{relay: r, prefix: prefix, streams: map[string]net.Conn{},
		listeners: map[string]net.Listener{}, canceled: map[string]bool{}}
	defer network.closeAll()
	go network.loop(ctx)
	tty, err := startTerminal()
	if err != nil {
		return err
	}
	defer tty.Close()
	fmt.Fprintf(os.Stderr, "Connected to %s as %s (%s/%s). Ctrl+C here disconnects.\n", r.origin, host, runtime.GOOS, runtime.GOARCH)
	failures := make(chan error, 2)
	go func() {
		buffer := make([]byte, 16384)
		attempt := 0
		for {
			n, readErr := tty.Read(buffer)
			if n > 0 {
				for {
					err := r.request(ctx, "POST", prefix+"/output", buffer[:n], nil)
					if err == nil {
						attempt = 0
						break
					}
					if ctx.Err() != nil {
						return
					}
					if fatalRelay(err) {
						failures <- err
						return
					}
					waitRetry(ctx, &attempt)
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
		attempt := 0
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
				if ctx.Err() != nil {
					return
				}
				if fatalRelay(err) {
					failures <- err
					return
				}
				waitRetry(ctx, &attempt)
				continue
			}
			attempt = 0
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
