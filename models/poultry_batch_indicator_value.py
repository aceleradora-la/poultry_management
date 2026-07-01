# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryBatchIndicatorValue(models.Model):
    _name = 'poultry.batch.indicator.value'
    _description = 'Valor Real de Indicador por Lote'
    _order = 'date desc'
    _rec_name = 'display_name'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True, index=True)
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador', required=True,
                                    index=True, ondelete='restrict')
    date = fields.Date(string='Fecha', required=True, index=True)
    value = fields.Float(string='Valor Real', digits=(16, 4))

    production_id = fields.Many2one('mrp.production', string='Orden de Fabricación de Origen',
                                     readonly=True,
                                     help='OF de Huevo sin Clasificar que originó este cálculo')
    notes = fields.Text(string='Notas')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('unique_batch_indicator_date', 'unique(batch_id, indicator_id, date)',
         'Ya existe un valor real para este lote, este indicador y esta fecha.'),
    ]

    @api.depends('batch_id.name', 'indicator_id.name', 'date')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} - {record.indicator_id.name} - {record.date}'

    @api.model
    def _set_value(self, batch, coop, target_date, indicator, value, production=None):
        """Crea o actualiza (upsert) el valor real de un indicador para un lote y fecha,
        de forma que recalcular (p. ej. re-cerrar una OF) no duplique registros."""
        existing = self.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', indicator.id),
            ('date', '=', target_date),
        ], limit=1)
        vals = {
            'coop_id': coop.id,
            'value': value,
            'production_id': production.id if production else False,
        }
        if existing:
            existing.write(vals)
            return existing
        vals.update({
            'batch_id': batch.id,
            'indicator_id': indicator.id,
            'date': target_date,
        })
        return self.create(vals)
