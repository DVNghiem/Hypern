from hypern.datastructures import SwaggerConfig
from hypern.hypern import DatabaseConfig


class ConfigManager:
    def __init__(self):
        self.database_config = None
        self.swagger_config = None

    def set_database_config(self, config: DatabaseConfig):
        self.database_config = config

    def set_swagger_config(self, config: SwaggerConfig):
        self.swagger_config = config
