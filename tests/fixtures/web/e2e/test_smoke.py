"""A smoke e2e test without a browser: it reads the page over HTTP from the origin the launcher passes."""

import os
import urllib.request


def test_the_cart_page_shows_the_item_count():
    with urllib.request.urlopen(os.environ["L4_E2E_BASE_URL"] + "/", timeout=5) as response:
        page = response.read().decode()
    assert 'data-testid="item-count">3 items<' in page
