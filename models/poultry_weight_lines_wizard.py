# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryWeightLinesWizard(models.TransientModel):
    """Generar Líneas de Pesaje: una línea por ave prevista en cada jaula de muestreo
    del galpón, en el orden físico. Reemplaza a la precarga desde la pesada anterior:
    propone las mismas aves por jaula que la última vez."""
    _name = 'poultry.weight.lines.wizard'
    _description = 'Generar Líneas de Pesaje'

    record_id = fields.Many2one('poultry.weight.record', string='Parte de Peso',
                                required=True, ondelete='cascade')
    coop_id = fields.Many2one(related='record_id.coop_id')
    birds_per_cage = fields.Integer(string='Aves por Jaula', compute='_compute_birds_per_cage',
                                    store=True, readonly=False)
    previous_name = fields.Char(string='Pesada Anterior', compute='_compute_previous_name')
    cage_count = fields.Integer(string='Jaulas de Muestreo', compute='_compute_counts')
    line_count = fields.Integer(string='Líneas a Crear', compute='_compute_counts')

    def _poultry_cages(self):
        self.ensure_one()
        return self.env['poultry.cage'].search([
            ('coop_id', '=', self.coop_id.id), ('is_sampling', '=', True),
        ]).sorted(key=lambda cage: cage._poultry_sort_key())

    def _poultry_previous_record(self):
        self.ensure_one()
        return self.record_id._poultry_previous_record() if self.record_id else None

    # Computes separados: Odoo exige métodos distintos para campos almacenados y no
    # almacenados que dependen de lo mismo.
    @api.depends('record_id')
    def _compute_birds_per_cage(self):
        for wizard in self:
            previous = wizard._poultry_previous_record()
            wizard.birds_per_cage = (previous.birds_per_cage if previous else 0) or 10

    @api.depends('record_id')
    def _compute_previous_name(self):
        for wizard in self:
            previous = wizard._poultry_previous_record()
            wizard.previous_name = previous.name if previous else False

    @api.depends('coop_id', 'birds_per_cage')
    def _compute_counts(self):
        for wizard in self:
            wizard.cage_count = len(wizard._poultry_cages()) if wizard.coop_id else 0
            wizard.line_count = wizard.cage_count * max(wizard.birds_per_cage, 0)

    def action_confirm(self):
        self.ensure_one()
        record = self.record_id
        if record.state != 'draft':
            raise ValidationError('Solo se pueden generar líneas en un parte en Borrador.')
        if record.line_ids:
            raise ValidationError('El parte ya tiene líneas.')
        if self.birds_per_cage < 1:
            raise ValidationError('Indicá cuántas aves se pesan por jaula.')
        cages = self._poultry_cages()
        if not cages:
            raise ValidationError('El galpón %s no tiene jaulas de muestreo. Elegilas en '
                                  'Configuración › Jaulas de Muestreo.' % record.coop_id.name)
        record.birds_per_cage = self.birds_per_cage
        record._poultry_add_cage_lines(cages, self.birds_per_cage)
        return True


class PoultryWeightRegisterWizard(models.TransientModel):
    """Aviso al registrar con jaulas sin pesar."""
    _name = 'poultry.weight.register.wizard'
    _description = 'Registrar Pesada con Jaulas sin Pesar'

    record_id = fields.Many2one('poultry.weight.record', string='Parte de Peso',
                                required=True, ondelete='cascade')
    pending_codes = fields.Text(string='Jaulas sin Pesar', compute='_compute_pending')
    pending_count = fields.Integer(compute='_compute_pending')

    @api.depends('record_id')
    def _compute_pending(self):
        for wizard in self:
            pending = wizard.record_id._poultry_pending_cages() if wizard.record_id else []
            wizard.pending_count = len(pending)
            wizard.pending_codes = ', '.join(pending.mapped('code')) if pending else ''

    def action_confirm(self):
        self.ensure_one()
        return self.record_id.action_register(force=True)
