# File Uploads

Hypern provides built-in support for handling multipart file uploads with efficient streaming and memory management.

## Basic File Upload

```python
from hypern import Hypern

app = Hypern()

@app.post("/upload")
def upload_file(req, res, ctx):
    # Get files from multipart form
    files = req.files()
    
    if "file" not in files:
        res.status(400).json({"error": "No file provided"})
        return
    
    uploaded_file = files["file"]
    
    # Save the file
    with open(f"/tmp/{uploaded_file.filename}", "wb") as f:
        f.write(uploaded_file.read())
    
    res.json({
        "filename": uploaded_file.filename,
        "size": uploaded_file.size,
        "content_type": uploaded_file.content_type
    })
```

## Multiple File Uploads

```python
@app.post("/upload-multiple")
def upload_multiple(req, res, ctx):
    files = req.files()
    uploaded = []
    
    for key, file in files.items():
        path = f"/tmp/{file.filename}"
        with open(path, "wb") as f:
            f.write(file.read())
        
        uploaded.append({
            "field": key,
            "filename": file.filename,
            "size": file.size,
            "content_type": file.content_type
        })
    
    res.json({"uploaded": uploaded})
```

## File Upload with Validation

```python
from hypern.validation import validate_body, validate_files
import msgspec

class UploadRequest(msgspec.Struct):
    description: str

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".pdf"}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB

@app.post("/upload-with-metadata")
@validate_body(UploadRequest)
def upload_with_metadata(req, res, ctx, body: UploadRequest):
    files = req.files()
    
    if "file" not in files:
        res.status(400).json({"error": "No file provided"})
        return
    
    file = files["file"]
    
    # Validate file extension
    import os
    _, ext = os.path.splitext(file.filename)
    if ext.lower() not in ALLOWED_EXTENSIONS:
        res.status(400).json({"error": f"File type {ext} not allowed"})
        return
    
    # Validate file size
    if file.size > MAX_FILE_SIZE:
        res.status(413).json({"error": "File too large"})
        return
    
    # Process file
    path = f"/tmp/{file.filename}"
    with open(path, "wb") as f:
        f.write(file.read())
    
    res.json({
        "filename": file.filename,
        "description": body.description,
        "size": file.size,
        "message": "File uploaded successfully"
    })
```

## Streaming Large Files

For very large files, use streaming to avoid loading everything into memory:

```python
@app.post("/upload-stream")
def upload_stream(req, res, ctx):
    files = req.files()
    
    if "file" not in files:
        res.status(400).json({"error": "No file provided"})
        return
    
    file = files["file"]
    chunk_size = 1024 * 1024  # 1MB chunks
    
    with open(f"/tmp/{file.filename}", "wb") as f:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            f.write(chunk)
    
    res.json({
        "filename": file.filename,
        "message": "File uploaded successfully"
    })
```

## File Information

Access file properties:

```python
file = files["file"]

# Attributes
print(file.filename)      # Original filename
print(file.size)          # File size in bytes
print(file.content_type)  # MIME type (e.g., "image/jpeg")
print(file.headers)       # Additional headers

# Methods
content = file.read()     # Read all content
chunk = file.read(1024)   # Read specific amount
file.seek(0)              # Reset position
```

## Form Data with Files

Combine file uploads with form fields:

```python
@app.post("/upload-form")
def upload_form(req, res, ctx):
    # Get form fields
    form = req.form()
    title = form.get("title")
    description = form.get("description")
    
    # Get files
    files = req.files()
    file = files.get("file")
    
    if not file:
        res.status(400).json({"error": "No file provided"})
        return
    
    # Save file
    with open(f"/tmp/{file.filename}", "wb") as f:
        f.write(file.read())
    
    res.json({
        "title": title,
        "description": description,
        "filename": file.filename,
        "size": file.size
    })
```

## Best Practices

1. **Always validate file types** - Check MIME types and extensions
2. **Implement size limits** - Prevent disk space exhaustion
3. **Use unique filenames** - Avoid conflicts and security issues
4. **Store outside web root** - Don't serve from upload directory
5. **Implement cleanup** - Remove old uploads periodically
6. **Use streaming for large files** - Reduces memory usage
7. **Scan for malware** - Use antivirus scanning for production
8. **Log uploads** - Track file uploads for audit trails

## Performance Tips

- Use background tasks to process uploaded files
- Implement progress tracking for UI feedback
- Use CDN for serving stored files
- Compress files when appropriate
- Implement resumable uploads for large files
