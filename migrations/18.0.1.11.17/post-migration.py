# -*- coding: utf-8 -*-
"""Quitar vista huérfana de Ajustes que bloqueaba instalación de otros módulos."""

import logging

_logger = logging.getLogger(__name__)

_VIEW_XMLID = 'poultry_management.res_config_settings_view_form_poultry_stock_dashboard'


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    view = env.ref(_VIEW_XMLID, raise_if_not_found=False)
    if view:
        _logger.info('Poultry: eliminando vista obsoleta %s (id=%s)', _VIEW_XMLID, view.id)
        view.unlink()
    else:
        stale = env['ir.ui.view'].sudo().search([
            ('model', '=', 'res.config.settings'),
            ('name', '=', 'res.config.settings.view.form.inherit.poultry.stock.dashboard'),
        ])
        if stale:
            _logger.info('Poultry: eliminando %s vista(s) obsoleta(s) de settings', len(stale))
            stale.unlink()
