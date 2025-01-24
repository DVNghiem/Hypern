from typing import Optional, Dict
from pydantic import BaseModel, AnyUrl
from dataclasses import dataclass, field


class BaseModelWithConfig(BaseModel):
    model_config = {"extra": "allow"}


class Contact(BaseModelWithConfig):
    name: Optional[str] = None
    url: Optional[AnyUrl] = None
    email: Optional[str] = None


class License(BaseModelWithConfig):
    name: str
    identifier: Optional[str] = None
    url: Optional[AnyUrl] = None


class Info(BaseModelWithConfig):
    title: str = "Swagger Document"
    version: str = "0.0.1"
    summary: Optional[str] = None
    description: Optional[str] = None
    contact: Optional[Contact] = None
    license: Optional[License] = None


@dataclass
class OAuth2Flow:
    authorizationUrl: Optional[str] = None
    tokenUrl: Optional[str] = None
    refreshUrl: Optional[str] = None
    scopes: Dict[str, str] = field(default_factory=dict)


@dataclass
class OAuth2Config:
    flows: Dict[str, OAuth2Flow]
    description: str = "OAuth2 authentication"


@dataclass
class SwaggerConfig:
    info: Info
    oauth2_config: Optional[OAuth2Config] = None
    openapi_url: str = "/openapi.json"
    docs_url: str = "/docs"

    def get_security_schemes(self) -> Dict:
        if not self.oauth2_config:
            return {}

        security_schemes = {"oauth2": {"type": "oauth2", "description": self.oauth2_config.description, "flows": {}}}

        for flow_name, flow in self.oauth2_config.flows.items():
            flow_config = {}
            if flow.authorizationUrl:
                flow_config["authorizationUrl"] = flow.authorizationUrl
            if flow.tokenUrl:
                flow_config["tokenUrl"] = flow.tokenUrl
            if flow.refreshUrl:
                flow_config["refreshUrl"] = flow.refreshUrl
            flow_config["scopes"] = flow.scopes
            security_schemes["oauth2"]["flows"][flow_name] = flow_config

        return security_schemes

    def get_openapi_schema(self) -> Dict:
        schema = {
            "openapi": "3.0.3",
            "info": self.info.model_dump(),
            "components": {"securitySchemes": self.get_security_schemes()},
            "security": [{"oauth2": []}] if self.oauth2_config else [],
        }
        return schema
