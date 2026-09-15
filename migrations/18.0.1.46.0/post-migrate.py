# -*- coding: utf-8 -*-
"""Semana de Vida pasa a numerarse desde 1 (los días 0-6 de vida son la Semana 1,
como en las guías de genética), en vez de desde 0.

- poultry_batch_indicator_weekly_value.week: +1 a TODAS las filas (las del sistema
  se calculaban 0-based; las manuales cargadas por fecha también). Las fechas
  Desde/Hasta de cada fila no cambian (mismo rango calendario, nueva etiqueta).
  Se corrige también el Período de cada fila (una semana que era la última de
  crianza 0-based puede pasar a ser la primera de producción 1-based).
- poultry.genetics.standard.week NO se toca: los estándares se importaron de la
  guía Hy-Line, que ya numera 1-based (crianza 1-17, producción 18+). Este cambio
  ALINEA los valores reales con esos estándares (antes había un corrimiento de
  una semana).
- Las Semanas de Vida de las líneas de Plan de Vacunación NO se tocan: las carga
  el usuario pensando 1-based; la vista de cumplimiento ahora las interpreta así.
- batch_age_weeks (Mortandad, Vacunación, Parte de Peso): recomputado con la
  nueva fórmula.
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    # Corrimiento +1 en dos pasos (negativo y de vuelta) para no chocar
    # transitoriamente con la restricción unique(batch, indicator, week).
    cr.execute("UPDATE poultry_batch_indicator_weekly_value SET week = -(week + 1)")
    cr.execute("UPDATE poultry_batch_indicator_weekly_value SET week = -week")

    env = api.Environment(cr, SUPERUSER_ID, {})

    # Período según la nueva numeración (crianza hasta rearing_end_week inclusive).
    weeklies = env['poultry.batch.indicator.weekly.value'].search([])
    for weekly in weeklies:
        rearing_end = weekly.batch_id.genetics_id.rearing_end_week or 17
        period = 'crianza' if weekly.week <= rearing_end else 'produccion'
        if weekly.period != period:
            weekly.period = period
    # display_name almacenado incluye la semana; el UPDATE por SQL no disparó el compute.
    weeklies._compute_display_name()

    # Edades almacenadas recalculadas con la nueva fórmula (días // 7 + 1).
    for model in ('poultry.mortality', 'poultry.vaccination', 'poultry.weight.record'):
        if model in env:
            records = env[model].with_context(active_test=False).search([])
            if records and 'batch_age_weeks' in records._fields:
                records._compute_batch_age()
