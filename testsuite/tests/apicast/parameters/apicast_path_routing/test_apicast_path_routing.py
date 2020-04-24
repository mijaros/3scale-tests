"""Rewrite of spec/openshift_specs/path_based_routing_two_backends_spec.rb

When `APICAST_PATH_ROUTING` parameter is set to true, the gateway will use path-based routing
in addition to the default host-based routing.
The API request will be routed to the first service that has a matching mapping rule,
from the list of services for which the value of the Host header of the request matches the Public Base URL.
"""
from urllib.parse import urlparse

import pytest
import requests

from testsuite.echoed_request import EchoedRequest
from testsuite.gateways.gateways import Capability

pytestmark = pytest.mark.required_capabilities(Capability.APICAST, Capability.CUSTOM_ENVIRONMENT)


@pytest.fixture(scope="module")
def staging_gateway(staging_gateway):
    """Enable path routing."""
    staging_gateway.set_env("APICAST_PATH_ROUTING", 1)

    return staging_gateway


def test_get_route_request_returns_ok(api_client, private_base_url):
    """Call to mapping /get returns 200 OK."""
    response = api_client.get("/get")
    echoed = EchoedRequest.create(response)

    assert response.status_code == 200
    assert echoed.headers["Host"] == urlparse(private_base_url()).hostname


def test_echo_route_request_returns_ok(api_client2, private_base_url):
    """Call to mapping /echo returns 200 OK."""
    response = api_client2.get("/echo")
    echoed = EchoedRequest.create(response)

    assert response.status_code == 200
    assert echoed.headers["Host"] == urlparse(private_base_url("echo-api")).hostname


def test_not_mapped_route_returns_ok(application2):
    """Call to not mapped route /anything/blah returns 200 OK.

    Path-based routing fails and it fallback to the default host-based routing.
    """
    session = requests.Session()
    session.auth = application2.authobj

    # skip retrying on 404 by passing Session instance to it
    client = application2.api_client(session=session)

    assert client.get("/anything/blah").status_code == 200