def unpack_auth_result(result, config):
    return result if isinstance(result, tuple) else (result, config)
