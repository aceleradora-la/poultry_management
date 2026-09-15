# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Congela el Tipo de Consumo Avícola en los movimientos existentes que hoy
    tienen una línea de Lista de Materiales marcada como Alimento/Agua. Así, si más
    adelante se cambia el componente de alimento en la Lista, el consumo ya
    calculado de las OFs pasadas queda protegido.

    Los movimientos cuya línea de Lista NO está marcada (histórico previo a marcar
    esas Listas) quedan sin congelar a propósito: se resuelven contra la Lista en
    vivo la próxima vez que se recalcule (y ahí se congelan). Para recuperarlos,
    marcar el Tipo de Consumo en las Listas de Materiales históricas y volver a
    correr 'Recalcular Indicadores de Producción'."""
    cr.execute("""
        UPDATE stock_move m
           SET poultry_consumption_type = l.poultry_consumption_type
          FROM mrp_bom_line l
         WHERE m.bom_line_id = l.id
           AND m.poultry_consumption_type IS NULL
           AND l.poultry_consumption_type IN ('feed', 'water')
    """)
    _logger.info('Poultry: Tipo de Consumo congelado en %s movimientos.', cr.rowcount)
