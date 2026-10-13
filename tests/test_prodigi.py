from app import prodigi


def test_recipient_from_paypal_shipping():
    pu = {"shipping": {"name": {"full_name": "Grandma Test"}, "address": {
        "address_line_1": "1 Main St", "admin_area_2": "Newburgh", "admin_area_1": "NY",
        "postal_code": "12550", "country_code": "US"}}}
    r = prodigi.recipient_from_paypal(pu, {"email_address": "g@example.com"})
    assert r == {"name": "Grandma Test", "email": "g@example.com", "address": {
        "line1": "1 Main St", "line2": None, "townOrCity": "Newburgh", "stateOrCounty": "NY",
        "postalOrZipCode": "12550", "countryCode": "US"}}


def test_no_address_means_no_print_order():
    assert prodigi.recipient_from_paypal({}, {}) is None


def test_describe_shows_issues_first():
    assert prodigi.describe({"status": {"stage": "InProgress", "issues": []}}) == "Sent to the print shop"
    assert "needs attention" in prodigi.describe({"status": {"stage": "InProgress", "issues": [{"errorCode": "X"}]}})
