# -*- coding: utf-8 -*-
"""
Migración: Recalcular quantity_huevos y quantity_cajones con signo (entrada/salida).

Se ejecuta al actualizar de 18.0.1.2.0 a 18.0.1.3.0.
Aplica la lógica de signo según dirección del movimiento para totalizar correctamente.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    _logger.info("Poultry: Recalculando quantity_huevos y quantity_cajones con signo...")

    env = api.Environment(cr, SUPERUSER_ID, {})

    StockMove = env['stock.move']
    domain = [('product_id.product_tmpl_id.is_egg_production', '=', True)]

    batch_size = 500
    offset = 0
    total_processed = 0

    while True:
        moves = StockMove.search(domain, limit=batch_size, offset=offset)
        if not moves:
            break

        _ = list(moves.mapped('quantity_huevos'))
        _ = list(moves.mapped('quantity_cajones'))

        total_processed += len(moves)
        offset += batch_size

        env.cr.commit()
        _logger.info("Poultry: Procesados %d movimientos...", total_processed)

    _logger.info("Poultry: Migración completada. Total: %d movimientos recalculados.", total_processed)
