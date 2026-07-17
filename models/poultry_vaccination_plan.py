# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryVaccinationPlan(models.Model):
    _name = 'poultry.vaccination.plan'
    _description = 'Plan de Vacunación'
    _order = 'name'

    # El plan es configuración (sin estados): una plantilla de vacunas por Semana de
    # Vida, independiente de la genética. Los lotes lo reciben vía asignaciones con
    # historial (poultry.batch.vaccination.plan).
    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', copy=False)
    active = fields.Boolean(string='Activo', default=True)
    line_ids = fields.One2many('poultry.vaccination.plan.line', 'plan_id',
                               string='Vacunas del Plan')
    assignment_ids = fields.One2many('poultry.batch.vaccination.plan', 'plan_id',
                                     string='Asignaciones a Lotes')
    notes = fields.Text(string='Notas')

    line_count = fields.Integer(string='Vacunas', compute='_compute_counts')
    batch_count = fields.Integer(string='Lotes Asignados', compute='_compute_counts')

    @api.depends('line_ids', 'assignment_ids.batch_id')
    def _compute_counts(self):
        for plan in self:
            plan.line_count = len(plan.line_ids)
            plan.batch_count = len(plan.assignment_ids.mapped('batch_id'))

    def action_view_assignments(self):
        self.ensure_one()
        return {
            'name': 'Asignaciones del Plan %s' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'poultry.batch.vaccination.plan',
            'view_mode': 'list,form',
            'domain': [('plan_id', '=', self.id)],
            'context': {'default_plan_id': self.id},
        }
