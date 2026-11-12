# -*- coding: utf-8 -*-
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    """El plan de pesaje de ejemplo pasa a llamarse "Plan Estándar" (pedido del usuario del
    2026-11-12). Es un dato noupdate: sin esto, las bases que ya lo tenían conservan el
    nombre viejo. Solo se renombra si nadie le cambió el nombre."""
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {})
    plan = env.ref('poultry_management.weight_plan_layers', raise_if_not_found=False)
    if plan and plan.name == 'Ponedoras estándar':
        plan.name = 'Plan Estándar'
