# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """Crea el indicador UNIFORMIDAD (%) (pedido del usuario del 2026-11-12) si la base
    no tiene uno, y publica sus valores desde los Partes de Peso confirmados."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['poultry.indicator']._poultry_ensure_uniformity_indicator()
