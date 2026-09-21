"""Custom URL converters."""
from werkzeug.routing import BaseConverter


class AlphaConverter(BaseConverter):
    """Letters only (``[a-zA-Z]+``) — the suffix of a TNS name such as ``2024abc``.

    Used as ``<int:year><alpha:letters>`` in the object routes.
    """

    def __init__(self, url_map):
        super().__init__(url_map)
        self.regex = r'[a-zA-Z]+'


def register_converters(app) -> None:
    app.url_map.converters['alpha'] = AlphaConverter
