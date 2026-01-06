# -*- coding: utf-8 -*-

from . import models
from . import reports


def post_init_renumber_collections(env):
    """
    Hook que se ejecuta después de instalar/actualizar el módulo.
    Renumera los registros existentes de producción usando la secuencia numérica.
    """
    try:
        collection_model = env['poultry.egg.collection']
        collection_model.renumber_existing_collections()
    except Exception as e:
        import logging
        _logger = logging.getLogger(__name__)
        _logger.warning(f"Error al renumerar colecciones existentes: {e}")
