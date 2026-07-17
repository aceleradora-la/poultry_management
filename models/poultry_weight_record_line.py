# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryWeightRecordLine(models.Model):
    _name = 'poultry.weight.record.line'
    _description = 'Peso Individual de Ave'
    _order = 'record_id, sequence, id'

    # Una fila por ave pesada (no por jaula): permite calcular uniformidad y CV, y la
    # carga es más rápida en una única lista editable que en un diálogo por jaula.
    record_id = fields.Many2one('poultry.weight.record', string='Parte de Peso',
                                required=True, index=True, ondelete='cascade')
    cage_id = fields.Many2one('poultry.cage', string='Jaula', required=True,
                              index=True, ondelete='restrict')
    weight_g = fields.Float(string='Peso (g)', required=True, digits=(16, 1))
    sequence = fields.Integer(string='Secuencia', default=10)
    deviation_pct = fields.Float(string='Desvío vs Promedio (%)',
                                 compute='_compute_deviation_pct', digits=(16, 2))

    @api.depends('weight_g', 'record_id.average_weight_g')
    def _compute_deviation_pct(self):
        for line in self:
            avg = line.record_id.average_weight_g
            line.deviation_pct = ((line.weight_g - avg) / avg * 100.0) if avg else 0.0

    @api.constrains('weight_g')
    def _check_weight(self):
        """El cero se permite en Borrador (filas precargadas); action_done es quien
        bloquea confirmar con pesos en cero."""
        for line in self:
            if line.weight_g < 0:
                raise ValidationError('El peso no puede ser negativo.')
            if line.weight_g > 10000:
                raise ValidationError(
                    'El peso %s g no es válido para una gallina (¿está cargado en '
                    'gramos?).' % line.weight_g)

    @api.constrains('cage_id', 'record_id')
    def _check_cage_coop(self):
        for line in self:
            if line.cage_id.coop_id != line.record_id.coop_id:
                raise ValidationError(
                    'La jaula %s pertenece al galpón %s, no al galpón del parte (%s).'
                    % (line.cage_id.name, line.cage_id.coop_id.name,
                       line.record_id.coop_id.name))
