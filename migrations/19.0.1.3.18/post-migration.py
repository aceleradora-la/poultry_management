# -*- coding: utf-8 -*-

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    _logger.info('Poultry: limpieza de vistas obsoletas en res.config.settings (migración %s)', version)
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.ui.view']._poultry_cleanup_obsolete_dashboard_settings_views()
