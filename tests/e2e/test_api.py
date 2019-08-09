import uuid
import pytest
import requests

from allocation import config

def random_ref(prefix):
    return prefix + '-' + uuid.uuid4().hex[:10]

def post_to_add_batch(ref, sku, qty, eta):
    url = config.get_api_url()
    r = requests.post(
        f'{url}/add_batch',
        json={'ref': ref, 'sku': sku, 'qty': qty, 'eta': eta}
    )
    assert r.status_code == 201

def get_allocation(orderid):
    url = config.get_api_url()
    return requests.get(f'{url}/allocations/{orderid}')


@pytest.mark.usefixtures('postgres_db')
@pytest.mark.usefixtures('restart_api')
def test_happy_path_returns_202_and_batch_is_allocated():
    orderid = random_ref('o')
    sku, othersku = random_ref('s1'), random_ref('s2')
    batch1, batch2, batch3 = random_ref('b1'), random_ref('b2'), random_ref('b3')
    post_to_add_batch(batch1, sku, 100, '2011-01-02')
    post_to_add_batch(batch2, sku, 100, '2011-01-01')
    post_to_add_batch(batch3, othersku, 100, None)
    data = {
        'orderid': orderid,
        'sku': sku,
        'qty': 3,
    }
    url = config.get_api_url()
    r = requests.post(f'{url}/allocate', json=data)
    assert r.status_code == 202
    r = get_allocation(orderid)
    assert r.ok
    assert r.json() == [
        {'sku': sku, 'batchid': batch2},
    ]


@pytest.mark.usefixtures('postgres_db')
@pytest.mark.usefixtures('restart_api')
def test_unhappy_path_returns_400_and_error_message():
    sku, orderid = random_ref('s'), random_ref('o')
    data = {'orderid': orderid, 'sku': sku, 'qty': 20}
    url = config.get_api_url()
    r = requests.post(f'{url}/allocate', json=data)
    assert r.status_code == 400
    assert r.json()['message'] == f'Invalid sku {sku}'
    r = get_allocation(orderid)
    assert r.status_code == 404

