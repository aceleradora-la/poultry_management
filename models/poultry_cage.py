# -*- coding: utf-8 -*-

from odoo import models, fields


class PoultryCage(models.Model):
    _name = 'poultry.cage'
    _description = 'Jaula de Muestreo de Peso'
    _order = 'coop_id, sequence, code'

    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', required=True, copy=False,
                       help='Identificador corto pintado en la jaula, para ubicarla '
                            'rápido al momento de la pesada.')
    coop_id = fields.Many2one('poultry.coop', string='Galpón', required=True,
                              index=True, ondelete='restrict',
                              domain="[('active', '=', True)]")
    sequence = fields.Integer(string='Secuencia', default=10,
                              help='Orden de carga en el Parte de Registro de Peso.')
    active = fields.Boolean(string='Activo', default=True,
                            help='Desactivar cuando la jaula queda definitivamente vacía '
                                 'o deja de usarse como muestra. Los partes históricos '
                                 'siguen mostrándola.')
    notes = fields.Text(string='Notas')

    _sql_constraints = [
        ('unique_coop_code', 'unique(coop_id, code)',
         'Ya existe una jaula con este código en el galpón.'),
    ]
