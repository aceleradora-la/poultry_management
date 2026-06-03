# -*- coding: utf-8 -*-

from . import models
from . import reports


def post_init_renumber_collections(env):
    """Hook ejecutado después de instalar/actualizar el módulo"""
    env['ir.ui.view']._poultry_cleanup_obsolete_dashboard_settings_views()
    env['poultry.egg.collection'].renumber_existing_collections()

