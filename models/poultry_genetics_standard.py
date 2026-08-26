# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryGeneticsStandard(models.Model):
    _name = 'poultry.genetics.standard'
    _description = 'Estándar de Genética por Semana'
    _order = 'genetics_id, version_id, period, week'
    _rec_name = 'display_name'

    version_id = fields.Many2one('poultry.genetics.standard.version', string='Versión',
                                  required=True, index=True, ondelete='cascade')
    # No se usa related=... a propósito: un related+store hereda el required=True del
    # campo genetics_id de Versión, lo que bloquea la importación (el campo es readonly,
    # así que el importador no puede completarlo, pero Odoo igual lo exige antes de crear
    # el registro). Con compute simple, el campo no hereda esa obligatoriedad.
    genetics_id = fields.Many2one('poultry.genetics', string='Genética', compute='_compute_genetics_id',
                                   store=True, index=True, readonly=True)
    indicator_id = fields.Many2one('poultry.indicator', string='Indicador', required=True,
                                    index=True, ondelete='restrict')
    period = fields.Selection([
        ('crianza', 'Crianza'),
        ('produccion', 'Producción'),
    ], string='Período', required=True, index=True,
        help='Período del Lote (Crianza o Producción) al que corresponde este valor estándar.')
    week = fields.Integer(string='Semana de Vida', required=True,
                          help='Semana de vida de las aves (desde la semana 1)')

    value_low = fields.Float(string='Bajo', digits=(16, 4))
    value_high = fields.Float(string='Alto', digits=(16, 4))

    notes = fields.Text(string='Notas')
    active = fields.Boolean(string='Activo', default=True)

    display_name = fields.Char(string='Nombre', compute='_compute_display_name', store=True)

    @api.depends('version_id.genetics_id')
    def _compute_genetics_id(self):
        for record in self:
            record.genetics_id = record.version_id.genetics_id

    @api.depends('genetics_id.name', 'version_id.name', 'indicator_id.name', 'period', 'week')
    def _compute_display_name(self):
        period_labels = dict(self._fields['period'].selection)
        for record in self:
            period_label = period_labels.get(record.period, '')
            record.display_name = (
                f'{record.genetics_id.name} [{record.version_id.name}] - '
                f'{record.indicator_id.name} - {period_label} S{record.week}'
            )

    _sql_constraints = [
        ('unique_version_indicator_week_period', 'unique(version_id, indicator_id, week, period)',
         'Ya existe un valor para este indicador, semana y período en esta versión.'),
        ('week_positive', 'CHECK(week >= 1)',
         'La semana debe ser mayor o igual a 1.'),
        ('value_low_positive', 'CHECK(value_low >= 0)',
         'El valor Bajo no puede ser negativo.'),
        ('value_high_positive', 'CHECK(value_high >= 0)',
         'El valor Alto no puede ser negativo.'),
        ('value_high_gte_low', 'CHECK(value_high >= value_low)',
         'El valor Alto no puede ser menor que el valor Bajo.'),
    ]
