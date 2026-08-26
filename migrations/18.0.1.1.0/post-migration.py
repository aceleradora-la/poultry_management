# -*- coding: utf-8 -*-
"""
Migración: Recalcular quantity_huevos y quantity_cajones en stock.move existentes.

Se ejecuta al actualizar de 18.0.1.1.0 a 18.0.1.2.0.
Recalcula los campos computados almacenados para movimientos de productos avícolas.
"""
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    _logger.info("Poultry: Recalculando quantity_huevos y quantity_cajones en stock.move...")

    env = api.Environment(cr, SUPERUSER_ID, {})

    StockMove = env['stock.move']
    domain = [('product_id.product_tmpl_id.is_egg_production', '=', True)]

    # Procesar en lotes para evitar problemas de memoria
    batch_size = 500
    offset = 0
    total_processed = 0

    while True:
        moves = StockMove.search(domain, limit=batch_size, offset=offset)
        if not moves:
            break

        # Acceder a los campos computados dispara el recálculo y almacenamiento
        _ = list(moves.mapped('quantity_huevos'))
        _ = list(moves.mapped('quantity_cajones'))

        total_processed += len(moves)
        offset += batch_size

        env.cr.commit()
        _logger.info("Poultry: Procesados %d movimientos...", total_processed)

    _logger.info("Poultry: Migración completada. Total: %d movimientos recalculados.", total_processed)
