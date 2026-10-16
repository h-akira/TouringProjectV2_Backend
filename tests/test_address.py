"""Tests for reverse geocoding to a town-level address."""
from lib.address import describe_location


class FakeGeo:
    def __init__(self, items=None, error=None):
        self.items, self.error, self.calls = items or [], error, []

    def reverse_geocode(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return {"ResultItems": self.items}


def item(**address):
    return {"Address": address}


def test_longitude_first_and_japanese():
    fake = FakeGeo([item(Region={"Name": "東京都"}, Locality="千代田区", SubDistrict="丸の内")])
    assert describe_location(35.6812, 139.7671, fake) == "東京都千代田区丸の内"
    assert fake.calls[0]["QueryPosition"] == [139.7671, 35.6812]
    assert fake.calls[0]["Language"] == "ja"


def test_designated_city_ward_and_town():
    fake = FakeGeo([item(Region={"Name": "北海道"}, Locality="札幌市", District="北区", SubDistrict="北6条西")])
    assert describe_location(43.0, 141.3, fake) == "北海道札幌市北区北6条西"


def test_county_when_no_locality():
    fake = FakeGeo([item(Region={"Name": "神奈川県"}, SubRegion={"Name": "足柄下郡"})])
    assert describe_location(35.2, 139.0, fake) == "神奈川県足柄下郡"


def test_region_only():
    assert describe_location(35.0, 139.0, FakeGeo([item(Region={"Name": "静岡県"})])) == "静岡県"


def test_nothing_found_or_error_is_none():
    assert describe_location(30.0, 140.0, FakeGeo([])) is None
    assert describe_location(35.0, 139.0, FakeGeo(error=RuntimeError("x"))) is None
