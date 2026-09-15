# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Completa "Cómo se calcula" en los indicadores existentes según lo que ya
    tenían: con fórmula cargada quedan en Fórmula configurable, sin fórmula en
    Cálculo interno del sistema.

    El campo solo gobierna qué se muestra y se completa en el formulario; el motor
    sigue decidiendo por el Modo de Cálculo, así que este backfill no cambia
    ningún valor calculado."""
    cr.execute("""
        UPDATE poultry_indicator
           SET calculation_source = CASE
                   WHEN formula_mode IS NOT NULL AND formula_mode != '' THEN 'formula'
                   ELSE 'legacy'
               END
         WHERE calculation_source IS NULL
            OR calculation_source = ''
    """)
    cr.execute("SELECT calculation_source, count(*) FROM poultry_indicator GROUP BY 1")
    resumen = ', '.join(f'{fuente or "sin definir"}: {cantidad}'
                        for fuente, cantidad in cr.fetchall())
    _logger.info('Poultry: "Cómo se calcula" completado en los indicadores (%s).', resumen)
