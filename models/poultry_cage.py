# -*- coding: utf-8 -*-

import base64

from odoo import models, fields, api


class PoultryCage(models.Model):
    _name = 'poultry.cage'
    _description = 'Jaula'
    _order = 'coop_id, sequence, row_no, side_no, bay_no, floor_no, cage_no, code'
    _rec_names_search = ['name', 'code']

    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', required=True, copy=False,
                       help='Galpón.Fila.Lado.Claro.Piso.Jaula (ej: 1.1.2.32.3.4). Es lo que '
                            'lleva el QR de la etiqueta, por eso no cambia una vez creada.')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              index=True, ondelete='restrict',
                              domain="[('active', '=', True)]")
    # Ubicación física de la jaula. Los carga el wizard Crear Jaulas y definen el
    # código. En cero solo quedan las jaulas anteriores a esta numeración.
    row_no = fields.Integer(string='Fila', readonly=True, aggregator=None)
    side_no = fields.Integer(string='Lado', readonly=True, aggregator=None)
    bay_no = fields.Integer(string='Claro', readonly=True, aggregator=None)
    floor_no = fields.Integer(string='Piso', readonly=True, aggregator=None)
    cage_no = fields.Integer(string='Jaula', readonly=True, aggregator=None)
    is_sampling = fields.Boolean(string='Muestreo', default=False, index=True,
                                 help='Jaula elegida para pesar en el Parte de Registro de '
                                      'Peso. Cambiar la marca no afecta a los partes ya '
                                      'cargados.')
    sequence = fields.Integer(string='Secuencia', default=10,
                              help='Orden de carga en el Parte de Registro de Peso.')
    active = fields.Boolean(string='Activo', default=True,
                            help='Desactivar cuando la jaula deja de existir en el galpón. '
                                 'Los partes históricos siguen mostrándola.')
    notes = fields.Text(string='Notas')

    _unique_coop_code = models.Constraint(
        'UNIQUE(coop_id, code)',
        'Ya existe una jaula con este código en el galpón.')

    @api.model
    def _poultry_compose_code(self, coop_number, row, side, bay, floor, cage):
        """Código de la jaula: Galpón.Fila.Lado.Claro.Piso.Jaula."""
        return '.'.join(str(part) for part in (coop_number, row, side, bay, floor, cage))

    def _poultry_qr_src(self):
        """QR del código como data URI. Va embebido para que imprimir un galpón entero
        no dispare una request de imagen por cada etiqueta. Nivel Q de corrección:
        la etiqueta tiene que seguir leyéndose con polvo y desgaste."""
        self.ensure_one()
        png = self.env['ir.actions.report'].barcode(
            'QR', self.code, width=300, height=300, barLevel='Q')
        return 'data:image/png;base64,%s' % base64.b64encode(png).decode()

    def _poultry_open_wizard(self, name, res_model):
        """Abre un wizard de jaulas con el galpón de la pantalla o de la selección."""
        coop_id = self.env.context.get('default_coop_id') or self.coop_id[:1].id
        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': res_model,
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_coop_id': coop_id},
        }

    def action_open_generate_wizard(self):
        return self._poultry_open_wizard('Crear Jaulas', 'poultry.cage.generate.wizard')

    def action_open_sampling_wizard(self):
        return self._poultry_open_wizard('Elegir Jaulas de Muestreo',
                                         'poultry.cage.sampling.wizard')
