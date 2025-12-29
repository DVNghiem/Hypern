from hypern import Hypern

async def hello_handler(request, response):
    print(f"Handling request for {request.path}")
    response.status(200).body_str(f"Hello, {request.path}").finish()
    print("Handler finished")

if __name__ == "__main__":
    app = Hypern()
    app.add_route("GET", "/hello", hello_handler)
    print("Starting server on port 5011...")
    app.start(port=5011, workers=1)
