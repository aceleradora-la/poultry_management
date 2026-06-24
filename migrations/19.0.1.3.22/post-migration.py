# -*- coding: utf-8 -*-
"""Migración Odoo 19: el sistema de UdM dejó de usar category_id + ratio==1.0 y pasó a
una jerarquía relative_uom_id donde la unidad raíz (sin relative_uom_id, factor=1.0) es la
referencia. Antes existía el flag `is_poultry_egg`; ahora el "Huevo" es implícitamente la
raíz de la familia.

Este script:
  1. Verifica que cada familia de UdM avícola (use_in_poultry) tenga una raíz coherente
     (factor == 1.0). Solo registra advertencias en el log; no fuerza cambios destructivos
     porque la configuración de la jerarquía la define el usuario.
  2. Fuerza el recálculo de los campos almacenados que dependían del antiguo `ratio` y ahora
     dependen de `factor`: uom_ratio, total_eggs_gross, total_produced_reference y las
     conversiones de stock.move (quantity_huevos / quantity_cajones).
"""

import logging

_logger = logging.getLogger(__name__)


def _verify_poultry_roots(env):
    Uom = env['uom.uom'].sudo()
    poultry_uoms = Uom.search([('use_in_poultry', '=', True), ('active', '=', True)])
    if not poultry_uoms:
        _logger.info('Poultry: no hay UdM marcadas use_in_poultry; nada que verificar.')
        return

    roots = set()
    for uom in poultry_uoms:
        root = uom._poultry_root_uom()
        roots.add(root.id)
        if root.factor and abs(root.factor - 1.0) > 1e-9:
            _logger.warning(
                'Poultry: la raíz "%s" (id=%s) de la familia de "%s" tiene factor=%s '
                '(se esperaba 1.0). Revise la jerarquía relative_uom_id.',
                root.display_name, root.id, uom.display_name, root.factor,
            )

    for root_id in roots:
        root = Uom.browse(root_id)
        if not root.use_in_poultry:
            _logger.warning(
                'Poultry: la raíz "%s" (id=%s) de una familia avícola no está marcada '
                'use_in_poultry. Verifique que el "Huevo" sea la unidad de referencia.',
                root.display_name, root.id,
            )
    _logger.info('Poultry: verificación de raíces de UdM avícolas completada (%s familias).',
                 len(roots))


def _recompute_stored_factor_fields(env):
    # Líneas de recolección: total_eggs_gross + total_produced_reference (vía _compute_production).
    Line = env['poultry.egg.collection.line'].sudo()
    lines = Line.search([])
    if lines:
        lines._compute_total_eggs_gross()
        lines._compute_production()
        _logger.info('Poultry: recalculadas %s líneas de recolección.', len(lines))

    # uom_ratio (related store de uom_id.factor): refrescar por las dudas.
    LineUom = env['poultry.egg.collection.line.uom'].sudo()
    line_uoms = LineUom.search([])
    if line_uoms:
        line_uoms.modified(['uom_id'])
        env.flush_all()
        _logger.info('Poultry: refrescados %s valores de UdM por línea.', len(line_uoms))

    # Conversiones de stock.move (quantity_huevos / quantity_cajones) de productos huevo.
    Move = env['stock.move'].sudo()
    moves = Move.search([('product_id.product_tmpl_id.is_egg_production', '=', True)])
    if moves:
        moves._compute_poultry_quantities()
        _logger.info('Poultry: recalculados %s movimientos de stock de huevo.', len(moves))


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    _logger.info('Poultry: post-migración %s (verificación raíces UdM + recálculo factor).', version)
    _verify_poultry_roots(env)
    _recompute_stored_factor_fields(env)
    _logger.info('Poultry: post-migración %s completada.', version)
