# Background Tasks

Hypern provides a background task system for offloading work from request handlers.

## Using Background Tasks in Any Module (Recommended)

**NEW:** You can now use background tasks in any module without importing the app instance, avoiding circular import issues in large applications.

### Global Background Decorator

```python
# services/email_service.py
from hypern import background

@background()  # Execute immediately
def send_welcome_email(to: str, name: str):
    """This runs in a background thread - no app import needed!"""
    import smtplib
    # Send email logic...
    print(f"Welcome email sent to {to}")
    return {"sent": True, "to": to}

@background(delay_seconds=300)  # Execute after 5 minutes
def send_reminder_email(to: str, name: str):
    """Send a delayed reminder email"""
    print(f"Reminder sent to {to}")
    return {"sent": True, "to": to}
```

```python
# routes/user_routes.py
from hypern import Router
from services.email_service import send_welcome_email

router = Router(prefix="/users")

@router.post("/")
def create_user(req, res, ctx):
    data = req.json()
    user = save_user_to_db(data)
    
    # Call background task - no circular import!
    task_id = send_welcome_email(user["email"], user["name"])
    
    res.status(201).json({
        "user": user,
        "email_task_id": task_id
    })
```

```python
# app.py
from hypern import Hypern
from routes.user_routes import router

app = Hypern()  # This initializes the global task executor
app.use(router)

if __name__ == "__main__":
    app.listen(3000)
```

### Global submit_task and get_task

```python
# services/report_service.py
from hypern import submit_task, get_task

def generate_pdf_report(user_id: str, data: dict):
    """Heavy computation"""
    import time
    time.sleep(5)
    return {"pdf_url": f"/reports/{user_id}.pdf"}

def request_report(user_id: str, report_data: dict):
    """Submit report generation without importing app"""
    task_id = submit_task(
        generate_pdf_report,
        args=(user_id, report_data),
        delay_seconds=60  # Execute after 1 minute
    )
    return task_id

def check_report_status(task_id: str):
    """Check task status without importing app"""
    result = get_task(task_id)
    if result:
        return {
            "status": result.status.name,
            "result": result.result,
            "error": result.error
        }
    return None
```

```python
# routes/report_routes.py
from hypern import Router
from services.report_service import request_report, check_report_status

router = Router(prefix="/reports")

@router.post("/")
def create_report(req, res, ctx):
    user_id = ctx.get("user_id")
    data = req.json()
    
    # No app import needed!
    task_id = request_report(user_id, data)
    res.json({"task_id": task_id})

@router.get("/:task_id")
def get_report_status(req, res, ctx):
    task_id = req.param("task_id")
    
    # No app import needed!
    status = check_report_status(task_id)
    if status:
        res.json(status)
    else:
        res.status(404).json({"error": "Task not found"})
```

**Benefits:**
- ✓ No circular imports in large applications
- ✓ Service layer can be completely independent
- ✓ Background tasks defined where they logically belong
- ✓ Easy to test services in isolation
- ✓ Clean separation of concerns
- ✓ Support for delayed task execution

## Basic Usage (App-Based)

You can still use the app-based approach if you prefer. However, this can lead to circular imports in large applications where services need to import the app instance.

**Note:** In large applications, prefer the global approach shown above to avoid circular import issues.

### Background Decorator (App-Based)

```python
from hypern import Hypern

app = Hypern()

@app.background()
def send_email(to: str, subject: str, body: str):
    """This runs in a background thread."""
    import smtplib
    # Send email logic...
    print(f"Email sent to {to}")

@app.post("/notify")
def notify_user(req, res, ctx):
    data = req.json()
    
    # Submit background task (non-blocking)
    send_email(data["email"], "Welcome!", "Thanks for signing up")
    
    # Respond immediately
    res.json({"status": "queued"})
```

### Delayed Execution

You can delay task execution by specifying `delay_seconds`:

```python
@app.background()  # Execute immediately
def immediate_task():
    pass

@app.background(delay_seconds=60)  # Execute after 60 seconds
def delayed_task():
    pass

@app.background(delay_seconds=3600)  # Execute after 1 hour
def scheduled_task():
    pass
```

## Programmatic Task Submission

```python
def process_data(data):
    # Heavy processing
    import time
    time.sleep(5)
    return {"processed": True, "items": len(data)}

@app.post("/process")
def start_processing(req, res, ctx):
    data = req.json()
    
    # Submit task and get task ID
    task_id = app.submit_task(
        process_data,
        args=(data["items"],)
    )
    
    res.json({"task_id": task_id})

@app.post("/process-delayed")
def start_delayed_processing(req, res, ctx):
    data = req.json()
    
    # Submit task with delay
    task_id = app.submit_task(
        process_data,
        args=(data["items"],),
        delay_seconds=300  # Execute after 5 minutes
    )
    
    res.json({"task_id": task_id})
```

## Checking Task Status

```python
@app.get("/tasks/:task_id")
def get_task_status(req, res, ctx):
    task_id = req.param("task_id")
    result = app.get_task(task_id)
    
    if result:
        res.json({
            "status": result.status.name,  # pending, running, completed, failed
            "result": result.result,
            "error": result.error
        })
    else:
        res.status(404).json({"error": "Task not found"})
```

## Task Status Values

```python
from hypern import TaskStatus

# Available statuses
TaskStatus.PENDING    # Task is queued
TaskStatus.RUNNING    # Task is executing
TaskStatus.COMPLETED  # Task finished successfully
TaskStatus.FAILED     # Task raised an exception
```

## Async Tasks

```python
@app.background(priority="normal")
async def async_task(url: str):
    import aiohttp
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            return await response.text()

@app.post("/fetch")
async def fetch_url(req, res, ctx):
    data = req.json()
    async_task(data["url"])
    res.json({"status": "fetching"})
```

## Task Patterns

### Email Sending

```python
@app.background()
def send_email_task(to: str, template: str, context: dict):
    from email.mime.text import MIMEText
    import smtplib
    
    # Render template
    body = render_template(template, context)
    
    # Send email
    msg = MIMEText(body, 'html')
    msg['Subject'] = context.get('subject', 'Notification')
    msg['To'] = to
    
    with smtplib.SMTP('localhost') as smtp:
        smtp.send_message(msg)

@app.post("/users")
def create_user(req, res, ctx):
    user = create_user_in_db(req.json())
    
    # Send welcome email in background
    send_email_task(
        to=user["email"],
        template="welcome.html",
        context={"name": user["name"]}
    )
    
    res.status(201).json(user)
```

### Report Generation

```python
@app.background()
def generate_report(report_type: str, params: dict, user_id: str):
    # Heavy computation
    data = fetch_report_data(report_type, params)
    pdf = render_to_pdf(data)
    
    # Save report
    report_id = save_report(pdf, user_id)
    
    # Notify user
    notify_user(user_id, f"Report {report_id} is ready")
    
    return report_id

@app.post("/reports")
def request_report(req, res, ctx):
    data = req.json()
    
    task_id = app.submit_task(
        generate_report,
        args=(data["type"], data["params"], ctx.get("user_id"))
    )
    
    res.json({
        "message": "Report generation started",
        "task_id": task_id
    })
```

### Batch Processing

```python
@app.background()
def process_batch(items: list):
    results = []
    for item in items:
        result = process_single_item(item)
        results.append(result)
    return results

@app.post("/batch")
def start_batch(req, res, ctx):
    items = req.json()["items"]
    
    # Split into chunks
    chunk_size = 100
    task_ids = []
    
    for i in range(0, len(items), chunk_size):
        chunk = items[i:i + chunk_size]
        task_id = app.submit_task(
            process_batch,
            args=(chunk,)
        )
        task_ids.append(task_id)
    
    res.json({"task_ids": task_ids})
```

## Configuration

```python
app = Hypern(
    task_workers=4,        # Number of background workers
    task_queue_size=1000,  # Max queued tasks
)
```

## Error Handling

```python
@app.background()
def risky_task(data):
    try:
        result = process(data)
        return result
    except Exception as e:
        # Log error
        logger.error(f"Task failed: {e}")
        # Re-raise to mark task as failed
        raise

@app.get("/tasks/:id/retry")
def retry_task(req, res, ctx):
    task_id = req.param("id")
    result = app.get_task(task_id)
    
    if result and result.status == TaskStatus.FAILED:
        # Resubmit the task
        new_task_id = app.submit_task(
            result.func,
            args=result.args
        )
        res.json({"new_task_id": new_task_id})
    else:
        res.status(400).json({"error": "Task not failed or not found"})
```
## Choosing Between Global and App-Based Approaches

### Global Approach (Recommended for Large Apps)

**Use when:**
- Building modular applications with separate service layers
- Avoiding circular import issues
- Background tasks are defined in utility/service modules
- You want clean separation between business logic and web framework

**Advantages:**
- ✓ No circular imports
- ✓ Services can be framework-agnostic
- ✓ Easier to test in isolation
- ✓ Better code organization
- ✓ Can be used in any module

**Example structure:**
```
project/
├── app.py              # Creates Hypern app
├── routes/
│   ├── user_routes.py  # Route handlers
│   └── order_routes.py
└── services/
    ├── email_service.py    # Uses @background
    ├── payment_service.py  # Uses submit_task
    └── report_service.py   # Uses get_task
```

### App-Based Approach

**Use when:**
- Building small, simple applications
- All background tasks are in the main app module
- You prefer explicit app instance usage

**Disadvantages:**
- ✗ Can cause circular imports in large apps
- ✗ Requires importing app instance everywhere
- ✗ Tightly couples services to the framework

## Complete Example: Large Application Structure

### Project Structure
```
myapp/
├── app.py                  # Main application
├── config.py               # Configuration
├── models/                 # Data models
│   ├── user.py
│   └── order.py
├── services/               # Business logic (uses global tasks)
│   ├── email_service.py
│   ├── payment_service.py
│   └── notification_service.py
├── routes/                 # Route handlers
│   ├── user_routes.py
│   ├── order_routes.py
│   └── admin_routes.py
└── tasks/                  # Background task definitions
    ├── email_tasks.py
    ├── report_tasks.py
    └── cleanup_tasks.py
```

### Implementation

```python
# tasks/email_tasks.py
"""
Email background tasks - no app import needed!
"""
from hypern import background
import smtplib

@background()  # Execute immediately
def send_order_confirmation(order_id: str, email: str):
    """Send order confirmation email"""
    # Email logic here
    return {"sent": True, "order_id": order_id}

@background(delay_seconds=3600)  # Send after 1 hour
def send_weekly_newsletter(subscriber_list: list):
    """Send newsletter to all subscribers"""
    sent_count = 0
    for subscriber in subscriber_list:
        # Send email
        sent_count += 1
    return {"sent": sent_count}
```

```python
# services/order_service.py
"""
Order service - uses background tasks without circular imports
"""
from tasks.email_tasks import send_order_confirmation
from models.order import Order

def create_order(user_id: str, items: list) -> dict:
    """Create order and send confirmation email"""
    # Save order to database
    order = Order.create(user_id=user_id, items=items)
    
    # Send confirmation email in background - no app import!
    task_id = send_order_confirmation(order.id, order.user_email)
    
    return {
        "order": order.to_dict(),
        "email_task_id": task_id
    }
```

```python
# routes/order_routes.py
"""
Order routes - clean and simple
"""
from hypern import Router
from services.order_service import create_order

router = Router(prefix="/orders")

@router.post("/")
def create_order_endpoint(req, res, ctx):
    data = req.json()
    user_id = ctx.get("user_id")
    
    # Service handles everything including background tasks
    result = create_order(user_id, data["items"])
    
    res.status(201).json(result)
```

```python
# app.py
"""
Main application - just wire everything together
"""
from hypern import Hypern
from routes.user_routes import router as user_router
from routes.order_routes import router as order_router

app = Hypern(
    task_workers=8,
    task_queue_size=2000
)

# Register routes
app.use(user_router)
app.use(order_router)

if __name__ == "__main__":
    app.listen(3000)
```

## Best Practices

### 1. Use Global Tasks for Services

```python
# ✓ GOOD - Service layer independent of framework
from hypern import background, submit_task

@background()  # or with delay: @background(delay_seconds=60)
def process_payment(order_id: str, amount: float):
    # Payment logic
    pass

# ✗ BAD - Service tightly coupled to app
from app import app  # Circular import risk!

@app.background()
def process_payment(order_id: str, amount: float):
    pass
```

### 2. Organize Tasks by Domain

```python
# tasks/email_tasks.py
from hypern import background

@background()
def send_verification_email(user_id: str):
    pass

@background(delay_seconds=86400)  # Daily newsletter
def send_newsletter(user_ids: list):
    pass

# tasks/data_tasks.py
from hypern import background

@background(delay_seconds=3600)  # Hourly cleanup
def cleanup_old_data():
    pass

@background(delay_seconds=7200)  # Every 2 hours
def generate_analytics():
    pass
```

### 3. Check Task Status in Routes

```python
from hypern import Router, get_task

router = Router(prefix="/tasks")

@router.get("/:task_id")
def check_task(req, res, ctx):
    task_id = req.param("task_id")
    result = get_task(task_id)
    
    if not result:
        res.status(404).json({"error": "Task not found"})
        return
    
    response = {
        "task_id": task_id,
        "status": result.status.name
    }
    
    if result.is_success():
        response["result"] = result.result
    elif result.is_failed():
        response["error"] = str(result.error)
    
    res.json(response)
```

### 4. Handle Task Errors Gracefully

```python
from hypern import background
import logging

logger = logging.getLogger(__name__)

@background()
def risky_operation(data: dict):
    try:
        # Attempt operation
        result = perform_operation(data)
        logger.info(f"Operation succeeded: {result}")
        return result
    except ValueError as e:
        logger.error(f"Validation error: {e}")
        # Don't retry validation errors
        raise
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        # Could implement retry logic here
        raise
```

## Migration Guide

### Migrating from App-Based to Global Tasks

**Before (causes circular imports):**
```python
# app.py
from hypern import Hypern
from routes.user_routes import router

app = Hypern()
app.use(router)

@app.background()
def send_email(to: str, subject: str):
    pass

# routes/user_routes.py
from app import app  # ← Circular import!
from app import send_email

router = Router()

@router.post("/users")
def create_user(req, res, ctx):
    send_email("user@example.com", "Welcome")
    pass
```

**After (no circular imports):**
```python
# tasks/email_tasks.py
from hypern import background

@background()
def send_email(to: str, subject: str):
    pass

# routes/user_routes.py
from tasks.email_tasks import send_email  # ← No circular import!

router = Router()

@router.post("/users")
def create_user(req, res, ctx):
    send_email("user@example.com", "Welcome")
    pass

# app.py
from hypern import Hypern
from routes.user_routes import router

app = Hypern()  # Initializes global task executor
app.use(router)
```