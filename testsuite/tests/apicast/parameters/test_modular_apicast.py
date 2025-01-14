"""
Tests that an apicast image containing custom policies can be build,
substituted for the image of the deployed apicast and the custom policies
are working as expected.
"""

import backoff

import pytest
import importlib_resources as resources
from testsuite import rawobj
from testsuite.capabilities import Capability
from testsuite.utils import blame

pytestmark = [pytest.mark.required_capabilities(Capability.STANDARD_GATEWAY),
              pytest.mark.issue("https://issues.redhat.com/browse/THREESCALE-553")]


@pytest.fixture(scope="module")
def image_template():
    """
    Returns the path of the apicast_example_policy_template
    """
    return resources.files('testsuite.resources.modular_apicast').joinpath("apicast_example_policy.yml")


@pytest.fixture(scope="module")
def image_stream_amp_apicast_custom_policy(request):
    """
    Returns the blamed name for the amp-apicast-custom-policy image stream
    """
    return blame(request, "is-amp-apicast-custom-policy")


@pytest.fixture(scope="module")
def build_images(openshift, request, image_template,
                 image_stream_amp_apicast_custom_policy):
    """
    Builds images defined by a template specified in the image template applied with parameter
    amp_release.
    oc new-app -f {image_template} --param AMP_RELEASE={amp_release}
    oc start-build {build_name}

    Adds finalizer to delete the created resources when the test ends.
    """
    openshift_client = openshift()

    amp_release = openshift_client.image_stream_tag("amp-apicast")
    build_name_example_policy = blame(request, "apicast-example-policy")
    build_name_custom_policies = blame(request, "apicast-custom-policies")
    image_stream_apicast_policy = blame(request, "is-apicast-policy")

    template_params = {"AMP_RELEASE": amp_release,
                       "BUILD_NAME_EXAMPLE_POLICY": build_name_example_policy,
                       "BUILD_NAME_CUSTOM_POLICY": build_name_custom_policies,
                       "IMAGE_STREAM_APICAST_POLICY": image_stream_apicast_policy,
                       "IMAGE_STREAM_AMP_APICAST_CUSTOM_POLICY": image_stream_amp_apicast_custom_policy
                       }

    def _delete_builds():
        openshift_client.delete_template(image_template, template_params)

    request.addfinalizer(_delete_builds)

    openshift_client.new_app(image_template, template_params)
    openshift_client.start_build(build_name_example_policy)


@pytest.fixture(scope="module")
def staging_gateway(staging_gateway, image_stream_amp_apicast_custom_policy):
    """
    Deploys template apicast.
    Updates the gateway to use the new imagestream.
    """
    staging_gateway.update_image_stream(image_stream_amp_apicast_custom_policy)
    return staging_gateway


@pytest.fixture(scope="module")
def policy_settings():
    """
    Enables the example policy - a custom policy present in the newly built apicast image.
    """
    return rawobj.PolicyConfig("example", configuration={}, version="0.1")


@pytest.fixture(scope="module")
def service(service, policy_settings):
    """
    Service with prepared policy_settings added.
    """
    service.proxy.list().policies.append(policy_settings)
    return service


# for some reason first requests do not seem to be modified, policy is applied later
@backoff.on_predicate(backoff.fibo, lambda x: "X-Example-Policy-Response" not in x.headers, 8, jitter=None)
def get(api_client, url):
    """Resilient get to ensure apicast has time to initalize policy chain"""
    return api_client.get(url)


# pylint: disable=unused-argument
def test_modular_apicast(build_images, api_client):
    """
    Sends a request.
    Asserts that the header added by the example policy is present.
    """
    response = get(api_client(), "/")
    assert response.status_code == 200
    assert 'X-Example-Policy-Response' in response.headers
