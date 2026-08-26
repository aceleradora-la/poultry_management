# -*- coding: utf-8 -*-

import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

_STALE_FIELD = 'poultry_stock_dashboard_category_ids'
_STALE_VIEW_XMLID = 'poultry_management.res_config_settings_view_form_poultry_stock_dashboard'


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    @api.model
    def _poultry_cleanup_obsolete_dashboard_settings_views(self):
        """Elimina vistas de Ajustes que aún referencian el tablero en res.config.settings.

        Se ejecuta en cada actualización del módulo (y en post_init) porque un rebuild en SH
        no siempre borra registros huérfanos y bloquea la instalación de otros módulos.
        """
        View = self.sudo()
        to_unlink = View.browse()

        view = self.env.ref(_STALE_VIEW_XMLID, raise_if_not_found=False)
        if view:
            to_unlink |= view

        candidates = View.search([('model', '=', 'res.config.settings')])
        for v in candidates:
            arch = (v.arch_db or v.arch or '') or ''
            if _STALE_FIELD in arch:
                to_unlink |= v

        if to_unlink:
            _logger.info(
                'Poultry: eliminando %s vista(s) obsoleta(s) de res.config.settings (tablero)',
                len(to_unlink),
            )
            to_unlink.unlink()
