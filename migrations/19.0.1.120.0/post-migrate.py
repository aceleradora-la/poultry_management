# -*- coding: utf-8 -*-
"""Adelanta las secuencias de data/ir_sequence_data.xml más allá del último número usado.

Hasta 19.0.1.119.0 ese archivo no era noupdate y fijaba number_next = 1, así que cada
actualización del módulo reiniciaba la numeración y los registros nuevos repetían nombres
(en jeica, al 2026-11-12: 344 repetidos en mortandad y 8 en movimientos). El archivo ya no
se recarga; esto deja cada secuencia apuntando al número siguiente al más alto en uso.
Idempotente: solo adelanta, nunca hace retroceder una secuencia."""
import logging
import re

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

# Secuencia -> (modelo, campo que numera). Los Cierres y los Partes de Peso numeran con
# secuencias propias de cada galpón, creadas por código, que nunca se reiniciaron.
SEQUENCES = {
    'sequence_poultry_coop': ('poultry.coop', 'code'),
    'sequence_poultry_batch': ('poultry.batch', 'code'),
    'sequence_poultry_egg_collection': ('poultry.egg.collection', 'name'),
    'sequence_poultry_mortality': ('poultry.mortality', 'name'),
    'sequence_poultry_vaccination': ('poultry.vaccination', 'name'),
    'sequence_poultry_batch_movement': ('poultry.batch.movement', 'name'),
}


def migrate(cr, version):
    if not version:
        return
    env = api.Environment(cr, SUPERUSER_ID, {'active_test': False})
    for xmlid, (model_name, field_name) in SEQUENCES.items():
        sequence = env.ref(f'poultry_management.{xmlid}', raise_if_not_found=False)
        if not sequence or model_name not in env:
            continue
        prefix, suffix = sequence._get_prefix_suffix()
        pattern = re.compile(r'^%s(\d+)%s$' % (re.escape(prefix), re.escape(suffix)))
        values = env[model_name].search([(field_name, '=like', prefix + '%')]).mapped(field_name)
        numbers = [int(match.group(1)) for match in map(pattern.match, filter(None, values)) if match]
        if not numbers:
            continue
        target = max(numbers) + sequence.number_increment
        current = sequence.number_next_actual
        if target > current:
            sequence.write({'number_next': target})
            _logger.info('Poultry: secuencia %s adelantada de %s a %s (número más alto en uso: %s).',
                         sequence.code, current, target, max(numbers))
