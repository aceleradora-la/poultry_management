# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PoultryCageSamplingWizard(models.TransientModel):
    _name = 'poultry.cage.sampling.wizard'
    _description = 'Elegir Jaulas de Muestreo'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              domain="[('active', '=', True)]")
    cage_ids = fields.Many2many('poultry.cage', 'poultry_cage_sampling_wizard_cage_rel',
                                'wizard_id', 'cage_id', string='Jaulas de Muestreo',
                                compute='_compute_cage_ids', store=True, readonly=False,
                                domain="[('coop_id', '=', coop_id)]")
    cage_count = fields.Integer(string='Jaulas Elegidas', compute='_compute_cage_count')

    @api.depends('coop_id')
    def _compute_cage_ids(self):
        """Arranca con las jaulas ya marcadas del galpón, para sacar y agregar sobre ellas."""
        for wizard in self:
            wizard.cage_ids = wizard.coop_id.cage_ids.filtered('is_sampling')

    @api.depends('cage_ids')
    def _compute_cage_count(self):
        for wizard in self:
            wizard.cage_count = len(wizard.cage_ids)

    def action_confirm(self):
        self.ensure_one()
        current = self.coop_id.cage_ids.filtered('is_sampling')
        (current - self.cage_ids).write({'is_sampling': False})
        (self.cage_ids - current).write({'is_sampling': True})
