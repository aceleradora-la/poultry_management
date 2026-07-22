# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    # False / vacío = heredar de la categoría. Al borrar el campo en formulario Odoo guarda 0 → se normaliza a False.
    poultry_cover_window_days = fields.Float(
        string='Días ventana consumo',
        digits=(16, 1),
        default=False,
        help='Días calendario cerrados (TZ compañía) para consumo: día (hoy−N) 00:00 a ayer 23:59, '
             'sin hoy. Dejar vacío para usar la categoría.',
    )

    is_egg_production = fields.Boolean(
        string='Usar en Producción de Huevos',
        default=False,
        help='Marque este campo si este producto se utiliza en el proceso de producción de huevos.'
    )

    poultry_validate_kit_consumption = fields.Boolean(
        string='Mix Producto Avicola',
        default=False,
        help=(
            'Si está activo, al finalizar una Orden de Fabricación se valida que la suma de las '
            'cantidades consumidas de sus componentes (convertidas a la UdM del producto final) '
            'sea igual a la cantidad producida.'
        ),
    )

    poultry_consumption_type = fields.Selection([
        ('feed', 'Alimento'),
        ('water', 'Agua'),
    ], string='Tipo de Consumo Avícola',
        help='Marca este producto como Alimento o Agua para el cálculo de consumo '
             '(g/ave-día, ml/ave-día). Es la fuente estable del tipo: un producto de '
             'alimento balanceado es Alimento sin importar en qué Lista de Materiales '
             'se consuma. Se usa como respaldo cuando la línea de la Lista no define '
             'un tipo, y permite reconocer OFs históricas cuyo componente de alimento '
             'ya no es el actual, sin editar las líneas a mano.')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('poultry_cover_window_days') in (0, 0.0):
                vals['poultry_cover_window_days'] = False
        return super().create(vals_list)

    def write(self, vals):
        if vals.get('poultry_cover_window_days') in (0, 0.0):
            vals['poultry_cover_window_days'] = False
        return super().write(vals)

    @api.constrains('poultry_cover_window_days')
    def _check_poultry_cover_window(self):
        for tmpl in self:
            w = tmpl.poultry_cover_window_days
            if w is not False and w is not None and w < 0:
                raise ValidationError('Los días de ventana de consumo no pueden ser negativos.')

    def _poultry_effective_cover_window_days(self):
        self.ensure_one()
        categ = self.categ_id
        w_prod = self.poultry_cover_window_days
        if w_prod not in (False, None) and float(w_prod) > 0:
            w = float(w_prod)
        else:
            w = categ.poultry_cover_window_days
        w = float(w or 7.0)
        return max(w, 1.0)
