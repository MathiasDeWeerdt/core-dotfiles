import sys, os, json

upload_dir = os.environ["EXPOSE_UPLOAD_DIR"]
content_type = os.environ.get("UPLOAD_CT", "")
content_len = int(os.environ.get("UPLOAD_CL", "0"))

os.makedirs(upload_dir, exist_ok=True)

body = sys.stdin.buffer.read(content_len)

boundary = None
for p in content_type.split(";"):
    p = p.strip()
    if p.startswith("boundary="):
        boundary = p[9:].strip('"')
        break

saved = []
if boundary and body:
    sep = ("--" + boundary).encode()
    parts = body.split(sep)
    for part in parts[1:]:
        if part.strip() == b"--" or not part.strip():
            continue
        chunks = part.split(b"\r\n\r\n", 1)
        if len(chunks) < 2:
            continue
        hdrs, fdata = chunks
        if fdata.endswith(b"\r\n"):
            fdata = fdata[:-2]
        filename = None
        for line in hdrs.decode("utf-8", errors="replace").split("\r\n"):
            if "filename=" in line.lower():
                for param in line.split(";"):
                    param = param.strip()
                    if param.lower().startswith("filename="):
                        filename = param[9:].strip('"')
                        break
        if filename:
            name = os.path.basename(filename).replace("..", "").lstrip(".")
            if not name:
                continue
            path = os.path.join(upload_dir, name)
            base, ext = os.path.splitext(name)
            i = 1
            while os.path.exists(path):
                path = os.path.join(upload_dir, f"{base}_{i}{ext}")
                i += 1
            with open(path, "wb") as f:
                f.write(fdata)
            saved.append(os.path.basename(path))

result = json.dumps({"saved": saved, "count": len(saved)})
sys.stdout.write(
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: application/json\r\n"
    f"Content-Length: {len(result)}\r\n"
    "Connection: close\r\n"
    "Server: expose\r\n"
    "\r\n" + result
)
