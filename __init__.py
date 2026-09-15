# -*- coding: utf-8 -*-

from . import models
from . import reports
from . import controllers


def post_init_renumber_collections(env):
    """Hook ejecutado después de instalar/actualizar el módulo"""
    env['ir.ui.view']._poultry_cleanup_obsolete_dashboard_settings_views()
    env['poultry.egg.collection'].renumber_existing_collections()
    # Una instalación nueva ya numera las Semanas de Vida desde 1 (es lo que hace
    # el código), pero no pasa por ninguna migración y por eso no tendría el
    # marcador. Sin él, un upgrade posterior de 18.0 a 19.0 correría la
    # migración 19.0.1.33.0 y le sumaría 1 a semanas que ya son 1-based (ver
    # migrations/19.0.1.33.0). Se deja el marcador desde el día cero.
    env['ir.config_parameter'].sudo().set_param(
        'poultry_management.week_numbering_1based', 'True')

