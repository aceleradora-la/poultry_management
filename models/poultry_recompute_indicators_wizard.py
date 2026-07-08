# -*- coding: utf-8 -*-

from odoo import models, fields


class PoultryRecomputeIndicatorsWizard(models.TransientModel):
    _name = 'poultry.recompute.indicators.wizard'
    _description = 'Recalcular Indicadores de Producción'

    date_from = fields.Date(string='Fecha Desde',
                             help='Vacío para recalcular desde el primer Cierre de Galpón existente.')
    date_to = fields.Date(string='Fecha Hasta',
                           help='Vacío para recalcular hasta el último Cierre de Galpón existente.')

    def action_recompute(self):
        """Reconstruye desde cero (borra y recalcula) los indicadores reales de
        Consumo y Producción de Huevos en el rango indicado, usando el mismo método
        que la migración automática de módulo."""
        self.ensure_one()
        count = self.env['poultry.coop.close']._poultry_rebuild_all_indicator_values(
            date_from=self.date_from, date_to=self.date_to
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Recálculo completado',
                'message': f'Se recalcularon los indicadores de {count} Cierres de Galpón.',
                'type': 'success',
                'sticky': False,
            }
        }
