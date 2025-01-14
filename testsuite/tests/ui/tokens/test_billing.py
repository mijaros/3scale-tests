"""
Rewrite of spec/ui_specs/tokens/billing_read_spec.rb
"""

import pytest

from testsuite.ui.views.admin.settings.tokens import Scopes, TokenNewView
from testsuite.utils import blame


@pytest.fixture(scope="module")
def token(custom_admin_login, navigator, request, threescale, permission):
    """
    Create token with scope set to 'Billing'
    """
    custom_admin_login()
    new = navigator.navigate(TokenNewView)
    name = blame(request, "token")
    token = new.create(name, [Scopes.BILLING.value], permission[0])

    def _delete():
        token = list(filter(lambda x: x["name"] == name, threescale.access_tokens.list()))[0]
        threescale.access_tokens.delete(token.entity_id)

    request.addfinalizer(_delete)
    return token


def test_read_service(token, api_client):
    """
    Request to get list of services should have status code 403
    """

    response = api_client("GET", '/admin/api/services', token)
    assert response.status_code == 403


def test_create_account_user(account, token, api_client, request):
    """
    Request to create user should have status code 403
    """

    name = blame(request, "acc")
    params = {"account_id": account.entity_id, "username": name, "email": f"{name}@anything.invalid",
              "password": "123456"}
    response = api_client("POST", f"/admin/api/accounts/{account.entity_id}/users", token, params)
    assert response.status_code == 403


def test_get_service_top_applications(service, token, api_client):
    """
    Request to get top applications should have status code 403
    """

    params = {"service_id": service.entity_id, "since": "2012-02-22 00:00:00", "period": "year", "metric_name": "hits"}
    response = api_client("GET", f"/stats/services/{service.entity_id}/top_applications", token, params)
    assert response.status_code == 403


def test_get_invoice_list(account, token, api_client):
    """
    Request to get list of invoices should have status code 200
    """

    params = {"account_id": account.entity_id}
    response = api_client("GET", f"/api/accounts/{account.entity_id}/invoices", token, params)
    assert response.status_code == 200


def test_create_invoice_line_item(invoice, token, api_client, request, permission):
    """
    Request to create line item should have status code 403 (201 for write permission)
    """

    name = blame(request, "item")
    params = {"invoice_id": invoice.entity_id, "name": name, "description": "description", "quantity": '1', "cost": 1}
    response = api_client("POST", f"/api/invoices/{invoice.entity_id}/line_items", token, json=params)
    assert response.status_code == permission[1]


def test_get_registry_policies_list(token, api_client):
    """
    Request to get list of registry policies should have status code 403
    """

    response = api_client("GET", "/admin/api/registry/policies", token)
    assert response.status_code == 403


def test_create_registry_policy(token, api_client, schema):
    """
    Request to create policy registry should have status code 403
    """
    params = {"name": "policy_registry", "version": "0.1", "schema": schema}
    response = api_client("POST", "/admin/api/registry/policies", token, json=params)
    assert response.status_code == 403
