import os
from hypern import Hypern

# ASYNC handler for benchmark
async def hello_handler(request, response):
    response.status(200).body_str(f"Hello, {request.path}").finish()

if __name__ == "__main__":
    app = Hypern()
    app.add_route("GET", "/", hello_handler)
    
    # Start in multiprocess mode (pure Rust fork)
    # 12 processes = 12 CPU cores
    app.start(
        host="0.0.0.0",
        port=5011,
        workers=8,  # Number of worker processes
        max_blocking_threads=512,  # Blocking threads for Python per process
        max_connections=10000,
    )
