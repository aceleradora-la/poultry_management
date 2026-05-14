# -*- coding: utf-8 -*-
"""Tras el cambio de umbrales y campos almacenados del semáforo, forzar un recálculo."""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    from odoo import api, SUPERUSER_ID

    env = api.Environment(cr, SUPERUSER_ID, {})
    Product = env['product.product'].sudo()
    domain = [('is_storable', '=', True), ('active', '=', True)]
    total = Product.search_count(domain)
    _logger.info('Poultry: recalculando cobertura de stock en %s variantes almacenables...', total)
    batch = 2000
    offset = 0
    while True:
        chunk = Product.search(domain, limit=batch, offset=offset)
        if not chunk:
            break
        chunk._compute_poultry_cover_metrics()
        offset += batch
    _logger.info('Poultry: recálculo de cobertura completado.')
