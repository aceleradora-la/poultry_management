# Gestión Avícola (poultry_management) para Odoo 19

Módulo de aceleradora para gestionar granjas de postura sobre Odoo. Integra la operación diaria con Inventario, Manufactura, Compras y Contabilidad.

Desarrollo a medida. Más información en https://aceleradora.la

## Funcionalidades

### Producción

- **Galpones y lotes.** Capacidad, ocupación, lotes por genética, asignaciones y movimientos de aves (ingreso, traslado y retiro).
- **Partes de producción.** Conteo inicial, bruto y final por calibre y envase, en cajones (360 huevos), maples (30 huevos) y huevos. Lo producido sale de la diferencia y entra al inventario con órdenes de fabricación.
- **Cierre de galpón.** Reúne los partes del día en la orden de huevo sin clasificar, con consumo de alimento y agua y mortandad.
- **Alimento balanceado.** Lista de materiales activa por galpón, con historial y carga automática en las órdenes de fabricación.

### Indicadores

- **Valores reales por lote.** Mortandad, viabilidad, peso corporal, uniformidad, consumo de alimento y agua, postura, masa y peso del huevo y conversión alimenticia.
- **Fórmulas configurables.** Numerador, denominador y modo de cálculo por indicador, con recálculo y verificación contra el cálculo interno.
- **Estándares de genética.** Valores bajo y alto por semana de vida, por versión de estándar.
- **Seguimiento de estándares.** Reporte interactivo por semana de vida o calendario, comparación de lotes, detalle diario y exportación a PDF y Excel.
- **Semáforo.** Cada valor semanal guarda su desvío y queda en verde, amarillo o rojo según la regla y la tolerancia del indicador.

### Sanidad y pesajes

- **Vacunación.** Vacunas, planes por lote, aplicaciones y cumplimiento (aplicada, pendiente o vencida).
- **Pesajes.** Muestreo por jaula con peso promedio, coeficiente de variación y uniformidad, planilla imprimible y etiquetas QR por jaula.
- **App Avícola Campo.** App instalable en el celular para cargar pesadas: la jaula se abre escaneando su QR o escribiendo el código.

### Compras y facturación

- **Cobertura de stock.** Tablero con días de cobertura real y pronosticada. El semáforo compara la cobertura con el plazo del proveedor, los días de compra y el margen de seguridad.
- **Análisis de facturas.** Cantidades en huevos y cajones y precio por cajón como promedio ponderado, disponibles para reportes y tableros.

## Dependencias

Odoo 19 con `mrp`, `stock`, `purchase_stock`, `account`, `hr` y `mail`. En Python, `xlsxwriter` para la exportación a Excel.

## Instalación

1. Copiá el módulo en la carpeta de addons.
2. Actualizá la lista de aplicaciones.
3. Instalá **Poultry Management**.

## Configuración inicial

1. Cargá las genéticas, sus versiones de estándar y los indicadores.
2. Creá los galpones y sus listas de materiales de alimento.
3. Creá los lotes y asignalos a los galpones.
4. Definí en cada galpón los tipos de operación y el producto de huevo sin clasificar.
5. Elegí las categorías del tablero de cobertura en la empresa.

## Permisos

Los permisos están en la categoría **Gestión Avícola**: rol, partes de producción, cierres de galpón, mortandad y app Avícola Campo.
