# -*- coding: utf-8 -*-

from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class UomUom(models.Model):
    _inherit = 'uom.uom'

    use_in_poultry = fields.Boolean(
        string='Usar en Gestión Avícola',
        default=False,
        help='Indica si esta unidad de medida se utiliza en el módulo de Gestión Avícola para el parte de producción'
    )
    
    display_name_poultry = fields.Char(
        string='Nombre para Parte de Producción',
        help='Nombre que se mostrará en las columnas del parte de producción. Si está vacío, se usará el nombre de la unidad de medida.'
    )
    
    @api.depends('use_in_poultry', 'display_name_poultry', 'name')
    def _compute_poultry_display_name(self):
        """Calcula el nombre a mostrar en el parte de producción"""
        for uom in self:
            if uom.display_name_poultry:
                uom.poultry_display_name = uom.display_name_poultry
                _logger.debug("UoM %s (%s): Usando display_name_poultry=%s", uom.id, uom.name, uom.poultry_display_name)
            else:
                uom.poultry_display_name = uom.name
                _logger.debug("UoM %s (%s): Usando name=%s", uom.id, uom.name, uom.poultry_display_name)
    
    poultry_display_name = fields.Char(
        string='Nombre Mostrar',
        compute='_compute_poultry_display_name',
        store=True,
        help='Nombre que se mostrará en el parte de producción'
    )

    def _poultry_root_uom(self):
        """Raíz de la jerarquía relative_uom_id (Odoo 19 reemplaza category_id).

        La unidad raíz no tiene relative_uom_id y su factor es 1.0; cumple el rol
        que en Odoo <=18 tenía la unidad con ratio == 1.0 dentro de la categoría.
        """
        self.ensure_one()
        uom = self
        while uom.relative_uom_id:
            uom = uom.relative_uom_id
        return uom

    def _has_common_reference(self, other):
        """True si ambas UdM pertenecen a la misma familia (comparten unidad raíz).

        Sustituye en Odoo 19 a la comparación por category_id: dos unidades son
        convertibles entre sí si comparten la misma raíz de relative_uom_id.
        """
        self.ensure_one()
        if not other:
            return False
        return self._poultry_root_uom() == other._poultry_root_uom()

