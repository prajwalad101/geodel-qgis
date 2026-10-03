def classFactory(iface):  # noqa: N802 - QGIS plugin API
    from .plugin import GeoDelPlugin

    return GeoDelPlugin(iface)
