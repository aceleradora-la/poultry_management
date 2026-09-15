# Módulo de Gestión Avícola (Poultry Management) para Odoo 18

## Descripción

Módulo completo para la gestión de granjas avícolas (huevos y pollos) en Odoo 18. Permite administrar galpones, lotes de aves, genéticas y listas de materiales de alimento balanceado, con integración al módulo de producción.

## Características Principales

### 1. Gestión de Galpones (Poultry Coops)
- **Información básica**: Código, nombre, tamaño (m²) y capacidad máxima de aves
- **Control de ocupación**: Cálculo automático del total de aves y porcentaje de ocupación
- **Asignación de lotes**: Visualización y gestión de los lotes de aves asignados al galpón
- **Lista de materiales activa**: Cada galpón puede tener una sola lista de materiales de alimento balanceado activa en un momento dado
- **Validaciones**: Previene que se exceda la capacidad del galpón

### 2. Gestión de Lotes de Aves (Poultry Batches)
- **Información del lote**: Código, nombre, fecha de nacimiento y genética
- **Asignación a galpón**: Fecha de asignación y galpón asignado
- **Cantidad de aves**: Control del número de aves por lote
- **Cálculos automáticos**: Edad del lote en días y días en el galpón
- **Proveedor**: Opción para registrar el proveedor del lote

### 3. Genéticas de Aves (Poultry Genetics)
- **Maestro de genéticas**: Registro de diferentes genéticas (Lohmann Brown, Hy-Line, ISA Brown, Cobb 500, Ross 308, etc.)
- **Datos precargados**: Incluye genéticas comunes de ponedoras y pollos de engorde

### 4. Listas de Materiales por Galpón (Coop BOM)
- **Historial completo**: Registro de todas las listas de materiales asignadas a cada galpón
- **Lista activa única**: Solo una lista de materiales puede estar activa por galpón a la vez
- **Control de fechas**: Fecha de inicio y fin de cada lista de materiales
- **Integración con MRP**: Uso de las listas de materiales (BOM) estándar de Odoo

### 5. Extensión de Órdenes de Fabricación
- **Campo galpón**: Se agregó el campo galpón a las órdenes de fabricación
- **Carga automática**: Al seleccionar un galpón, se carga automáticamente:
  - El producto de la lista de materiales activa
  - La lista de materiales (BOM) activa del galpón
  - Los componentes de la BOM

## Instalación

1. Coloque el módulo en la carpeta `addons` de su instalación de Odoo 18
2. Actualice la lista de aplicaciones
3. Instale el módulo "Poultry Management" desde el menú de Aplicaciones

## Estructura del Módulo

```
poultry_management/
├── __init__.py
├── __manifest__.py
├── README.md
├── models/
│   ├── __init__.py
│   ├── poultry_coop.py          # Modelo de Galpones
│   ├── poultry_batch.py          # Modelo de Lotes de Aves
│   ├── poultry_coop_bom.py       # Modelo de Listas de Materiales por Galpón
│   ├── poultry_genetics.py       # Modelo de Genéticas
│   └── mrp_production.py         # Extensión de Órdenes de Fabricación
├── views/
│   ├── poultry_coop_views.xml    # Vistas de Galpones
│   ├── poultry_batch_views.xml   # Vistas de Lotes de Aves
│   ├── poultry_coop_bom_views.xml # Vistas de Listas de Materiales
│   ├── poultry_genetics_views.xml # Vistas de Genéticas
│   ├── mrp_production_views.xml  # Vistas extendidas de Producción
│   └── poultry_menus.xml         # Menús del módulo
├── security/
│   ├── poultry_security.xml      # Grupos de seguridad
│   └── ir.model.access.csv       # Permisos de acceso
└── data/
    ├── __init__.py
    ├── ir_sequence_data.xml      # Secuencias para códigos automáticos
    └── genetics_data.xml         # Datos iniciales de genéticas
```

## Uso

### Crear un Galpón

1. Navegue a **Gestión Avícola > Galpones**
2. Haga clic en **Crear**
3. Complete los campos:
   - **Código**: Se genera automáticamente si se deja vacío
   - **Nombre**: Nombre descriptivo del galpón
   - **Tamaño**: Tamaño en metros cuadrados
   - **Capacidad**: Cantidad máxima de aves que puede albergar

### Crear un Lote de Aves

1. Navegue a **Gestión Avícola > Lotes de Aves**
2. Haga clic en **Crear**
3. Complete los campos:
   - **Código**: Se genera automáticamente si se deja vacío
   - **Nombre**: Se genera automáticamente basado en genética y fecha
   - **Genética**: Seleccione la genética del lote
   - **Fecha de Nacimiento**: Fecha en que nacieron las aves
   - **Galpón Asignado**: Seleccione el galpón donde se alojarán
   - **Fecha de Asignación**: Fecha en que se asignaron al galpón
   - **Cantidad de Aves**: Número de aves en el lote

### Asignar Lista de Materiales a un Galpón

1. Desde el formulario del galpón, vaya a la pestaña **Listas de Materiales**
2. Haga clic en **Agregar una línea**
3. Complete los campos:
   - **Lista de Materiales**: Seleccione una BOM existente
   - **Fecha de Inicio**: Fecha desde la cual esta lista está activa
   - Haga clic en **Activar** para activarla

### Crear Orden de Fabricación para un Galpón

1. Navegue a **Manufactura > Órdenes de Fabricación**
2. Haga clic en **Crear**
3. En el campo **Galpón**, seleccione el galpón deseado
4. Automáticamente se cargarán:
   - El producto de la lista de materiales activa del galpón
   - La lista de materiales activa
   - Los componentes necesarios

## Permisos y Seguridad

El módulo incluye dos grupos de seguridad:
- **Gestor Avícola**: Acceso completo (lectura, escritura, creación, eliminación)
- **Usuario Avícola**: Solo lectura

## Dependencias

- `base`: Módulo base de Odoo
- `mrp`: Módulo de manufactura (producción)
- `product`: Módulo de productos

## Licencia

LGPL-3

## Autor

aceleradora.la

## Versión

18.0.1.0.0

