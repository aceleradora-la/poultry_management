# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryBatchIndicatorWeeklyValue(models.Model):
    _name = 'poultry.batch.indicator.weekly.value'
    _description = 'Valor Real Semanal de Indicador por Lote'
    _order = 'week desc'
    _rec_name = 'display_name'

    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                                index=True, ondelete='cascade')
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador', required=True,
                                    index=True, ondelete='restrict')
    week = fields.Integer(string='Semana de Vida', required=True, index=True)
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período')

    real_value = fields.Float(string='Valor Real', digits=(16, 4))

    week_date_from = fields.Date(string='Desde')
    week_date_to = fields.Date(string='Hasta')

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    _sql_constraints = [
        ('unique_batch_indicator_week', 'unique(batch_id, indicator_id, week)',
         'Ya existe un valor semanal para este lote, este indicador y esta semana.'),
    ]

    @api.depends('batch_id.name', 'indicator_id.name', 'week')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f'{record.batch_id.name} - {record.indicator_id.name} - Semana {record.week}'
