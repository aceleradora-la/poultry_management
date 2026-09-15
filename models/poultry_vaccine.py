# -*- coding: utf-8 -*-

from odoo import models, fields

# Vías de aplicación de vacunas. Definidas una sola vez acá y reusadas por las líneas
# de plan y los registros de aplicación, para que las tres selecciones nunca diverjan.
VACCINE_ROUTES = [
    ('drinking_water', 'Agua de Bebida'),
    ('spray', 'Aspersión'),
    ('eye_drop', 'Gota Ocular'),
    ('nasal', 'Nasal'),
    ('subcutaneous', 'Subcutánea'),
    ('intramuscular', 'Intramuscular'),
    ('wing_web', 'Punción Alar'),
    ('oral', 'Oral'),
]


class PoultryVaccine(models.Model):
    _name = 'poultry.vaccine'
    _description = 'Vacuna Avícola'
    _order = 'name'

    name = fields.Char(string='Nombre', required=True, index=True)
    code = fields.Char(string='Código', copy=False)
    disease = fields.Char(string='Enfermedad que Previene')
    default_route = fields.Selection(VACCINE_ROUTES, string='Vía de Aplicación Habitual')
    default_dose = fields.Char(string='Dosis Sugerida',
                               help='Texto libre, ej: "0,5 ml/ave" o "1 dosis en agua de bebida".')
    laboratory = fields.Char(string='Laboratorio Habitual')
    active = fields.Boolean(string='Activo', default=True)
    notes = fields.Text(string='Notas')
