import argparse


class ArgsConfig:
    def __init__(self) -> None:
        parser = argparse.ArgumentParser(description="Hypern: A Versatile Python and Rust Framework")
        self.parser = parser
        parser.add_argument(
            "--host",
            type=str,
            default=None,
            required=False,
            help="Choose the host. [Defaults to `127.0.0.1`]",
        )

        parser.add_argument(
            "--port",
            type=int,
            default=None,
            required=False,
            help="Choose the port. [Defaults to `5000`]",
        )

        parser.add_argument(
            "--processes",
            type=int,
            default=None,
            required=False,
            help="Choose the number of processes. [Default: 1]",
        )
        parser.add_argument(
            "--workers",
            type=int,
            default=None,
            required=False,
            help="Choose the number of workers. [Default: 1]",
        )

        parser.add_argument(
            "--max-blocking-threads",
            type=int,
            default=None,
            required=False,
            help="Choose the maximum number of blocking threads. [Default: 100]",
        )

        parser.add_argument(
            "--reload",
            action="store_true",
            help="It restarts the server based on file changes.",
        )
        parser.add_argument(
            "--auto-workers",
            action="store_true",
            help="It sets the number of workers and max-blocking-threads automatically.",
        )

        args, _ = parser.parse_known_args()

        self.host = args.host or "127.0.0.1"
        self.port = args.port or 5000
        self.max_blocking_threads = args.max_blocking_threads or 32
        self.processes = args.processes or 1
        self.workers = args.workers or 1
        self.reload = args.reload or False
        self.auto_workers = args.auto_workers
