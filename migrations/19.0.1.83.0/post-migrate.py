# -*- coding: utf-8 -*-
"""Dos cosas, ambas idempotentes:

1) Deja el marcador 'poultry_management.week_numbering_1based' en las bases que ya
   renumeraron antes de que ese marcador existiera: por migrations/19.0.1.33.0, o
   por su gemela 18.0.1.46.0 cuando todavía eran 18.0. Sin él, al actualizar una
   base de 18.0 a 19.0, la 19.0.1.33.0 vuelve a sumar 1 a todas las Semanas de
   Vida (ver el comentario en 19.0.1.33.0).

2) Repara las filas semanales que hayan quedado corridas por ese doble corrimiento:
   la Semana de Vida de cada fila se rederiva desde su propia fecha (Fecha del
   Dato en las manuales, Hasta en las del sistema), que la migración original
   nunca tocó y por eso sigue siendo la verdad. Si el dato ya está bien, no
   cambia nada, así que puede correr en cada rebuild sin riesgo.

   Colisiones al mover una fila a su semana correcta:
   - si la que estorba es del SISTEMA, se borra (el recálculo la regenera);
   - si la que se mueve es del SISTEMA y estorba una manual, se borra la que se
     mueve (la manual tiene prioridad por diseño);
   - si las dos son MANUALES es un error de carga: se deja como está y se avisa
     en el log, nunca se pisa un dato cargado a mano."""
import logging

from odoo import api, SUPERUSER_ID

_logger = logging.getLogger(__name__)

WEEK_NUMBERING_MARKER = 'poultry_management.week_numbering_1based'


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    env['ir.config_parameter'].sudo().set_param(WEEK_NUMBERING_MARKER, 'True')
    _repair_shifted_weeks(env)


def _repair_shifted_weeks(env):
    Weekly = env['poultry.batch.indicator.weekly.value'].sudo()
    # Ascendente por semana: al mover una fila a la semana anterior se libera el
    # lugar que necesita la siguiente. Se itera por ids y se rebrowsea porque el
    # bucle puede borrar registros.
    ids = Weekly.search([], order='batch_id, indicator_id, week').ids
    moved = deleted = skipped = 0
    for row_id in ids:
        row = Weekly.browse(row_id).exists()
        if not row:
            continue
        batch = row.batch_id
        reference = row.manual_date or row.week_date_to
        if not reference or not batch.birth_date:
            continue
        expected = batch._poultry_week_of(reference)
        if not expected or expected == row.week:
            continue
        clash = Weekly.search([
            ('batch_id', '=', batch.id),
            ('indicator_id', '=', row.indicator_id.id),
            ('week', '=', expected),
            ('id', '!=', row.id),
        ], limit=1)
        if clash:
            if row.source == 'system':
                row.unlink()
                deleted += 1
                continue
            if clash.source == 'system':
                clash.unlink()
                deleted += 1
            else:
                skipped += 1
                _logger.warning(
                    'Poultry: %s / %s: dos valores MANUALES caen en la semana %s '
                    '(ids %s y %s); se deja como está, revisar la carga.',
                    batch.display_name, row.indicator_id.display_name, expected,
                    row.id, clash.id)
                continue
        rearing_end = batch.genetics_id.rearing_end_week or 17
        row.write({
            'week': expected,
            'period': 'crianza' if expected <= rearing_end else 'produccion',
        })
        moved += 1
    _logger.info(
        'Poultry: reparación de Semanas de Vida: %s filas movidas, %s del sistema '
        'borradas (las regenera el recálculo), %s conflictos manuales sin tocar.',
        moved, deleted, skipped)
