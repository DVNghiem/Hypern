from typing import Any


class DependencyManager:
    def __init__(self):
        self.dependencies = {}

    def inject(self, key: str, value: Any):
        self.dependencies[key] = value
