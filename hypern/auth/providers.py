from typing import Dict
from dataclasses import dataclass


@dataclass
class OAuth2Provider:
    name: str
    client_id: str
    client_secret: str
    authorize_url: str
    token_url: str
    scopes: Dict[str, str]


class OAuth2Providers:
    @staticmethod
    def github(client_id: str, client_secret: str) -> OAuth2Provider:
        return OAuth2Provider(
            name="GitHub",
            client_id=client_id,
            client_secret=client_secret,
            authorize_url="https://github.com/login/oauth/authorize",
            token_url="https://github.com/login/oauth/access_token",
            scopes={"user": "Read user information", "repo": "Access repositories"},
        )

    @staticmethod
    def google(client_id: str, client_secret: str) -> OAuth2Provider:
        return OAuth2Provider(
            name="Google",
            client_id=client_id,
            client_secret=client_secret,
            authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
            token_url="https://oauth2.googleapis.com/token",
            scopes={"profile": "Read user profile", "email": "Read user email"},
        )
