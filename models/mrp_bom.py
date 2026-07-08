# -*- coding: utf-8 -*-

from odoo import models, fields, api
from odoo.exceptions import ValidationError


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    use_for_egg_production = fields.Boolean(
        string='Usar para OF de Gestión Avícola',
        default=False,
        help='Si está activo, esta es la Lista de Materiales que el módulo de '
             'Gestión Avícola usará al generar las Órdenes de Fabricación al '
             'procesar el parte de producción. Aplica al producto/variante de la '
             'BOM. Si no hay ninguna marcada, se usa la primera BOM activa.'
    )

    # Auxiliar para mostrar el checkbox solo en productos de producción de huevos.
    product_is_egg_production = fields.Boolean(
        related='product_tmpl_id.is_egg_production',
        readonly=True,
    )

    @api.constrains('use_for_egg_production', 'product_id', 'product_tmpl_id')
    def _check_single_egg_production_bom(self):
        """Una sola BOM marcada por alcance: misma variante, o mismo producto base
        cuando no hay variante específica."""
        for bom in self.filtered('use_for_egg_production'):
            domain = [
                ('use_for_egg_production', '=', True),
                ('product_tmpl_id', '=', bom.product_tmpl_id.id),
                ('id', '!=', bom.id),
            ]
            if bom.product_id:
                domain.append(('product_id', '=', bom.product_id.id))
            else:
                domain.append(('product_id', '=', False))
            if self.search_count(domain):
                scope = bom.product_id.display_name if bom.product_id else bom.product_tmpl_id.display_name
                raise ValidationError(
                    f'Ya existe una Lista de Materiales marcada para Gestión Avícola '
                    f'para "{scope}". Solo puede haber una.'
                )
