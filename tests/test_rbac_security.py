import pytest

@pytest.mark.asyncio
async def test_billing_rbac(async_client, auth_tokens, db_session):
    # Owner should be allowed
    res_owner = await async_client.get(
        "/api/v1/admin/billing/transactions",
        headers=auth_tokens["owner"]
    )
    assert res_owner.status_code == 200

    # Admin should be allowed
    res_admin = await async_client.get(
        "/api/v1/admin/billing/transactions",
        headers=auth_tokens["admin"]
    )
    assert res_admin.status_code == 200

    # Cashier should be forbidden
    res_cashier = await async_client.get(
        "/api/v1/admin/billing/transactions",
        headers=auth_tokens["cashier"]
    )
    assert res_cashier.status_code == 403

    # Kitchen Staff should be forbidden
    res_staff = await async_client.get(
        "/api/v1/admin/billing/transactions",
        headers=auth_tokens["staff"]
    )
    assert res_staff.status_code == 403
