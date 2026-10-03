from geodel.auth_compat import unpack_auth_result


def test_unpacks_qgis_3_and_qgis_4_auth_results():
    original = object()
    returned = object()

    assert unpack_auth_result(True, original) == (True, original)
    assert unpack_auth_result((True, returned), original) == (True, returned)
