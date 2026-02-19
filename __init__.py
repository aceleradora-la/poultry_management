# -*- coding: utf-8 -*-

from . import models
from . import reports


def post_init_renumber_collections(env):
    """Hook ejecutado después de instalar/actualizar el módulo"""
    env['poultry.egg.collection'].renumber_existing_collections()

