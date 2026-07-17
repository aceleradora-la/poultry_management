# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryBatchVaccinationPlan(models.Model):
    _name = 'poultry.batch.vaccination.plan'
    _description = 'Asignación de Plan de Vacunación a Lote'
    _order = 'batch_id, date_from desc, id desc'

    # Asignación con historial: desasignar un plan es cerrar la vigencia (date_to),
    # nunca borrar la fila, para que siempre quede el registro de qué plan de
    # vacunación tuvo cada lote y en qué período. Un lote puede tener más de un plan
    # vigente a la vez (ej. plan base + refuerzos).
    batch_id = fields.Many2one('poultry.batch', string='Lote de Aves', required=True,
                               index=True, ondelete='cascade')
    plan_id = fields.Many2one('poultry.vaccination.plan', string='Plan de Vacunación',
                              required=True, index=True, ondelete='restrict',
                              domain="[('active', '=', True)]")
    date_from = fields.Date(string='Vigente Desde', required=True, default=fields.Date.today)
    date_to = fields.Date(string='Vigente Hasta',
                          help='Vacío = asignación vigente. Al desasignar el plan se '
                               'completa esta fecha; la fila no se borra (historial).')
    assigned_by_id = fields.Many2one('res.users', string='Asignado por',
                                     default=lambda self: self.env.user, readonly=True)
    notes = fields.Text(string='Notas')

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for record in self:
            if record.date_to and record.date_to < record.date_from:
                raise ValidationError(
                    'La fecha "Vigente Hasta" no puede ser anterior a "Vigente Desde".')

    @api.constrains('batch_id', 'plan_id', 'date_to')
    def _check_unique_open_assignment(self):
        for record in self:
            if record.date_to:
                continue
            other_open = self.search_count([
                ('id', '!=', record.id),
                ('batch_id', '=', record.batch_id.id),
                ('plan_id', '=', record.plan_id.id),
                ('date_to', '=', False),
            ])
            if other_open:
                raise ValidationError(
                    'El plan %s ya está asignado y vigente para el lote %s. Cerrá la '
                    'asignación anterior (Vigente Hasta) antes de volver a asignarlo.'
                    % (record.plan_id.name, record.batch_id.name))

    def action_close_assignment(self):
        """Desasigna el plan cerrando la vigencia a hoy (preserva el historial)."""
        for record in self:
            if record.date_to:
                raise ValidationError('La asignación ya está cerrada.')
        self.write({'date_to': fields.Date.today()})
