# -*- coding: utf-8 -*-
"""Auto-marca la unidad Huevo (is_poultry_egg) en cada categoría avícola.

Hasta ahora la unidad de referencia (Huevo) se infería por ratio == 1.0.
Con el nuevo campo explícito is_poultry_egg, marcamos automáticamente la
unidad de referencia de cada categoría que tenga unidades usadas en Gestión
Avícola, para no requerir marcado manual en bases existentes.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Uom = env['uom.uom'].sudo()

    # Categorías que tienen al menos una UdM usada en Gestión Avícola.
    poultry_uoms = Uom.search([('use_in_poultry', '=', True)])
    categories = poultry_uoms.mapped('category_id')

    marked = 0
    for category in categories:
        # Si ya hay una marcada en la categoría, respetarla.
        existing = Uom.search([
            ('category_id', '=', category.id),
            ('is_poultry_egg', '=', True),
        ], limit=1)
        if existing:
            continue

        # La unidad de referencia de la categoría es la de ratio == 1.0 (el Huevo).
        cat_uoms = Uom.search([('category_id', '=', category.id)])
        reference = cat_uoms.filtered(lambda u: u.ratio == 1.0)
        if reference:
            reference[0].is_poultry_egg = True
            marked += 1
            _logger.info(
                'Poultry: marcada "%s" como Huevo en categoría "%s".',
                reference[0].name, category.display_name,
            )
        else:
            _logger.warning(
                'Poultry: no se encontró unidad de referencia (ratio=1.0) en la '
                'categoría "%s"; márquela manualmente como Huevo.',
                category.display_name,
            )

    _logger.info('Poultry: %s unidades marcadas como Huevo.', marked)
