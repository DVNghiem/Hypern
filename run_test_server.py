import os
from hypern import Hypern

# ASYNC handler for benchmark
async def hello_handler(request, response):
    response.status(200).body_str(f"Hello, {request.path}").finish()

if __name__ == "__main__":
    print(f"Main process PID: {os.getpid()}")
    
    app = Hypern()
    app.add_route("GET", "/hello", hello_handler)
    
    # Start in multiprocess mode (pure Rust fork)
    # 12 processes = 12 CPU cores
    app.start_multiprocess(
        host="0.0.0.0",
        port=5011,
        num_processes=12,  # Number of worker processes
        tokio_workers_per_process=2,  # Tokio async workers per process
        max_blocking_threads=16,  # Blocking threads for Python per process
        max_connections=10000,
    )
