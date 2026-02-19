# -*- coding: utf-8 -*-

from odoo import models, fields
from datetime import timedelta


class PoultryProductionReportWizard(models.TransientModel):
    """Wizard para reporte de producción por galpón y fechas."""
    _name = 'poultry.production.report.wizard'
    _description = 'Asistente de Reporte de Producción'

    coop_id = fields.Many2one('poultry.coop', string='Galpón',
                              domain="[('active', '=', True)]")
    date_from = fields.Date(string='Fecha Desde', required=True,
                            default=lambda self: fields.Date.today() - timedelta(days=30))
    date_to = fields.Date(string='Fecha Hasta', required=True,
                          default=fields.Date.today)

    def action_generate_report(self):
        """Abre el reporte de producción (pivot en líneas) con filtros"""
        domain = [
            ('collection_id.state', '=', 'done'),
            ('collection_id.date', '>=', self.date_from),
            ('collection_id.date', '<=', self.date_to),
        ]
        if self.coop_id:
            domain.append(('collection_id.coop_id', '=', self.coop_id.id))
        return {
            'name': 'Reporte de Producción',
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.egg.collection.line',
            'view_mode': 'list,pivot,form',
            'domain': domain,
            'context': {
                'pivot_measures': ['total_produced_reference', 'total_boxes', 'average_weight_elaborated_aggregated'],
                'pivot_row_groupby': ['collection_date:day'],
                'pivot_column_groupby': ['collection_coop_id'],
            },
        }
