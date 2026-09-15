# -*- coding: utf-8 -*-
"""Limpia los datos de poultry.genetics.standard antes del rediseño del modelo.

El modelo pasa de un esquema plano (semana + standard_type + standard_value)
a un esquema con indicador, versión, período y rango Bajo/Alto. No existe una
correspondencia automática válida entre ambos esquemas (requiere criterio
humano para asignar indicador/versión), por lo que se eliminan los registros
existentes -pérdida de datos ya acordada con el usuario- para que _auto_init
recree la tabla limpia con las nuevas columnas NOT NULL (version_id,
indicator_id, period) sin fallar por filas huérfanas.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    # Solo borrar si la tabla todavía tiene el ESQUEMA VIEJO (columna
    # standard_type). Si la tabla ya está en el esquema nuevo (version_id/
    # indicator_id), los datos son estándares importados válidos y NO deben
    # tocarse: este caso se da cuando la versión instalada del módulo quedó
    # desincronizada del esquema real (ej. un rebuild de staging desde una
    # producción con número de versión viejo pero datos nuevos).
    cr.execute("""
        SELECT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'poultry_genetics_standard'
              AND column_name = 'standard_type'
        )
    """)
    if cr.fetchone()[0]:
        cr.execute("DELETE FROM poultry_genetics_standard")
        _logger.info('Poultry: se eliminaron los estándares de genética existentes '
                     '(esquema anterior incompatible con el nuevo modelo).')
    else:
        _logger.info('Poultry: estándares ya en el esquema nuevo, no se borra nada.')
