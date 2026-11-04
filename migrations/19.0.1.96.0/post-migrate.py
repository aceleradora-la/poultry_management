# -*- coding: utf-8 -*-
"""Jaulas del galpón (19.0.1.96.0).

poultry.cage pasa de ser la lista de jaulas de muestreo a ser el maestro de todas las
jaulas, y la muestra queda indicada con la marca is_sampling. Las jaulas activas que
ya existían eran las de muestreo, así que se marcan para que el Parte de Peso las siga
ofreciendo. Las archivadas ya habían dejado de usarse como muestra: quedan sin marca.
"""


def migrate(cr, version):
    if version:
        cr.execute("UPDATE poultry_cage SET is_sampling = TRUE WHERE active")
