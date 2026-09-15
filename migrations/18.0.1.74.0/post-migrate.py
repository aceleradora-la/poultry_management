# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Deja explícita la Agregación Semanal de los indicadores de CANTIDAD que ya
    existían: la cantidad de aves muertas se sumaba por un caso especial cableado
    a su categoría ('mortality_count'), y ahora eso se declara en el indicador.

    El caso especial sigue en el código por compatibilidad, pero con este backfill
    los indicadores existentes dejan de depender de él. Los demás quedan en
    'auto' (el default), que reproduce exactamente la agregación de siempre: las
    tasas como suma(numerador)/suma(denominador) y los acumulados como último
    valor del período. No cambia ningún número."""
    cr.execute("""
        UPDATE poultry_indicator
           SET weekly_aggregation = 'sum'
         WHERE category = 'mortality_count'
           AND (weekly_aggregation IS NULL OR weekly_aggregation = 'auto')
    """)
    updated = cr.rowcount
    cr.execute("""
        UPDATE poultry_indicator
           SET weekly_aggregation = 'auto'
         WHERE weekly_aggregation IS NULL
    """)
    _logger.info(
        'Poultry: Agregación Semanal = Suma en %s indicadores de cantidad; el resto en '
        'Automática (sin cambios de valor).', updated)
