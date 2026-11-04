# -*- coding: utf-8 -*-

import math
import re
from itertools import product

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class PoultryCageGenerateWizard(models.TransientModel):
    _name = 'poultry.cage.generate.wizard'
    _description = 'Crear Jaulas de un Galpón'

    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              domain="[('active', '=', True)]")
    coop_number = fields.Integer(string='Número de Galpón', compute='_compute_coop_number',
                                 store=True, readonly=False,
                                 help='Primer número del código de cada jaula (G1 = 1).')
    coop_number_locked = fields.Boolean(compute='_compute_coop_number_locked')

    row_from = fields.Integer(string='Fila desde', default=1, required=True)
    row_to = fields.Integer(string='Fila hasta', default=2, required=True)
    side_from = fields.Integer(string='Lado desde', default=1, required=True)
    side_to = fields.Integer(string='Lado hasta', default=2, required=True)
    bay_from = fields.Integer(string='Claro desde', default=1, required=True)
    bay_to = fields.Integer(string='Claro hasta', default=51, required=True)
    floor_from = fields.Integer(string='Piso desde', default=1, required=True)
    floor_to = fields.Integer(string='Piso hasta', default=4, required=True)
    cage_from = fields.Integer(string='Jaula desde', default=1, required=True)
    cage_to = fields.Integer(string='Jaula hasta', default=4, required=True)

    total_count = fields.Integer(string='Jaulas del Rango', compute='_compute_preview')
    existing_count = fields.Integer(string='Ya Existen', compute='_compute_preview')
    new_count = fields.Integer(string='A Crear', compute='_compute_preview')
    first_code = fields.Char(string='Primera Jaula', compute='_compute_preview')
    last_code = fields.Char(string='Última Jaula', compute='_compute_preview')

    @api.depends('coop_id')
    def _compute_coop_number(self):
        """Toma el número del galpón o, si todavía no tiene, lo sugiere desde su código
        (G1 → 1). Una vez creadas las jaulas no se cambia: está en sus etiquetas."""
        for wizard in self:
            coop = wizard.coop_id
            match = re.search(r'(\d+)\s*$', coop.code or '')
            wizard.coop_number = coop.cage_number or (int(match.group(1)) if match else 0)

    @api.depends('coop_id')
    def _compute_coop_number_locked(self):
        for wizard in self:
            wizard.coop_number_locked = bool(wizard.coop_id
                                             and wizard.coop_id._poultry_numbered_cages())

    def _poultry_ranges(self):
        """Rango de cada variable, en el orden del código y por campo de la jaula."""
        self.ensure_one()
        return {
            'row_no': range(self.row_from, self.row_to + 1),
            'side_no': range(self.side_from, self.side_to + 1),
            'bay_no': range(self.bay_from, self.bay_to + 1),
            'floor_no': range(self.floor_from, self.floor_to + 1),
            'cage_no': range(self.cage_from, self.cage_to + 1),
        }

    def _poultry_compose_code(self, numbers):
        return self.env['poultry.cage']._poultry_compose_code(self.coop_number, *numbers)

    def _poultry_existing_cages(self):
        """Jaulas del galpón por código, archivadas incluidas. El código manda porque
        también hay jaulas cargadas a mano, sin Fila ni Claro."""
        self.ensure_one()
        cages = self.env['poultry.cage'].with_context(active_test=False).search_fetch(
            [('coop_id', '=', self.coop_id.id)], ['code', 'row_no'])
        return {cage.code: cage for cage in cages}

    @api.depends('coop_id', 'coop_number', 'row_from', 'row_to', 'side_from', 'side_to',
                 'bay_from', 'bay_to', 'floor_from', 'floor_to', 'cage_from', 'cage_to')
    def _compute_preview(self):
        for wizard in self:
            ranges = wizard._poultry_ranges()
            total = math.prod(len(numbers) for numbers in ranges.values())
            existing = 0
            if total and wizard.coop_id:
                cages = wizard._poultry_existing_cages()
                existing = sum(wizard._poultry_compose_code(numbers) in cages
                               for numbers in product(*ranges.values()))
            wizard.total_count = total
            wizard.existing_count = existing
            wizard.new_count = total - existing
            wizard.first_code = wizard._poultry_compose_code(
                numbers[0] for numbers in ranges.values()) if total else False
            wizard.last_code = wizard._poultry_compose_code(
                numbers[-1] for numbers in ranges.values()) if total else False

    def action_generate(self):
        """Crea las jaulas del rango que falten, así el mismo wizard sirve para ampliar
        un galpón después. Las archivadas cuentan como existentes: no se recrean. Una
        cargada a mano con un código del rango es esa jaula: se le completa la ubicación."""
        self.ensure_one()
        if self.coop_number <= 0:
            raise ValidationError('Indicá el Número de Galpón.')
        ranges = self._poultry_ranges()
        if any(numbers.start < 1 or not numbers for numbers in ranges.values()):
            raise ValidationError(
                'Cada variable debe empezar en 1 o más, y su Hasta no puede ser menor '
                'que su Desde.')
        self.coop_id.cage_number = self.coop_number
        existing = self._poultry_existing_cages()
        vals_list = []
        for numbers in product(*ranges.values()):
            code = self._poultry_compose_code(numbers)
            location = dict(zip(ranges, numbers))
            cage = existing.get(code)
            if not cage:
                vals_list.append({
                    'coop_id': self.coop_id.id,
                    'code': code,
                    'name': code,
                    **location,
                })
            elif not cage.row_no:
                cage.write(location)
        if not vals_list:
            raise ValidationError('Todas las jaulas de este rango ya existen.')
        self.env['poultry.cage'].create(vals_list)
        return self.coop_id.action_view_cages()
