import time
import requests
import pytest
from multiprocessing import Process
from hypern import Hypern

def hello_handler(request, response):
    # New API: request: FastRequest, response: ResponseWriter
    response.status(200)
    response.header("Content-Type", "text/plain")
    response.body_str(f"Hello, {request.path}")
    response.finish()

def run_server(port):
    app = Hypern()
    app.add_route("GET", "/hello", hello_handler)
    app.start(port=port)

@pytest.fixture
def server():
    port = 5007
    p = Process(target=run_server, args=(port,))
    p.start()
    time.sleep(2) # Wait for server to start
    yield f"http://127.0.0.1:{port}"
    p.terminate()
    p.join()

def test_hello_endpoint(server):
    res = requests.get(f"{server}/hello")
    assert res.status_code == 200
    assert "Hello, /hello" in res.text

def test_404_endpoint(server):
    res = requests.get(f"{server}/notfound")
    assert res.status_code == 404
    assert res.text == "Not Found"
