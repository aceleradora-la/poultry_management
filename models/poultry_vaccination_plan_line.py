# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError

from .poultry_vaccine import VACCINE_ROUTES


class PoultryVaccinationPlanLine(models.Model):
    _name = 'poultry.vaccination.plan.line'
    _description = 'Línea de Plan de Vacunación'
    _order = 'week, sequence, id'

    plan_id = fields.Many2one('poultry.vaccination.plan', string='Plan de Vacunación',
                              required=True, index=True, ondelete='cascade')
    week = fields.Integer(string='Semana de Vida', required=True,
                          help='Semana de vida del lote (0 = primera semana) en la que '
                               'corresponde aplicar la vacuna.')
    vaccine_id = fields.Many2one('poultry.vaccine', string='Vacuna', required=True,
                                 ondelete='restrict',
                                 domain="[('active', '=', True)]")
    route = fields.Selection(VACCINE_ROUTES, string='Vía de Aplicación')
    dose = fields.Char(string='Dosis')
    sequence = fields.Integer(string='Secuencia', default=10)
    notes = fields.Char(string='Notas')

    @api.onchange('vaccine_id')
    def _onchange_vaccine_id(self):
        """Propone la vía y dosis habituales de la vacuna."""
        if self.vaccine_id:
            self.route = self.vaccine_id.default_route
            self.dose = self.vaccine_id.default_dose

    @api.constrains('week')
    def _check_week(self):
        for line in self:
            if line.week < 0:
                raise ValidationError('La Semana de Vida no puede ser negativa.')
