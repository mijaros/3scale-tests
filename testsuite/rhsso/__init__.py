"""Utility classes for working with RHSSO server"""
import functools

import backoff
from keycloak import KeycloakOpenID
from keycloak.exceptions import KeycloakGetError
from threescale_api.auth import BaseClientAuth
from threescale_api.resources import Service
from threescale_api.utils import HttpClient

from testsuite.httpx import HttpxOidcClientAuth
from testsuite.rhsso.objects import Realm, Client, RHSSO, Token


class RHSSOServiceConfiguration:
    """
    Wrapper for all information that tests need to know about RHSSO
    """

    # pylint: disable=too-many-arguments
    def __init__(self, rhsso: RHSSO, realm: Realm, client: Client, user, username, password) -> None:
        self.rhsso = rhsso
        self.realm = realm
        self.user = user
        self.client = client
        self.username = username
        self.password = password
        self._oidc_client = None

    @property
    def oidc_client(self) -> KeycloakOpenID:
        """OIDCClient for the created client"""
        if not self._oidc_client:
            self._oidc_client = self.client.oidc_client
        return self._oidc_client

    def issuer_url(self) -> str:
        """
        Returns issuer url for 3scale in format
        http(s)://<HOST>:<PORT>/auth/realms/<REALM_NAME>
        :return: url
        """
        return self.oidc_client.well_know()["issuer"]

    def jwks_uri(self):
        """
        Returns jwks uri for 3scale in format
        http(s)://<HOST>:<PORT>o/auth/realms/<REALM_NAME>/protocol/openid-connect/certs
        :return: url
        """
        return self.oidc_client.well_know()["jwks_uri"]

    def authorization_url(self) -> str:
        """
        Returns authorization url for 3scale in format
        http(s)://<CLIENT_ID>:<CLIENT_SECRET>@<HOST>:<PORT>/auth/realms/<REALM_NAME>
        :return: url
        """
        url = self.issuer_url()
        client_id = self.oidc_client.client_id
        secret = self.oidc_client.client_secret_key
        return url.replace("://", f"://{client_id}:{secret}@", 1)

    @backoff.on_exception(backoff.fibo, KeycloakGetError, 8, jitter=None)
    def password_authorize(self, client_id, secret, username=None, password=None):
        """Returns token retrieved by password authentication"""
        username = username or self.username
        password = password or self.password
        return Token(self.realm.oidc_client(client_id, secret).token(username, password))

    # Not sure if backoff is needed, disabling for now
    @backoff.on_predicate(backoff.fibo, lambda x: x is None, 8, jitter=None)
    def get_application_client(self, application):
        """Returns ID of a client (not clientId) for an application"""
        return self.realm.admin.get_client_id(application["client_id"])

    def token_url(self) -> str:
        """
        Returns token endpoint url
        http(s)://<HOST>:<PORT>/auth/realms/<REALM_NAME>/protocol/openid-connect/token
        :return: url
        """
        return self.oidc_client.well_know()["token_endpoint"]

    def body_for_token_creation(self, app, use_service_accounts=False) -> str:
        """
        Returns body for creation of token
        :return: body
        """
        app_key = app.keys.list()["keys"][0]["key"]["value"]
        app_id = app["client_id"]
        grant_type = "client_credentials" if use_service_accounts else "password"
        user_credentials = "" if use_service_accounts else f"&username={self.username}&password={self.password}"
        return f"grant_type={grant_type}&client_id={app_id}&client_secret={app_key}{user_credentials}"

    def access_token(self, app) -> str:
        """
        Returns access token for given application
        :param app: 3scale application
        :return: access token
        """
        # Wait for application client to be created
        self.get_application_client(app)
        app_key = app.keys.list()["keys"][0]["key"]["value"]
        return self.password_authorize(app["client_id"], app_key)["access_token"]


class OIDCClientAuth(BaseClientAuth):
    """Authentication class for  OIDC based authorization"""

    @classmethod
    def partial(cls, service_rhsso_info, **kwargs):
        """Returns partially "initialized instance" with interface suitable for register_auth"""

        return functools.partial(cls, service_rhsso_info, **kwargs)

    def __init__(self, service_rhsso_info, application, location=None) -> None:
        super().__init__(application, location)
        self.service_rhsso_info = service_rhsso_info

    def __call__(self, request):
        access_token = self.service_rhsso_info.access_token(self.app)
        credentials = {"access_token": access_token}

        if self.location == "authorization":
            request.headers.update({'Authorization': 'Bearer ' + access_token})
        elif self.location == "headers":
            request.prepare_headers(credentials)
        elif self.location == "query":
            request.prepare_url(request.url, credentials)
        else:
            raise ValueError("Unknown credentials location '%s'" % self.location)
        return request


class OIDCClientAuthHook:
    """Configure rhsso auth through app hooks"""

    def __init__(self, rhsso_service_info, credentials_location="authorization", oidc_configuration=None):
        self.rhsso_service_info = rhsso_service_info
        self.credentials_location = credentials_location
        self.oidc_configuration = oidc_configuration
        if self.oidc_configuration is None:
            self.oidc_configuration = {
                "standard_flow_enabled": False,
                "direct_access_grants_enabled": True}

    # pylint: disable=no-self-use
    def before_service(self, service_params: dict) -> dict:
        """Update service params"""
        service_params.update(backend_version=Service.AUTH_OIDC)
        return service_params

    # pylint: disable=unused-argument
    def before_proxy(self, service: Service, proxy_params: dict):
        """Update proxy params"""
        proxy_params.update(
            credentials_location=self.credentials_location,
            oidc_issuer_endpoint=self.rhsso_service_info.authorization_url(),
            oidc_issuer_type="keycloak")
        return proxy_params

    # pylint: disable=no-self-use
    def on_service_create(self, service):
        """Update oidc config"""

        service.proxy.oidc.update(params={"oidc_configuration": self.oidc_configuration})

    def on_application_create(self, application):
        """Register OIDC auth object for api_client"""

        # pylint: disable=protected-access
        if application._client_factory is HttpClient:
            application.register_auth(
                Service.AUTH_OIDC, OIDCClientAuth.partial(self.rhsso_service_info, location=self.credentials_location))
        else:
            application.register_auth(
                Service.AUTH_OIDC,
                HttpxOidcClientAuth.partial(self.rhsso_service_info, location=self.credentials_location))
