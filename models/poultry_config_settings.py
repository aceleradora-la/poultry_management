# -*- coding: utf-8 -*-

from odoo import models, fields, api


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    # El campo poultry_unclassified_egg_product_id fue movido a poultry.coop
    # para permitir configuración por galpón en lugar de global

